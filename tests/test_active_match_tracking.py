import copy
import gzip
import json
from pathlib import Path
import struct
import pytest

from fm_live_mcp.active_match_tracking import clip_tracking, project


def actual():
    with gzip.open(Path(__file__).parent / 'fixtures/retained_tracking_average_positions.json.gz', 'rt') as f:
        packet = json.load(f)
    tracking = packet['tracking']
    for name in ('orientation_profile', 'possession_samples'):
        tracking[name] = bytes.fromhex(tracking[name])
    for row in tracking['players']:
        row['samples'] = bytes.fromhex(row['samples'])
    return packet


def control(cursor=10000):
    packet = actual()
    source = dict(state='available_engine_tracking_source', tracking=packet['tracking'],
                  match_unique_id=1, engine_frontier_raw=25000, pitch_geometry=None)
    bound = dict(official_match_unique_id=1, current_time_slice=cursor, buffered_max_time_slice=25000)
    binding = dict(state='validated_native_stored_slots', official_match_unique_id=1)
    return packet, source, bound, binding


def test_actual_retained_prefix_controls_include_no_future_points_or_entrants():
    packet, source, bound, binding = control()
    result = project(source, bound, packet['players'], actor_binding=binding)
    assert len(result['players']) == 22
    assert all(row['sample_count'] == 416 for row in result['players'])
    assert all(row['coverage']['last_nonzero_sample_tick'] <= 10000 for row in result['players'])
    assert result['online_positive_control_verified'] is False
    assert result['current_time_slice'] == 10000
    assert result['native_tracking_clock_domain_verified'] is True


def test_changed_future_coordinates_or_phases_cannot_change_cursor_report():
    packet, source, bound, binding = control()
    before = project(source, bound, packet['players'], actor_binding=binding)
    changed = copy.deepcopy(source)
    for row in changed['tracking']['players']:
        keep = max(0, (10000 - row['start_tick']) // 24 + 1)
        row['samples'] = row['samples'][:keep * 4] + bytes.fromhex('ff7fff7f') * (len(row['samples']) // 4 - keep)
    phases = changed['tracking']['possession_samples']
    changed['tracking']['possession_samples'] = phases[:417] + bytes((8,)) * (len(phases) - 417)
    assert project(changed, bound, packet['players'], actor_binding=binding) == before


def test_native_exact_sample_boundary_is_inclusive_and_next_point_excluded():
    packet, source, bound, binding = control(24)
    at = project(source, bound, packet['players'], actor_binding=binding)
    assert all(row['sample_count'] == 1 for row in at['players'])
    bound['current_time_slice'] = 23
    before = project(source, bound, packet['players'], actor_binding=binding)
    assert before['players'] == []


def test_unknown_actors_and_invalid_clock_never_become_named_positions():
    packet, source, bound, binding = control()
    assert project(source, bound, packet['players'])['reason'] == 'unavailable_active_tracking_actor_join'
    bound['buffered_max_time_slice'] = 9999
    assert project(source, bound, packet['players'], actor_binding=binding)['reason'] == 'unavailable_clock_range_or_wrap'
    bound['official_match_unique_id'] = 2
    with pytest.raises(ValueError, match='identities'):
        project(source, bound, packet['players'], actor_binding=binding)


def test_unsupported_width_and_wrapped_clock_fail_closed():
    packet = actual()['tracking']
    packet['players'][0]['samples'] += b'x'
    with pytest.raises(ValueError, match='geometry'):
        clip_tracking(packet, 10000)
    with pytest.raises(ValueError, match='clock'):
        clip_tracking(actual()['tracking'], 65536)


def test_final_cursor_reconstructs_all_frozen_retained_means_exactly():
    packet, source, bound, binding = control(25000)
    result = project(source, bound, packet['players'], actor_binding=binding)
    assert result['players'] == packet['expected']['players']


def test_native_capture_reads_only_current_position_and_phase_prefix_bytes():
    from fm_live_mcp.active_match_tracking import _read_prefix
    cbe, headers, samples, phases = 0x10000, 0x20000, 0x30000, 0x40000
    entry = bytearray(40)
    struct.pack_into('<I', entry, 8, 24)
    struct.pack_into('<QQQ', entry, 16, samples, samples + 16, samples + 16)
    p = bytes(16)
    memory = {cbe + 0xd0: struct.pack('<QQQ', headers, headers + 40, headers + 40),
              headers: bytes(entry), cbe + 0xe8: struct.pack('<QQQ', phases, phases + 10, phases + 16),
              cbe + 0x108: p, samples: bytes(8), phases: bytes((0, 1, 255))}
    calls = []
    def read(address, size):
        calls.append((address, size))
        raw = memory[address]
        assert len(raw) == size, 'Attempted to read beyond the verified playback prefix'
        return raw
    packet = _read_prefix(read, cbe, 48)
    assert packet['players'][0]['samples'] == bytes(8)
    assert packet['possession_samples'] == bytes((0, 1, 255))
    assert (samples, 8) in calls and (samples, 16) not in calls


def test_unresolved_selected_actor_is_explicit_partial_and_future_actor_not_exposed():
    packet, source, bound, binding = control()
    players = [row for row in packet['players'] if (row['side_index'], row['stored_player_slot']) != (0, 0)]
    output = project(source, bound, players, actor_binding=binding)
    assert output['state'] == 'available_partial'
    assert len(output['players']) == 21
    assert output['unresolved_tracking_actors'] == [dict(side_index=0, stored_player_slot=0,
            sample_count=416, state='unresolved_active_tracking_actor_join')]
    assert all(row['stored_player_slot'] < 11 for row in output['players'])


def test_real_live_lille_readset_positive_matches_and_buffer_can_lead_engine():
    with gzip.open(Path(__file__).parent / 'fixtures/active_lille_tracking_cursor.json.gz', 'rt') as f:
        packet = json.load(f)
    assert packet['observed_readset_verified'] is True
    assert packet['fixture']['home_team']['native_id'] == 858
    assert packet['fixture']['away_team']['native_id'] == 688
    source = packet['source']
    for name in ('orientation_profile', 'possession_samples'):
        source['tracking'][name] = bytes.fromhex(source['tracking'][name])
    for row in source['tracking']['players']:
        row['samples'] = bytes.fromhex(row['samples'])
    assert source['engine_frontier_raw'] == packet['bound']['current_time_slice'] == 4559
    assert packet['bound']['buffered_max_time_slice'] == 4631
    output = project(source, packet['bound'], packet['actors']['players'], actor_binding=packet['actors'])
    assert output == packet['expected']
    assert len(output['players']) == 22
    assert sum(row['sample_count'] for row in output['players']) == 4158


def prefix_verification_control(monkeypatch):
    from fm_live_mcp import active_match_tracking as query, active_match_playback
    packet, source, bound, actors = control(10000)
    bound.update(playback_address=100, frame_provider_address=200, source_match_address=300, local_playback_handle=2)
    source.update(source_identity=(10, 20, ('fixture',)), cbe_address=30)
    source['tracking'] = query.clip_tracking(source['tracking'], bound['current_time_slice'])
    current = {**bound, 'current_time_slice': 10010}
    monkeypatch.setattr(active_match_playback, 'capture', lambda *a, **k:
                        {'state': 'bound_playback_cursor', 'bound_playback': current.copy()})
    checked = copy.deepcopy(source)
    monkeypatch.setattr(query, 'capture_source', lambda *a, **k: copy.deepcopy(checked))
    anchors = {20 + 0x154dc: 10010, 20 + 0x20: 1, 10 + 0x138: 1, 20 + 0x14e98: 30, 10 + 0xf8: 40, 40 + 0x18: 20}
    def fresh_read(address, length):
        assert length in (4, 8)
        return struct.pack('<I' if length == 4 else '<Q', anchors[address])
    return query, source, bound, checked, current, anchors, fresh_read


def test_reverify_allows_monotonic_advance_and_effectively_unused_future_profile_change(monkeypatch):
    query, source, bound, checked, current, anchors, read = prefix_verification_control(monkeypatch)
    profile = bytearray(checked['tracking']['orientation_profile'])
    struct.pack_into('<i', profile, 0, 15000)  # Both future first-period boundaries exceed10000.
    checked['tracking']['orientation_profile'] = bytes(profile)
    result = query.verify_prefix(read, 0, 10, 20, bound, source)
    assert result['current_time_slice'] == 10000
    assert result['verified_at_time_slice'] == 10010
    assert result['selected_sample_count'] == 9152


@pytest.mark.parametrize('mutation', ['rewind', 'relink', 'coordinate', 'phase', 'orientation', 'early_engine', 'late_owner'])
def test_fixed_prefix_reverification_rejects_seek_relink_or_consumed_changes(monkeypatch, mutation):
    query, source, bound, checked, current, anchors, read = prefix_verification_control(monkeypatch)
    if mutation == 'rewind':
        current['current_time_slice'] = 9999
    elif mutation == 'relink':
        current['source_match_address'] = 301
    elif mutation == 'coordinate':
        row = checked['tracking']['players'][0]
        row['samples'] = bytes((row['samples'][0] ^ 1,)) + row['samples'][1:]
    elif mutation == 'phase':
        raw = bytearray(checked['tracking']['possession_samples']); raw[1] ^= 1
        checked['tracking']['possession_samples'] = bytes(raw)
    elif mutation == 'orientation':
        raw = bytearray(checked['tracking']['orientation_profile']); raw[13] ^= 1
        checked['tracking']['orientation_profile'] = bytes(raw)
    elif mutation == 'early_engine':
        checked['engine_frontier_raw'] = 9999
    else:
        anchors[20 + 0x14e98] = 31
    with pytest.raises(ValueError):
        query.verify_prefix(read, 0, 10, 20, bound, source)


def test_reverification_reselects_new_backing_buffer_without_reading_released_old_bytes(monkeypatch):
    query, source, bound, checked, current, anchors, anchor_read = prefix_verification_control(monkeypatch)
    cbe, headers, replacement, phases = 0x10000, 0x20000, 0x50000, 0x40000
    entry = bytearray(40); struct.pack_into('<I', entry, 8, 24)
    struct.pack_into('<QQQ', entry, 16, replacement, replacement + 8, replacement + 16)
    profile = source['tracking']['orientation_profile']
    memory = {cbe + 0xd0: struct.pack('<QQQ', headers, headers + 40, headers + 40),
              headers: bytes(entry), cbe + 0xe8: struct.pack('<QQQ', phases, phases + 3, phases + 8),
              cbe + 0x108: profile, replacement: bytes(8), phases: bytes((0, 1, 255))}
    bound['current_time_slice'] = 48
    source['tracking'] = {'orientation_profile': profile, 'possession_samples': memory[phases],
                          'players': [dict(side_index=0, stored_player_slot=0, start_tick=24, samples=bytes(8))]}
    calls = []
    def fresh_read(address, size):
        calls.append(address)
        if address in memory:
            assert len(memory[address]) == size
            return memory[address]
        return anchor_read(address, size)
    monkeypatch.setattr(query, 'capture_source', lambda read, *a, **kw:
        {**source, 'tracking': query._read_prefix(read, cbe, kw['current_time_slice'])})
    result = query.verify_prefix(fresh_read, 0, 10, 20, bound, source)
    assert result['backing_buffer_reselected']
    assert replacement in calls and 0x30000 not in calls
