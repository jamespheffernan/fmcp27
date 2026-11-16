from contextlib import contextmanager
from copy import deepcopy
import asyncio

import pytest

from fm_live_mcp import bridge as module, players, server, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge


@pytest.fixture
def query(bridge, monkeypatch):
    memory = {0x100: b'data'}
    snapshot = world.ReadSet(lambda address, size: memory.get(address, bytes(size))[:size])
    coach = {'name': 'Coach', 'club': {'name': 'Club'}, 'team_address': 0x8000}
    save = {'name': 'Career', 'current_date': '2030-10-28', 'coaches': [coach]}
    status = {'state': 'checked', 'flagged': False, 'stored_injury_record_count': 0}
    slots = [{'slot_index': i, 'category': 'starting_position' if i < 11 else 'bench' if i < 20 else 'outside_selected_bench_boundary',
              'state': 'selected_person' if i < 20 else 'empty_slot',
              'person': {'database_index': i} if i < 20 else None} for i in range(26)]
    sheet = {'team': {'database_index': 545}, 'source_state': 'available',
             'unavailable_reason': None, 'role_boundary_state': 'native_first_11_and_stored_selected_end', 'slots': slots}
    calls = {'opened': 0, 'closed': 0, 'projected': []}

    @contextmanager
    def scope(session):
        assert bridge.lock._is_owned()
        calls['opened'] += 1
        try:
            yield
        finally:
            calls['closed'] += 1

    def pointer(read, address):
        return address + 0x1000

    def person(read, base, people, address):
        index = (address - 0x61000) // 8
        return address, 0, {'record_kind': 'actual', 'display_name': None,
                            'native_identity': {'database_index': index, 'native_id': 100 + index, 'random_id': None}}, 0, 0

    def decode(read, address, *args, **kwargs):
        index = (address - 0x61000) // 8
        return {'record_kind': 'actual', 'display_name': f'Player {index}',
                'native_identity': {'database_index': index, 'native_id': 100 + index, 'random_id': None}}, (index,)

    def project(read, base, primary, kind, *args):
        read(0x100, 4)
        calls['projected'].append(primary)
        return deepcopy(status)

    monkeypatch.setattr(bridge, '_read_scope', scope)
    monkeypatch.setattr(bridge, '_player_layout', lambda process: tuple(0x100000 + rva for rva in players.RVA))
    monkeypatch.setattr(bridge, '_world_state', lambda *args: (snapshot, save, None))
    monkeypatch.setattr(module.player_injury_status, 'verify_native', lambda *args: None)
    monkeypatch.setattr(module.player_injury_status, 'calendar', lambda *args: (__import__('datetime').date(2030, 10, 28), 2030, 301))
    monkeypatch.setattr(module.player_injury_status, 'project', project)
    monkeypatch.setattr(module.database, 'table', lambda *args: {'start': 0x60000, 'count': 100})
    monkeypatch.setattr(module.live_team_sheet_source, 'inspect', lambda *args: deepcopy(sheet))
    monkeypatch.setattr(module.world, 'pointer', pointer)
    monkeypatch.setattr(module.assessment_people, '_person', person)
    monkeypatch.setattr(bridge, '_roster_player', decode)
    return {'memory': memory, 'snapshot': snapshot, 'save': save, 'sheet': sheet,
            'status': status, 'calls': calls, 'project': project}


def test_default_one_pass_checked_all_picked_and_preserves_empty_slots(bridge, query):
    result = bridge.get_player_injury_status(bridge.session)
    assert result['state'] == 'available' and result['count'] == 20
    assert result['checked_negative_count'] == 20 and result['flagged_count'] == 0
    assert len(result['selection']['slots']) == 26
    assert result['selection']['slots'][25]['person_index'] is None
    assert result['players'][0]['person']['display_name'] == 'Player 0'
    assert all(row['player_ref'] in bridge.player_refs for row in result['players'])
    assert query['calls']['opened'] == query['calls']['closed'] == 1
    assert result['as_of_date'] == '2030-10-28' and result['fixture_clearance'] == 'not_assessed'


def test_duplicate_pick_is_preserved_projected_once_and_reuses_ref(bridge, query):
    query['sheet']['slots'][1]['person']['database_index'] = 0
    result = bridge.get_player_injury_status(bridge.session)
    assert result['count'] == 20 and result['unique_person_count'] == 19
    assert len(query['calls']['projected']) == 19
    assert result['players'][0]['player_ref'] == result['players'][1]['player_ref']


def test_unsupported_never_counted_as_uninjured(bridge, query):
    query['status'].update(state='unsupported', flagged=None)
    result = bridge.get_player_injury_status(bridge.session)
    assert result['state'] == 'partial' and result['unsupported_count'] == 20
    assert result['checked_negative_count'] == 0 and not result['complete_status_coverage']


def test_missing_or_unresolved_selection_not_an_empty_injury_negative(bridge, query):
    query['sheet'].update(source_state='unavailable', unavailable_reason='missing', slots=None)
    result = bridge.get_player_injury_status(bridge.session)
    assert result['state'] == 'unavailable' and result['unavailable_reason'] == 'missing'
    assert not result['complete_selected_person_coverage'] and result['players'] == []
    assert query['calls']['projected'] == [] and bridge.player_refs == {}


def test_mutation_rejects_whole_response_before_minting_refs(bridge, query, monkeypatch):
    def changed(*args):
        result = query['project'](*args)
        if len(query['calls']['projected']) == 20:
            query['memory'][0x100] = b'edit'
        return result
    monkeypatch.setattr(module.player_injury_status, 'project', changed)
    with pytest.raises(BridgeError, match='no partial read'):
        bridge.get_player_injury_status(bridge.session)
    assert bridge.player_refs == {} and query['calls']['closed'] == 1


def test_explicit_refs_cannot_silently_use_coach_selection(bridge):
    with pytest.raises(BridgeError, match='coach_name applies'):
        bridge.get_player_injury_status(bridge.session, ['ref'], 'Coach')
    for refs in ([], [1], [''], ['ref'] * 101):
        with pytest.raises(BridgeError):
            bridge.get_player_injury_status(bridge.session, refs)


def test_public_schema_default_and_readonly_annotation():
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'fm_get_player_injury_status')
    assert tool.inputSchema['required'] == ['session_id']
    assert tool.inputSchema['properties']['player_refs']['default'] is None
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint


def test_compact_virtual_reference_is_explicitly_unknown_not_negative(bridge, query, monkeypatch):
    token = (module.virtual_identity.BINDING_KIND, 5, 105, 0)
    native = {'database_index': 5, 'native_id': 105, 'random_id': 0}
    bridge.player_refs['virtual'] = {
        'record_kind': 'virtual', 'binding_kind': module.virtual_identity.BINDING_KIND,
        'address': 0x9000, 'tables': tuple(0x100000 + rva for rva in players.RVA),
        'database_index': 5, 'person_offset': 0x20, 'identity': token,
    }
    monkeypatch.setattr(module.virtual_identity, 'inspect', lambda *args: {
        'identity': token, 'native_identity': native,
    })
    query['status'].update(state='unsupported', flagged=None)
    result = bridge.get_player_injury_status(bridge.session, ['virtual'])
    assert result['state'] == 'partial' and result['unsupported_count'] == 1
    assert result['checked_negative_count'] == 0
    assert result['players'][0]['person']['native_identity'] == native
    bridge.player_refs['virtual']['person_offset'] = 0
    with pytest.raises(BridgeError, match='membership changed'):
        bridge.get_player_injury_status(bridge.session, ['virtual'])


def test_today_mismatch_rejected_before_projection(bridge, query, monkeypatch):
    monkeypatch.setattr(module.player_injury_status, 'calendar', lambda *args: (
        __import__('datetime').date(2030, 10, 29), 2030, 302))
    with pytest.raises(BridgeError, match='date differs'):
        bridge.get_player_injury_status(bridge.session)
    assert query['calls']['projected'] == [] and bridge.player_refs == {}


def test_unknown_or_stale_explicit_reference_does_not_publish_partial(bridge, query):
    with pytest.raises(BridgeError, match='Unknown or expired'):
        bridge.get_player_injury_status(bridge.session, ['missing'])
    assert query['calls']['projected'] == [] and bridge.player_refs == {}


def test_bench_from_the_next_fixture_rule_answers_and_names_its_source(bridge, query):
    """A session with no stored end: the sheet's bench comes from the selection screen's rule for
    the cached next fixture, and the report covers that XI and bench and says so."""
    query['sheet'].update(
        role_boundary_state=module.live_team_sheet_source.NEXT_FIXTURE_END, bench_end=20,
        bench_boundary_source='selection_screen_rule_for_cached_next_fixture',
        bench_boundary_unavailable_reason=None,
        bench_fixture={'date': '2030-10-30', 'managed_side': 'away', 'named_substitute_cap': 9})
    result = bridge.get_player_injury_status(bridge.session)
    assert result['state'] == 'available' and result['count'] == 20
    assert result['complete_selected_person_coverage'] is True and result['unavailable_reason'] is None
    assert [row['selection_category'] for row in result['players']] == ['starting_position'] * 11 + ['bench'] * 9
    assert result['selection']['bench_boundary_source'] == 'selection_screen_rule_for_cached_next_fixture'
    assert result['selection']['bench_end'] == 20
    assert result['selection']['bench_fixture']['named_substitute_cap'] == 9
    assert 'not a submitted match squad' in result['limitations']


def test_unresolved_bench_end_reports_nobody_and_the_reason(bridge, query):
    for slot in query['sheet']['slots'][11:]:
        slot.update(category=None, state='stored_person_boundary_unresolved' if slot['person'] else 'empty_slot')
    query['sheet'].update(role_boundary_state='stored_boundary_unmapped', bench_end=None,
                          bench_boundary_source=None, bench_boundary_unavailable_reason='next_fixture_not_cached')
    result = bridge.get_player_injury_status(bridge.session)
    assert result['state'] == 'unavailable' and result['unavailable_reason'] == 'selection_boundary_unresolved'
    assert result['players'] == [] and result['count'] == 0
    assert result['complete_selected_person_coverage'] is False
    assert result['selection']['bench_boundary_unavailable_reason'] == 'next_fixture_not_cached'
