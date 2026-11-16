"""Compatibility shim controls preserve the current native PERSON route."""
import pytest
from fm_live_mcp import active_match_people as people, native_match_stats_person as native, world
from historical_match_identity_fixture import historical_team_identity_contract
from test_current_player_statistics33_integration import Joint33
from test_native_match_stats_person import Genuine


def test_old_partial33_packet_requires_its_declared_historical_identity_contract(historical_team_identity_contract):
    f = Joint33()
    # Causal diagnosis: current production requires operands this partial journal
    # never captured. The versioned replay retains all41 original identities.
    with pytest.raises(ValueError, match='Missing qualified33-field byte'):
        historical_team_identity_contract(world.ReadSet(f.read), f.base, f.engine, identity_only=True)
    result = people.inspect_canonical(world.ReadSet(f.read), f.base, f.engine, identity_only=True)
    assert sum(row['person'] is not None for row in result['rows']) == 41
    assert result == people._inspect_canonical_team(f.read, f.base, f.engine, identity_only=True)


@pytest.mark.parametrize('nested', [False, True])
def test_genuine154_unmarked_reader_keeps_new_route_inside_historical_fixture(nested):
    f = Genuine()
    read = world.ReadSet(f.read)
    if nested:
        read = world.ReadSet(read)
    result = people.inspect_canonical(read, f.base, f.engine, identity_only=True)
    read.verify()
    assert sum(row['person'] is not None for row in result['rows']) == 43
    assert result['rows'][43]['person']['name'] == 'Rhys Godwin'
    assert result['rows'][45]['person']['name'] == 'José Luis Montero'
    assert result['rows'][43]['identity_state'] == native.IDENTITY_STATE


@pytest.mark.parametrize('offset', [native.GETTER_RVA, 0x55FA810, 0x56D2D78])
def test_genuine154_missing_new_source_still_refuses_inside_historical_fixture(offset):
    f = Genuine()
    del f.memory[f.base + offset]
    with pytest.raises(ValueError, match='Missing genuine captured operand'):
        people.inspect_canonical(world.ReadSet(f.read), f.base, f.engine, identity_only=True)
