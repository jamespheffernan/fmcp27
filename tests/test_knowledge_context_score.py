"""Private synthetic composition and copied ARM64 controls, never live proof."""
from _knowledge_stream_fixture import native_stream_transport
from dataclasses import replace
import hashlib
import itertools
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE
import unicorn.arm64_const as registers

from fm_live_mcp import knowledge_context_score as score

import _pinned_build
PLUGIN = _pinned_build.PLUGIN
ARENA, STACK, STOP = 0x10000000, 0x20000000, 0x30000000


class Copied:
    """Strict Unicorn copy of the independently reviewed local native controls.

    No game function executes. Instructions come from the pinned installed file;
    initialized-byte reads and separate synthetic-stack writes are enforced.
    """
    def __init__(self):
        with PLUGIN.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == score.PLUGIN_SHA256
            self.functions = {}
            for rva, size, digest in score.NATIVE_GUARDS:
                stream.seek(0x5ed4000 + rva)
                raw = stream.read(size)
                assert hashlib.sha256(raw).hexdigest() == digest
                self.functions[rva] = raw
            self.factors = {}
            for rva in (0x52f6ff0, 0x5388818, 0x538773c, 0x5389a1c):
                stream.seek(0x5ed4000 + rva)
                self.factors[rva] = stream.read(4)
        self.uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.pages, self.known, self.rom = set(), set(), set()
        for rva, raw in self.functions.items():
            self.map(rva, len(raw)); self.uc.mem_write(rva, raw)
        for rva, raw in self.factors.items():
            self.put(rva, int.from_bytes(raw, 'little'), 4, rom=True)
        self.map(ARENA, 0x20000); self.map(STACK, 0x10000); self.map(STOP, 4096)
        self.uc.hook_add(UC_HOOK_CODE, self.code)
        self.uc.hook_add(UC_HOOK_MEM_READ, self.data_read)
        self.uc.hook_add(UC_HOOK_MEM_WRITE, self.data_write)
        self.stops, self.reads = set(), []

    def map(self, address, size):
        for page in range(address & ~4095, (address + size + 4095) & ~4095, 4096):
            if page not in self.pages:
                self.uc.mem_map(page, 4096); self.pages.add(page)

    def put(self, address, value, size=8, rom=False):
        self.map(address, size)
        self.uc.mem_write(address, (value & ((1 << (size * 8)) - 1)).to_bytes(size, 'little'))
        (self.rom if rom else self.known).update(range(address, address + size))

    def code(self, uc, address, size, user):
        if address in self.stops:
            uc.emu_stop(); return
        assert any(start <= address < start + len(raw) for start, raw in self.functions.items()), hex(address)

    def data_read(self, uc, access, address, size, value, user):
        assert all(p in self.known or p in self.rom for p in range(address, address + size)), ('uninitialized copied operand', hex(address), size)
        self.reads.append((address, size))

    def data_write(self, uc, access, address, size, value, user):
        assert STACK <= address < STACK + 0x10000
        self.known.update(range(address, address + size))

    def begin(self):
        self.known.clear(); self.reads.clear()

    def execute(self, start, values, stops=()):
        for index in range(29):
            self.uc.reg_write(getattr(registers, f'UC_ARM64_REG_X{index}'), 0)
        self.uc.reg_write(registers.UC_ARM64_REG_SP, STACK + 0xf000)
        self.uc.reg_write(registers.UC_ARM64_REG_LR, STOP)
        for name, value in values.items():
            self.uc.reg_write(getattr(registers, 'UC_ARM64_REG_' + name.upper()), value & ((1 << 64) - 1))
        self.stops = {STOP, *stops}
        self.uc.emu_start(start, STOP, count=10000)
        end = self.uc.reg_read(registers.UC_ARM64_REG_PC)
        assert end in self.stops
        return end

    def reg(self, name):
        return self.uc.reg_read(getattr(registers, 'UC_ARM64_REG_' + name.upper()))


@pytest.fixture(scope='module')
def native():
    return Copied()


def ref(address, kind):
    return score.Ref(address, kind, (address // 8, address, address + 1))


OWNER = score.Person(ref(0x100548, 'human_person'), 0x100000)
PLAYER = score.Person(ref(0x200388, 'actual_person'), 0x200000)
CLUB = ref(0x300000, 'club')
OTHER = ref(0x310000, 'club')
NATION = ref(0x400000, 'nation')
NATION2 = ref(0x410000, 'nation')
NATIONAL = ref(0x500000, 'national_team')
CONTAINER = ref(0x510000, 'national_team_container')
TEAM = ref(0x600000, 'team')
COMP = ref(0x700000, 'competition')


class Inputs:
    def __init__(self, values=None, *, owner=OWNER, subject=PLAYER):
        self.context = score.Context('synthetic-context', score.PLUGIN_SHA256, owner, subject, score.NativeDate(2030, 317))
        self.values = dict(values or {})
        self.reads, self.verified = [], 0
        self.final = lambda: None

    def operand(self, name, *arguments):
        key = (name, *arguments)
        self.reads.append(key)
        if key in self.values:
            value = self.values[key]
        elif name in self.values:
            value = self.values[name]
        else:
            raise score.SourceUnavailable('Unproved reached operand: ' + name)
        if isinstance(value, Exception):
            raise value
        return value if type(value) is score.Operand else score.Operand(self.context, value)

    def verify(self):
        self.verified += 1
        return self.final()


def basic(scalar=8000, **changes):
    values = {'subject_common102': 0, 'current_club': None, 'owner408_team': None,
              'player120_national': None, 'relevant_subject_club': None,
              'common_d8_pointer': 0, 'player25a': scalar, 'stored_team': None,
              'subject238_context': None, 'eligible_owner_contract_team': None,
              'common38': None}
    values.update(changes)
    return Inputs(values)


@pytest.mark.parametrize('scalar,expected', [(8000, 80), (32767, 80), (7999, 50), (6500, 50), (6499, 30), (5000, 30), (4999, 0), (-32768, 0)])
def test_positive_complete_local_numeric_routes(scalar, expected):
    source = basic(scalar)
    result = score.evaluate(source)
    assert result.score == expected and result.reason is None
    assert source.verified == 1
    assert result.scope == 'private_local_contextual_K_composition_not_field_permission'


def test_every_relation_mask_matches_independent_copied_instructions(native):
    for mask in range(65536):
        native.begin()
        end = native.execute(0x23867a4, {'x0': mask}, (0x2386890, 0x2386d90))
        assert score.relation_score(mask) == (100 if end == 0x2386890 else native.reg('w27'))


def test_contract_dates_match_copied_native_year_day_and_default(native):
    for cy, dy, cd, dd in itertools.product((1900, 2029, 2030, 2031), (1900, 2029, 2030, 2031), (1, 100, 365, 511), (1, 100, 365, 511)):
        if (cy, cd) == (1900, 1):
            continue
        native.begin()
        native.put(ARENA, dd, 2); native.put(ARENA + 2, dy, 2)
        native.put(ARENA + 0x100, cd, 2); native.put(ARENA + 0x102, cy, 2)
        native.put(STACK + 0xf008, 0, 4)
        native.execute(0x2386b4c, {'x0': ARENA, 'x26': ARENA + 0x100, 'x28': 777}, (0x2386938,))
        actual = score._signed(native.reg('w8'), 32)
        assert score.date_contribution(score.NativeDate(cy, cd), score.NativeDate(dy, dd)) == actual
    native.begin(); native.execute(0x2386df4, {'x8': 250}, (0x2386938,))
    assert score.date_contribution(score.NativeDate(1900, 1), score.NativeDate(2030, 1)) == score._signed(native.reg('w8'), 32) == 100


def test_binary32_wide_threshold_and_factor_match_copied_instructions(native):
    for scalar, raw, context in itertools.product((-32768, -1, 0, 2999, 3000, 3999, 4000, 4999, 5000, 7000, 32767),
                                                  (-(1 << 31), -1, 0, 31, 80, 100, 255, (1 << 31) - 1),
                                                  (-32768, -1, 0, 6500, 7000, 32767)):
        native.begin()
        native.put(ARENA + 0x1ea, context, 2)
        native.put(ARENA + 0x1258, scalar, 2)
        native.execute(0x2386bdc, {'x25': ARENA, 'x20': ARENA + 0x1000, 'x0': raw}, (0x2386c10,))
        assert score.score_threshold(raw, context) == score._signed(native.reg('w9'), 32)
        native.begin(); native.put(STACK + 0xf000, 61, 4)
        native.execute(0x2386d70, {'x0': raw, 'x8': scalar}, (0x2386ea0,))
        assert score.scaled_score_base(raw, scalar) == score._signed(native.reg('w2'), 32)


@pytest.mark.parametrize('prior,scalar,expected', [(0, 8000, 80), (8, 8000, 80), (64, 8000, 91), (128, 1, 100), (2, 6500, 50)])
def test_relation_and_scalar_composition(prior, scalar, expected):
    source = basic(scalar, relation_mask=prior, transfer_predicate=False)
    source.values[('current_club', OWNER)] = CLUB
    assert score.evaluate(source).score == expected
    if prior == 128:
        assert not any(k[0] in ('transfer_predicate', 'player25a') for k in source.reads)


def test_transfer_short_circuit_skips_unconsumed_scalar():
    source = basic()
    source.values.update({('current_club', OWNER): CLUB, 'relation_mask': 8, 'transfer_predicate': True})
    del source.values['player25a']
    assert score.evaluate(source).score == 61
    assert not any(k[0] == 'player25a' for k in source.reads)


@pytest.mark.parametrize('active,end,expected', [(1, (2030, 318), None), (1, (2030, 317), 80), (1, (2030, 316), 80), (2, None, 80)])
def test_national_exact_flag_and_strict_expiry(active, end, expected):
    source = basic(player120_national=NATIONAL, national_e2=active)
    if end:
        source.values['national_b8'] = score.NativeDate(*end)
    # Active X reaches later aggregate only below5000; no owner TEAM at8000.
    result = score.evaluate(source)
    assert result.score == (80 if expected is None else expected)
    assert not any(k[0] == 'game_team98' for k in source.reads)
    if active != 1:
        assert not any(k[0] == 'national_b8' for k in source.reads)


def test_checked_national_and_owner_auxiliary_identity_short_circuit():
    source = basic(owner408_team=NATIONAL, player120_national=NATIONAL,
                   national_e2=1, national_b8=score.NativeDate(2030, 318), team_owner=CONTAINER)
    del source.values['player25a']
    assert score.evaluate(source).score == 100
    assert not any(k[0] == 'relevant_subject_club' for k in source.reads)


def test_aggregate_numeric_branch_and_byte_scaling(native):
    for aggregate in (80, 90, 99, 100, 127, 255, 256, 32767):
        source = basic(4999, player120_national=NATIONAL, national_e2=1,
                       national_b8=score.NativeDate(2030, 318), team_owner=CONTAINER,
                       container170=NATION, club_aggregate=aggregate,
                       relation_mask=0, transfer_predicate=False)
        source.values[('current_club', OWNER)] = CLUB
        native.begin(); native.execute(0x2386e20, {'x0': aggregate}, (0x2386e30,))
        expected = min(native.reg('w2'), 100)
        assert score.evaluate(source).score == expected
        assert not any(k[0] == 'first_team' for k in source.reads)


def test_perceived_score_path_uses_P258_factor_not_P25A():
    source = basic(1000, relation_mask=0, transfer_predicate=False, first_team=None,
                   association_context=CONTAINER, container170=NATION, club_score=80, association1ea=100,
                   player258=5000)
    source.values[('current_club', OWNER)] = CLUB
    assert score.evaluate(source).score == 26  # copied binary32 .20*80 +10
    source.values['player258'] = 3000
    assert score.evaluate(source).score == 18


def test_final_association_numeric_route_and_youth_native_consumption():
    source = basic(4000, common38=NATION)
    assert score.evaluate(source).score == 10
    source = basic(4000, stored_team=TEAM, team28=1, native_age=21,
                   common38=NATION, team_owner=CLUB, first_team=None)
    assert score.evaluate(source).score == 0
    assert ('common38', OWNER) in source.reads and ('common38', PLAYER) in source.reads


def test_same_club_raw_primary_flags_short_circuit():
    source = basic(primary2e8=2, primary300=0, current_club=CLUB)
    assert score.evaluate(source).score == 100
    assert not any(k[0] == 'stored_team' for k in source.reads)
    source = basic(primary2e8=1, current_club=CLUB, stored_team=TEAM,
                   team_owner=CLUB, first_team=TEAM, selected_contract=score.Contract(0x800000, 'full'))
    assert score.evaluate(source).score == 100
    assert not any(k[0] in ('primary300', 'owner408_team') for k in source.reads)


def test_first_qualifying_false_relation_beats_later_positive_and_skips_bad():
    source = basic()
    row = score.RelationRow(0x900000)
    source.values.update({'club163': 16, 'club_relation_count': 2,
        ('club_relation_row', OTHER, 0): row,
        ('relation_first', row): OTHER, ('relation_second', row): CLUB,
        ('relation_kind', row): 0, ('relation_byte15', row): 0, ('relation_word1c', row): 0,
        ('club_relation_row', OTHER, 1): score.SourceUnavailable('must remain unread')})
    reader = score._Score(source)
    assert reader.club_relation(OTHER, CLUB) is False
    assert ('club_relation_row', OTHER, 1) not in source.reads
    source.values[('relation_word1c', row)] = 2
    assert reader.club_relation(OTHER, CLUB) is True


@pytest.mark.parametrize('name,value', [('player25a', True), ('player25a', 32768), ('subject_common102', -1),
                                     ('player120_national', TEAM), ('common_d8_pointer', None)])
def test_malformed_or_wrong_family_never_returns_score(name, value):
    source = basic(**{name: value})
    assert score.evaluate(source).score is None
    assert source.verified == 1


def test_distinct_nonnull_D8_requires_owning_source_before_shape_read():
    source = basic(4999, relation_mask=0, transfer_predicate=False,
                   common_d8_pointer=OTHER.address, first_team=TEAM,
                   team_owner=CLUB, team_definition=COMP)
    source.values[('current_club', OWNER)] = CLUB
    result = score.evaluate(source)
    assert result.score is None and 'proved_common_d8_club' in result.reason
    assert ('first_team', OTHER) not in source.reads


def test_missing_dependencies_and_context_mismatch_stay_unknown():
    source = basic(5000)
    source.values[('current_club', OWNER)] = CLUB
    assert score.evaluate(source).score is None  # relation_mask uncomputed, not0
    source = basic()
    source.values['player25a'] = score.Operand(replace(source.context, observation='other'), 8000)
    assert score.evaluate(source).score is None


def test_final_drift_and_failed_verification_withhold_known_or_unknown_results():
    for scalar in (8000, None):
        source = basic(scalar)
        def drift():
            raise score.SourceUnavailable('consumed bytes changed')
        source.final = drift
        result = score.evaluate(source)
        assert result.score is None and 'verification failed' in result.reason
        assert source.verified == 1
    source = basic(); source.final = lambda: False
    assert score.evaluate(source).score is None


def test_native_guard_accepts_exact_source_and_rejects_changed_tail(native):
    def read(address, size):
        rva = address - 0x100000000
        return native.functions[rva] if rva in native.functions else native.factors[rva]
    score.verify_native(read, 0x100000000)
    first = score.NATIVE_GUARDS[0][0]
    old = native.functions[first]
    native.functions[first] = old[:-1] + bytes([old[-1] ^ 1])
    try:
        with pytest.raises(score.SourceUnavailable):
            score.verify_native(read, 0x100000000)
    finally:
        native.functions[first] = old
    first_factor = score.FLOAT_GUARDS[0][0]
    old = native.factors[first_factor]
    native.factors[first_factor] = old[:-1] + bytes([old[-1] ^ 1])
    try:
        with pytest.raises(score.SourceUnavailable):
            score.verify_native(read, 0x100000000)
    finally:
        native.factors[first_factor] = old


def test_whole_ordered_club_leaf_matches_copied_native(native):
    a, b, c, d = (ref(ARENA + n * 0x1000, 'club') for n in range(4))
    cases = [({a: []}, set(), a, None), ({a: []}, set(), a, a),
             ({a: [(b, a, 4, 0, 0)], b: []}, set(), a, b),
             ({a: [(c, a, 4, 0, 0)], b: [(c, b, 4, 0, 0)], c: []}, set(), a, b)]
    for kind, flags, byte15 in itertools.product((0, 17, 24, 4), (0, 2, 1 << 30, (1 << 30) | 2), (0, 32)):
        cases += [({a: [(a, b, kind, byte15, flags), (a, b, 0, 0, 2)], b: []}, set(), a, b),
                  ({a: [(c, a, 4, 0, 0)], b: [(d, b, 4, 0, 0)], c: [(c, d, kind, byte15, flags)], d: []}, set(), a, b)]
    cases += [({a: [(b, a, 4, 0, 0)], b: []}, {a}, a, b),
              ({a: [(None, a, 4, 0, 0), (b, a, 4, 0, 0)], b: []}, set(), a, b)]
    for clubs, blocked, left, right in cases:
        source = basic()
        native.begin(); cursor = ARENA + 0x8000
        for club, rows in clubs.items():
            source.values[('club163', club)] = 16 if club in blocked else 0
            source.values[('club_relation_count', club)] = len(rows)
            native.put(club.address + 0x163, 16 if club in blocked else 0, 1)
            begin = cursor; cursor += 0x100
            native.put(club.address + 0x118, begin)
            native.put(club.address + 0x120, begin + 8 * len(rows))
            for index, (first, second, kind, byte15, flags) in enumerate(rows):
                row = score.RelationRow(cursor); cursor += 0x100
                source.values.update({('club_relation_row', club, index): row,
                    ('relation_first', row): first, ('relation_second', row): second,
                    ('relation_kind', row): kind, ('relation_byte15', row): byte15,
                    ('relation_word1c', row): flags})
                native.put(begin + 8 * index, row.address)
                for offset, size, value in ((0, 8, first.address if first else 0), (8, 8, second.address if second else 0),
                                            (0x30, 1, kind), (0x15, 1, byte15), (0x1c, 4, flags)):
                    native.put(row.address + offset, value, size)
        native.execute(0xe14c9c, {'x0': left.address, 'x1': right.address if right else 0})
        assert score._Score(source).club_relation(left, right) == bool(native.reg('w0'))


def test_final_association_full_composition_matches_copied_branch(native):
    for owner, subject, club_assoc, club, youth, aux, aux_assoc in itertools.product(
            (None, NATION, NATION2), (None, NATION, NATION2), (None, NATION, NATION2),
            (None, CLUB), (False, True), (False, True), (None, NATION, NATION2)):
        source = basic(4999, relation_mask=0, transfer_predicate=False,
                       player120_national=NATIONAL if aux else None, national_e2=1,
                       national_b8=score.NativeDate(2030, 318), container170=aux_assoc,
                       club_aggregate=0, first_team=None, association_context=None,
                       stored_team=TEAM if youth else None, team28=1, native_age=21)
        source.values.update({('current_club', OWNER): club, ('common38', OWNER): owner,
            ('common38', PLAYER): subject, ('club_d8', CLUB): club_assoc,
            ('team_owner', NATIONAL): CONTAINER, ('team_owner', TEAM): CLUB})
        native.begin(); primary, table, auxiliary, raw = ARENA, ARENA + 0x1000, ARENA + 0x3000, ARENA + 0x4000
        native.put(primary, table); native.put(table - 0x20, 0x278)
        native.put(primary + 0x278 + 0x38, subject.address if subject else 0)
        native.put(STACK + 0xf008, int(aux), 4)
        if club:
            native.put(club.address + 0xd8, club_assoc.address if club_assoc else 0)
        if aux and owner:
            native.put(auxiliary + 0x30, raw); native.put(auxiliary + 0x2f, 1, 1)
            native.put(raw + 0x170, aux_assoc.address if aux_assoc else 0)
        end = native.execute(0x2386c9c, {'x0': owner.address if owner else 0,
            'x20': primary, 'x21': club.address if club else 0, 'x24': auxiliary, 'x27': int(youth)}, (0x2386d28, 0x2386d38))
        assert score.evaluate(source).score == (10 if end == 0x2386d38 else 0)


@pytest.mark.parametrize('base', [-32768, -1, 0, 10, 80, 90, 91, 100, 127, 255, 256, (1 << 31) - 1])
@pytest.mark.parametrize('in_range', [False, True])
def test_range_adjustment_local_widths_and_explicit_dependencies(native, base, in_range):
    source = basic(stored_team=TEAM, team_owner=CLUB, first_team=TEAM,
                   team_definition=COMP, eligible_owner_contract_team=TEAM,
                   association_context=CONTAINER, container170=NATION, range_helper=in_range)
    native.begin()
    start = 0x23887c4 if in_range else 0x2388728
    native.execute(start, {'x23': max(base, 0)}, (0x2388738,))
    assert score._Score(source).adjust(base) == native.reg('w0')
    assert ('range_helper', PLAYER, OWNER, CLUB, COMP, NATION) in source.reads


def test_relation_row_field_short_circuit_refuses_only_consumed_fields():
    source = basic(club163=0, club_relation_count=1)
    row = score.RelationRow(0x900000)
    source.values.update({('club_relation_row', OTHER, 0): row,
                          ('relation_second', row): OTHER,
                          ('relation_kind', row): 4,
                          ('relation_first', row): CLUB})
    assert score._Score(source).club_relation(OTHER, CLUB) is True
    assert not any(k[0] in ('relation_byte15', 'relation_word1c') for k in source.reads)
    source = basic(club163=16, club_relation_count=1)
    source.values.update({('club_relation_row', OTHER, 0): row, ('relation_kind', row): 17})
    assert score._Score(source).club_relation(OTHER, CLUB) is False
    assert not any(k[0] in ('relation_byte15', 'relation_first', 'relation_second') for k in source.reads)


def test_cold_fixture_unknown_is_distinct_from_checked_null():
    source = basic(5000, owner408_team=TEAM, player120_national=NATIONAL,
                   national_e2=1, national_b8=score.NativeDate(2030, 318),
                   team_owner=CONTAINER, common38=None, container170=None)
    source.values[('team_owner', TEAM)] = CLUB
    source.values['club_d8'] = NATION
    assert score.evaluate(source).score is None
    assert not any(k[0] == 'game_team98' for k in source.reads)
    source.values.update(next_fixture=None, game_team98=False)
    assert score.evaluate(source).score == 30
    assert ('game_team98', TEAM, NATIONAL, None) in source.reads


def test_missing_observer_and_discarded_native_scores_are_not_permissions():
    source = Inputs(owner=None)
    assert score.evaluate(source).score == 100 and source.reads == []
    source = Inputs({'subject_common102': 128})
    assert score.evaluate(source).score == 0
    assert source.reads == [('subject_common102', PLAYER)]
    assert source.verified == 1


def test_scalar_branches_adjustment_and_merges_match_copied_native(native):
    for scalar, prior in itertools.product((5000, 6499, 6500, 7999, 8000, 32767), (0, 21, 61, 91)):
        native.begin()
        native.put(ARENA + 0x25a, scalar, 2)
        native.put(STACK + 0xf004, 0, 4); native.put(STACK + 0xf008, 0, 4)
        end = native.execute(0x23867d4, {'x20': ARENA, 'x19': ARENA + 0x1000, 'x27': prior, 'x28': 1}, (0x2386dcc, 0x23869c0))
        base = native.reg('w2')
        native.begin(); native.execute(0x2388728, {'x23': base}, (0x2388738,))
        adjusted = native.reg('w0')
        native.begin()
        native.execute(0x2386dd0 if end == 0x2386dcc else 0x23869c4,
                       {'x27': prior, 'x0': adjusted}, (0x2386894,))
        native.execute(0x23868b0, {'x8': native.reg('w8')})
        source = basic(scalar, relation_mask={0: 0, 21: 2, 61: 8, 91: 64}[prior], transfer_predicate=False)
        source.values[('current_club', OWNER)] = CLUB
        assert score.evaluate(source).score == score._signed(native.reg('w0'), 32)


def test_same_address_changed_identity_is_unknown_and_context_rebind_refuses():
    source = basic(4000, common38=NATION)
    source.values[('common38', PLAYER)] = replace(NATION, identity=(1, 99, 99))
    assert score.evaluate(source).score is None
    source = basic()
    def rebind():
        source.context = replace(source.context, observation='new-lifetime')
    source.final = rebind
    assert score.evaluate(source).score is None


@pytest.mark.parametrize('expiry,expected', [(318, 30), (330, 100), (316, 30), (307, 100)])
def test_same_club_trial_date_route_preserves_signed_wrapping(expiry, expected):
    contract = score.Contract(0x800000, 'trial')
    source = basic(1000, current_club=CLUB, primary2e8=1,
                   stored_team=TEAM, team_owner=CLUB, first_team=TEAM,
                   selected_contract=contract, team_definition=COMP,
                   relation_mask=0, transfer_predicate=False, team28=0,
                   contract_expiry=score.NativeDate(2030, expiry))
    assert score.evaluate(source).score == expected
    assert ('contract_expiry', contract) in source.reads
    # A100 date contribution is not an early return: native still reads later
    # scalar/context dependencies before the final merge.
    assert ('team28', TEAM) in source.reads


def test_uncomputed_dependencies_cannot_be_replaced_by_stored_fow_byte():
    source = basic(8000, stored_fow_score=100)
    source.values[('current_club', OWNER)] = CLUB
    assert score.evaluate(source).score is None
    assert not any(k[0] == 'stored_fow_score' for k in source.reads)
    source.values['relation_mask'] = 0
    assert score.evaluate(source).score is None  # transfer still uncomputed


def test_early_unsigned32_merge_differs_from_later_unsigned_byte_merge(native):
    for prior in (0, 91, 128, 255, 0x100, 0xffffff00, 0xffffffff):
        for byte in (False, True):
            source = basic()
            native.begin()
            if byte:
                native.put(STACK + 0xf000, prior, 4)
                native.execute(0x2386d58, {'x0': 80}, (0x2386894,))
            else:
                native.execute(0x2386dd0, {'x27': prior, 'x0': 80}, (0x2386894,))
            native.execute(0x23868b0, {'x8': native.reg('w8')})
            assert score._Score(source).merged(prior, 80, byte=byte) == score._signed(native.reg('w0'), 32)


@pytest.mark.parametrize('name,source', [
    ('aggregate', basic(4999, player120_national=NATIONAL, national_e2=1,
        national_b8=score.NativeDate(2030, 318), team_owner=CONTAINER,
        container170=NATION, relation_mask=0, transfer_predicate=False)),
    ('association', basic(4999, first_team=None, relation_mask=0,
        transfer_predicate=False)),
    ('range', basic(8000, stored_team=TEAM, team_owner=CLUB, first_team=TEAM,
        team_definition=COMP, eligible_owner_contract_team=TEAM,
        association_context=CONTAINER, container170=NATION)),
])
def test_reached_lower_unknown_remains_unavailable(name, source):
    if name != 'range':
        source.values[('current_club', OWNER)] = CLUB
    result = score.evaluate(source)
    assert result.score is None
    assert source.verified == 1


@pytest.mark.parametrize('native_date', [score.NativeDate(2030, 0), score.NativeDate(2030, 366),
                                        score.NativeDate(2030, 511), score.NativeDate(1, 1)])
def test_malformed_current_or_consumed_assignment_dates_stay_unknown(native_date):
    with pytest.raises(score.SourceUnavailable):
        replace(basic().context, today=native_date)
    source = basic(player120_national=NATIONAL, national_e2=1, national_b8=native_date)
    assert score.evaluate(source).score is None


def test_date_domain_checks_are_lazy_and_keep_native_flags():
    source = basic(player120_national=NATIONAL, national_e2=0,
                   national_b8=score.NativeDate(2030, 0))
    assert score.evaluate(source).score == 80
    assert not any(k[0] == 'national_b8' for k in source.reads)
    source = basic(player120_national=NATIONAL, national_e2=1,
                   national_b8=score.NativeDate(2030, 318 | 0xfe00))
    assert score.evaluate(source).score == 80
