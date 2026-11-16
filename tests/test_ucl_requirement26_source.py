"""Synthetic object cases execute complete pinned originals, without callees stubs."""
import hashlib
import json
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs

from fm_live_mcp import players, ucl_requirement26_source as source, world

BASE, HEAP, STACK, STOP = 0x100000000, 0x200000000, 0x400000000000, 0x400000100000
TEAM, CLUB, TEAMS, ROSTER = [HEAP + i * 0x1000 for i in range(4)]
ORIGINAL = json.loads((Path(__file__).parent / 'fixtures/ucl_requirement26_native.json').read_text())


def memory(rating=20, durations=(40, 40), weeks=-1, day=100):
    cells = {}
    def put(at, raw):
        cells.update((at + i, byte) for i, byte in enumerate(raw))
    def q(at, value): put(at, struct.pack('<Q', value))
    for row in ORIGINAL['rows']:
        raw = bytes.fromhex(row['raw_hex'])
        assert len(raw) == row['size'] and hashlib.sha256(raw).hexdigest() == row['sha256']
        put(BASE + row['rva'], raw)
    for obj, size in [(TEAM, 0x90), (CLUB, 0x180), (TEAMS, 8), (ROSTER, len(durations) * 8)]:
        put(obj, bytes(size))
    q(TEAM + 0x30, CLUB)
    q(CLUB + 0x18, TEAMS); q(CLUB + 0x20, TEAMS + 8)
    q(TEAMS, TEAM)
    q(TEAM + 0x38, ROSTER); q(TEAM + 0x40, ROSTER + len(durations) * 8)
    q(BASE + players.RVA[0] - 0x18, 0x388)
    q(BASE + players.RVA[0] + 0x390, BASE + 0xD5B2A0)
    q(BASE + players.RVA[0] + 0x250, BASE + 0xD56498)
    q(BASE + players.RVA[0] + 0xC8, BASE + 0xD09BD0)
    q(BASE + players.RVA[2] + 0x668, BASE + 0xD5C5FC)
    put(BASE + players.RVA[2] - 0x678, struct.pack('<q', -0x388))
    put(BASE + 0x56B1DB8, struct.pack('<HH', day, 2030))
    primaries = []
    for i, duration in enumerate(durations):
        primary, header, entries, instance = [HEAP + 0x4000 + i * 0x4000 + j * 0x1000 for j in range(4)]
        primaries.append(primary)
        put(primary, bytes(0x400)); put(header, bytes(24)); put(entries, bytes(8)); put(instance, bytes(0x40))
        q(ROSTER + i * 8, primary); q(primary, BASE + players.RVA[0])
        q(primary + 0x388, BASE + players.RVA[2]); put(primary + 0x148, struct.pack('<b', rating))
        if duration is not None:
            q(primary + 0xF0, header); q(header, entries); q(header + 8, entries + 8); q(entries, instance)
            put(instance + 0x20, struct.pack('<HH', day, 2030))
            put(instance + 0x28, struct.pack('<h', duration)); put(instance + 0x33, struct.pack('<b', weeks))
    return cells, primaries, put, q


def original(cells, args, entry=0x14F9FA0):
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    known = set(cells)
    pages = {at & ~4095 for at in cells} | set(range(STACK, STACK + 0x10000, 4096)) | {STOP}
    for page in pages: uc.mem_map(page, 4096)
    for page in {at & ~4095 for at in cells}:
        uc.mem_write(page, bytes(cells.get(at, 0) for at in range(page, page + 4096)))
    spans = [(BASE + r['rva'], r['size']) for r in ORIGINAL['rows'] if r['rva'] < 0x4B00000]
    trace, reads, missing = [], [], []
    def instruction(machine, at, n, unused):
        if at == STOP: machine.emu_stop(); return
        assert any(start <= at and at + n <= start + size for start, size in spans), 'Unproved original callee'
        assert all(at + i in known for i in range(n)), 'Missing original instruction'
        trace.append(at - BASE)
    def load(machine, access, at, n, value, unused):
        if not all(at + i in known for i in range(n)):
            missing.append((hex(at), n)); machine.emu_stop(); return
        if not STACK <= at < STACK + 0x10000: reads.append((at, n))
    def store(machine, access, at, n, value, unused):
        assert STACK <= at and at + n <= STACK + 0x10000, 'Nonstack write'
        known.update(range(at, at + n))
    def invalid(machine, access, at, n, value, unused):
        missing.append((hex(at), n)); machine.emu_stop(); return False
    uc.hook_add(UC_HOOK_CODE, instruction); uc.hook_add(UC_HOOK_MEM_READ, load)
    uc.hook_add(UC_HOOK_MEM_WRITE, store); uc.hook_add(UC_HOOK_MEM_INVALID, invalid)
    for i, value in enumerate(args): uc.reg_write(getattr(regs, 'UC_ARM64_REG_X' + str(i)), value)
    uc.reg_write(regs.UC_ARM64_REG_SP, STACK + 0xF000); uc.reg_write(regs.UC_ARM64_REG_LR, STOP)
    try: uc.emu_start(BASE + entry, STOP, count=20000)
    except Exception:
        if missing: raise AssertionError(('Missing original operand', missing))
        raise
    assert not missing, ('Missing original operand', missing)
    assert uc.reg_read(regs.UC_ARM64_REG_PC) == STOP, 'Original did not terminate'
    return uc.reg_read(regs.UC_ARM64_REG_X0), trace, reads


def test_new_native_guards_match_original_payload_and_detect_drift():
    cells, _, _, _ = memory()
    read = lambda at, n: bytes(cells[at + i] for i in range(n))
    source.verify_native(read, BASE)
    for rva, _, _ in source.NATIVE_GUARDS:
        changed = dict(cells); changed[BASE + rva] ^= 1
        with pytest.raises(ValueError, match='source changed'):
            source.verify_native(lambda at, n: bytes(changed[at + i] for i in range(n)), BASE)


@pytest.mark.parametrize('rating,durations,weeks,expected', [
    (14, (40, 40), -1, 0), (15, (40, 40), -1, 1), (20, (40, None), -1, 0),
    (20, (40, 30), -1, 0), (20, (40, 31), -1, 1), (20, (40, 40), 4, 0),
    (20, (40, 40), 5, 1), (20, (None, None), -1, 0)])
def test_complete_requirement26_and_aggregate_known_synthetic_cases(rating, durations, weeks, expected):
    cells, primaries, _, _ = memory(rating, durations, weeks)
    result, trace, reads = original(cells, (primaries[0], 26, TEAM, 0, 0, 0, 0, 0))
    assert result == expected
    assert (0x177AA7C in trace) is (rating >= 15)
    assert (0xD09BD0 in trace) is (rating >= 15)
    assert reads


def test_native_aggregate_preserves_repeated_roster_slots():
    cells, primaries, _, q = memory(durations=(40, None))
    q(ROSTER + 8, primaries[0])
    result, _, _ = original(cells, (primaries[0], 26, TEAM, 0, 0, 0, 0, 0))
    assert result == 1  # Original counts both stored occurrences, without deduplication.


def test_reached_operand_deletion_refuses_positive_original():
    cells, primaries, _, _ = memory()
    args = (primaries[0], 26, TEAM, 0, 0, 0, 0, 0)
    result, _, reads = original(cells, args)
    assert result == 1
    for at, _ in set(reads):
        changed = dict(cells); del changed[at]
        with pytest.raises(AssertionError, match='Missing original operand'):
            original(changed, args)


@pytest.mark.parametrize('selector', [-1, 8, 1, True, None])
def test_unbound_or_pl_selector_is_never_collected(selector):
    with pytest.raises(ValueError, match='proved UCL selector0'):
        source.collect_operands(lambda *args: pytest.fail('Read before selector guard'), BASE, TEAM, selector)


def collection_control(monkeypatch, rosters):
    """Canonical adapters are mocked here; native parity is checked above."""
    cells, primaries, put, q = memory(rating=14)
    q(BASE + 0x56D57D0, HEAP + 0x20000)
    q(HEAP + 0x20000, BASE + 0x55DD068)
    q(BASE + 0x55DD068 + 0x30, BASE + 0x1BDBC08)
    club_teams = tuple(TEAM + i * 0x100 for i in range(len(rosters)))
    for i, address in enumerate(club_teams):
        put(address, bytes(0x90)); put(address + 8, i.to_bytes(4, 'little'))
    monkeypatch.setattr(source, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.assessment_people, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.fixtures, 'typed', lambda *args: None)
    monkeypatch.setattr(source.world, 'typed', lambda *args: None)
    def team(read, base, index):
        return dict(native_id=100 + index), dict(address=club_teams[index], owner_kind='club', owner_address=CLUB)
    monkeypatch.setattr(source.teams, 'by_index', team)
    def vector(read, address, limit):
        if address == CLUB + 0x18: return club_teams, None
        if address == CLUB + 0x118: return (), None
        index = club_teams.index(address - 0x38)
        assert limit == 512
        return rosters[index], None
    monkeypatch.setattr(source.competition_stages, 'vector', vector)
    monkeypatch.setattr(source.database, 'table', lambda *args: {'count': 100})
    monkeypatch.setattr(source.database, 'player_membership', lambda *args: None)
    monkeypatch.setattr(source.players, 'person_offset', lambda *args: 0x388)
    def person(read, base, people, address):
        primary = address - 0x388
        return primary, 0x388, dict(record_kind='actual', native_identity={'database_index': 1}), 1, 2
    monkeypatch.setattr(source.assessment_people, '_person', person)
    return cells, primaries, put, q


def test_collector_preserves_empty_and_repeated_stored_slots(monkeypatch):
    primary = HEAP + 0x4000
    cells, _, _, _ = collection_control(monkeypatch, [(0, primary, primary)])
    result = source.collect_operands(lambda at, n: bytes(cells[at + i] for i in range(n)), BASE, TEAM, 0)
    slots = result['teams'][0]['player_slots']
    assert [slot['primary'] for slot in slots] == [0, primary, primary]
    assert slots[0]['person'] is None
    assert slots[1]['person'] == slots[2]['person']
    assert slots[1]['person']['goalkeeper_position_rating'] == 14
    assert result['unique_player_count'] == 1 and result['stored_player_slot_count'] == 3
    assert result['native_requirement26'] is None and result['full_eligibility_evaluated'] is False


def test_collector_combined_roster_bound_refuses_before_player_reads(monkeypatch):
    cells, _, _, _ = collection_control(monkeypatch, [(0,) * 512, (0,) * 512, (0,)])
    with pytest.raises(ValueError, match='combined roster slots exceed bound'):
        source.collect_operands(lambda at, n: bytes(cells[at + i] for i in range(n)), BASE, TEAM, 0)


@pytest.mark.parametrize('value', [0, 0x1004, 2 ** 64 - 4])
def test_object_pointer_rejects_null_or_unaligned_where_required(value):
    read = lambda at, n: struct.pack('<Q', value)
    if value == 0:
        assert source._pointer(read, HEAP) == 0
    else:
        with pytest.raises(ValueError, match='object pointer'): source._pointer(read, HEAP)


def test_exact_native_code_dispatch_accepts_four_byte_alignment_only():
    rva = 0xD5C5FC
    assert (BASE + rva) % 8 == 4
    assert source._code(lambda *args: struct.pack('<Q', BASE + rva), BASE, HEAP, rva) == BASE + rva
    with pytest.raises(ValueError, match='dispatch changed'):
        source._code(lambda *args: struct.pack('<Q', BASE + rva + 4), BASE, HEAP, rva)
