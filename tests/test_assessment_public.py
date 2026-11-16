"""Composed assessment API checks against real typed memory and physical sources."""
from copy import deepcopy
import struct

import pytest

from fm_live_mcp import assessment_people, assessment_source, world
from fm_live_mcp.bridge import BridgeError
from test_assessment_source import add_assessments
from test_shortlist_public import (shortlist_public_memory, prepared_tactics_memory,
                                  bridge, database_memory, memory, team_memory, world_memory)


@pytest.fixture
def public_assessment_memory(bridge, shortlist_public_memory):
    m = add_assessments(shortlist_public_memory)
    for rva, raw in assessment_people.NATIVE_SPANS:
        m['put'](m['base'] + rva, raw)
    m['q'](m['assessment_records'][0] + 8, 0)
    row = bridge.get_managed_shortlists(bridge.session)['entries'][0]
    m['assessment_player_ref'] = row['player_ref']
    return m


def query(bridge, m, **kw):
    return bridge.get_player_assessments(bridge.session, [m['assessment_player_ref']], **kw)


def test_composed_physical_duplicates_nulls_and_page_union(bridge, public_assessment_memory):
    m = public_assessment_memory
    result = query(bridge, m); player = result['players'][0]
    assert result['completed_scout_report_status'] == 'unproved'
    assert player['native_identity'] == {'database_index': 0, 'native_id': 12345, 'random_id': None}
    assert player['display_name'] == 'Test Müller' and player['record_kind'] == 'actual'
    assert [r['source_index'] for r in player['matches']] == [0, 3]
    assert result['source']['source_total'] == result['source']['scanned_count'] == 4
    assert result['source']['complete_source'] is True
    match = player['matches'][0]
    assert match['assessor'] == {'state': 'null_person', 'display_name': None,
                                'native_identity': None, 'record_kind': None}
    assert match['stored_population_date'] == {'value': '2030-10-28',
        'state': 'stored_base_population_date', 'raw_hex': '2d1bee07'}
    assert match['assessment_payload_state'] == 'stored_assessment_extra_data_present'
    pages = [query(bridge, m, source_offset=i, source_limit=1) for i in range(4)]
    assert all(not p['source']['complete_source'] for p in pages)
    assert [r for p in pages for r in p['players'][0]['matches']] == player['matches']
    assert pages[1]['players'][0]['matches'] == [] and pages[1]['source']['scanned_count'] == 1


def test_canonical_actual_assessor_is_known_unsupported_not_scout(bridge, public_assessment_memory):
    m = public_assessment_memory; m['q'](m['assessment_records'][0] + 8, 0x1388)
    assessor = query(bridge, m)['players'][0]['matches'][0]['assessor']
    assert assessor == {'state': 'unsupported_person_kind', 'display_name': None,
        'native_identity': {'database_index': 0, 'native_id': 12345, 'random_id': None}, 'record_kind': 'actual'}


def test_independent_secondary_zero_and_legacy_ref_index_recovery(bridge, public_assessment_memory):
    m = public_assessment_memory
    m['put'](0x1398, struct.pack('<I', 0))
    fresh = bridge.get_managed_shortlists(bridge.session)['entries'][0]['player_ref']
    bridge.player_refs[fresh].pop('database_index')
    result = bridge.get_player_assessments(bridge.session, [fresh])
    assert result['players'][0]['native_identity'] == {'database_index': 0, 'native_id': 12345, 'random_id': 0}
    assert [r['source_index'] for r in result['players'][0]['matches']] == [0, 3]


def test_repeated_inputs_preserve_order_without_multiplying_source_population(bridge, public_assessment_memory):
    m = public_assessment_memory; ref = m['assessment_player_ref']
    result = bridge.get_player_assessments(bridge.session, [ref] * 100)
    assert len(result['players']) == 100 and result['source']['scanned_count'] == 4
    assert all(p['player_ref'] == ref and [r['source_index'] for r in p['matches']] == [0, 3]
               for p in result['players'])


@pytest.mark.parametrize('null', [True, False])
def test_true_empty_source_is_complete_with_explicit_empty_matches(bridge, public_assessment_memory, null):
    m = public_assessment_memory; m['set_assessments']([], null=null)
    result = query(bridge, m)
    assert result['source']['source_state'] == 'available'
    assert result['source']['source_total'] == result['source']['scanned_count'] == 0
    assert result['source']['complete_source'] is True and result['source']['next_source_offset'] is None
    assert result['players'][0]['matches'] == []


@pytest.mark.parametrize('date,state', [(struct.pack('<HH', 1, 1900), 'native_default_sentinel'),
                                       (struct.pack('<HH', 511, 2030), 'unmapped_packed_value')])
def test_default_and_malformed_population_dates_are_explicit_unknown(bridge, public_assessment_memory, date, state):
    m = public_assessment_memory; m['put'](m['assessment_records'][0] + 0x18, date)
    value = query(bridge, m)['players'][0]['matches'][0]['stored_population_date']
    assert value == {'value': None, 'state': state, 'raw_hex': date.hex()}


@pytest.mark.parametrize('fault', ['identity', 'stored_index'])
def test_confirmed_stale_input_is_rejected_and_invalidated(bridge, public_assessment_memory, fault):
    m = public_assessment_memory; ref = m['assessment_player_ref']
    if fault == 'identity':
        m['put'](0x1394, struct.pack('<I', 54321))
    else:
        bridge.player_refs[ref]['database_index'] = 1
    with pytest.raises(BridgeError):
        query(bridge, m)
    assert ref not in bridge.player_refs
    assert bridge.player_refs['existing'] == {'untouched': True}


def test_temporary_canonical_slot_failure_preserves_otherwise_usable_ref(bridge, public_assessment_memory):
    m = public_assessment_memory; before = deepcopy(bridge.player_refs)
    start = struct.unpack('<Q', m['read'](m['headers']['people'], 8))[0]
    m['q'](start, m['manager'] + 0x548)
    with pytest.raises(BridgeError):
        query(bridge, m)
    assert bridge.player_refs == before
    m['q'](start, 0x1388)
    assert query(bridge, m)['source']['complete_source'] is True


def test_stale_identity_with_outer_save_drift_preserves_reference(bridge, public_assessment_memory, monkeypatch):
    m = public_assessment_memory; before = deepcopy(bridge.player_refs)
    m['put'](0x1394, struct.pack('<I', 54321))
    original = assessment_people.bound_player
    reached_stale = []
    def drift_after_real_stale_check(*args, **kwargs):
        try:
            return original(*args, **kwargs)
        except assessment_people.StalePlayerReference:
            reached_stale.append(True)
            address = m['base'] + world.CURRENT_DATE
            raw = struct.unpack('<I', m['read'](address, 4))[0]
            m['put'](address, struct.pack('<I', raw + 1))
            raise
    monkeypatch.setattr(assessment_people, 'bound_player', drift_after_real_stale_check)
    with pytest.raises(BridgeError, match='changed during read'):
        query(bridge, m)
    assert reached_stale == [True] and bridge.player_refs == before


@pytest.mark.parametrize('fault', ['header', 'pair', 'date', 'child', 'native', 'identity'])
def test_late_failure_returns_no_result_and_publishes_no_refs(bridge, public_assessment_memory, monkeypatch, fault):
    m = public_assessment_memory; before = deepcopy(bridge.player_refs)
    original = assessment_source.project
    def changed(*args, **kwargs):
        value = original(*args, **kwargs)
        record = m['assessment_records'][0]
        address = {'header': m['manager'] + 0x110, 'pair': record,
                   'date': record + 0x18, 'child': record + 0x30,
                   'native': m['base'] + assessment_source.NATIVE_SPANS[0][0],
                   'identity': 0x1394}[fault]
        m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
        return value
    monkeypatch.setattr(assessment_source, 'project', changed)
    with pytest.raises(BridgeError):
        query(bridge, m)
    assert bridge.player_refs == before


def test_unknown_mixed_input_does_not_publish_partial_or_remove_valid_ref(bridge, public_assessment_memory):
    m = public_assessment_memory; before = deepcopy(bridge.player_refs)
    with pytest.raises(BridgeError, match='Unknown'):
        bridge.get_player_assessments(bridge.session, [m['assessment_player_ref'], 'unknown'])
    assert bridge.player_refs == before
    assert query(bridge, m)['source']['complete_source'] is True


def test_real_bridge_reader_ceiling_is_respected_for_full_4096_slots(bridge, public_assessment_memory, monkeypatch):
    m = public_assessment_memory
    m['set_assessments']([0] * 4095 + [m['assessment_records'][0]], capacity=6074)
    def read(process, address, size):
        assert 1 <= size <= 16384
        return m['read'](address, size)
    monkeypatch.setattr(bridge, '_read_memory', read)
    result = query(bridge, m)
    assert result['source']['source_total'] == result['source']['scanned_count'] == 4096
    assert result['source']['complete_source'] is True
    assert [r['source_index'] for r in result['players'][0]['matches']] == [4095]


def test_stored_joining_interest_is_optional_and_rechecks_the_consumed_value(
    bridge, public_assessment_memory, monkeypatch,
):
    from fm_live_mcp import assessment_interest_labels, assessment_interest_source

    m = public_assessment_memory
    for module in (assessment_interest_labels, assessment_interest_source):
        for rva, expected in module.NATIVE_SPANS:
            m['put'](m['base'] + rva, expected)
    record = m['assessment_records'][0]
    child = m['allocate'](0x1b0)
    entry = m['allocate'](0x68)
    m['q'](record + 0x30, child)
    m['put'](child + 0x178, struct.pack('<QQQ', entry, entry + 0x68, entry + 0x68))
    m['put'](entry + 0x60, bytes([5]))
    m['put'](record + 0x20, struct.pack('<i', 100000))
    m['put'](record + 0x41, bytes([0]))
    m['put'](child + 0x79, bytes([0]))

    assert all('joining_interest' not in r for r in query(bridge, m)['players'][0]['matches'])
    rows = query(bridge, m, include_joining_interest=True)['players'][0]['matches']
    assert [r['source_index'] for r in rows] == [0, 3]
    assert all(r['joining_interest']['compact']['text'] == 'Extremely Interested' for r in rows)

    original = assessment_source.project

    def change_value_after_read(*args, **kwargs):
        projected = original(*args, **kwargs)
        m['put'](record + 0x20, struct.pack('<i', -100000))
        return projected

    monkeypatch.setattr(assessment_source, 'project', change_value_after_read)
    with pytest.raises(BridgeError, match='changed during read'):
        query(bridge, m, include_joining_interest=True)


@pytest.mark.parametrize('flag', ['true', 1, None])
def test_joining_interest_rejects_nonboolean_flags(bridge, public_assessment_memory, flag):
    with pytest.raises(BridgeError, match='must be a boolean'):
        query(bridge, public_assessment_memory, include_joining_interest=flag)
