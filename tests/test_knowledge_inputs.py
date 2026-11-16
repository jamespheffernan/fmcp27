"""Input fingerprints and incremental invalidation on a synthetic memory that the test mutates.

A toy evaluation with the same kinds of inputs as the knowledge engine runs over
``fmdb.memory.SnapshotMemory`` through the real ``PagedJournal``, ``Inputs``, ``Fingerprints``
and ``Verifier``: a player's own record bytes, a club record shared by several players (a
transparent memo), a lookup in a shared vector (an outcome group over an index group) and an age
(a date fact). After each mutation the players that the fingerprints call invalid are compared
with the players whose result really changed in a from-scratch evaluation.
"""
import random
import struct

import pytest

from fm_live_mcp import knowledge_bulk as kb
from fm_live_mcp import knowledge_field_firewall as firewall
from fm_live_mcp import knowledge_inputs as ki
from fm_live_mcp.fmdb.memory import SnapshotMemory

PAGE = 16384
PLAYERS, CLUBS, VECTOR, DATE = 0x100000, 0x200000, 0x300000, 0x400000
RECORD, CLUB = 64, 32
MODE = CLUBS + 0x1000
N = 60


def world(seed=1):
    """Players 0..N-1 in 6 clubs; every third player has a report in the shared vector."""
    rng = random.Random(seed)
    memory = SnapshotMemory()
    for base in (PLAYERS, CLUBS, VECTOR, VECTOR + PAGE, DATE):
        memory.add_page(base, bytes(PAGE))
    for i in range(N):
        memory.load(PLAYERS + i * RECORD, struct.pack('<IIHBB', i, i % 6, 2000 + rng.randrange(14), rng.randrange(1, 21),
                                                      rng.randrange(1, 200)))
    for c in range(6):
        memory.load(CLUBS + c * CLUB, bytes([rng.randrange(1, 100), rng.randrange(256)]))
    entries = [(i, rng.randrange(1, 100)) for i in range(0, N, 3)]
    write_vector(memory, entries)
    memory.load(DATE, struct.pack('<H', 2030))
    return memory


def write_vector(memory, entries):
    memory.load(VECTOR, struct.pack('<I', len(entries)) + b''.join(struct.pack('<IB3x', i, r) for i, r in entries))


def poke(memory, address, data):
    memory.load(address, data)


def evaluate(journal, idx):
    """One player's row; every byte it depends on goes through the journal."""
    inputs = journal.inputs
    record = PLAYERS + idx * RECORD
    club = struct.unpack('<I', journal.read(record + 4, 4))[0]
    reputation = journal.memo(('club', club), lambda: journal.read(CLUBS + club * CLUB, 1)[0])

    def index():
        count = struct.unpack('<I', journal.read(VECTOR, 4))[0]
        out = {}
        for n in range(count):
            who, report = struct.unpack('<IB3x', journal.read(VECTOR + 4 + 8 * n, 8))
            out.setdefault(who, report)
        return out

    def lookup():
        return journal.memo(('index',), index, firewall=True).get(idx)

    report = journal.memo(('report', idx), lookup, firewall=True)
    birth = struct.unpack('<H', journal.read(record + 8, 2))[0]
    inputs.suspend()
    try:
        today = struct.unpack('<H', journal.read(DATE, 2))[0]
    finally:
        inputs.resume()
    age = today - birth
    inputs.derive('age', (birth,), age)
    skill = journal.read(record + 10, 1)[0]
    mode = journal.read(MODE, 1)[0]                 # a global every player reads
    return dict(idx=idx, reputation=reputation, report=report, age=age, skill=skill, mode=mode)


def call(memory, keys, plan=None):
    """What the engine's paged call does, on the toy: verify, evaluate the rest, fence, fingerprint."""
    journal = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    inputs = journal.inputs
    stored, groups = (plan or ({}, {}))
    kept, rows, collectors = [], {}, {}

    def facts(kind, args):
        return struct.unpack('<H', journal.source.read(DATE, 2))[0] - args[0] if kind == 'age' else object()

    def recompute(text):
        key = ki.decode_key(text)
        try:
            if key[0] == 'index':
                evaluate_index(journal)
            elif key[0] == 'report':
                evaluate_lookup(journal, key[1])
            else:
                return None
        except kb.SOURCE_ERRORS:
            pass
        record = inputs.groups.get(key)
        return record[0] if record else None

    verifier = ki.Verifier(journal.source, groups, facts, recompute)
    inputs.push()
    verifier.prefetch([stored[k]['spans'] for k in keys if k in stored])
    valid = {k for k in keys if k in stored and verifier.fingerprint_ok(stored[k])}
    inputs.pop()
    for key in keys:
        if key in valid:
            kept.append(key)
            continue
        collector = inputs.push()
        try:
            rows[key] = evaluate(journal, key)
        finally:
            inputs.pop()
        collectors[key] = collector
    journal.checked = verifier.checked
    after_evaluation = getattr(call, 'before_fence', None)
    if after_evaluation:
        after_evaluation(memory)
    journal.verify()
    prints = ki.Fingerprints(inputs, journal.source, minimum=4)
    return dict(rows=rows, kept=kept, players=prints.players(collectors), groups=prints.groups(),
                verifier=verifier, journal=journal)


def evaluate_index(journal):
    count = struct.unpack('<I', journal.read(VECTOR, 4))[0]
    out = {}
    for n in range(count):
        who, report = struct.unpack('<IB3x', journal.read(VECTOR + 4 + 8 * n, 8))
        out.setdefault(who, report)
    return out


def evaluate_lookup(journal, idx):
    def lookup():
        return journal.memo(('index',), lambda: evaluate_index(journal), firewall=True).get(idx)
    return journal.memo(('report', idx), lookup, firewall=True)


KEYS = list(range(N))


@pytest.fixture
def state():
    memory = world()
    first = call(memory, KEYS)
    assert len(first['rows']) == N and not first['kept']
    return memory, first


def update(memory, first):
    """(incremental result, from-scratch rows) on the memory as it is now."""
    inc = call(memory, KEYS, (first['players'], first['groups']))
    scratch = call(memory, KEYS)['rows']
    for key in inc['kept']:
        assert first['rows'][key] == scratch[key], f'kept row {key} is stale'
    for key, row in inc['rows'].items():
        assert row == scratch[key]
    changed = {k for k in KEYS if first['rows'][k] != scratch[k]}
    return inc, changed


def test_nothing_changed_keeps_everyone(state):
    memory, first = state
    inc, changed = update(memory, first)
    assert inc['kept'] == KEYS and not inc['rows'] and not changed
    assert inc['verifier'].recomputed == 0


def test_own_byte_invalidates_one_player(state):
    memory, first = state
    poke(memory, PLAYERS + 7 * RECORD + 10, bytes([first['rows'][7]['skill'] % 20 + 1]))
    inc, changed = update(memory, first)
    assert set(inc['rows']) == {7} == changed


def test_unconsumed_byte_on_the_same_page_invalidates_nobody(state):
    memory, first = state
    poke(memory, PLAYERS + 7 * RECORD + 11, b'\xff')           # the hidden byte: never read
    poke(memory, PLAYERS + 7 * RECORD + 40, b'\x55' * 8)
    inc, changed = update(memory, first)
    assert not inc['rows'] and not changed


def test_shared_club_byte_invalidates_its_players(state):
    memory, first = state
    poke(memory, CLUBS + 2 * CLUB, bytes([first['rows'][2]['reputation'] ^ 0x7f]))
    inc, changed = update(memory, first)
    assert set(inc['rows']) == {i for i in KEYS if i % 6 == 2} == changed
    poke(memory, CLUBS + 2 * CLUB + 1, b'\x99')                 # a club byte nobody read
    inc2, changed2 = update(memory, dict(first, players={**first['players'], **inc['players']},
                                         groups={**first['groups'], **inc['groups']},
                                         rows={**first['rows'], **inc['rows']}))
    assert not inc2['rows'] and not changed2


def test_common_group_byte_invalidates_everyone(state):
    memory, first = state
    poke(memory, MODE, b'\x03')
    inc, changed = update(memory, first)
    assert set(inc['rows']) == set(KEYS) == changed


def test_shared_vector_change_reaches_only_the_players_whose_lookup_changed(state):
    memory, first = state
    entries = [(i, first['rows'][i]['report']) for i in range(0, N, 3)]
    # a new report for player 4 goes in front: every entry moves, one lookup changes
    write_vector(memory, [(4, 77)] + entries)
    inc, changed = update(memory, first)
    assert set(inc['rows']) == {4} == changed
    assert inc['verifier'].recomputed >= N        # the index and every lookup were recomputed, cheaply
    # player 9's report byte changes in place
    write_vector(memory, [(i, 5 if i == 9 else r) for i, r in entries])
    inc, changed = update(memory, first)
    assert set(inc['rows']) == {9} == changed


def test_date_change_reaches_only_players_whose_age_fact_changed(state):
    memory, first = state
    # the toy date is a year: every age changes
    poke(memory, DATE, struct.pack('<H', 2031))
    inc, changed = update(memory, first)
    assert set(inc['rows']) == set(KEYS) == changed
    # bytes of the date that do not change the fact (the unread high half of the word)
    poke(memory, DATE, struct.pack('<H', 2030))
    poke(memory, DATE + 2, b'\x01\x02')
    inc, changed = update(memory, first)
    assert not inc['rows'] and not changed


def test_fingerprint_shapes(state):
    _, first = state
    fp = first['players'][7]
    spans = ki.unpack_spans(fp['spans'])
    assert spans == sorted(spans) and all(a < b for a, b in spans)
    assert [f[0] for f in fp['facts']] == ['age']
    keys = [ki.decode_key(k) for k, _ in fp['groups']]
    assert ('report', 7) in keys and any(k[0] == 'common' for k in keys)
    common = [g for k, g in first['groups'].items() if k.startswith('["common"')]
    assert len(common) == 1 and ki.unpack_spans(common[0]['spans']) == [(MODE, MODE + 1)]
    # the date bytes are not a raw input of any player or group
    for record in list(first['players'].values()) + list(first['groups'].values()):
        assert all(not (a <= DATE < b) for a, b in ki.unpack_spans(record['spans']))
    # the club byte sits in the own spans of every member of the club (a memo's inputs are
    # attached to each user, not only to the first)
    for i in (1, 7, 13):
        assert any(a <= CLUBS + 1 * CLUB < b for a, b in ki.unpack_spans(first['players'][i]['spans']))
    assert ki.decode_key(ki.encode_key(('op', 'x', None, 5, ('a', 2)))) == ('op', 'x', None, 5, ('a', 2))


def test_random_mutations_never_keep_a_stale_row():
    rng = random.Random(42)
    exact = 0
    for trial in range(60):
        memory = world(seed=trial)
        first = call(memory, KEYS)
        region = rng.choice((PLAYERS, PLAYERS, CLUBS, VECTOR, DATE))
        span = {PLAYERS: N * RECORD, CLUBS: 6 * CLUB, VECTOR: 4 + 8 * (N // 3), DATE: 4}[region]
        for _ in range(rng.randrange(1, 4)):
            address = region + rng.randrange(span)
            if region == PLAYERS and 4 <= (address - PLAYERS) % RECORD < 8:
                continue                               # a wild club index reads unmapped memory
            old = memory.read(address, 1)[0]
            poke(memory, address, bytes([old ^ (1 << rng.randrange(8))]))
        inc, changed = update(memory, first)          # asserts: no kept row is stale
        assert changed <= set(inc['rows'])
        exact += changed == set(inc['rows'])
    assert exact >= 45                                 # usually exactly the changed players


def test_fence_covers_what_verification_compared(state):
    memory, first = state
    call.before_fence = lambda m: poke(m, PLAYERS + 3 * RECORD + 10, b'\x00')   # changes after it was verified
    try:
        with pytest.raises(ValueError, match='Verified byte changed at final physical fence'):
            call(memory, KEYS, (first['players'], first['groups']))
    finally:
        call.before_fence = None


def test_fence_detects_a_consumed_byte_changing_and_ignores_others():
    memory = world()
    journal = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    evaluate(journal, 5)
    poke(memory, PLAYERS + 5 * RECORD + 11, b'\x7f')           # not consumed, same page
    journal.verify()
    journal2 = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    evaluate(journal2, 5)
    poke(memory, PLAYERS + 5 * RECORD + 10, b'\x7f')
    with pytest.raises(ValueError, match='Consumed byte changed at final physical fence'):
        journal2.verify()
    with pytest.raises(ValueError, match='poisoned'):
        journal2.read(PLAYERS, 4)


def test_firewall_holds_on_the_page_transport():
    memory = world()
    journal = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    hidden = PLAYERS + 9 * RECORD + 11
    journal.forbidden = firewall.Intervals([(PLAYERS + i * RECORD + 11, PLAYERS + i * RECORD + 12) for i in range(N)])
    assert journal.read(PLAYERS + 9 * RECORD + 10, 1)           # the neighbour byte is readable
    journal.permissions[(PLAYERS + 8 * RECORD + 11, 1)] = (0, 2)
    assert len(journal.read(PLAYERS + 8 * RECORD + 11, 1)) == 1  # an exact granted byte
    with pytest.raises(ValueError, match='forbidden'):
        journal.read(hidden, 1)
    with pytest.raises(ValueError, match='poisoned'):            # and the call is lost for good
        journal.read(PLAYERS, 4)
    journal3 = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    journal3.forbidden = journal.forbidden
    with pytest.raises(ValueError, match='forbidden'):
        journal3.read(PLAYERS + 9 * RECORD + 8, 8)               # a wider read that would cover it


def test_memo_attaches_inputs_to_every_user_and_caches_refusals():
    memory = world()
    journal = kb.PagedJournal(ki.PageSource(memory, readahead=0), None)
    inputs = journal.inputs
    calls = []

    def compute():
        calls.append(1)
        journal.read(CLUBS, 1)
        raise ValueError('refused')

    logs = []
    for _ in range(2):
        collector = inputs.push()
        with pytest.raises(ValueError, match='refused'):
            journal.memo(('x',), compute)
        inputs.pop()
        logs.append(collector.log)
    assert len(calls) == 1 and logs[0] == logs[1] == [(CLUBS, 1)]
    # first use inside a suspended section still records the memo's inputs for later users
    inputs.push()
    inputs.suspend()
    journal.memo(('y',), lambda: journal.read(CLUBS + CLUB, 1))
    inputs.resume()
    quiet = inputs.pop()
    later = inputs.push()
    journal.memo(('y',), lambda: None)
    inputs.pop()
    assert quiet.log == [] and later.log == [(CLUBS + CLUB, 1)]


def test_page_source_reads_and_readahead():
    memory = world()
    source = ki.PageSource(memory, readahead=3)
    assert source.read(VECTOR + PAGE - 2, 4) == memory.read(VECTOR + PAGE - 2, 4)   # across two pages
    assert source.fetches == 1 and set(source.fresh()) == {VECTOR, VECTOR + PAGE}
    assert len(source.pages()) == 2                     # the pages after it are unmapped: skipped quietly
    with pytest.raises(ValueError, match='Unreadable page'):
        source.read(0x900000, 4)
