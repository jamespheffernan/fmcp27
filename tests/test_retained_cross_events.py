import asyncio
import copy
import gzip
import hashlib
import json
from pathlib import Path
import struct
from contextlib import nullcontext
from types import SimpleNamespace

import pytest
from fm_live_mcp import retained_cross_events as q


def packet():
    with gzip.open(Path(__file__).parent / 'fixtures/retained_cross_events_city_138453.json.gz', 'rt') as f:
        return json.load(f)


def decode(p):
    return q.decode_cross_events(bytes.fromhex(p['events_hex']), p['players'], p['fixture'], p['native_match_key'], p['pitch_geometry'])


def test_actual_city_all_forty_counters_close_with_seventy_nine_crosses():
    p = packet()
    out = decode(p)
    assert out['state'] == 'available'
    home, away = out['sides']
    assert (home['attempt_count'], home['completed_count'], away['attempt_count'], away['completed_count']) == (42, 8, 37, 3)
    assert len(out['cross_events']) == 79
    assert sum(s['captured_player_counter_checks'] for s in out['sides']) == 40
    assert sum(s['zero_counter_players_checked'] for s in out['sides']) == 21
    assert all(s['all_player_counters_match'] for s in out['sides'])
    assert away['event_position_counts'] == [
        dict(analytical_pitch_third='attacking', analytical_lateral_channel='outer', attempts=27, completed=3, not_completed=24),
        dict(analytical_pitch_third=None, analytical_lateral_channel=None, attempts=10, completed=0, not_completed=10),
    ]
    henrique = [r for r in out['cross_events'] if r['person_name'] == 'Luiz Henrique']
    assert len(henrique) == 9 and not any(r['completed'] for r in henrique)
    assert all(r['recipient_name'] is r['shot_event_id'] is r['ball_release_location'] is None for r in out['cross_events'])


def test_one_missing_cross_withholds_entire_side_and_never_repairs_counts():
    p = packet()
    b = bytearray.fromhex(p['events_hex'])
    index = next(i for i in range(0, len(b), 56) if b[i + 40] == 1 and b[i + 42] in range(12, 18))
    del b[index:index + 56]
    p['events_hex'] = b.hex()
    out = decode(p)
    assert out['state'] == 'available_partial' and out['sides'][1]['attempt_count'] is None
    assert all(r['side_index'] == 0 for r in out['cross_events'])
    assert out['sides'][0]['attempt_count'] == 42


def test_zero_counter_is_checked_and_unknown_original_slot_is_not_inferred():
    p = packet()
    b = bytearray.fromhex(p['events_hex'])
    index = next(i for i in range(0, len(b), 56) if b[i + 40] == 1 and b[i + 42] in range(12, 18))
    b[index + 39] = 0  # Kobel's independent zero must fail.
    p['events_hex'] = b.hex()
    out = decode(p)
    assert not out['sides'][1]['all_player_counters_match']
    assert next(c for c in out['sides'][1]['player_checks'] if c['person_name'] == 'Gregor Kobel')['event_attempted'] == 1
    b[index + 39] = 25
    p['events_hex'] = b.hex()
    assert decode(p)['sides'][1]['unresolved_actor_slots'] == [25]


@pytest.mark.parametrize('field', ['fixture_key', 'team_index_word', 'canonical_team_id', 'person_index_word', 'row_sha256', 'crosses_attempted'])
def test_wrong_wire_identity_scope_or_projected_counter_rejects(field):
    p = packet()
    row = p['players'][0]
    row[field] = '0' * 64 if field == 'row_sha256' else row[field] + 1
    with pytest.raises(ValueError):
        decode(p)


def test_duplicate_actor_and_duplicate_events_reject():
    p = packet()
    p['players'].append(copy.deepcopy(p['players'][0]))
    with pytest.raises(ValueError, match='slot'):
        decode(p)
    p = packet()
    p['events_hex'] += p['events_hex'][:112]
    with pytest.raises(ValueError, match='Duplicate'):
        decode(p)


def test_no_geometry_preserves_counters_and_native_clocks_keep_their_real_width():
    p = packet()
    p['pitch_geometry'] = None
    out = decode(p)
    assert out['state'] == 'available' and all(r['analytical_event_position'] is None for r in out['cross_events'])
    raw = bytes.fromhex(p['events_hex'])
    for r in out['cross_events']:
        at = r['record_index'] * 56
        assert r['native_clock_start_raw'] == struct.unpack_from('<H', raw, at + 34)[0]
        assert r['native_clock_end_raw'] == struct.unpack_from('<H', raw, at + 50)[0]
        assert r['displayed_time'] is None


def test_analytical_event_bands_use_event_direction_and_keep_outside_points_unknown():
    p = packet()
    b = bytearray.fromhex(p['events_hex'])
    at = next(i for i in range(0, len(b), 56) if b[i + 42] in range(12, 18))
    eid = struct.unpack_from('<I', b, at + 44)[0]
    struct.pack_into('<ff', b, at + 24, 0., 40.)
    b[at + 49] |= 1
    p['events_hex'] = b.hex()
    row = next(r for r in decode(p)['cross_events'] if r['event_id'] == eid)
    assert row['analytical_event_position']['analytical_pitch_third'] == 'attacking'
    b[at + 49] &= ~1
    p['events_hex'] = b.hex()
    assert next(r for r in decode(p)['cross_events'] if r['event_id'] == eid)['analytical_event_position']['analytical_pitch_third'] == 'defensive'
    struct.pack_into('<f', b, at + 24, 1000.)
    p['events_hex'] = b.hex()
    assert next(r for r in decode(p)['cross_events'] if r['event_id'] == eid)['analytical_event_position']['analytical_pitch_third'] is None


def service(monkeypatch):
    from fm_live_mcp import match_data_query, live_retained_shots
    p = packet()
    f = {**p['fixture'], 'fixture_ref': 'f'}
    teams = [{'team_index': f[k]['database_index'], 'team_identity_word': f[k]['native_id']} for k in ('home_team', 'away_team')]
    data = dict(capture=dict(fixtures=[dict(fixture=f, native_match_key=p['native_match_key'])]),
                _live_capture_epoch=('epoch',), retained_players=p['players'], team_totals=dict(records=[dict(result_key=p['native_match_key'], teams=teams)]),
                raw_frames=[dict(fixture_ref='f', key=p['native_match_key'], raw=bytes.fromhex(p['raw_frame_hex']))])
    b = SimpleNamespace(lock=nullcontext(), _read_scope=lambda _: nullcontext(), _current=lambda _: None,
                        _player_layout=lambda _: (0,), _world_state=lambda *a: (SimpleNamespace(verify=lambda: None), {}, None),
                        get_save=lambda _: dict(save=dict(current_date='2030-11-25')))
    source = dict(state='available', events=bytes.fromhex(p['events_hex']), pitch_geometry=p['pitch_geometry'])
    monkeypatch.setattr(q, 'verify_native', lambda *a: None)
    monkeypatch.setattr(match_data_query, 'capture_epoch', lambda *a: ('epoch',))
    monkeypatch.setattr(match_data_query, 'capture_live', lambda *a, **kw: data)
    monkeypatch.setattr(live_retained_shots, 'capture_source', lambda *a, **kw: source)
    return b, data, source


def test_pages_use_whole_source_counters_and_pins_include_selectors_and_geometry(monkeypatch):
    b, data, source = service(monkeypatch)
    first = q.get_retained_cross_events(b, 's', 'f', team_native_id=688, limit=2)
    assert first['state'] == 'available' and first['total_count'] == 37 and len(first['cross_events']) == 2
    assert first['sides'][0]['captured_player_counter_checks'] == 20
    assert sum(c['attempts'] for c in first['sides'][0]['event_position_counts']) == 37
    second = q.get_retained_cross_events(b, 's', 'f', team_native_id=688, offset=2, limit=2, expected_source_id=first['source_id'])
    assert not {r['event_id'] for r in first['cross_events']} & {r['event_id'] for r in second['cross_events']}
    with pytest.raises(ValueError, match='continuation'):
        q.get_retained_cross_events(b, 's', 'f', offset=2)
    with pytest.raises(ValueError, match='source or selectors'):
        q.get_retained_cross_events(b, 's', 'f', team_native_id=679, offset=2, expected_source_id=first['source_id'])
    source['pitch_geometry'] = {**source['pitch_geometry'], 'half_width_native': 35.}
    with pytest.raises(ValueError, match='source or selectors'):
        q.get_retained_cross_events(b, 's', 'f', team_native_id=688, offset=2, expected_source_id=first['source_id'])


def test_known_zero_actor_stays_zero_but_missing_actor_stays_unknown(monkeypatch):
    b, _, _ = service(monkeypatch)
    zero = q.get_retained_cross_events(b, 's', 'f', team_native_id=688, person_native_id=98040383)
    unknown = q.get_retained_cross_events(b, 's', 'f', team_native_id=688, person_native_id=99999)
    assert zero['state'] == 'available' and zero['total_count'] == 0
    assert unknown['state'] == 'unavailable_selected_cross_actor' and unknown['total_count'] is None


def test_truncated_roster_reload_and_missing_native_source_do_not_publish(monkeypatch):
    from fm_live_mcp import match_data_query
    b, data, _ = service(monkeypatch)
    data['retained_players'].pop()
    with pytest.raises(ValueError, match='full native roster'):
        q.get_retained_cross_events(b, 's', 'f')
    b, _, _ = service(monkeypatch)
    calls = iter([('epoch',), ('reload',)])
    monkeypatch.setattr(match_data_query, 'capture_epoch', lambda *a: next(calls))
    with pytest.raises(ValueError, match='career or save changed'):
        q.get_retained_cross_events(b, 's', 'f')
    b, _, source = service(monkeypatch)
    source['state'] = 'unavailable_not_retained'
    out = q.get_retained_cross_events(b, 's', 'f')
    assert out['total_count'] is None and out['cross_events'] == []


def test_native_guards_reject_drift():
    with pytest.raises(ValueError, match='binding changed'):
        q.verify_native(lambda a, n: bytes(n), 0)


def test_tool_schema_is_readonly_and_rejects_boolean_selectors():
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.exceptions import ToolError
    from fm_live_mcp.retained_cross_event_tools import register_retained_cross_event_tools
    async def run():
        m = FastMCP('test')
        register_retained_cross_event_tools(m, None)
        t, = await m.list_tools()
        assert t.name == 'fm_get_retained_cross_events' and t.annotations.readOnlyHint and not t.annotations.destructiveHint
        assert set(t.inputSchema['required']) == {'session_id', 'fixture_ref'}
        assert 'box occupation remain unknown' in t.description
        for extra in [dict(team_native_id=True), dict(limit=True), dict(offset=-1)]:
            with pytest.raises(ToolError, match='validation error'):
                await m.call_tool(t.name, dict(session_id='s', fixture_ref='f', **extra))
    asyncio.run(run())
