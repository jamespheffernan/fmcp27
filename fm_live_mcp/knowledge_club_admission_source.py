"""Private passive club-admission E58E5C for ordinary actual/combined players.

This is a native Player Search dependency, not a discovery population, field
permission, reputation label or model-ranking input. All inputs are
caller-bound current identities.
"""
from copy import deepcopy
import hashlib
import math
import struct

from . import assessment_people, prepared_tactics_source, world
from . import knowledge_club_score_source as score
from . import knowledge_scouting_range_source as scouting
from . import knowledge_search_preliminary_source as preliminary
from . import knowledge_transfer_predicate as transfer

NATIVE_GUARDS = (
    (0xe58e5c, 0x434, '807cf62487e1ad8fd655fa96357c4844da4ffe9bc36026f9aed6f226800535c5'),
    (0xd4a494, 0x1d4, 'd7dc4d49ab0bc67064faae061a58d7e0a8debe8b597536583eeaa4792ca531c8'),
    (0x148a068, 0x2cc, '92d0cfa708412a836ee68b5cd64c1456730a4577b0d3c6e1fda6a7dfa657005c'),
    (0x1693adc, 0x104, 'e9086b9f67570d3f4e4ddb1d4119ba437cc1351cac80197b97c2f737fcc9dbb7'),
    (0x1300074, 0x14, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa'),
    (0x1005c90, 8, '202b2f20cab67372e4d0f3ce5eaa8cf7cc723ac9dc52103896995f3d35d5016c'),
    (0xca4950, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0xca49c0, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
    (0xca4e30, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0xca4e78, 20, 'd00a7e05bbc8b02cfe3ef011a288eeb1d787d8e9d9bea42002c050b8b2a56139'),
    (0xcb36dc, 24, '8ec6815dfc2912ab6bc1fcec1a8e5def9008e0bbaff0a21ad3f97a6aecd4c1c0'),
    (0xd5c344, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0xca4674,24,'64164ca1568787b841601d69f3ceda841316cad0e4423bb8dd9b7768d7206047'),
)


def signed(value, bits=32):
    return (value + (1 << (bits - 1))) % (1 << bits) - (1 << (bits - 1))


def f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def verify_native(read, base):
    transfer.verify_native(read, base)
    score.verify_native(read, base)
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != digest:
            raise ValueError('Club-admission native source changed')


class Reader(score.Reader, preliminary.Reader):
    def _club_projection(self, club):
        if not club:
            return 0
        self.club(club)
        nation = self.ptr(club + 0xd8)
        if not nation:
            return 0
        self.entity(nation, ('nation',))
        return self.project(nation, self.u8(club + 0xb9) != 0)

    def _team_projection(self, team):
        if not team:
            return 0
        self.team(team)
        owner = self.ptr(team + 0x30)
        if not owner:
            return 0
        nation = self.ptr(owner + (0xd8 if self.u8(team + 0x2f) == 0 else 0x170))
        if not nation:
            return 0
        self.entity(nation, ('nation',))
        return self.project(nation, self.u8(owner + 0xb9) != 0)

    def owner(self, club):
        team = self.first_team(club)
        owner = self.ptr(team + 0x80) if team else 0
        if not owner:
            return 0, None
        prepared_tactics_source._typed(self.read, self.base, owner,
                                      world.TYPES['manager'][0], world.TYPES['manager'][1])
        person = owner + 0x548
        primary, offset, public, uid, secondary = assessment_people._person(
            self.read, self.base, self.table('people'), person)
        if primary != owner or offset != 0x548 or public['record_kind'] != 'human_manager':
            raise transfer.SourceUnavailable('Unproved club-admission owner PERSON family')
        self.adjustment(self.ptr(owner), 0x20, 0x548)
        self.route(self.ptr(person), 0x6f0, 0x1300074)
        return owner, (public['native_identity']['database_index'], uid, secondary)

    def discarded(self, context, person):
        start, count = self.bounds(context + 0x30, 8, 100_000)
        if not count:
            return False
        info = self.table('people')
        alternate = None
        if not self.u8(self.base + 0x56d34e0) & 1:
            alternate = self.bounds2(info['root'] + 0x68, 8, transfer.TABLE_LIMIT)
        for index in range(count):
            entry = self.ptr(start + index * 8)
            if not entry:
                continue
            ordinal = self.i32(entry)
            resolved = 0
            if ordinal >= 0:
                if alternate is not None and ordinal < alternate[1]:
                    resolved = self.ptr(alternate[0] + ordinal * 8)
                elif ordinal < info['count']:
                    resolved = self.ptr(info['start'] + ordinal * 8)
            if resolved == person:
                return True
        return False

    def association(self, person):
        """148A068(...,1), including both ordinary secondary fallbacks."""
        primary, common, _, _ = self.person(person)
        stored = self.team(self.ptr(primary + 0x128))
        self.route(self.ptr(person), 0x230, 0xd5c578)
        self.adjustment(self.ptr(person), 0x240, primary - person)
        club = 0
        if stored and self.u8(stored + 0x2f) == 0:
            club = self.ptr(stored + 0x30)
        if not club:
            self.route(self.ptr(person), 0x3c8, 0xcb3724)
            self.adjustment(self.ptr(person), 0x3d8, -0x110)
            main = self.ptr(common + 0x78)
            if main:
                self.contract(main, person)
                role = self.u8(main + 0x26)
                if role > 1:
                    accepted = True
                else:
                    table = self.ptr(main)
                    kind = next(k for k in transfer.CONTRACTS if table == self.base + world.TYPES[k][0])
                    self.route(table, 0x70, 0x129a4b8 if kind == 'full_contract' else 0xd88c6c)
                    accepted = kind == 'full_contract' and self.u8(main + 0xc2) >= 2
                if accepted:
                    team = self.team(self.ptr(main + 0x10))
                    if team and self.u8(team + 0x2f) == 0:
                        club = self.ptr(team + 0x30)
        projection = self._club_projection(club)
        if projection:
            return projection
        table = self.ptr(person)
        combined = person - primary == 0x480
        self.route(table, 0x4e0, 0xca4e30 if combined else 0xca4950)
        if combined:
            self.route(table, 0x658, 0xca4e78)
            self.adjustment(table, 0x668, -0x208)
            nonplayer = primary + 0x278
            # PERSON's secondary NON_PLAYER casts through its recorded +F8
            # COMMON virtual base before calling COMMON438.
            self.adjustment(self.ptr(nonplayer), 0x18, 0xf8)
            self.route(self.ptr(common), 0x438, 0xcb36dc)
            holder = self.ptr(common + 0x80)
            secondary = self.ptr(holder + 0x10) if holder else 0
            if secondary:
                self.contract(secondary, person)
                projection = self._team_projection(self.ptr(secondary + 0x10))
                if projection:
                    return projection
            projection = self._team_projection(self.ptr(nonplayer + 0x60))
            if projection:
                return projection
        self.route(table, 0x238, 0xca474c)
        self.adjustment(table, 0x248, -0x110)
        projection = self._club_projection(self.ptr(common + 0xd8))
        if projection:
            return projection
        nation = self.subject_nation(person)
        if not nation:
            return 0
        alternate = False
        if self.u8(self.base + 0x56d4992) == 1:
            # Both supported ordinary PERSON4d8 getters are literal true,
            # so the native secondary-status alternative is unreachable.
            self.route(table, 0x4d8, 0xd5c344)
            alternate = bool(int.from_bytes(self.read(person + 0x18, 8), 'little') & 0x1000)
        return self.project(nation, alternate)

    def prominent(self, person):
        primary, common, _, _ = self.person(person)
        scalar = signed(int.from_bytes(self.read(primary + 0x25a, 2), 'little'), 16)
        if scalar > 7000:
            return True
        mode = self.u8(self.base + 0x56d4951)
        if scalar >= 5000 and mode not in (1, 2) and self.u8(self.base + 0x56d496e) & 1:
            return True
        nation = self.subject_nation(person)
        value = int.from_bytes(self.read(common + 0x104, 2), 'little') if nation else None
        if nation:
            projection = self.projection(person, nation)
            if not projection:
                raise transfer.SourceUnavailable('Null native prominence projection')
            team = self.first_team(projection)
            if team:
                raw = signed(int.from_bytes(self.read(team + 0xa8, 2), 'little'), 16)
                shifted = ((raw * 0x5f5f) & 0xffffffff) >> 16
                intermediate = (shifted - raw) & 0xffffffff
                threshold = signed((intermediate >> 6) & 0x3ff, 10) + ((intermediate & 0x8000) >> 15) + 120
            else:
                threshold = 106
            if threshold < value:
                return True
        if scalar < 6251:
            return False
        if value is None:
            value = int.from_bytes(self.read(common + 0x104, 2), 'little')
        product = (scalar * -0xea1) & 0xffffffff
        threshold = (signed(product) >> 18) + (product >> 31) + 120
        if threshold >= value:
            return False
        association = self.association(person)
        if not association:
            return False
        raw = signed(int.from_bytes(self.read(association + 0x572, 2), 'little'), 16)
        divided = f32(f32(raw) / f32(10.0))
        rounded = math.floor(divided + 0.5) if divided >= 0 else math.ceil(divided - 0.5)
        bound = max(signed(rounded, 8), 1)
        return 15 - (((value * 0xcccd) & 0xffffffff) >> 19) <= bound

    def _owned_context(self, owner, offset):
        personal = self.ptr(owner + 0x388)
        if not personal:
            raise transfer.SourceUnavailable('Missing native club-admission HUMAN personal data')
        return personal + offset

    def _first_definition(self, club):
        team = self.first_team(club)
        if not team or not self.ptr(team + 0x30):
            return 0
        definition = self.ptr(team + 0x50)
        if definition:
            self.entity(definition, ('competition',))
        return definition

    def admission(self, club, person, mode):
        primary, common, _, _ = self.person(person)
        owner, owner_identity = self.owner(club)
        self.owner_identity = owner_identity
        if self.u8(self.base + 0x56d4951) == 1:
            return True
        team = self.first_team(club)
        if owner and team:
            context = self._owned_context(owner, 0xbd8 if self.u8(team + 0x2f) == 0 else 0xdb8)
            if self.discarded(context, person):
                return False
        association = self.association(person)
        nation = self.ptr(association + 0x170) if association else 0
        if not nation or not self.ptr(club + 0xd8):
            return False
        if mode:
            if signed(int.from_bytes(self.read(primary + 0x25a, 2), 'little'), 16) > 7999:
                return True
        elif self.prominent(person):
            return True
        stored = self.team(self.ptr(primary + 0x128))
        context_club = self.ptr(stored + 0x30) if stored and self.u8(stored + 0x2f) == 0 else 0
        definition = self._first_definition(context_club) if context_club else 0
        if not definition:
            self.route(self.ptr(person), 0x238, 0xca474c)
            self.adjustment(self.ptr(person), 0x248, -0x110)
            context_club = self.ptr(common + 0xd8)
            if context_club:
                self.club(context_club)
            definition = self._first_definition(context_club) if context_club else 0
        if definition and owner:
            if scouting.admitted(self, club, self._owned_context(owner, 0xbd8), definition, nation):
                return True
        if mode:
            return False
        if definition and nation == self.ptr(club + 0xd8):
            simulation_mode = self.u8(self.base + 0x56d4950)
            if 1 <= simulation_mode <= 3:
                return True
            main = self.ptr(common + 0x78)
            category = self.contract(main, person)
            if category and category[0] == 0:
                dependent = self.ptr(main + 0x18)
            else:
                if stored and not main:
                    holder = self.ptr(common + 0x80)
                    if not holder or not any(self.ptr(holder + off) for off in (0, 8, 0x10, 0x18)):
                        return False
                # Actual PLAYER's getter is literal null. Combined's getter
                # returns main+10 only when the contract's role26 >=2.
                if person - primary == 0x388 or not main:
                    dependent = 0
                else:
                    self.route(self.ptr(main), 0x58, 0xd8c3c8)
                    dependent = self.ptr(main + 0x10) if self.u8(main + 0x26) >= 2 else 0
            if not dependent:
                return True
            if not main or category[0] != 0:
                return False
            table = self.ptr(main)
            self.route(table, 0x128, 0x1005c90)
            native_flags = self.u8(main + 0x57)
            return bool(native_flags & (1 | 8 | 2))
        # CMP age,16; CCMP owner,0,#4,LE; B.NE reject. Preserve this
        # conditional comparison rather than imposing an age-policy meaning.
        if self.native_age(person) <= 16 and owner:
            return False
        raw, _, _ = self.score(club, nation, person)
        simulation_mode = self.u8(self.base + 0x56d4950)
        value = raw if simulation_mode in (1, 2, 3) else int(raw / 2)
        nation_uid = self.entity(nation, ('nation',))[1][1]
        if nation_uid == 0x31c:
            value = int(value / 2)
        elif nation_uid == 0x307 and value < 20:
            value = 20
        if value <= 0:
            return False
        if value >= 100:
            return True
        projection = self.project(nation, bool(int.from_bytes(self.read(person + 0x18, 8), 'little') & 0x1000))
        if not projection:
            raise transfer.SourceUnavailable('Null native score-threshold projection')
        reputation = signed(int.from_bytes(self.read(projection + 0x1ea, 2), 'little'), 16)
        limit = math.trunc(f32(f32(f32(100 - value) / f32(100.0)) * f32(reputation)))
        actual = signed(int.from_bytes(self.read(primary + 0x258, 2), 'little'), 16)
        return limit <= actual


def evaluate(read, base, club, club_identity, person, person_identity, *, check_current, mode=0, expected_owner_identity=None):
    transfer._identity(club_identity)
    transfer._identity(person_identity)
    if type(mode) is not int or mode not in (0, 1):
        raise ValueError('Expected native club-admission mode0/1')
    if expected_owner_identity is not None:
        transfer._identity(expected_owner_identity)
    if not callable(check_current):
        raise ValueError('A checked club-admission lifetime callback is required')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('A checked nonempty lifetime identity is required')
    read = world.ReadSet(read)
    verify_native(read, base)
    reader = Reader(read, base)
    if reader.club(club) != club_identity or reader.person(person)[3] != person_identity:
        raise ValueError('Club-admission canonical identity changed')
    value = reader.admission(club, person, mode)
    if expected_owner_identity is not None and reader.owner_identity != expected_owner_identity:
        raise ValueError('Club-admission selected HUMAN identity changed')
    read.verify()
    if check_current() != before:
        raise ValueError('Club-admission lifetime changed')
    read.verify()
    return {'scope': 'private_native_club_search_admission_branch_only', 'native_result': value,
            'native_mode': mode, 'complete_search_population_evaluated': False,
            'field_visibility_evaluated': False, 'non_atomic': True}
