import struct

import pytest

from fm_live_mcp import players, virtual, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_player_profile import populate, profile_memory
from test_player_staff import staff_memory
from test_players import memory
from test_virtual import virtual_memory
from test_world import world_memory


@pytest.mark.parametrize('include_profile', [False, True])
def test_required_team_identity_is_additive_without_changing_rich_profiles(
        bridge, monkeypatch, profile_memory, include_profile):
    m = profile_memory
    bind(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    result = bridge.get_team_squad(bridge.session, team['team_ref'], include_profile=include_profile)
    assert result['count'] == team['count']
    assert result['complete_native_roster'] is True
    assert 'profile_policy' not in result  # Preserve the existing required response.
    addresses = [m['regular'], m['compact']] if m['is_virtual'] else [0x1000]
    for row, address in zip(result['players'], addresses):
        if address == m.get('compact'):
            legacy, _ = virtual.decode(m['read'], address, m['tables'], include_profile=include_profile)
            expected = {'database_index': 0, 'native_id': 12345, 'random_id': None}
        else:
            legacy, _ = players.decode(m['read'], address, m['tables'], include_profile=include_profile)
            expected = {'database_index': 0, 'native_id': 678 if m['is_virtual'] else 12345,
                        'random_id': None}
        assert row['native_identity'] == expected
        assert {k: v for k, v in row.items() if k not in ('native_identity', 'player_ref')} == legacy
        assert bridge.get_player(bridge.session, row['player_ref'], include_profile=include_profile)['player'] == legacy


def test_same_name_players_keep_distinct_canonical_ids_in_required_detail_rows(
        bridge, monkeypatch, database_memory):
    m = database_memory
    populate(m, 0x1000)
    duplicate = m['allocate'](players.SIZE)
    m['put'](duplicate, m['read'](0x1000, players.SIZE))
    m['put'](duplicate + 0x390, struct.pack('<III', 1, 67890, 0))
    m['vec'](m['team'] + 0x38, [0x1000, duplicate])
    m['vec'](m['headers']['people'], [0x1388, duplicate + 0x388])
    bind(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    required = bridge.get_team_squad(bridge.session, team['team_ref'], include_profile=True)
    snapshot = world.ReadSet(m['read'])
    available = [bridge._roster_player(snapshot, address, m['tables'], False, {},
                                      include_profile=True, profile_policy='available')[0]
                 for address in (0x1000, duplicate)]
    snapshot.verify()
    assert required['count'] == len(available) == 2
    assert [p['name'] for p in required['players']] == ['Test Müller', 'Test Müller']
    identities = [p['native_identity'] for p in required['players']]
    assert identities == [p['native_identity'] for p in available]
    assert identities == [{'database_index': 0, 'native_id': 12345, 'random_id': None},
                          {'database_index': 1, 'native_id': 67890, 'random_id': 0}]
    # A retained row's canonical ID resolves one current profile despite identical names.
    matches = [p for p in required['players'] if p['native_identity']['native_id'] == 67890]
    assert len(matches) == 1 and matches[0]['native_identity']['database_index'] == 1
    assert len({p['player_ref'] for p in required['players']}) == 2


def test_required_identity_drift_publishes_no_partial_roster_or_new_refs(
        bridge, monkeypatch, database_memory):
    m = database_memory
    m['vec'](m['team'] + 0x38, [0x1000])
    bind(bridge, monkeypatch, m)
    team = bridge.get_club_squads(bridge.session)['squads'][0]
    bridge.player_refs['existing'] = {'kept': True}
    original = players.decode

    def mutate(*args, **kwargs):
        result = original(*args, **kwargs)
        m['put'](0x1394, struct.pack('<I', 777))
        return result

    monkeypatch.setattr(players, 'decode', mutate)
    with pytest.raises(BridgeError, match='no partial roster.*identity disagrees'):
        bridge.get_team_squad(bridge.session, team['team_ref'])
    assert bridge.player_refs == {'existing': {'kept': True}}
    assert team['team_ref'] not in bridge.team_refs
