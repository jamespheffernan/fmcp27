"""Live-gated PERSON / CLUB / PLAYER_REPORT checks (skipped unless FM27 runs).

Structural checks compare the recipes with the game's own aggregates. Ground-truth checks
against the owner's screens (Newcastle, 10 Dec 2030) run only with FMDB_REFERENCE_SAVE=1,
because the save moves on.
"""
import os
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_ui_live import _live_available  # noqa: E402

pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')
REFERENCE = os.environ.get('FMDB_REFERENCE_SAVE') == '1'


@pytest.fixture(scope='module')
def live():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm, managed_team
    session, memory, vm = open_vm()
    yield session, vm, managed_team(session)
    memory.close()
    session.close()


def _roster(session, team):
    from fm_live_mcp import world
    return world.vector(session.reader.read, team + 0x38, 512)


def test_person_data_protocol_is_order_independent(live):
    from fm_live_mcp.fmdb import ui_recipes_person as P
    session, vm, team = live
    pid = P.person_id(vm, session.reader.read, _roster(session, team)[0])
    alone = P.DataReader(vm, vm.build(P.DATABASE_RECORD, {'dref': pid}))
    first = P._value(alone.get('HPPo'))
    after = P.DataReader(vm, vm.build(P.DATABASE_RECORD, {'dref': pid}))
    after.get('d1g4')                       # HappinessTraining first used to empty HPPo
    assert P._value(after.get('HPPo')) == first
    assert isinstance(first, list) and first


def test_player_status_shape(live):
    from fm_live_mcp.fmdb import ui_recipes_person as P
    session, vm, team = live
    st = P.player_status(vm, _roster(session, team)[0], read=session.reader.read)
    f = st['fields']
    assert st['handler'] == 'PERSON_UI_HANDLER'
    assert isinstance(f['name'], str) and f['name']
    assert isinstance(f['morale'], str) and isinstance(f['morale_value'], int)
    assert isinstance(f['happiness_level'], int)
    assert isinstance(f['promises'], list) and isinstance(f['active_interested_clubs'], list)
    assert st['contract']['squad_status_actual']['qvJ6']
    assert not st['failed_data_keys']


def test_first_team_very_happy_matches_club_count(live):
    """Pohl > 59 over the first team equals the club's own HappyPlayersCount (cwnt)."""
    from fm_live_mcp.fmdb import ui_recipes_person as P
    from fm_live_mcp import players
    session, vm, team = live
    read = session.reader.read
    count = 0
    for primary in _roster(session, team):
        if struct.unpack('<Q', read(primary, 8))[0] not in (session.base + players.RVA[0],
                                                            session.base + players.STAFF_RVA[0]):
            continue
        st = P.player_status(vm, primary, keys=['Pohl'], read=read, contract=False)
        count += st['squad_screen_band'] == 'very happy'
    cv = P.club_vision(vm, read=read, members=False)
    assert count == cv['fields']['happy_players']['cwnt']
    if REFERENCE:
        assert cv['fields']['happy_players'] == {'cwnt': 23, 'ptvl': 47}


def test_club_vision(live):
    from fm_live_mcp.fmdb import ui_recipes_person as P
    session, vm, team = live
    cv = P.club_vision(vm, read=session.reader.read)
    board, fans = cv['objectives']['board'], cv['objectives']['supporters']
    assert cv['handler'] == 'CLUB_UI_HANDLER' and cv['request_params_used'] > 0
    assert board['actionable'] and fans['culture']
    assert len(cv['board_members']) == cv['fields']['board_members_count']
    if not REFERENCE:
        return
    rows = lambda lst: [(o['objective'], o['importance']) for o in lst]  # noqa: E731
    assert rows(board['actionable']) == [
        ('Work within wage budget', 'Required'), ('Sign players to sell for a profit', 'Preferred'),
        ('Maximum one-year contracts for players over the age of 33', 'Preferred'),
        ('Maximum two-year contracts for players over the age of 31', 'Preferred'),
        ('Maximum three-year contracts for players over the age of 29', 'Favoured'),
        ('Minimum 4-year contracts for first-team players', 'Preferred')]
    assert rows(board['culture']) == [
        ('Make the most of set pieces', 'Preferred'), ('Play attacking football', 'Preferred'),
        ('Play entertaining football', 'Favoured'), ('Play high-tempo pressing football', 'Favoured')]
    assert rows(fans['actionable']) == [('Finish above Sunderland in the league', 'Desired'),
                                        ('Qualify for the UEFA Europa League', 'Required')]
    assert sorted(rows(fans['culture'])) == sorted([
        ('Play attacking football', 'Required'), ('Play high-tempo pressing football', 'Required'),
        ('Play entertaining football', 'Required'), ('Play possession football', 'Preferred'),
        ('Make the most of set pieces', 'Preferred')])
    assert len(fans['all']) == 7
    assert rows(board['competitions_this_season']) == [
        ('Reach the latter stages of the UEFA Champions League', 'Required'),
        ('Qualify for the UEFA Champions League', 'Required'),
        ('Be competitive in the EFL Cup', 'Favoured'),
        ('Be competitive in the Community Shield', 'Favoured')]   # FA Cup row: not returned
    assert cv['fields']['supporter_board_influence'] == 'Low'
    wages = cv['fields']['wages']
    assert wages['Nj5T'] == '£258,727,924' and wages['LjzV'] == '£284,229,244'
    by_status = {r['name']: (r['h1Lu'], r[' 2Ez']) for r in wages['cU18'][:6]}
    assert by_status == {'Star Player': (1, '£7,139,496'), 'Important Player': (8, '£91,965,224'),
                         'Regular Starter': (8, '£73,513,544'), 'Squad Player': (5, '£24,177,192'),
                         'Impact Sub': (0, '£0'), 'Fringe Player': (1, '£6,500,000')}
    members = [(m['name'], m['role'], m['nationality']) for m in cv['board_members']]
    assert members[:3] == [('Y. Al-Rumayyan', 'Chairperson', 'Saudi'),
                           ('D. Hopkinson', 'Managing Director', 'Canadian'),
                           ('J. Reuben', 'Director', 'English')]
    assert [m[1:] for m in members[3:]] == [('Director', 'Saudi'), ('Director', 'Saudi')]


def test_scout_report_for_reported_player(live):
    from fm_live_mcp import world
    from fm_live_mcp.fmdb import ui_recipes_person as P
    session, vm, team = live
    read = session.reader.read
    human = world.loaded(world.ReadSet(read), session.base)[0]['coaches'][0]['manager_address']
    manager = vm.object_ref(human + 0x548)
    person = None
    for offset in (0x128, 0x110):            # the HUMAN's two report vectors
        begin, end = struct.unpack('<QQ', read(human + offset, 16))
        for i in range(min((end - begin) // 8, 400)):
            row = struct.unpack('<Q', read(begin + 8 * i, 8))[0]
            target = struct.unpack('<Q', read(row, 8))[0] if row else 0
            if target and vm.object_ref(target) >> 24 == 1:
                person = vm.object_ref(target)
                break
        if person is not None:
            break
    if person is None:
        pytest.skip('no scout report on the manager')
    rep = P.scout_report(vm, person, manager)
    assert rep['handler'] == 'PLAYER_REPORT_UI_HANDLER'
    assert all(v.startswith('ok') for v in rep['inputs'].values())
    assert rep['summary']['recommendation'] and rep['summary']['report_date']
    assert isinstance(rep['summary']['pros'], list)
