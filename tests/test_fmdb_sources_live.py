"""Collection tables against the running game, checked with the hand-built decoders.

Skipped unless a supported FM27 process and the native helper are available.
"""
import random
import struct
import sys

import pytest


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
def engine():
    from fm_live_mcp.fmdb.engine import Engine
    e = Engine.open()
    yield e
    e.close()


def _table(engine, module, name):
    from fm_live_mcp.fmdb import sources
    found, failures = sources.discover(engine, only=[module])
    assert not failures
    return next(t for _, t in found if t.name == name)


def test_main_contract_wages_match_the_wage_decoder(engine):
    from fm_live_mcp import wages
    from fm_live_mcp.fmdb.sources import _common as C, contracts
    walk = contracts._walk(engine)[0]
    assert len(walk) > 50_000
    people = C.live(engine, 'people')
    sample = random.Random(5).sample([k for k in walk if k['role'] == 'main'], 150)
    values, _ = C.getter_values(engine, 'FULL_CONTRACT', [k['ptr'] for k in sample if k['class'] == 'FULL_CONTRACT'],
                                ['Cwwa'])
    fulls = [k for k in sample if k['class'] == 'FULL_CONTRACT']
    cur = wages.base_currency(engine.read, engine.base)
    for k, wage in zip(fulls, values['Cwwa']):
        assert wages.decode(engine.read, engine.base, people.pointers[k['person_idx']], cur)['amount'] == wage


def test_fixtures_and_league_tables_agree(engine):
    rows = list(_table(engine, 'fixture_tables', 'fixture').rows())
    # The table holds the years the game keeps in memory (its main year and the years linked to it),
    # so its size follows the career: 50,000+ rows in December 2030, 46,100 on 21 Jan 2031 once 2031
    # was the main year (2031: 11,076, 2030: 34,876, 2032: 122, 2033: 26, the game's own counts).
    coverage = list(_table(engine, 'fixture_tables', 'fixture_coverage').rows())
    resident = sum(c[4] for c in coverage if c[1] in ('main', 'linked'))
    assert rows and resident and abs(len(rows) - resident) <= resident // 100      # the owner may play between the reads
    assert {r[3] for r in rows} == {'fixture', 'result'}
    stand = list(_table(engine, 'fixture_tables', 'standing').rows())
    assert len(stand) > 1_000
    # each top-level league row with resident results: played and goals equal the results
    from collections import defaultdict
    agg = defaultdict(lambda: [0, 0, 0])
    for r in rows:
        if r[3] != 'result':
            continue
        comp, season, stage = r[6], r[18], r[19]
        for team, gf, ga in ((r[4], r[7], r[8]), (r[5], r[8], r[7])):
            a = agg[(comp, season, stage, team)]
            a[0] += 1
            a[1] += gf or 0
            a[2] += ga or 0
    stages = {(s[0], s[4]): s[3] for s in _table(engine, 'fixture_tables', 'competition_stage').rows()}
    checked = 0
    for s in stand:
        comp, path, team, played, gf, ga = s[0], s[2], s[5], s[6], s[11], s[12]
        if '.' in path or not played:
            continue
        key = (comp, stages.get((comp, path)), int(path), team)
        if key in agg:
            assert agg[key] == [played, gf, ga]
            checked += 1
    assert checked > 100


def test_archived_group_loader_reproduces_a_resident_group(engine):
    from fm_live_mcp import fixtures
    from fm_live_mcp.fmdb.sources import _common as C, fixture_tables as F
    from fm_live_mcp.fmdb.sources._archive_vm import archive_vm
    store, keys = F._archive_keys(engine)
    cat, bindings, _ = fixtures.catalog(engine.read, engine.base)
    both = [(y, g) for y, g, size in keys if y in bindings and bindings[y]['flags'][g] & 1 and size > F.EMPTY_GROUP_BYTES]
    if not both:
        pytest.skip('no group is both in memory and in the archive index right now (the game pages them)')
    year, g = both[0]
    fn = C.u64s(engine, [C.u64s(engine, [store])[0] + F.LOAD_SLOT])[0]
    for attempt in range(2):            # the game pages its archive: a load can fail transiently
        engine.memory.invalidate()
        vm = archive_vm(engine, budget=500_000_000, timeout_us=300_000_000)
        key = vm._static(struct.pack('<IHH', g, year, 0))
        blank = vm._static(b'\0' * F.GROUP_BYTES)
        try:
            vm.call(fn, (store, blank, key))
            break
        except Exception as exc:  # noqa: BLE001
            if attempt:
                # known transient state (COLLECTIONS.md): the loader reads archive state the game
                # changes while paging; fixture_history then stores nothing for the group
                pytest.skip(f'archive loader failed in the current game state: {exc}')

    def records(read, group):
        out = []
        for h in struct.unpack('<366Q', read(group, 366 * 8)):
            if h:
                s, e, _ = struct.unpack('<QQQ', read(h, 24))
                out += [read(p, 0x70)[:0x3A] for p in struct.unpack(f'<{(e - s) // 8}Q', read(s, e - s))] if e > s else []
        return out
    assert records(vm.read, blank) == records(engine.read, bindings[year]['groups'][g])


def test_injuries_match_player_health(engine):
    from fm_live_mcp import player_health
    from fm_live_mcp.fmdb import tables as T
    from fm_live_mcp.fmdb.sources import _common as C
    rows = list(_table(engine, 'live_state', 'player_injury').rows())
    assert rows
    people = C.live(engine, 'people')
    off = {n: o for _, (n, _, o) in T.CLASSES.items() if o is not None}
    by = {}
    for r in rows:
        by.setdefault(r[0], []).append(r[3])
    for i in random.Random(2).sample(sorted(by), min(200, len(by))):
        d = player_health.decode(engine.read, engine.base, people.pointers[i] - off[people.classes[i]])
        assert [x['started'] for x in d['injuries']] == by[i]


def test_news_and_offers(engine):
    news = list(_table(engine, 'live_state', 'news_item').rows())
    assert sum(1 for r in news if r[3] == 'news_manager') > 1_000
    inbox = [r for r in news if r[3] == 'inbox']
    assert inbox and all(r[7] == 1 for r in inbox)
    offers = list(_table(engine, 'live_state', 'transfer_offer').rows())
    assert offers and all(r[4] is not None or r[3] == 'trade' for r in offers)
