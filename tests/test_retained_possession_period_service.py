"""Public adapter semantics with real frozen projection; no live proof."""
from contextlib import nullcontext
from copy import deepcopy
import gzip
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import retained_possession_periods as q, possession_period_attestations as attest
from fm_live_mcp.match_period_observations import ObservationStore, digest


def service(monkeypatch, tmp_path):
    from fm_live_mcp import live_retained_shots, match_data_query, match_period_observations, retained_possession_events, live_match_players
    from fm_live_mcp.active_pass_network import PASS_CLOCK_SPANS
    fixtures = Path(__file__).parent / 'fixtures'
    with gzip.open(fixtures / 'possession_events_forest_2030_11_11.json.gz', 'rt') as stream:
        packet = json.load(stream)
    witness = json.loads((fixtures / 'possession_period_witness_forest_2030_11_11.json').read_text())
    parent = witness['parent_observation']
    fixture = {**packet['fixture'], 'fixture_ref': 'f'}
    epoch = ('checked', 'scope')
    spans = {}
    for rva, raw in retained_possession_events.NATIVE_SPANS + PASS_CLOCK_SPANS:
        for index, byte in enumerate(raw):
            if rva + index in spans:
                assert spans[rva + index] == byte
            spans[rva + index] = byte

    class Read:
        def __call__(self, address, size):
            return bytes(spans[address + index] for index in range(size))

        def verify(self):
            pass

    bridge = SimpleNamespace(lock=nullcontext(), _read_scope=lambda sid: nullcontext(), _current=lambda sid: None,
        _player_layout=lambda process: (0x5588ee8,), _world_state=lambda *args: (Read(), {}, None),
        get_save=lambda sid: {'save': {**parent['career'], 'current_date': '2030-11-13'}})
    teams = [{'side_index': side, 'team_index': fixture[field]['database_index'],
              'team_identity_word': fixture[field]['native_id']} for side, field in enumerate(('home_team', 'away_team'))]
    capture = {'_live_capture_epoch': epoch, 'capture': {'fixtures': [{'fixture': fixture, 'native_match_key': packet['native_match_key']}]},
               'team_totals': {'records': [{'result_key': packet['native_match_key'], 'teams': teams}]},
               'retained_players': packet['players'], 'raw_frames': [{'key': packet['native_match_key'], 'raw': b'frame'}]}
    complete = {'coverage': {'complete_side_sections': True, 'stored_rows_per_side': [20, 20]}, 'rows': deepcopy(packet['players'])}
    source = {'state': 'available', 'events': bytes.fromhex(packet['events_hex']),
              'vectors': [b'left', b'right'], 'pitch_geometry': packet['pitch_geometry']}
    link = dict(state='verified_retrospective_continuity', capture_id=digest(parent), native_match_key=packet['native_match_key'],
        official_match_unique_id=parent['official_match_unique_id'], clock_domain='native_playback_time_slice',
        intervals=parent['intervals'], provenance={'fixture': 'genuine_frozen_source_test'})
    store = ObservationStore(tmp_path / 'periods')
    store.save(parent)
    attest.write(store.root, parent, witness['attestation'])
    order = []
    monkeypatch.setattr(match_data_query, 'capture_epoch', lambda *args: epoch)
    monkeypatch.setattr(match_data_query, 'capture_live', lambda *args, **kwargs: capture)
    monkeypatch.setattr(live_match_players, 'project_frame', lambda raw, key: complete)
    monkeypatch.setattr(live_retained_shots, 'capture_source', lambda *args: deepcopy(source))
    monkeypatch.setattr(live_retained_shots, 'decode_attempts', lambda *args: {'shots': [], 'side_coverage': [{'state': 'available'}, {'state': 'available'}]})
    monkeypatch.setattr(match_period_observations, 'process_epoch', lambda b: 'current_epoch')

    def verified_link(*args):
        order.append('normal_link_retained')
        return link

    monkeypatch.setattr(match_period_observations, 'link_retained', verified_link)
    actual_load = attest.load

    def load_after_normal_link(*args):
        assert order == ['normal_link_retained']
        order.append('metric_attestation')
        return actual_load(*args)

    monkeypatch.setattr(attest, 'load', load_after_normal_link)
    return bridge, store, source, link, spans, capture, order


def test_public_service_full_frozen_projection_and_selected_actor_keep_side_totals(monkeypatch, tmp_path):
    bridge, store, _, _, _, _, order = service(monkeypatch, tmp_path)
    before = {path: path.read_bytes() for path in store.root.rglob('*.json')}
    out = q.report(bridge, 's', 'f', store=store)
    assert out['state'] == 'available' and out['saved_file_fallback'] is False
    assert order == ['normal_link_retained', 'metric_attestation']
    assert [[(p['possession_won_events'], p['possession_lost_events']) for p in side['periods']]
            for side in out['sides']] == [[(47, 44), (45, 45)], [(39, 48), (36, 50)]]
    assert {path: path.read_bytes() for path in store.root.rglob('*.json')} == before
    order.clear()
    person = out['sides'][0]['periods'][0]['players'][0]['person_native_id']
    chosen = q.report(bridge, 's', 'f', team_native_id=688, person_native_id=person, store=store)
    assert len(chosen['sides']) == 1
    assert chosen['sides'][0]['periods'][0]['possession_lost_events'] == 44
    assert len(chosen['sides'][0]['periods'][0]['players']) == 1
    assert chosen['sides'][0]['periods'][0]['players'][0]['person_native_id'] == person


def test_new_attestation_cannot_bypass_normal_unfinalized_epoch_link(monkeypatch, tmp_path):
    bridge, store, _, link, _, _, order = service(monkeypatch, tmp_path)
    link.clear()
    link.update(state='unavailable_no_verified_host_period_link', reasons=['unfinalized_observation_process_or_load_changed'])
    out = q.report(bridge, 's', 'f', store=store)
    assert out['state'] == 'unavailable_possession_period_source' and out['sides'] is None
    assert out['reason'] == 'verified_host_period_link_required'
    assert order == ['normal_link_retained']


@pytest.mark.parametrize('family', ['possession', 'clock'])
def test_native_source_and_clock_guards_are_required(monkeypatch, tmp_path, family):
    from fm_live_mcp.retained_possession_events import NATIVE_SPANS
    from fm_live_mcp.active_pass_network import PASS_CLOCK_SPANS
    bridge, store, _, _, spans, _, order = service(monkeypatch, tmp_path)
    rva, raw = (NATIVE_SPANS if family == 'possession' else PASS_CLOCK_SPANS)[0]
    spans[rva] ^= 1
    with pytest.raises(ValueError, match='source changed|binding changed'):
        q.report(bridge, 's', 'f', store=store)
    assert not order


def test_changed_retained_source_aborts_instead_of_publishing_stale_report(monkeypatch, tmp_path):
    from fm_live_mcp import live_retained_shots
    bridge, store, source, _, _, _, _ = service(monkeypatch, tmp_path)
    calls = 0

    def changed(*args):
        nonlocal calls
        calls += 1
        result = deepcopy(source)
        if calls == 2:
            result['events'] += bytes(56)
        return result

    monkeypatch.setattr(live_retained_shots, 'capture_source', changed)
    with pytest.raises(ValueError, match='source changed'):
        q.report(bridge, 's', 'f', store=store)


def test_changed_epoch_aborts_instead_of_publishing_stale_report(monkeypatch, tmp_path):
    from fm_live_mcp import match_data_query
    bridge, store, _, _, _, _, _ = service(monkeypatch, tmp_path)
    epochs = iter([('checked', 'scope'), ('different',)])
    monkeypatch.setattr(match_data_query, 'capture_epoch', lambda *args: next(epochs))
    with pytest.raises(ValueError, match='source changed'):
        q.report(bridge, 's', 'f', store=store)


@pytest.mark.parametrize('kwargs', [{'team_native_id': True}, {'person_native_id': 1},
    {'team_native_id': 111}, {'team_native_id': 688, 'person_native_id': -1}])
def test_invalid_team_player_selectors_do_not_become_empty_zero_rows(monkeypatch, tmp_path, kwargs):
    bridge, store, _, _, _, _, _ = service(monkeypatch, tmp_path)
    with pytest.raises(ValueError):
        q.report(bridge, 's', 'f', store=store, **kwargs)


def test_missing_selected_actor_stays_unavailable(monkeypatch, tmp_path):
    bridge, store, _, _, _, _, _ = service(monkeypatch, tmp_path)
    out = q.report(bridge, 's', 'f', team_native_id=688, person_native_id=1, store=store)
    assert out['state'] == 'unavailable_selected_possession_actor' and out['sides'] is None


def test_dropped_zero_actor_rejects_full_roster_completeness_claim(monkeypatch, tmp_path):
    bridge, store, _, _, _, capture, _ = service(monkeypatch, tmp_path)
    zero = next(row for row in capture['retained_players'] if row['possession_won'] == row['possession_lost'] == 0)
    capture['retained_players'].remove(zero)
    with pytest.raises(ValueError, match='including zero actors'):
        q.report(bridge, 's', 'f', store=store)


def test_unretained_source_has_no_period_numbers_and_does_not_consult_witness(monkeypatch, tmp_path):
    bridge, store, source, _, _, _, order = service(monkeypatch, tmp_path)
    source.clear()
    source.update(state='unavailable_not_retained')
    out = q.report(bridge, 's', 'f', store=store)
    assert out['state'] == 'unavailable_not_retained' and out['sides'] is None
    assert not order
