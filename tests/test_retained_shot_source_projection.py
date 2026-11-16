"""Explicit native XgValue projection keeps the legacy contract separate."""
from fm_live_mcp import live_retained_shots as query


def test_explicit_source_projection_has_one_primary_page_and_rejects_stale_pin(monkeypatch):
    def capture(*args, **kwargs):
        assert kwargs['projection'] == 'source_proven'
        return {'records': [{'projection': 'source_proven', 'source_id': 'b'*64,
            'attempts': [{'event_id': i} for i in range(101)], 'own_goal_markers': []}]}
    monkeypatch.setattr(query, 'capture_retained_shot_maps', capture)
    page = query.get_retained_shot_map(None, 's', 'ref', projection='source_proven')
    assert len(page['attempts']) == 100 and page['next_offset'] == 100
    assert page['total_available_attempts'] == 101 and 'shots' not in page

import copy
import gzip
import hashlib
import json
import math
from pathlib import Path
import struct
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from fm_live_mcp.retained_shot_source_projection import project_source_attempts
from fm_live_mcp.retained_shot_values import NATIVE_XG_VALUE_SPANS, verify_native_xg_value

CONTROLS = json.loads(gzip.decompress((Path(__file__).parent / 'fixtures/retained_shot_maps.json.gz').read_bytes()))


def source(key=136157):
    c = next(row for row in CONTROLS if row['key'] == key)
    return c, [bytes.fromhex(v) for v in c['vectors']], bytes.fromhex(c['events'])


def event_offset(events, event_id):
    return next(at for at in range(0, len(events), 56) if struct.unpack_from('<I', events, at + 44)[0] == event_id)


def test_genuine_two_ulp_control_exposes_nine_native_values_without_reinterpreting_legacy_xg():
    c, vectors, events = source()
    legacy = query.decode_attempts(vectors, events, c['teams'])
    result = project_source_attempts(vectors, events, c['teams'])
    assert len(legacy['shots']) == 6 and len(result['attempts']) == 9
    assert result['state'] == 'available' and all(s['complete_side'] for s in result['side_coverage'])
    assert result['native_xg_value_definition']['official_frontend_property'] == 'XgValue'
    assert result['native_xg_value_definition']['aggregate_equivalence'] is False
    assert all('expected_goals' not in row for row in result['attempts'])
    assert all(row['native_xg_value_state'] == 'verified_native_ui_xg_value' for row in result['attempts'])
    assert all(row['credited_expected_goals_contribution'] is None for row in result['attempts'])
    assert all(row['credited_expected_goals_contribution_state'] == 'not_retained_in_checked_shot_representation' for row in result['attempts'])
    side = result['side_coverage'][1]
    assert side['shot_count'] == 3 and side['legacy_aggregate_comparison']['float32_ulp_distance'] == 2
    assert side['legacy_aggregate_comparison']['within_legacy_guard'] is False
    assert side['legacy_aggregate_comparison']['max_float32_ulps'] == 1
    assert side['native_float32_xg_value_sum'] == 0.3730766773223877
    assert side['official_expected_goals'] == 0.3730766177177429
    assert query.decode_attempts(vectors, events, c['teams']) == legacy


@pytest.mark.parametrize('field', ['native_xg_value', 'native_x', 'native_y'])
def test_one_invalid_field_preserves_other_proven_event_and_value_fields(field):
    c, vectors, events = source()
    event_id = struct.unpack_from('<I', vectors[0], 36)[0]
    if field == 'native_xg_value':
        raw = bytearray(vectors[0]); struct.pack_into('<f', raw, 32, math.nan); vectors[0] = bytes(raw)
    else:
        raw = bytearray(events); at = event_offset(events, event_id)
        struct.pack_into('<f', raw, at + (24 if field == 'native_x' else 28), math.nan); events = bytes(raw)
    result = project_source_attempts(vectors, events, c['teams'], pitch_geometry={'half_length_native': 52.5})
    assert len(result['attempts']) == 9 and result['side_coverage'][0]['complete_side']
    row = next(r for r in result['attempts'] if r['event_id'] == event_id)
    assert row[field] is None and row['field_states'][field].startswith('unavailable_')
    assert row['outcome_state'] == 'official_native_end_shot_category'
    if field == 'native_xg_value':
        assert row['native_x'] is not None and row['native_y'] is not None
        assert result['side_coverage'][0]['native_float32_xg_value_sum'] is None
        assert result['side_coverage'][0]['known_native_float32_xg_value_subtotal'] > 0
    else:
        assert row['native_xg_value'] is not None
        assert row['location_state'] == 'unavailable_coordinate'
    assert result['side_coverage'][0]['field_errors'][0]['field'] == field


@pytest.mark.parametrize('kind', ['missing', 'cross_side_duplicate', 'wrong_side'])
def test_bad_link_keeps_other_valid_records_without_claiming_complete_side(kind):
    c, vectors, events = source()
    if kind == 'cross_side_duplicate':
        vectors[1] += vectors[0][:48]
    elif kind == 'missing':
        raw = bytearray(vectors[0]); struct.pack_into('<I', raw, 36, 0xffffffff); vectors[0] = bytes(raw)
    else:
        raw = bytearray(events); event_id = struct.unpack_from('<I', vectors[0], 36)[0]
        raw[event_offset(events, event_id) + 40] = 1; events = bytes(raw)
    result = project_source_attempts(vectors, events, c['teams'])
    assert result['state'] == 'available_partial' and len(result['attempts']) == 8
    assert result['side_coverage'][0]['shot_count'] is None
    assert all(row['native_xg_value'] is not None for row in result['attempts'])
    assert result['side_coverage'][0]['link_errors']
    assert result['side_coverage'][0]['link_errors'][0]['stored_native_xg_value'] is not None
    assert result['side_coverage'][0]['link_errors'][0]['stored_native_xg_value_state'] == 'verified_stored_value_unresolved_event'
    if kind == 'cross_side_duplicate':
        assert result['side_coverage'][1]['shot_count'] is None
    else:
        assert result['side_coverage'][1]['shot_count'] == 3


def test_genuine_own_goal_stays_outside_attempts_and_native_value_rankings():
    c, vectors, events = source(135904)
    result = project_source_attempts(vectors, events, c['teams'])
    assert len(result['attempts']) == 23
    marker, = result['own_goal_markers']
    assert (marker['actor_side_index'], marker['beneficiary_side_index']) == (1, 0)
    assert marker['native_xg_value'] is None and marker['native_xg_value_state'] == 'not_a_statistical_attempt'
    assert marker['statistical_shot'] is False
    assert all(row['event_id'] != marker['event_id'] for row in result['attempts'])


def test_known_zero_unknown_aggregate_and_unknown_native_category_are_separate():
    teams = [dict(shots=0, shots_on_target=0, expected_goals=None) for _ in range(2)]
    empty = project_source_attempts([b'', b''], b'', teams)
    assert not empty['attempts']
    assert all(s['shot_count'] == 0 and s['native_float32_xg_value_sum'] == 0. for s in empty['side_coverage'])
    assert all(s['official_expected_goals'] is None and s['legacy_aggregate_comparison']['within_legacy_guard'] is None for s in empty['side_coverage'])
    c, vectors, events = source()
    raw = bytearray(events)
    event_id = next(struct.unpack_from('<I', raw, at + 44)[0] for at in range(0, len(raw), 56) if raw[at + 42] == 2)
    raw[event_offset(events, event_id) + 42] = 250
    result = project_source_attempts(vectors, bytes(raw), c['teams'])
    row = next(r for r in result['attempts'] if r['event_id'] == event_id)
    assert row['outcome'] is None and row['native_xg_value'] is not None


@pytest.mark.parametrize('projection,observed', [('bad', False), (True, False), ('source_proven', True)])
def test_invalid_or_mixed_projection_refuses_before_any_capture(monkeypatch, projection, observed):
    monkeypatch.setattr(query, 'capture_epoch', lambda *_: pytest.fail('invalid projection must refuse before capture'))
    with pytest.raises(ValueError):
        query.capture_retained_shot_maps(None, 's', ['ref'], projection=projection, include_source_observed=observed)
    with pytest.raises(ValueError):
        query.get_retained_shot_map(None, 's', 'ref', projection=projection, include_source_observed=observed)


def test_capture_preserves_legacy_and_binds_new_projection_pin_and_actor_unknowns(monkeypatch):
    c, vectors, events = source(132398)
    raw = gzip.decompress((Path(__file__).parent / 'fixtures/saved_match_stats_132398.bin.gz').read_bytes())
    fixture = {'fixture_ref': 'ref', 'date': c['fixture']['date'], 'competition': {'native_id': 11},
        'home_team': {'database_index': c['teams'][0]['team_index'], 'native_id': c['teams'][0]['team_identity_word']},
        'away_team': {'database_index': c['teams'][1]['team_index'], 'native_id': c['teams'][1]['team_identity_word']}}
    packet = {'_live_capture_epoch': ('load',), 'capture': {'fixtures': [{'fixture': fixture, 'native_match_key': 132398}]},
        'raw_frames': [{'fixture_ref': 'ref', 'key': 132398, 'raw': raw, 'raw_sha256': hashlib.sha256(raw).hexdigest()}],
        'retained_players': []}
    monkeypatch.setattr(query, 'capture_epoch', lambda *_: ('load',))
    seen = []
    def captured(*args, **kwargs):
        seen.append(kwargs)
        return dict(state='available', events=events, vectors=vectors, coach_index=0, coach_name='Coach', owner_team_native_id=688)
    monkeypatch.setattr(query, 'capture_source', captured)
    monkeypatch.setattr(query, 'read_selected_matches', lambda *_a, **_k: pytest.fail('must reuse exact private frame'))
    bridge = SimpleNamespace(get_save=lambda *_: {'save': {}})
    legacy = query.capture_retained_shot_maps(bridge, 's', ['ref'], fixture_captures=packet)['records'][0]
    explicit = query.capture_retained_shot_maps(bridge, 's', ['ref'], fixture_captures=packet, projection='legacy_reconciled')['records'][0]
    native = query.capture_retained_shot_maps(bridge, 's', ['ref'], fixture_captures=packet, projection='source_proven')['records'][0]
    # Separate observations have their own publication timestamp. All source/semantic fields must match.
    semantic = lambda row: {k: v for k, v in row.items() if k != 'observed_at'}
    assert semantic(legacy) == semantic(explicit) and seen[:2] == [{}, {}] and seen[2] == {'verify_xg_value': True}
    assert len(native['attempts']) == 18 and 'shots' not in native
    assert all(row['actor'] is None and row['actor_identity_state'] == 'unresolved_actor_or_team_binding' for row in native['attempts'])
    assert native['native_source_id'] == legacy['source_id'] and native['source_id'] != legacy['source_id']
    assert native['source_id'] == hashlib.sha256(b'source_proven:v1\0' + bytes.fromhex(legacy['source_id'])).hexdigest()
    # Exercise actor qualification through the complete adapter with the genuine raw frame.
    # Canonical identity rows here are controlled at the existing private-packet boundary.
    first = native['attempts'][0]
    side = first['event_side_index']
    actor = dict(native_match_key=132398, side_index=side, stored_player_slot=first['stored_player_slot'],
        team_index_word=c['teams'][side]['team_index'], canonical_team_id=c['teams'][side]['team_identity_word'],
        person_index_word=7, canonical_person_id=77, person_name='Controlled canonical actor',
        identity_state='same_snapshot_canonical_PERSON')
    packet['retained_players'] = [actor]
    bound = query.capture_retained_shot_maps(bridge, 's', ['ref'], fixture_captures=packet, projection='source_proven')['records'][0]
    assert bound['attempts'][0]['actor']['canonical_person_id'] == 77 and not bound['actor_binding_errors']
    packet['retained_players'] = [actor, dict(actor)]
    ambiguous = query.capture_retained_shot_maps(bridge, 's', ['ref'], fixture_captures=packet, projection='source_proven')['records'][0]
    assert len(ambiguous['attempts']) == 18 and all(row['native_xg_value'] is not None for row in ambiguous['attempts'])
    assert ambiguous['attempts'][0]['actor'] is None and len(ambiguous['actor_binding_errors']) == 2
    assert ambiguous['side_coverage'] == native['side_coverage']
    assert ambiguous['source_id'] != native['source_id']
    monkeypatch.setattr(query, 'capture_retained_shot_maps', lambda *_a, **_k: {'records': [copy.deepcopy(native)]})
    with pytest.raises(ValueError, match='source changed'):
        query.get_retained_shot_map(None, 's', 'ref', projection='source_proven', expected_source_id=legacy['source_id'])


def test_actual_native_source_guards_reject_mutations_before_fixture_reads(monkeypatch):
    import _pinned_build
    binary = _pinned_build.PLUGIN
    if not binary.exists():
        pytest.skip('Exact supported native image unavailable for disk-only source controls')
    base = 0x100000000
    from fm_live_mcp import players
    with binary.open('rb') as file:
        def read(at, size):
            file.seek(0x5ed4000 + at - base)
            return file.read(size)
        verify_native_xg_value(read, base)
        for target, _ in NATIVE_XG_VALUE_SPANS:
            def changed(at, size):
                raw = bytearray(read(at, size))
                if at == base + target:
                    raw[0] ^= 1
                return bytes(raw)
            with pytest.raises(ValueError, match='XgValue source binding changed'):
                verify_native_xg_value(changed, base)
        target = NATIVE_XG_VALUE_SPANS[0][0]
        def changed(at, size):
            raw = bytearray(read(at, size))
            if at == base + target:
                raw[0] ^= 1
            return bytes(raw)
        layout = [base + players.RVA[0]]
        # The sealed collector binds identity and runtime layout before any native-source read.
        monkeypatch.setattr(query.players, 'verify_runtime', lambda *_a: layout)
        bridge = SimpleNamespace(lock=nullcontext(), _read_scope=lambda _, final_verify=None: nullcontext(), _current=lambda _: 'process',
            plugin_identity=(None, None), world_identity=None, fixture_refs={},
            _player_layout=lambda _: layout, _world_state=lambda *_: (changed, {}, None))
        with pytest.raises(ValueError, match='XgValue source binding changed'):
            query.capture_source(bridge, 's', 'ref', 1, {}, verify_xg_value=True)


def test_actual_registered_tool_schema_declares_explicit_projection_and_legacy_default():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.retained_shot_tools import register_retained_shot_tools
    async def check():
        server = FastMCP('Source-proven shot schema')
        register_retained_shot_tools(server, None)
        tool = next(t for t in await server.list_tools() if t.name == 'fm_get_retained_shot_map')
        assert tool.inputSchema['properties']['projection']['enum'] == ['legacy_reconciled', 'source_proven']
        assert tool.inputSchema['properties']['projection']['default'] == 'legacy_reconciled'
        assert tool.annotations.readOnlyHint and tool.annotations.destructiveHint is False
        assert 'credited' in tool.description and 'XgValue' in tool.description
    asyncio.run(check())


def test_201_source_attempts_page_once_without_double_counting_or_legacy_arrays(monkeypatch):
    c, vectors, events = source()
    sample = vectors[0][:48]
    sample_event = events[event_offset(events, struct.unpack_from('<I', sample, 36)[0]):][:56]
    repeated, linked = [], []
    for index in range(201):
        record = bytearray(sample); event = bytearray(sample_event)
        struct.pack_into('<I', record, 36, index + 10000)
        struct.pack_into('<I', event, 44, index + 10000)
        repeated.append(bytes(record)); linked.append(bytes(event))
    teams = [dict(side_index=0, shots=201, shots_on_target=201 if sample_event[42] in (1, 4) else 0, expected_goals=40.),
             dict(side_index=1, shots=0, shots_on_target=0, expected_goals=0.)]
    packet = project_source_attempts([b''.join(repeated), b''], b''.join(linked), teams)
    packet['source_id'] = 'b' * 64
    assert packet['side_coverage'][0]['complete_side']
    monkeypatch.setattr(query, 'capture_retained_shot_maps', lambda *_a, **_k: {'records': [copy.deepcopy(packet)]})
    rows, offset = [], 0
    for _ in range(3):
        page = query.get_retained_shot_map(None, 's', 'ref', projection='source_proven', offset=offset,
                                         expected_source_id=packet['source_id'] if offset else None)
        assert not {'shots', 'source_observed_shots'} & page.keys()
        rows += page['attempts']
        offset = page['next_offset']
        if offset is None:
            break
    assert offset is None and len(rows) == 201 and len({row['event_id'] for row in rows}) == 201
    with pytest.raises(ValueError, match='requires expected_source_id'):
        query.get_retained_shot_map(None, 's', 'ref', projection='source_proven', offset=100)
    with pytest.raises(ValueError, match='source changed'):
        query.get_retained_shot_map(None, 's', 'ref', projection='source_proven', offset=100, expected_source_id='a'*64)


@pytest.mark.parametrize('value', [-.01, 1.01, math.inf, -math.inf])
def test_out_of_domain_native_value_stays_unknown_without_erasing_other_fields(value):
    c, vectors, events = source()
    record = bytearray(vectors[0]); struct.pack_into('<f', record, 32, value); vectors[0] = bytes(record)
    result = project_source_attempts(vectors, events, c['teams'])
    assert len(result['attempts']) == 9 and result['side_coverage'][0]['shot_count'] == 6
    assert result['attempts'][0]['native_xg_value'] is None
    assert result['attempts'][0]['native_x'] is not None


def test_native_source_profile_and_work_budgets_fail_closed():
    c, vectors, events = source()
    for bad_vectors, bad_events in [(vectors[:1], events), (vectors, events[:-1]),
            ([vectors[0] + b'x', vectors[1]], events), ([bytes(48 * 1025), b''], b''),
            ([b'', b''], bytes(56 * 30001))]:
        with pytest.raises(ValueError, match='profile|budget|width'):
            project_source_attempts(bad_vectors, bad_events, c['teams'])


def test_unavailable_native_projection_does_not_become_known_zero(monkeypatch):
    monkeypatch.setattr(query, 'capture_epoch', lambda *_: ('load',))
    monkeypatch.setattr(query, 'read_selected_matches', lambda *_a, **_k: {'records': [
        dict(fixture_ref='ref', fixture_native={}, key=1, state='not_in_active_match_banks')]})
    monkeypatch.setattr(query, 'capture_source', lambda *_a, **_k: pytest.fail('missing independent oracle'))
    bridge = SimpleNamespace(get_save=lambda *_: {'save': {}})
    packet = query.get_retained_shot_map(bridge, 's', 'ref', projection='source_proven')
    assert packet['state'] == 'unavailable_team_oracle' and not packet['attempts']
    assert 'shots' not in packet and all(row['shot_count'] is None for row in packet['side_coverage'])


def test_actual_registered_mcp_executes_projection_and_rejects_bad_literal_before_decoder(monkeypatch):
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp import retained_shot_tools
    c, vectors, events = source()
    observed = []
    def captured(*args):
        observed.append(args[-1])
        return project_source_attempts(vectors, events, c['teams']) if args[-1] == 'source_proven' else query.decode_attempts(vectors, events, c['teams'])
    monkeypatch.setattr(retained_shot_tools, 'get_retained_shot_map', captured)
    async def check():
        server = FastMCP('Source-proven actual MCP boundary')
        retained_shot_tools.register_retained_shot_tools(server, None)
        result = await server.call_tool('fm_get_retained_shot_map', {'session_id': 's', 'fixture_ref': 'ref', 'projection': 'source_proven'})
        assert len(result[1]['attempts']) == 9 and result[1]['projection'] == 'source_proven'
        old = await server.call_tool('fm_get_retained_shot_map', {'session_id': 's', 'fixture_ref': 'ref'})
        assert len(old[1]['shots']) == 6 and observed == ['source_proven', 'legacy_reconciled']
        for value in ['bad', True, None]:
            with pytest.raises(Exception, match='projection|literal|validation'):
                await server.call_tool('fm_get_retained_shot_map', {'session_id': 's', 'fixture_ref': 'ref', 'projection': value})
        assert observed == ['source_proven', 'legacy_reconciled']
    asyncio.run(check())


def test_actor_qualification_is_independent_of_attempt_values_and_never_guesses_ambiguous_names():
    from fm_live_mcp.retained_shot_source_projection import source_actor_bindings
    teams = [{'team_index': 5, 'team_identity_word': 10}, {'team_index': 6, 'team_identity_word': 20}]
    actor = dict(side_index=0, stored_player_slot=3, team_index_word=5, canonical_team_id=10,
        person_index_word=7, canonical_person_id=77, person_name='Checked actor', identity_state='same_snapshot_canonical_PERSON')
    actors, errors = source_actor_bindings([actor], teams)
    assert actors[0, 3]['person_name'] == 'Checked actor' and not errors
    for field, value in [('canonical_team_id', 99), ('identity_state', 'unresolved'),
                         ('canonical_person_id', None), ('stored_player_slot', True)]:
        bad = {**actor, field: value}
        actors, errors = source_actor_bindings([bad], teams)
        assert not actors and errors
    actors, errors = source_actor_bindings([{**actor, 'stored_player_slot': True}, {**actor, 'stored_player_slot': 1}], teams)
    assert all(error.get('reason') != 'ambiguous_actor_slot' for error in errors)
    assert errors[0]['reason'] == 'invalid_actor_side_or_slot'
    actors, errors = source_actor_bindings([actor, dict(actor)], teams)
    assert not actors and all(error['reason'] == 'ambiguous_actor_slot' for error in errors)
    c, vectors, events = source()
    before = project_source_attempts(vectors, events, c['teams'])
    assert len(before['attempts']) == 9 and all(r['native_xg_value'] is not None for r in before['attempts'])
