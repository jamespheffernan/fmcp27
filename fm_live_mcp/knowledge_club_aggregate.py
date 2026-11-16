"""Private warm-input replay of 0x2AC4C4C; never a Manager knowledge gate.

Source: knowledge-club-aggregate-20261108/{source-note.md,producers/source-note.md,
filtered-pool/source-note.md}
in the canonical reader evidence. Call only after plugin/runtime verification.
The consumer must establish the H caller's selected owner and subject TEAM,
including its optional-context/expiry/age branch. ContextBinding carries checked
canonical identity expectations, not permission supplied by a user or model.
check_current must actually check the process/save/build lifetime and return
the expected identity tuple; a caller-supplied permission boolean is rejected.

This observes retained NPP+b0 rows only. It never fills/rebuilds their caches,
calls native functions, changes game bytes, proves freshness, or computes the
complete H score/state. A null retained header contributes native zero while
remaining distinct from an unread source. Filtered derived pools support the
pinned normal rules manager; other consumed dispatches remain unavailable.
Results/addresses/raw scores remain private; do not
serialize them into model context or expose this module through an MCP tool.
"""
from bisect import bisect_left
from dataclasses import dataclass
import struct

from . import database, players, world


BINARY_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
STAFF_LIMIT = 4096
ROW_LIMIT = 4096
TEAM_LIMIT = 128
_ROLES = frozenset((14, 15, 44, 45))
_TEAM_ROLES = frozenset((2, 20, 22, 26, 34, 64))
_CONTRACTS = ('full_contract', 'basic_contract', 'loan_contract', 'trial_contract')
# NPP vtable -> (RTTI, offset-to-top, PERSON rel/vtable, DATA rel/vtable).
_NPP = {
    0x5583660: (b'N2db17ACTUAL_NON_PLAYERE', 0, 0x208, 0x55849D8, 0xF8, 0x5583CE8),
    0x55AC480: (b'N2db16HUMAN_NON_PLAYERE', 0, 0x548, 0x55AD820, 0x438, 0x55ACB30),
    0x558F568: (b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE', -0x278, 0x208, 0x55908E0, 0xF8, 0x558FBF0),
}


class SourceUnavailable(ValueError):
    """A required private source/branch has no supported passive replay."""


def _pointer(value):
    if type(value) is not int or not 4096 <= value < 1 << 64 or value % 8:
        raise ValueError('Invalid club aggregate pointer')
    return value


def _character_pointer(value, length):
    # RTTI names are byte-aligned; validate the complete read without imposing
    # the eight-byte alignment required for native object/vtable pointers.
    if (type(value) is not int or type(length) is not int or length < 1
            or not 4096 <= value < 1 << 64 or length > (1 << 64) - value):
        raise ValueError('Invalid aggregate RTTI character range')
    return value


@dataclass(frozen=True)
class EntityBinding:
    """Expected canonical identity from the consumer's checked context source."""

    address: int
    kind: str
    index: int
    primary_id: int

    def __post_init__(self):
        _pointer(self.address)
        if type(self.index) is not int or not 0 <= self.index < 0xFFFFFFFF:
            raise ValueError('Expected canonical table index')
        if type(self.primary_id) is not int or not -(1 << 31) <= self.primary_id < 1 << 31:
            raise ValueError('Expected signed native primary ID')


@dataclass(frozen=True)
class ContextBinding:
    """Selected owner, subject TEAM and its owner; no observer permission claim.

    lifetime is (positive PID, nonempty save identity string, pinned plugin SHA,
    ...optional immutable lifetime fields). A genuine check_current callback
    must revalidate those facts. This module cannot establish who selected the
    owner, the H caller's date conditions, or the callback's implementation.
    """

    owner: EntityBinding
    subject_team: EntityBinding
    subject_team_owner: EntityBinding
    lifetime: tuple

    def __post_init__(self):
        if not all(isinstance(v, EntityBinding) for v in
                   (self.owner, self.subject_team, self.subject_team_owner)):
            raise ValueError('Expected canonical consumer entity bindings')
        value = self.lifetime
        if (type(value) is not tuple or len(value) < 3 or type(value[0]) is not int
                or value[0] <= 0 or type(value[1]) is not str or not value[1]
                or value[2] != BINARY_SHA256):
            raise ValueError('Expected checked process/save/pinned-build lifetime')
        if any(type(v) not in (int, str, bytes, type(None)) for v in value):
            raise ValueError('Lifetime fields must be immutable scalar identities')


@dataclass(frozen=True)
class AggregateResult:
    """Private numeric replay and coverage; never a percentage/public value."""

    native_value: int
    termination: str
    first_pool_visited: int
    derived_pool_visited: int
    null_retained_headers: int
    q: int
    q_primary_id: int | None
    non_atomic_read: bool = True


class _Source:
    def __init__(self, read, base):
        self.read = world.ReadSet(read)
        self.base = _pointer(base)
        self.tables = {}
        self.null_headers = 0

    def pointer(self, address):
        value = players.u64(self.read(address, 8))
        return _pointer(value) if value else 0

    def vector(self, address, limit):
        start, end, cap = struct.unpack('<QQQ', self.read(address, 24))
        if (start, end, cap) == (0, 0, 0):
            return ()
        _pointer(start)
        if (any(v % 8 for v in (end, cap)) or not start <= end <= cap
                or cap - start > limit * 8):
            raise ValueError('Invalid aggregate vector bounds or reader budget')
        count = (end - start) // 8
        values = []
        for offset in range(0, count, 2048):
            size = min(2048, count - offset)
            values.extend(struct.unpack(f'<{size}Q', self.read(start + offset * 8, size * 8)))
        return tuple(values)  # Preserve native order, nulls and duplicates.

    def table(self, kind):
        if kind not in self.tables:
            self.tables[kind] = database.table(self.read, self.base, kind)
        return self.tables[kind]

    def membership(self, address, table_kind):
        index, identity = struct.unpack('<Ii', self.read(address + 8, 8))
        table = self.table(table_kind)
        if (index >= table['count'] or
                self.pointer(table['start'] + index * 8) != address):
            raise ValueError('Aggregate entity canonical membership differs')
        return index, identity

    def entity(self, address, kind):
        if kind not in ('club', 'national_team_container', 'nation', 'team', 'national_team'):
            raise SourceUnavailable('Unsupported aggregate context type')
        _pointer(address)
        world.typed(self.read, self.base, address, kind)
        table_kind = {'club': 'clubs', 'national_team_container': 'national_team_containers',
                      'nation': 'nations', 'team': 'teams', 'national_team': 'teams'}[kind]
        return self.membership(address, table_kind)

    def binding(self, binding, allowed):
        if binding.kind not in allowed:
            raise SourceUnavailable('Unsupported consumer aggregate binding type')
        if self.entity(binding.address, binding.kind) != (binding.index, binding.primary_id):
            raise ValueError('Consumer aggregate identity differs from canonical source')

    def typed_subobject(self, address, table_rva, name, top):
        table = self.base + table_rva
        if self.pointer(address) != table:
            raise SourceUnavailable('Unsupported aggregate staff subobject type')
        raw = self.read(table - 16, 16)
        if struct.unpack_from('<q', raw)[0] != top:
            raise ValueError('Aggregate staff offset-to-top differs')
        info = players.u64(raw, 8)
        length = len(name) + 1
        text = _character_pointer(players.u64(self.read(info + 8, 8)), length)
        if self.read(text, length) != name + b'\0':
            raise ValueError('Aggregate staff RTTI differs')

    def staff(self, address):
        _pointer(address)
        table = self.pointer(address)
        fields = _NPP.get(table - self.base)
        if fields is None:
            raise SourceUnavailable('Unsupported aggregate NON_PLAYER base')
        name, top, person_rel, person_vt, data_rel, data_vt = fields
        self.typed_subobject(address, table - self.base, name, top)
        if struct.unpack('<qq', self.read(table - 0x20, 16)) != (person_rel, data_rel):
            raise ValueError('Aggregate staff virtual-base adjustments differ')
        person, data = address + person_rel, address + data_rel
        self.typed_subobject(person, person_vt, name, top - person_rel)
        self.typed_subobject(data, data_vt, name, top - data_rel)
        if (players.u64(self.read(self.base + person_vt + 0x3C8, 8)) != self.base + 0xCB3724
                or struct.unpack('<q', self.read(self.base + person_vt - 0x3D8, 8))[0] != -0x110):
            raise ValueError('Aggregate main-contract getter route differs')
        self.membership(person, 'people')
        return person, data

    def first_pool_role(self, person, data):
        contract = self.pointer(data + 0x78)
        if not contract:
            return False
        table = self.pointer(contract)
        kind = next((k for k in _CONTRACTS if table == self.base + world.TYPES[k][0]), None)
        if kind is None:
            raise SourceUnavailable('Unsupported aggregate main-contract type')
        world.typed(self.read, self.base, contract, kind)
        if self.pointer(contract + 8) != person:
            raise ValueError('Aggregate staff main-contract owner differs')
        if players.u64(self.read(table + 0x58, 8)) != self.base + 0xD8C3C8:
            raise ValueError('Aggregate contract primary-role getter differs')
        if self.read(contract + 0x26, 1)[0] in _ROLES:
            return True
        secondary_getter = 0x129A4B8 if kind == 'full_contract' else 0xD88C6C
        if players.u64(self.read(table + 0x70, 8)) != self.base + secondary_getter:
            raise ValueError('Aggregate contract secondary-role getter differs')
        return kind == 'full_contract' and self.read(contract + 0xC2, 1)[0] in _ROLES

    def checked_contract(self, contract, person):
        table = self.pointer(contract)
        kind = next((k for k in _CONTRACTS if table == self.base + world.TYPES[k][0]), None)
        if kind is None:
            raise SourceUnavailable('Unsupported filtered-pool contract type')
        world.typed(self.read, self.base, contract, kind)
        if self.pointer(contract + 8) != person:
            raise ValueError('Filtered-pool contract PERSON owner differs')
        return kind, table

    def primary_role(self, contract, table):
        if players.u64(self.read(table + 0x58, 8)) != self.base + 0xD8C3C8:
            raise ValueError('Filtered-pool primary-role getter differs')
        return self.read(contract + 0x26, 1)[0] & 0xFE

    def team_byte28(self, team):
        # Canonical ownership guards bound supported inputs; owner equality with
        # the selected context is deliberately not part of native admission.
        table = self.pointer(team)
        kind = next((k for k in ('team', 'national_team')
                     if table == self.base + world.TYPES[k][0]), None)
        if kind is None:
            raise SourceUnavailable('Unsupported filtered-pool TEAM type')
        self.entity(team, kind)
        marker = self.read(team + 0x2F, 1)[0]
        if (marker == 0) != (kind == 'team'):
            raise SourceUnavailable('Unsupported filtered-pool TEAM marker/type')
        owner = self.pointer(team + 0x30)
        if not owner:
            raise ValueError('Filtered-pool TEAM owner is null')
        self.entity(owner, 'club' if marker == 0 else 'national_team_container')
        if team not in self.vector(owner + 0x18, TEAM_LIMIT):
            raise ValueError('Filtered-pool TEAM is absent from its canonical owner')
        return self.read(team + 0x28, 1)[0]

    def current_team(self, person, data):
        # 1489ACC(PERSON,0,0): affiliation and special64 exclusions are dead.
        contract = self.pointer(data + 0x78)
        if not contract:
            return 0
        kind, table = self.checked_contract(contract, person)
        team = self.pointer(contract + 0x10)
        if team:
            marker = self.team_byte28(team)
            role = self.primary_role(contract, table)
            if role in _TEAM_ROLES or role == 16 and marker != 0:
                return team
        secondary_getter = 0x127BE24 if kind == 'full_contract' else 0xD88C60
        if players.u64(self.read(table + 0x60, 8)) != self.base + secondary_getter:
            raise ValueError('Filtered-pool secondary TEAM getter differs')
        team = self.pointer(contract + 0xA0) if kind == 'full_contract' else 0
        if not team:
            return 0
        marker = self.team_byte28(team)
        secondary_role_getter = 0x129A4B8 if kind == 'full_contract' else 0xD88C6C
        if players.u64(self.read(table + 0x70, 8)) != self.base + secondary_role_getter:
            raise ValueError('Filtered-pool secondary-role getter differs')
        role = self.read(contract + 0xC2, 1)[0] & 0xFE if kind == 'full_contract' else 0
        return team if role in _TEAM_ROLES or role == 16 and marker != 0 else 0

    def auxiliary_slot2(self, data):
        table = self.pointer(data)
        human = table == self.base + 0x55ACB30
        getter = 0x12FFE58 if human else 0xCB36DC
        if players.u64(self.read(table + 0x438, 8)) != self.base + getter:
            raise ValueError('Filtered-pool DATA auxiliary getter differs')
        if human:
            if self.read(self.base + 0x56D4993, 1)[0] != 1:
                return 0
            if struct.unpack('<q', self.read(table - 0x450, 8))[0] != -0x438:
                raise ValueError('Filtered-pool HUMAN primary adjustment differs')
        holder = self.pointer(data + 0x80)
        return self.pointer(holder + 0x10) if holder else 0

    def normal_rules(self):
        root = self.pointer(self.base + 0x56D57D0)
        table = self.base + 0x55DD068
        if not root or self.pointer(root) != table:
            raise SourceUnavailable('Unsupported filtered-pool rules-manager dispatch')
        self.typed_subobject(root, 0x55DD068, b'23GAME_RULE_GROUP_MANAGER', 0)
        if players.u64(self.read(table + 0x30, 8)) != self.base + 0x1BDBC08:
            raise SourceUnavailable('Unsupported filtered-pool rules-manager virtual30')
        # The pinned leaf is literal0. No input boolean substitutes for it.

    def discarded_projection(self, person, data):
        data_table, person_table = self.pointer(data), self.pointer(person)
        if struct.unpack('<q', self.read(data_table - 0x18, 8))[0] != 0x110:
            raise ValueError('Filtered-pool DATA to PERSON adjustment differs')
        combined = person_table == self.base + 0x55908E0
        predicate = 0xD5C344 if combined else 0xCA4948
        if players.u64(self.read(person_table + 0x4D8, 8)) != self.base + predicate:
            raise ValueError('Filtered-pool PERSON4d8 dispatch differs')
        if combined:
            if (players.u64(self.read(person_table + 0x220, 8)) != self.base + 0xD5C560
                    or struct.unpack('<q', self.read(person_table - 0x230, 8))[0] != -0x480):
                raise ValueError('Filtered-pool combined stored-projection route differs')
            # d5c560 only reads full-primary+120; its ignored return has no
            # eligibility/date/non-null condition and can be elided passively.

    def filtered_keep(self, entry, owner_kind):
        if owner_kind not in (0, 1):
            return True
        person, data = self.staff(entry)
        if owner_kind == 0:
            return bool(self.current_team(person, data))
        contract = self.auxiliary_slot2(data)
        if not contract:
            return False
        _, table = self.checked_contract(contract, person)
        team = self.pointer(contract + 0x10)
        if not team:
            return False
        marker = self.team_byte28(team)
        self.normal_rules()
        role = self.primary_role(contract, table)
        self.discarded_projection(person, data)
        return role in _TEAM_ROLES or role == 16 and marker != 0

    def derived_pool(self, owner):
        entries = [entry for entry in self.vector(owner + 0x78, STAFF_LIMIT) if entry]
        containers = self.table('national_team_containers')
        filtered = bool(self.read(containers['root'] + 0x62, 1)[0] & 0x04)
        if filtered and entries:
            owner_kind = self.read(owner + 0xBA, 1)[0]
            # Native erasure walks backwards; preserve survivor order/duplicates.
            for index in range(len(entries) - 1, -1, -1):
                if not self.filtered_keep(entries[index], owner_kind):
                    del entries[index]
        return tuple(entries), filtered

    def lookup(self, staff, key):
        header = self.pointer(staff + 0xB0)
        if not header:
            self.null_headers += 1
            return 0
        rows = self.vector(header, ROW_LIMIT)
        keys = []
        for row in rows:
            if not row:
                raise ValueError('Null retained row is outside the native lookup contract')
            _pointer(row)
            target = self.pointer(row)
            if not target:
                raise SourceUnavailable('Unresolved retained row key')
            _, identity = self.entity(target, 'national_team_container')
            keys.append(identity)
        if any(left > right for left, right in zip(keys, keys[1:])):
            raise SourceUnavailable('Retained row keys are not in native signed order')
        index = bisect_left(keys, key)
        if index == len(rows) or keys[index] != key:
            return 0
        # The native consumer ignores row date/auxiliary refs and sign-extends24.
        return struct.unpack('<b', self.read(rows[index] + 0x24, 1))[0]


def observe(read, base, context: ContextBinding, *, check_current) -> AggregateResult:
    """Replay the bounded aggregate from materialized, typed canonical inputs.

    Both pools retain order/duplicates and first-equal signed key lookup.
    Native best starts0 and returns as soon as best>99; a first100 can conceal
    a later127. The second pool copies owner+78. Table+62 mask0x04 (bit2) then
    filters the copied pool through the pinned current/auxiliary contract routes
    and normal rules root. Unknown consumed dispatches raise SourceUnavailable;
    no asserted caller pool or permission flag substitutes for those sources.

    Existing read failures, corrupt identities and drift raise. An observed
    null Q/header follows its native zero branch. Date/assessment freshness and
    the H caller's selection prerequisites remain the consumer's responsibility.
    """
    if not isinstance(context, ContextBinding) or not callable(check_current):
        raise ValueError('Expected explicit consumer context and lifetime checker')
    before = check_current()
    if type(before) is not tuple or before != context.lifetime:
        raise ValueError('Aggregate process/save/build binding differs')
    source = _Source(read, base)
    verify_native(source.read, base)
    source.binding(context.owner, ('club', 'national_team_container'))
    source.binding(context.subject_team, ('team', 'national_team'))
    source.binding(context.subject_team_owner, ('club', 'national_team_container'))
    team, team_owner, owner = (context.subject_team.address,
                               context.subject_team_owner.address, context.owner.address)
    if source.pointer(team + 0x30) != team_owner:
        raise ValueError('Aggregate subject TEAM owner backlink differs')
    if team not in source.vector(team_owner + 0x18, TEAM_LIMIT):
        raise ValueError('Aggregate subject TEAM is absent from its owner')
    marker = source.read(team + 0x2F, 1)[0]
    route = ('team', 'club', 0xD8) if marker == 0 else ('national_team', 'national_team_container', 0x170)
    if (context.subject_team.kind, context.subject_team_owner.kind) != route[:2]:
        raise SourceUnavailable('Unsupported subject TEAM/owner marker combination')
    nation = source.pointer(team_owner + route[2])
    if not nation:
        raise SourceUnavailable('H caller would skip aggregate for null association context')
    source.entity(nation, 'nation')
    discriminator = source.read(owner + 0xB9, 1)[0]
    q = source.pointer(nation + (0x118 if discriminator else 0x110))
    first_count = derived_count = best = 0
    key = None
    termination = 'null_q'
    if q:
        _, key = source.entity(q, 'national_team_container')
        # Retain reciprocal canonical ownership for the selected Q projection.
        if source.pointer(q + 0x170) != nation:
            raise ValueError('Aggregate Q NATION ownership backlink differs')
        first = source.vector(owner + 0x90, STAFF_LIMIT)
        for entry in first:
            first_count += 1
            if not entry:
                continue
            person, data = source.staff(entry)
            if not source.first_pool_role(person, data):
                continue
            best = max(best, source.lookup(entry, key))
            if best > 99:
                termination = 'first_pool_early_exit'
                break
        else:
            derived, filtered = source.derived_pool(owner)
            termination = 'complete_filtered_derived_pool' if filtered else 'complete_unfiltered_derived_pool'
            for entry in derived:
                derived_count += 1
                source.staff(entry)
                best = max(best, source.lookup(entry, key))
                if best > 99:
                    termination = 'derived_pool_early_exit'
                    break
    result = AggregateResult(best, termination, first_count, derived_count,
                             source.null_headers, q, key)
    source.read.verify()
    after = check_current()
    if type(after) is not tuple or after != before:
        raise ValueError('Aggregate process/save/build lifetime changed')
    source.read.verify()
    return result


def verify_native(read, base):
    """Check pinned source instructions without invoking any native target."""
    _pointer(base)
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Club aggregate native source changed at {rva:#x}')


NATIVE_SPANS = (
    (0x2AC4C4C, bytes.fromhex(
        'ff0302d1fc6f02a9fa6703a9f85f04a9f65705a9f44f06a9fd7b07a9fdc3019108e442391f0100710822805209238052'
        '2811889a356868f8550e00b4f30300aa165c49a9df0217eb000e00541400805238008052190098d21900c6f21a008092'
        'db0240f97b0c00b4680340f908015ef8696b68f829e541f96003088b20013fd6800b00b4089840391fb500710823c89a'
        '0801198a049940fa60030054685b40f9c80900b4092940a9480109eb800200540efd4393a80e40b9ccfd41d32d0d0c8b'
        'ab0140f96b0140f96b0d40b97f01086baa000054a9210091eb032caacc010b8b040000141f010b6bca020054ea030daa'
        'ee030caa2cfeffb537000014eb030aaa30000014080040f9083940f9fc0300aa00013fd6e803002a1fb400710823c89a'
        '0801198a049940fa40060054e0031caa880340f9083140f900013fd6d8ffff17eb030daadf0500f1a0010054eb0309aa'
        '89fd41d36e0d098bcf8540f8ef0140f9ef0d40b950074cca8c01108bff01086b8cb1899acbb18b9accfeffb5a9210091'
        '4c0109ebc00100548afd43934cfd41d32d0d0c8bae8540f8ce0140f9ce0d40b94f074aca4a010f8b1f010e6b29b18d9a'
        '8ab18a9acafeffb502000014e9030aaa7f0109eb80000054680140f9089140390200001408008052091d00138a1e0013'
        '5f81286b54c1891a9f8e0171ec0d0054d6220091df0217eb41f3ff5404000014140080526900001414008052ffff00a9'
        'ff0f00f9165f0190c84a45f9080100b5e85f01b008a1199108c1bf38080d0036e85f01b008c11891c84a05f9e1230091'
        'e00313aa02008052030080528405b497e1a340a93f0008ebc009005409008092ea0301aa4b0140f9eb0800b46b5940f9'
        'eb0700b46c3540a9ab010ceb8002005471fd4393ab0e40b92ffe41d3900d0f8b0e0240f9ce0140f9ce0d40b9df010b6b'
        'aa0000540c220091ee032faa2f020e8b040000147f010e6bea000054ed0310aaf1030faa2ffeffb528000014ee030daa'
        '21000014ee0310aa3f0600f1a0010054ee030caaecfd41d3d10d0c8b208640f8000040f9000c40b922054fcaef01028b'
        '1f000b6befb18c9a2eb28e9acffeffb50c220091af010cebc0010054edfd4393affd41d3900d0f8b118640f8310240f9'
        '310e40b920054dcaad01008b7f01116b8cb1909aedb18d9acdfeffb502000014ec030daadf010ceb80000054cb0140f9'
        '6b914039020000140b0080526c1d00138d1e0013bf812b6bb4c18c1a9f8e01718c0000544a2100915f0108ebc1f6ff54'
        'c10000b4e10b00f9e80f40f9020101cbc04a45f9b9436294801e0013fd7b47a9f44f46a9f65745a9f85f44a9fa6743a9'
        'fc6f42a9ff030291c0035fd6e05f019000a01991e4a58094c0f2ff34e05f019000c01891ec40629480c400b000400191'
        'e15f019021c01891c2a9fef042000091c1a58094e05f019000a01991d9a5809488ffff17f30300aae05f019000a01991'
        'cea58094e00313aafc7f5597fb7f5597f30300aae10740f9c10000b4e10b00f9e80f40f9020101cbc04a45f98f436294'
        'e00313aa98a48094f07f5597')),
    (0x17C64A8, bytes.fromhex(
        'ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191f50302aaf30301aaf40300aa09a047a9'
        '080109cb01fd4393e00313aa9d86d99796de47a9df0217eb8005005455040036c80240f9e80700f9680300b4090140f9'
        '29015ef80a6969f84ae541f90001098b40013fd6200200b40898403908191f121f51007100020054080040f9083940f9'
        'f50300aa00013fd608181f121f510071c1000054a80240f9083140f9e00315aa00013fd604000014e1230091e00313aa'
        '55a2da97d6220091df0217eb21fcff540a000014c80240f9e80700f9880000b4e1230091e00313aa4ba2da97d6220091'
        'df0217eb01ffff5468f8019008bd46f90889413928101036692240a9080109ebc00f005417fd4393182100d1f90308cb'
        '7af801f0680240f9166978f8360700b488ea423928010035c80240f908015ef8c002088b0100805202008052360df397'
        'c00b00b488ea42391f050071e10c0054c80240f908815ef8c96a68f8291d42f9c002088b20013fd6800a00b4080840f9'
        '480a00b4c80240f908815ef8c96a68f8291d42f9c002088b20013fd6080840f91ca140399f030071fb179f1a40eb43f9'
        '080040f9081940f900013fd640030034c80240f908815ef8c96a68f8291d42f9c002088b20013fd6600200b4f50300aa'
        '080040f9084940f900013fd61f140071a0010054a04a4079400100348267ee9708001c2a1f1d0072fb179f1a06000014'
        '1501188ba1220091690640f92e0000141b008052c80240f908815ef8d502088ba80240f9081d42f9e00315aa00013fd6'
        'c00000b4080040f9082d40f900013fd616181f120200001416008052a80240f908815ef8a96a68f8296d42f9a002088b'
        '20013fd6e0000034a80240f908815ef8a96a68f8291141f9a002088b20013fd6c80a00511ff900710801005429008052'
        '2821c89ae98300b28922a0f20900e8f21f0109ea21020054df420071e8179f1a08013b0aa8010037682640a91501188b'
        'a1220091280108cb3603088b3f0009eb80000054e00315aae20316aa8aa1cc94a802168b680600f9182300d139230091'
        'f70600d117f1ffb5fd7b46a9f44f45a9f65744a9f85f43a9fa6742a9fc6f41a9ffc30191c0035fd6')),
    (0xCB3724, bytes.fromhex('080040f908610fd1080140f90800088b003d40f9c0035fd6')),
    (0xD8C3C8, bytes.fromhex('00984039c0035fd6')),
    (0x129A4B8, bytes.fromhex('00084339c0035fd6')),
    (0xD88C6C, bytes.fromhex('00008052c0035fd6')),
    (0x2386A28, bytes.fromhex('081b40f9880100b409bf40393f010071092e80520a1b80524901899a016969f8a10000b4e00315aa')),
)

# Closed filtered-pool callees: stored reads/literals, never native invocation.
NATIVE_SPANS += (
    (0x1489acc, bytes.fromhex(
        'f657bda9f44f01a9fd7b02a9fd830091f50302aaf40301aa080040f908e541f900013fd6c01400b4f30300aa090840f9'
        'c90700b428a140391f010071f6179f1ad50300342abd40398a030035291940f92a8d45392a0320372aad51a95f010beb'
        'c00200542c0080520d3e80520d02a0724e0140f9cf0540f9ff0109ebe1000054cfc14039ff5100718f21cf1aef010d0a'
        'e499407aa10000544a2100915f010beb81feff54050000141f1d0072c80140f9000940faf6179f1a680240f9082d40f9'
        'e00313aa00013fd608181f12090900513ff900712a0080524921c99aea8300b28a22a0f20a00e8f229010a8a249940fa'
        '6001005414010034680240f9082d40f9e00313aa00013fd608181f121f010171c0000054600a40f9690000141f410071'
        'c8069f1a88fe0736680240f9083140f9e00313aa00013fd6400100b4680240f9083140f9e00313aa00013fd608a04039'
        '1f010071f6179f1a950000353100001416008052f5050034680240f9083140f9e00313aa00013fd6400500b4680240f9'
        '083140f9e00313aa00013fd608bc403988040035680240f9083140f9e00313aa00013fd608bc403968000034080080d2'
        '02000014081840f9098d45392903203709a951a93f010aebc00200542b0080520c3e80520c02a0722d0140f9ae0540f9'
        'df0108ebe1000054aec14039df5100716e21ce1ace010c0ac499407aa1000054292100913f010aeb81feff5405000014'
        'a80140f91f0100f1e8179f1a1601160a680240f9083140f9e00313aa00013fd6600400b4680240f9083940f9e00313aa'
        '00013fd608181f12090900513ff900712a0080524921c99aea8300b28a22a0f20a00e8f229010a8a249940fa00020054'
        '14010034680240f9083940f9e00313aa00013fd608181f121f01017160010054680240f9013140f9e00313aafd7b42a9'
        'f44f41a9f657c3a820001fd61f410071c8069f1ae8fd0736000080d2fd7b42a9f44f41a9f657c3a8c0035fd6'
    )),
    (0xcb36dc, bytes.fromhex(
        '084040f9680000b4000940f9c0035fd6000080d2c0035fd6'
    )),
    (0x12ffe58, bytes.fromhex(
        'a81e02b0084d66391f05007181010054080040f9084111d1080140f90800088b090140f929815ef80801098b084140f9'
        '680000b4000940f9c0035fd6000080d2c0035fd6'
    )),
    (0x127be24, bytes.fromhex(
        '005040f9c0035fd6'
    )),
    (0xd88c60, bytes.fromhex(
        '000080d2c0035fd6'
    )),
    (0xca4948, bytes.fromhex(
        '00008052c0035fd6'
    )),
    (0xd5c344, bytes.fromhex(
        '20008052c0035fd6'
    )),
    (0xd5c560, bytes.fromhex(
        '080040f908c108d1080140f90800088b009140f9c0035fd6'
    )),
    (0x1bdbc08, bytes.fromhex(
        '00008052c0035fd6'
    )),
)
