"""Genuine immutable source controls plus synthetic boundary/drift negatives."""
from collections import Counter
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import retained_possession_periods as q
from fm_live_mcp.match_period_observations import digest

FIXTURES = Path(__file__).parent / 'fixtures'


def sample():
    with gzip.open(FIXTURES / 'possession_events_forest_2030_11_11.json.gz', 'rt') as stream:
        source = json.load(stream)
    witness = json.loads((FIXTURES / 'possession_period_witness_forest_2030_11_11.json').read_text())
    parent = witness['parent_observation']
    link = dict(state='verified_retrospective_continuity', capture_id=digest(parent), native_match_key=source['native_match_key'],
        official_match_unique_id=parent['official_match_unique_id'], clock_domain='native_playback_time_slice',
        intervals=parent['intervals'], provenance=dict(original_terminal_sha256=witness['original_terminal_sha256']))
    return source, link, parent, witness['attestation']


def project(source, link, parent, attestation):
    return q.project(bytes.fromhex(source['events_hex']), source['players'], source['fixture'],
        source['native_match_key'], link, parent, attestation=attestation)


def test_genuine_original_terminal_witness_matches_all354_retained_possession_events():
    source, link, parent, attestation = sample()
    assert digest(parent) == '96a4c9a070ecea5badb975a5146dc61aadc63f19e2fc675b06463a9e45cd439f'
    out = project(source, link, parent, attestation)
    assert out['state'] == 'available'
    assert out['complete_event_vector_continuity'] == 'mismatch'
    assert out['possession_period_report_continuity'] == 'matched'
    assert out['metric_attestation_id'] == attestation['attestation_id']
    assert [side['full_fixture_player_counter_checks'] for side in out['sides']] == [20, 20]
    assert [[(period['possession_won_events'], period['possession_lost_events']) for period in side['periods']]
            for side in out['sides']] == [[(47, 44), (45, 45)], [(39, 48), (36, 50)]]
    assert [side['unknown_interval_event_count'] for side in out['sides']] == [0, 0]
    # Independent direct-record census, including every zero actor and all354 IDs.
    raw = bytes.fromhex(source['events_hex'])
    oracle = Counter()
    for at in range(0, len(raw), 56):
        row = raw[at:at + 56]
        if row[42] not in (52, 53):
            continue
        start = int.from_bytes(row[34:36], 'little')
        end = int.from_bytes(row[50:52], 'little')
        group = 0 if 1 <= start <= end < 11655 else 1 if 11715 <= start <= end < 23929 else None
        oracle[row[40], row[39], group, row[42]] += 1
    assert sum(oracle.values()) == 354
    for side in out['sides']:
        for group, period in enumerate(side['periods']):
            assert len(period['players']) == 20
            for player in period['players']:
                assert player['possession_won_events'] == oracle[side['side_index'], player['stored_player_slot'], group, 52]
                assert player['possession_lost_events'] == oracle[side['side_index'], player['stored_player_slot'], group, 53]
            assert any(player['possession_won_events'] == player['possession_lost_events'] == 0 for player in period['players'])


def _fresh_witness(source, parent, link):
    # Synthetic changed-input controls only; never a host/live attestation.
    parent.pop('possession_period_report_fingerprint', None)
    parent['possession_period_report_fingerprint'] = q.possession_period_fingerprint(bytes.fromhex(source['events_hex']), parent['fingerprint_cursor'])
    link['capture_id'] = digest(parent)


@pytest.mark.parametrize('start,end,first,second,unknown', [
    (11654, 11655, 0, 0, 1), (11655, 11655, 0, 0, 1),
    (11654, 11716, 0, 0, 1), (11715, 11716, 0, 1, 0),
    (23928, 23929, 0, 0, 1), (0, 0, 0, 0, 1),
])
def test_native_boundary_ties_crossings_gaps_are_unassigned(start, end, first, second, unknown):
    source, link, parent, _ = sample()
    raw = bytearray.fromhex(source['events_hex'])
    at = next(at for at in range(0, len(raw), 56) if raw[at + 42] == 52 and raw[at + 40] == 0)
    struct.pack_into('<H', raw, at + 34, start)
    struct.pack_into('<H', raw, at + 50, end)
    source['events_hex'] = raw.hex()
    _fresh_witness(source, parent, link)
    out = project(source, link, parent, None)['sides'][0]
    assert [period['possession_won_events'] for period in out['periods']] == [46 + first, 45 + second]
    assert out['unknown_interval_event_count'] == unknown


@pytest.mark.parametrize('offset', [34, 39, 40, 42, 44, 50])
def test_consumed_possession_fields_must_match_independent_prior_witness(offset):
    source, link, parent, attestation = sample()
    raw = bytearray.fromhex(source['events_hex'])
    at = next(at for at in range(0, len(raw), 56) if raw[at + 42] in (52, 53))
    raw[at + offset] ^= 1
    source['events_hex'] = raw.hex()
    out = project(source, link, parent, attestation)
    assert out['state'] == 'unavailable_possession_period_source' and out['sides'] is None


@pytest.mark.parametrize('offset', [0, 8, 16, 24, 28, 41, 48])
def test_unconsumed_pointers_coordinates_flags_do_not_become_false_full_byte_equality(offset):
    source, link, parent, attestation = sample()
    raw = bytearray.fromhex(source['events_hex'])
    at = next(at for at in range(0, len(raw), 56) if raw[at + 42] in (52, 53))
    raw[at + offset] ^= 1
    source['events_hex'] = raw.hex()
    out = project(source, link, parent, attestation)
    assert out['state'] == 'available' and out['complete_event_vector_continuity'] == 'mismatch'
    assert out['possession_period_report_continuity'] == 'matched'


def test_pass_only_witness_is_not_reused_for_possession():
    source, link, parent, _ = sample()
    assert parent['pass_period_report_fingerprint']
    out = project(source, link, parent, None)
    assert out['reason'] == 'independent_possession_event_witness_required' and out['sides'] is None


@pytest.mark.parametrize('fault', ['link', 'observation', 'fixture', 'key', 'uid', 'clock', 'attestation_parent', 'attestation_hash'])
def test_near_identical_invalid_scope_never_produces_period_numbers(fault):
    source, link, parent, attestation = sample()
    if fault == 'link':
        link['state'] = 'unavailable_no_verified_host_period_link'
        assert project(source, link, parent, attestation)['sides'] is None
        return
    if fault == 'observation': parent['extra'] = True
    if fault == 'fixture': source['fixture']['date'] = '2030-11-12'
    if fault == 'key': source['native_match_key'] += 1
    if fault == 'uid': link['official_match_unique_id'] += 1
    if fault == 'clock': link['clock_domain'] = 'displayed_minutes'
    if fault == 'attestation_parent':
        attestation['attestation']['parent_capture_id'] = '0' * 64
        attestation['attestation_id'] = digest(attestation['attestation'])
    if fault == 'attestation_hash': attestation['attestation_id'] = '0' * 64
    with pytest.raises(ValueError): project(source, link, parent, attestation)


def test_counter_disagreement_withholds_only_affected_side_and_zeros_stay_qualified():
    source, link, parent, attestation = sample()
    row = source['players'][0]
    raw = bytearray.fromhex(row['raw_child_hex'])
    raw[151 + (4 if raw[0] < 2 else 0)] += 1
    row.update(raw_child_hex=raw.hex(), row_sha256=hashlib.sha256(raw).hexdigest(), possession_won=row['possession_won'] + 1)
    out = project(source, link, parent, attestation)
    assert out['state'] == 'partial' and out['sides'][0]['periods'] is None
    assert out['sides'][0]['unknown_interval_event_count'] is None
    assert out['sides'][1]['state'] == 'available'


@pytest.mark.parametrize('intervals', [[], [{'period': 'FirstHalf', 'start_tick': 10, 'end_tick': 10}],
    [{'period': 'FirstHalf', 'start_tick': 1, 'end_tick': 20}, {'period': 'SecondHalf', 'start_tick': 10, 'end_tick': 30}],
    [{'period': 'Guessed45Minutes', 'start_tick': 0, 'end_tick': 45}],
    [{'period': 'FirstHalf', 'start_tick': True, 'end_tick': 100}],
])
def test_missing_or_invalid_intervals_never_become_guessed_halves(intervals):
    source, link, parent, attestation = sample()
    link['intervals'] = intervals
    if not intervals:
        assert project(source, link, parent, attestation)['reason'] == 'no_closed_observed_periods'
    else:
        with pytest.raises(ValueError): project(source, link, parent, attestation)


def test_sdk_tool_has_structured_schema_host_write_annotation_and_no_caller_half_clocks():
    import asyncio
    from mcp.server.fastmcp import FastMCP
    from fm_live_mcp.retained_possession_period_tools import register_retained_possession_period_tools
    mcp = FastMCP()
    register_retained_possession_period_tools(mcp, object())
    tool = asyncio.run(mcp.list_tools())[0]
    assert tool.name == 'fm_report_retained_possession_by_period' and tool.outputSchema
    assert tool.annotations.readOnlyHint is False and not tool.annotations.destructiveHint
    assert set(tool.inputSchema['properties']) == {'session_id', 'fixture_ref', 'team_native_id', 'person_native_id'}
    assert 'persist finalized local host period-link metadata' in tool.description
    assert 'normal epoch and existing-pin checks' in tool.description
    assert 'Creates no new native observation' in tool.description
    assert 'no game-memory/save writes' in tool.description
