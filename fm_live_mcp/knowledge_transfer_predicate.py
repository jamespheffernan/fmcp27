"""Private, build-pinned passive cbb9f8 specialization for Passing's score.

Consumes checked actual/combined PERSON and nonnull owner CLUB bindings in the
caller's ReadSet/lifetime. This computes one native predicate; it grants no
Manager knowledge permission and does not evaluate the full score or population.
No native calls, writes, refresh, generated profiles, names or attributes.
"""
from copy import deepcopy
import hashlib
import struct

from . import assessment_people, database, knowledge_inputs, live_transfer_offers, players, world


class SourceUnavailable(ValueError):
    """A taken native branch lacks a proved passive typed source."""


VECTOR_LIMIT = 100_000
TEAM_LIMIT = 4096
TABLE_LIMIT = 2_000_000
PARENT_LIMIT = 64
CONTRACTS = {
    'full_contract': (0x129FFFC, 0, 0xD88C8C, 0),
    'basic_contract': (0xD8C3D0, 5, 0xD88C8C, 0),
    'loan_contract': (0x13781B8, 1, 0x13781C0, 1),
    'trial_contract': (0x1006B44, 2, 0xD88C8C, 0),
}


def _pointer(value):
    return assessment_people._address(value)


def _identity(value):
    if (type(value) is not tuple or len(value) != 3
            or any(type(v) is not int or not 0 <= v < 1 << 32 for v in value)
            or not value[1]):
        raise ValueError('Expected exact canonical ordinal/UID/raw-secondary identity')
    return value


def verify_native(read, base):
    # Pinned-code guard: the same answer for the whole of a journalled bulk call.
    memo = knowledge_inputs.call_memo(read)
    if memo is not None:
        return memo(('verify_native', 'transfer_predicate', base), lambda: _verify_native(read, base))
    return _verify_native(read, base)


def _verify_native(read, base):
    assessment_people._address(base, max(rva + size for rva, size, _ in NATIVE_GUARDS))
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError(f'Transfer predicate native instructions changed at {rva:#x}')


class _Reader:
    def __init__(self, read, base):
        self.read, self.base = read, base
        self.tables, self.entities, self.people = {}, {}, {}
        # Bulk knowledge engine (knowledge_fast): a journalled read source may share the pure
        # canonical-identity checks between readers of one call. Absent everywhere else.
        probe = read
        for _ in range(4):
            hook = getattr(probe, 'reader_hook', None)
            if hook is not None:
                hook(self)
                break
            probe = getattr(probe, 'read', None)
            if probe is None:
                break

    def before_today(self, year, day):
        current = struct.unpack('<I', self.read(self.base + world.CURRENT_DATE, 4))[0]
        return (year, day) < (current >> 16, current & 0x1FF)

    def u8(self, address):
        return self.read(address, 1)[0]

    def i32(self, address):
        return struct.unpack('<i', self.read(address, 4))[0]

    def ptr(self, address):
        value = players.u64(self.read(address, 8))
        return _pointer(value) if value else 0

    def route(self, table, slot, expected):
        if players.u64(self.read(table + slot, 8)) != self.base + expected:
            raise SourceUnavailable('Unproved transfer predicate virtual route')

    def adjustment(self, table, slot, expected):
        if struct.unpack('<q', self.read(table - slot, 8))[0] != expected:
            raise ValueError('Transfer predicate virtual-base adjustment changed')

    def bounds(self, header, width, limit):
        start, end, cap = struct.unpack('<QQQ', self.read(header, 24))
        if (start, end, cap) == (0, 0, 0):
            return 0, 0
        if (start < 4096 or any(p % min(width, 8) for p in (start, end, cap))
                or (end-start) % width or (cap-start) % width
                or not start <= end <= cap or cap - start > width * limit):
            raise ValueError('Invalid transfer predicate vector geometry or reader budget')
        return start, (end - start) // width

    def pointers(self, header, limit=TEAM_LIMIT):
        start, count = self.bounds(header, 8, limit)
        values = []
        for offset in range(0, count, 1024):
            n = min(1024, count - offset)
            values.extend(struct.unpack(f'<{n}Q', self.read(start + offset * 8, n * 8)))
        return values

    def table(self, kind):
        if kind not in self.tables:
            self.tables[kind] = database.table(self.read, self.base, kind)
        return self.tables[kind]

    def entity(self, address, kinds):
        _pointer(address)
        if address in self.entities:
            kind, identity = self.entities[address]
            if kind not in kinds:
                raise SourceUnavailable('Unexpected transfer predicate entity family')
            return kind, identity
        table = self.ptr(address)
        kind = next((k for k in kinds if table == self.base + world.TYPES[k][0]), None)
        if kind is None:
            raise SourceUnavailable('Unproved transfer predicate entity type')
        world.typed(self.read, self.base, address, kind)
        identity = struct.unpack('<III', self.read(address + 8, 12))
        if not identity[1]:
            raise ValueError('Missing transfer predicate canonical UID')
        source = self.table({'club': 'clubs', 'league_body_club': 'clubs',
                             'team': 'teams', 'national_team': 'teams',
                             'competition': 'competitions', 'nation': 'nations',
                             'national_team_container': 'national_team_containers'}[kind])
        if identity[0] >= source['count'] or self.ptr(source['start'] + 8 * identity[0]) != address:
            raise ValueError('Transfer predicate canonical entity backlink changed')
        self.entities[address] = kind, identity
        return kind, identity

    def club(self, address):
        return self.entity(address, ('club',))[1]

    def team(self, address):
        if not address:
            return 0
        self.entity(address, ('team', 'national_team'))
        owner = self.ptr(address + 0x30)
        if owner:
            self.entity(owner, ('club', 'league_body_club', 'national_team_container'))
            if address not in self.pointers(owner + 0x18) + self.pointers(owner + 0x30):
                raise ValueError('Transfer predicate TEAM owner backlink changed')
        return address

    def person(self, person):
        _pointer(person)
        if person in self.people:
            return self.people[person]
        table = self.ptr(person)
        if table - self.base not in (players.RVA[2], players.STAFF_RVA[2]):
            raise SourceUnavailable('Transfer predicate needs ordinary actual/combined PERSON')
        primary, offset, public, uid, secondary = assessment_people._person(
            self.read, self.base, self.table('people'), person)
        common = primary + (0x278 if offset == 0x388 else 0x370)
        common_rva = 0x5589A90 if offset == 0x388 else 0x558FBF0
        if self.ptr(common) != self.base + common_rva:
            raise ValueError('Transfer predicate COMMON relation changed')
        displacement, info = struct.unpack('<qQ', self.read(self.base + common_rva - 16, 16))
        if displacement != -(common - primary) or info != self.ptr(self.ptr(primary) - 8):
            raise ValueError('Transfer predicate COMMON type changed')
        if struct.unpack('<q', self.read(self.ptr(common) - 0x18, 8))[0] != 0x110:
            raise ValueError('Transfer predicate COMMON to PERSON adjustment changed')
        for slot, target, negative, delta in ((0x230, 0xD5C578, 0x240, -offset),
                (0x3C0, 0xCB8C68, 0x3D0, -0x110), (0x3C8, 0xCB3724, 0x3D8, -0x110),
                (0x3E8, 0xCB8EB0, 0x3F8, -0x110), (0x668, 0xD5C5FC, 0x678, -offset)):
            self.route(table, slot, target)
            self.adjustment(table, negative, delta)
        self.route(table, 0x1B0, 0xCA4638)
        self.route(table, 0x3F8, 0xCA47D4 if offset == 0x388 else 0xC8CDF0)
        if offset == 0x480:
            self.adjustment(table, 0x408, -0x208)
            if self.ptr(primary + 0x278) != self.base + 0x558F568:
                raise ValueError('Transfer predicate combined NON_PLAYER relation changed')
            self.adjustment(self.base + 0x558F568, 0x18, 0xF8)
            delta, info2 = struct.unpack('<qQ', self.read(self.base + 0x558F568 - 16, 16))
            if delta != -0x278 or info2 != info:
                raise ValueError('Transfer predicate combined NON_PLAYER type changed')
        value = (primary, common, public['record_kind'],
                 (public['native_identity']['database_index'], uid, secondary))
        self.people[person] = value
        return value

    def resolve_placeholder(self, person):
        if not person:
            return 0
        _pointer(person)
        if self.i32(person + 0xC) != -1:
            self.person(person)
            return person
        index = self.i32(person + 8)
        if index < 0:
            return 0
        people = self.table('people')
        if not self.u8(self.base + 0x56D34E0) & 1:
            start, count = self.bounds(people['root'] + 0x68, 8, TABLE_LIMIT)
            if index < count:
                value = self.ptr(start + index * 8)
                if value and self.person(value)[3][0] != index:
                    raise ValueError('Transfer placeholder ordinal backlink changed')
                return value
        if index >= people['count']:
            return 0
        value = self.ptr(people['start'] + index * 8)
        if value and self.person(value)[3][0] != index:
            raise ValueError('Transfer placeholder ordinal backlink changed')
        return value

    def contract(self, address, person):
        if not address:
            return None
        table = self.ptr(address)
        kind = next((k for k in CONTRACTS if table == self.base + world.TYPES[k][0]), None)
        if kind is None:
            raise SourceUnavailable('Unproved transfer predicate contract type')
        world.typed(self.read, self.base, address, kind)
        if self.ptr(address + 8) != person:
            raise ValueError('Transfer predicate contract PERSON owner changed')
        category, value, loan, loan_value = CONTRACTS[kind]
        for slot, target in ((0x58, 0xD8C3C8), (0x90, category), (0x98, loan)):
            self.route(table, slot, target)
        return value, loan_value

    def current_team(self, person):
        primary, common, kind, _ = self.person(person)
        main = self.ptr(common + 0x78)
        category = self.contract(main, person)
        if category and category[0] == 0:
            return self.team(self.ptr(main + 0x18))
        stored = self.team(self.ptr(primary + 0x128))
        if stored and not main:
            holder = self.ptr(common + 0x80)
            if not holder or all(not self.ptr(holder + off) for off in (0, 8, 0x10, 0x18)):
                return stored
        if kind == 'player_staff' and main and self.u8(main + 0x26) >= 2:
            return self.team(self.ptr(main + 0x10))
        return 0

    def parent(self, club):
        self.club(club)
        if self.u8(club + 0x163) & 0x10:
            return 0
        for row in self.pointers(club + 0x118):
            _pointer(row)
            if self.ptr(row + 8) != club:
                continue
            kind = self.u8(row + 0x30)
            if kind <= 20 and (1 << kind) & 0x1001F0:
                parent = self.ptr(row)
                if parent:
                    self.club(parent)
                return parent
        return 0

    def related_team(self, team):
        self.team(team)
        owner = self.ptr(team + 0x30)
        if self.u8(team + 0x28):
            if not owner:
                raise ValueError('Missing related TEAM owner')
            values = self.pointers(owner + 0x18)
            for index in range(1, len(values)):
                if values[index] == team:
                    return self.team(values[index - 1])
        if self.u8(team + 0x2F) or not owner:
            return 0
        self.club(owner)
        parent = self.parent(owner)
        if not parent:
            return 0
        rules = self.ptr(self.base + 0x56D57D0)
        if not rules or self.ptr(rules) != self.base + 0x55DD068:
            raise SourceUnavailable('Unproved related TEAM rules-manager mode')
        displacement, info = struct.unpack('<qQ', self.read(self.base + 0x55DD068 - 16, 16))
        if displacement != 0:
            raise ValueError('Related TEAM rules-manager displacement changed')
        name = players.u64(self.read(info + 8, 8))
        if name < 4096:
            raise ValueError('Invalid rules-manager RTTI name')
        if self.read(name, len(b'23GAME_RULE_GROUP_MANAGER\0')) != b'23GAME_RULE_GROUP_MANAGER\0':
            raise SourceUnavailable('Unproved related TEAM rules-manager RTTI')
        self.route(self.base + 0x55DD068, 0x30, 0x1BDBC08)
        result = 0
        for candidate in self.pointers(parent + 0x18) + self.pointers(parent + 0x30):
            _pointer(candidate)  # Native dereferences every visited candidate.
            self.team(candidate)
            if self.ptr(candidate + 0x30) == owner:
                break
            if self.u8(candidate + 0x28) == 0:
                result = candidate
        return result

    def matches_owner(self, selected, owner):
        if not selected:
            return False
        self.team(selected)
        raw = self.ptr(selected + 0x30)
        if self.u8(selected + 0x2F) == 0 and raw == owner:
            return True
        first = self.pointers(owner + 0x18)
        if not first or not first[0]:
            return False
        first = self.team(first[0])
        other_raw = self.ptr(first + 0x30)
        if raw == other_raw:
            return False
        a = self.related_team(selected)
        if a and self.ptr(a + 0x30) == other_raw:
            return True
        b = self.related_team(first)
        if not b:
            return False
        b_raw = self.ptr(b + 0x30)
        if b_raw == raw or (a and b_raw == self.ptr(a + 0x30)):
            return True
        c = self.related_team(b)
        return bool(c and self.ptr(c + 0x30) == raw)

    def club_uid(self, uid):
        source = self.table('clubs')
        if not source['count']:
            return 0
        root = source['root']
        secondary = self.u8(root + 0x64) & 1
        start, count = (self.bounds(root + 0x90, 8, TABLE_LIMIT) if secondary
                        else (source['start'], source['count']))
        sort = bool(secondary and self.u8(root + 0xA8) == 1)
        rows, seen = [], set()
        for index in range(count):
            club = self.ptr(start + index * 8)
            raw_uid = self.club(club)[1]
            signed = raw_uid if raw_uid < 1 << 31 else raw_uid - (1 << 32)
            if signed in seen:
                raise SourceUnavailable('Ambiguous canonical CLUB UID ties')
            seen.add(signed)
            rows.append((signed, club))
        if sort:
            rows.sort()
        elif rows != sorted(rows):
            raise SourceUnavailable('Unsorted CLUB lookup without native sort branch')
        lo, hi = 0, len(rows) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            key, club = rows[mid]
            if key == uid:
                return club
            if key > uid:
                hi = mid - 1
            else:
                lo = mid + 1
        return 0

    def special_mode(self):
        mode953 = self.u8(self.base + 0x56D4953)
        mode951 = self.u8(self.base + 0x56D4951)
        return mode953 == 1 and mode951 not in (1, 2)

    def definition_clear(self, team, key):
        owner = self.ptr(team + 0x30)
        current = self.ptr(team + 0x50) if owner else 0
        if current:
            self.entity(current, ('competition',))
        if not current or self.i32(current + 0xC) != key:
            current = self.ptr(team + 0x58) or self.ptr(team + 0x50)
            if current:
                self.entity(current, ('competition',))
            if not current or self.i32(current + 0xC) != key:
                return False
        self.entity(current, ('competition',))
        nation = self.ptr(current + 0x60)
        if not nation:
            return False
        self.entity(nation, ('nation',))
        projection = self.ptr(nation + (0x118 if self.u8(current + 0xF9) else 0x110))
        if not projection:
            raise SourceUnavailable('Missing typed effective-TEAM definition projection')
        self.entity(projection, ('national_team_container',))
        if self.ptr(projection + 0x170) != nation:
            raise ValueError('Effective-TEAM definition NATION backlink changed')
        return not struct.unpack('<H', self.read(projection + 0x56E, 2))[0] & 0x80

    def change_row(self, primary, supplied_club):
        if not supplied_club:
            return False
        row = self.ptr(primary + 0xE0)
        if not row:
            return False
        uid = self.i32(row + 0x10)
        if uid == -1:
            return False
        club = self.club_uid(uid)
        if not club:
            return False
        values = self.pointers(club + 0x18)
        first = self.team(values[0]) if values else 0
        date = struct.unpack('<I', self.read(row, 4))[0]
        year, day = date >> 16, date & 0x1FF
        if (year, day) != (1900, 1):
            if self.before_today(year, day):
                return False
        if (self.special_mode() and first and
                (self.definition_clear(first, 40) or self.definition_clear(first, 0x773799D3))):
            return club != supplied_club
        # TEAM+60's stored identity family is not proved by the consumer alone.
        if first and self.ptr(first + 0x60):
            raise SourceUnavailable('TEAM+60 raw-ID fallback lacks typed reference provenance')
        return False

    def effective_team(self, person, stored, flags):
        if not person:
            return 0
        primary, common, _, _ = self.person(person)
        if not stored:
            return self.current_team(person)
        self.team(stored)
        if self.special_mode() and not flags & (1 << 11) and self.definition_clear(stored, 40):
            main = self.ptr(common + 0x78)
            category = self.contract(main, person)
            blocked = category and category[0] == 0 and self.u8(main + 0x28) & 8
            club = self.ptr(stored + 0x30) if self.u8(stored + 0x2F) == 0 else 0
            if not blocked and self.change_row(primary, club):
                row = self.ptr(primary + 0xE0)
                uid = self.i32(row + 0x10) if row else -1
                target = self.club_uid(uid) if uid != -1 else 0
                if target:
                    values = self.pointers(target + 0x18)
                    return self.team(values[0]) if values else 0
        # Ordinary PERSON1b0 is literal0, including TEAM.byte2f==1.
        return self.current_team(person)

    def contract_fallback(self, person, owner):
        _, common, _, _ = self.person(person)

        def candidates():
            # cb87c0 returns a main match before cb87c4 reads COMMON+80.
            yield self.ptr(common + 0x78)
            holder = self.ptr(common + 0x80)
            if holder:
                # Each cb85fc holder match returns before the next slot load.
                for offset in (0, 8, 0x10, 0x18):
                    yield self.ptr(holder + offset)

        visited = set()
        for _ in range(PARENT_LIMIT):
            if owner in visited:
                raise SourceUnavailable('Cyclic transfer contract parent fallback')
            visited.add(owner)
            self.club(owner)
            for contract in candidates():
                if not contract:
                    continue
                category = self.contract(contract, person)
                team = self.team(self.ptr(contract + 0x10))
                if team and self.ptr(team + 0x30) == owner:
                    return bool(category[0] != 5 and category[1]
                                and self.i32(contract + 0xC0) >= 0
                                and self.u8(contract + 0xF7) == 100)
            if self.u8(owner + 0xBA) != 0:
                return False
            owner = self.parent(owner)
            if not owner:
                return False
        raise SourceUnavailable('Transfer contract parent fallback exceeds reader budget')

    def predicate(self, person, owner):
        _, common, _, _ = self.person(person)
        indices = self.ptr(common + 0x68)
        if not indices:
            return False, 'null_offer_index_pointer', None
        start, count = self.bounds(indices, 4, VECTOR_LIMIT)
        if count:
            manager = live_transfer_offers._manager(self.read, self.base)
            if not manager or self.ptr(self.base + 0x56A67F0) != manager + 0x18:
                raise SourceUnavailable('Transfer predicate BASE manager roots disagree or absent')
            offers = self.pointers(manager + 0x20, VECTOR_LIMIT)
            for ordinal in range(count):
                index = self.i32(start + ordinal * 4)
                if index < 0 or index >= len(offers) or not offers[index]:
                    continue
                offer = _pointer(offers[index])
                if self.u8(offer + 0x8D) != 19:
                    continue
                table = self.ptr(offer)
                if table - self.base not in live_transfer_offers.CLASSES:
                    raise SourceUnavailable('Unproved transfer predicate offer type')
                kind = live_transfer_offers._type(self.read, self.base, table)
                if kind == 'trade':
                    self.route(table, 0x3A8, 0x1850FD8)
                    rows, n = self.bounds(offer + 0x90, 16, VECTOR_LIMIT)
                    matched = False
                    for i in range(n):
                        raw = self.ptr(rows + 16 * i)
                        if not raw:
                            raise ValueError('Null native trade PERSON row')
                        if self.resolve_placeholder(raw) == person:
                            matched = True
                            break
                    raw_person = None  # The type9 nonmatch cold path uses raw38.
                else:
                    raw_person = self.resolve_placeholder(self.ptr(offer + 0x38))
                    matched = raw_person == person
                if matched:
                    selected = self.team(self.ptr(offer + 0x40))
                    # The other side is not consumed by this exact native caller.
                else:
                    selected = self.ptr(offer + 0x50)
                    if not self.u8(offer + 0x8E) & 1 and not selected:
                        if self.u8(offer + 0x85) != 1:
                            raw = self.ptr(offer + 0x38) if kind == 'trade' else raw_person
                            selected = self.effective_team(raw, self.ptr(offer + 0x40),
                                                           self.i32(offer + 0x30))
                    selected = self.team(selected)
                if self.matches_owner(selected, owner):
                    return True, 'first_offer_vector', ordinal
        return self.contract_fallback(person, owner), 'contract_fallback', None


def evaluate(read, base, subject_person, subject_identity, owner_club, owner_identity, *, check_current):
    """Evaluate the pinned score-call specialization, never a visibility decision.

    Supply the caller's actual ReadSet and current process/save/build callback.
    Arguments are checked canonical source identities, not permission booleans.
    Deriving the score wrapper's selected owner/subject remains its collector's
    responsibility; no result here asserts that those caller branches ran.
    """
    if not isinstance(read, world.ReadSet) or not callable(check_current):
        raise ValueError('Transfer predicate requires caller ReadSet and lifetime callback')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('Invalid transfer predicate lifetime identity')
    subject_identity, owner_identity = _identity(subject_identity), _identity(owner_identity)
    verify_native(read, base)
    source = _Reader(read, base)
    if source.person(subject_person)[3] != subject_identity or source.club(owner_club) != owner_identity:
        raise ValueError('Transfer predicate caller identity binding changed')
    result, route, ordinal = source.predicate(subject_person, owner_club)
    read.verify()
    if check_current() != before:
        raise ValueError('Transfer predicate process/save/build lifetime changed')
    read.verify()
    return {'scope': 'passing_score_cbb9f8_dependency', 'full_score_evaluated': False,
            'native_predicate': result, 'route': route, 'offer_index_ordinal': ordinal,
            'subject_identity': subject_identity, 'owner_identity': owner_identity}


# Pinned static bodies from context/transfer-predicate and closed CLUB/contract source.
NATIVE_GUARDS = (
    (0xcbb9f8, 1592, 'd54857f9120a2a27b088065ec6b0ef0297b4dab89fd6dd3b276b13e3872c3be8'),
    (0x1850fd8, 544, '6bfcb71fb13ac096b6aac965ec2451983397363171fb2efe7cfeac218e66ab06'),
    (0x1869938, 472, 'fe3fad1a76a98d8c6b921c66bc94d910ef49a2601212020fcc087df19b74ffde'),
    (0xd04a24, 544, 'e9a6b2c63f0c07c4762c2bb04c6b0c9e81bd31d3e967af3e1ab5027e9af76899'),
    (0xcb8eb0, 184, 'a2e933cca7e541788985d13045bd634d586b6841962655525e5c8e943a61e161'),
    (0xca47d4, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
    (0xc8cdf0, 96, 'b5e0d9c049be709af1d1247b1dd6b971b16ffa192db1f7ebf876f655c6b0eba6'),
    (0x175d4f4, 688, '070cefa6919c29d791312c8870fe8af8b9cd0df7d2c251412a9f11afb06c71a0'),
    (0xd5c5fc, 20, '62e50aff752959cc367e0ab72a4ea1286e80d2e70d5a58cc8796f16a3c89568d'),
    (0xd5c578, 24, '6e7663bd324f74dd5501be3fbb62c43fb3dbc93e85bb760cc631d976b41ff680'),
    (0xcb3724, 24, 'fe47a1190093b8b56ecf05ed26903bb1621e5bc979ff3fce60ff77b0404010f4'),
    (0xcb8c68, 20, '25c942ded4925619f93fb980c3fde293992b8e61aa50588e1f093c2a01e5cabb'),
    (0xca4638, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x1bdbc08, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0xd8c3c8, 8, '2ce3d9dd052c51e9b635f532c8c1836f5f6300e103cf5ac7f3599a786e511f57'),
    (0x2386d98, 36, 'f3ab784449375b48dcfd1e2512dba592b075b1aec4b25dbcf2b9b648be61b310'),
    (0x105b430, 300, 'bc1df04ac576b24bcc53e63c615900fe0b9c332e768ace0674552898c39776b3'),
    (0x109e5a4, 20, 'da715ff631e5f639ffda0bad4d79071eaff1d4a0eda4a2ac951adfccf1e85027'),
    (0x129fffc, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0xd8c3d0, 8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8'),
    (0x13781b8, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x1006b44, 8, '0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a'),
    (0xd88c8c, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x13781c0, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0xcb85fc, 1644, '671f408e0f459d91457c63d89717b3937b07703b9bdeebfe868c1ad1baa62b62'),
)
