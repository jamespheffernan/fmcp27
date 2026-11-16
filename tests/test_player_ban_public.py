"""Exercise the public batch with real referenced players and checked physical data."""
import struct
import pytest

from fm_live_mcp import player_ban_source
from fm_live_mcp.bridge import BridgeError
from test_assessment_public import (public_assessment_memory, bridge, shortlist_public_memory,
                                    prepared_tactics_memory, database_memory, memory,
                                    team_memory, world_memory)


@pytest.fixture
def ban_world(public_assessment_memory, bridge):
    m = public_assessment_memory
    for rva, expected in player_ban_source.NATIVE_SPANS:
        m['put'](m['base'] + rva, expected)
    ref = m['assessment_player_ref']
    player = bridge.player_refs[ref]['address']
    secondary = m['allocate'](0x40)
    ban = m['allocate'](0x20)
    m['q'](player + 0xF0, secondary)
    m['vec'](secondary + 0x18, [ban])
    raw = bytearray(0x20)
    raw[5] = 20
    struct.pack_into('<HH', raw, 0x10, 283, 2030)
    raw[0x1C] = 2
    m['put'](ban, bytes(raw))
    return m, ref, player, secondary, ban


def test_query_preserves_repeats_and_returns_native_text(bridge, ban_world):
    _, ref, *_ = ban_world
    before = dict(bridge.player_refs)
    result = bridge.get_player_bans(bridge.session, [ref, ref])
    first, second = result['players']
    assert first == second and first['player_ref'] == ref
    assert first['display_name'] == 'Test Müller'
    assert first['record_kind'] == 'actual' and first['native_identity']['native_id'] == 12345
    assert first['source_state'] == 'present_records' and first['physical_record_count'] == 1
    record, = first['records']
    assert record['main_text']['text'] == 'Banned for 2 international matches'
    assert record['stored_start_date']['value'] == '2030-10-10'
    assert result['eligibility_state'] == 'not_evaluated'
    assert before == bridge.player_refs


def test_present_empty_and_missing_secondary_are_distinct(bridge, ban_world):
    m, ref, player, secondary, _ = ban_world
    m['put'](secondary + 0x18, bytes(24))
    empty, = bridge.get_player_bans(bridge.session, [ref])['players']
    assert (empty['source_state'], empty['records'], empty['physical_record_count']) == (
        'present_empty', [], 0)
    m['q'](player + 0xF0, 0)
    absent, = bridge.get_player_bans(bridge.session, [ref])['players']
    assert (absent['source_state'], absent['records'], absent['physical_record_count']) == (
        'secondary_absent', None, None)


def test_late_drift_rejects_checked_batch(bridge, ban_world, monkeypatch):
    m, ref, _, _, ban = ban_world
    project = player_ban_source.project
    def mutate_after_read(*args):
        projected = project(*args)
        m['put'](ban + 0x1D, b'\x01')
        return projected
    monkeypatch.setattr(player_ban_source, 'project', mutate_after_read)
    with pytest.raises(BridgeError, match='changed during read'):
        bridge.get_player_bans(bridge.session, [ref])
    assert ref in bridge.player_refs


def test_unknown_and_stale_refs_reject_entire_batch(bridge, ban_world):
    m, ref, *_ = ban_world
    with pytest.raises(BridgeError, match='Unknown or expired'):
        bridge.get_player_bans(bridge.session, [ref, 'bad'])
    assert ref in bridge.player_refs
    m['put'](0x1394, struct.pack('<I', 54321))
    with pytest.raises(BridgeError, match='identity changed'):
        bridge.get_player_bans(bridge.session, [ref])
    assert ref not in bridge.player_refs
