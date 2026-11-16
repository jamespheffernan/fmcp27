"""Live-gated inbox / calendar checks (skipped unless one supported FM27 process and the helper run).

Reads are emulated on copied memory; nothing is written to the game.
"""
from datetime import date, timedelta
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _live_available():
    if sys.platform != 'darwin':
        return False
    try:
        from fm_live_mcp.bridge import Bridge, discover_processes
        return Bridge().helper.is_file() and len(discover_processes()) == 1
    except Exception:  # noqa: BLE001
        return False


pytestmark = pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')


@pytest.fixture(scope='module')
def live():
    sys.path.insert(0, str(ROOT / 'scripts'))
    from fmdb_ui_read import open_vm
    session, memory, vm = open_vm()
    yield session, vm
    memory.close()
    session.close()


def test_inbox_count_and_items_stable(live):
    from fm_live_mcp.fmdb import ui_recipes_news as N
    _, vm = live
    view = N.viewer(vm)
    first = N.inbox_entries(vm, view.human)
    second = N.inbox_entries(vm, view.human)
    assert len(first) == len(second) > 0
    assert [e.unid for e in first] == [e.unid for e in second]
    rows_a = N.inbox(vm, limit=3)
    rows_b = N.inbox(vm, limit=3)
    assert [r['unid'] for r in rows_a] == [e.unid for e in first[:3]]
    for a, b in zip(rows_a, rows_b):
        assert (a['subject'], a['body'], a['date'], a['read']) == (b['subject'], b['body'], b['date'], b['read'])
        assert a['subject'] and a['body'] and a['date']
        assert a['read'] == a['read_flag']           # NewsItemHasBeenRead == item flags bit 0


def _bridge_fixtures(team_native_ids, first, last):
    from fm_live_mcp.bridge import Bridge
    from fm_live_mcp.fmdb import ui_recipes_news as N
    bridge = Bridge()
    session = bridge.attach()['session_id']
    rows = {}
    for native in team_native_ids:
        for year in range(first.year, last.year + 1):
            lo = max(first, date(year, 1, 1)).isoformat()
            hi = min(last, date(year, 12, 31)).isoformat()
            cursor = None
            while True:
                page = bridge.find_fixtures(session, year=year, date_from=lo, date_to=hi,
                                            team_native_id=native, max_matches=100, cursor=cursor)
                for row in page['fixtures']:
                    rows[N.bridge_fixture_key(row)] = row
                cursor = page.get('next_cursor')
                if not cursor:
                    break
    return list(rows.values())


def test_calendar_fixtures_match_fixture_reader(live):
    from fm_live_mcp.fmdb import ui_recipes_news as N
    _, vm = live
    rows = N.calendar(vm, days=60)
    assert rows and rows[0]['_meta']['rng_uses'] == 0
    fixtures = [r for r in rows if r['kind'] == 'fixture']
    assert fixtures
    natives = set()
    for row in fixtures:
        team = N.resolve(vm, row['team']['id'])
        natives.add(struct.unpack('<I', vm.reader.read(team + 0xC, 4))[0])
    first = date.fromisoformat(rows[0]['date'])
    last = first + timedelta(days=59)
    result = N.cross_check_fixtures(fixtures, _bridge_fixtures(sorted(natives), first, last))
    # A fixture played earlier on the current game day stays in the calendar without its stadium
    # (seen on 13 Dec 2030 after West Ham v Newcastle); every other difference is a failure.
    today = rows[0]['date']
    played_today = [m for m in result['mismatched'] if m['key'][0] == today and set(m['differs']) == {'stadium'}
                    and m['calendar']['stadium'] is None]
    mismatched = [m for m in result['mismatched'] if m not in played_today]
    assert not mismatched, mismatched
    assert not result['calendar_only'], result['calendar_only']
    assert not result['bridge_only'], result['bridge_only']
    assert len(result['matched']) + len(played_today) == len(fixtures)


def test_known_next_fixture(live):
    """Owner-confirmed fact for the Newcastle career at 10 Dec 2030."""
    from fm_live_mcp.fmdb import ui_recipes_news as N
    _, vm = live
    view = N.viewer(vm)
    if view.current_date != '2030-12-10':
        pytest.skip('career date moved on')
    nxt = next(r for r in N.calendar(vm, days=7) if r['kind'] == 'fixture'
               and r['team']['name'] == 'Newcastle United')
    assert nxt['date'] == '2030-12-10'
    assert nxt['competition']['name'] == 'UEFA Champions League'
    assert (nxt['home_team'], nxt['away_team']) == ('Villarreal C.F.', 'Newcastle United')
    assert nxt['venue'] == 'away' and nxt['stadium'] == 'Estadio de La Cerámica'
