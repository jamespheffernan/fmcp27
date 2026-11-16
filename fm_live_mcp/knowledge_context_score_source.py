"""Private byte-bound Passing18 K collector; no native calls or field permission.

The public entry owns Bridge process/build/save checks and the selected HUMAN,
CLUB, ordinary subject and FOW owner-record binding. Named operands below are
decoded from those bytes, never accepted as user-supplied score/Boolean facts.
The frozen local K composition is unchanged. Unsupported lower source branches
raise explicitly; a remembered score, fabricated null or cached lookup is not
an alternative. No rich profile, raw attribute getter or UI is read.
"""
from .knowledge_native_scope import collection_stream
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
import struct

from . import (assessment_people, bridge as bridge_module, database,
               knowledge_club_aggregate as aggregate,
               knowledge_context_score as core,
               knowledge_club_score_source as club_score,
               knowledge_scouting_range_source as scouting_range,
               knowledge_search_admission as age,
               knowledge_transfer_predicate as transfer,
               players, prepared_tactics_source, world)

FIELD = 18
LIMIT = 4096


class _Source:
    FIELD_SCOPE = 'Passing18'

    def _supports_field(self, field):
        return type(field) is int and field == FIELD

    def _verify_field_metadata(self):
        if (self.read(self.base + 0x540420e + FIELD, 1) != b'\x16'
                or self.read(self.base + 0x50bda9a, 8) != b'Passing\0'
                or 0x1567f04 + 4 * self.u16(self.base + 0x539d234 + FIELD * 2) != 0x1568350):
            raise core.SourceUnavailable('Selected Passing18 metadata binding changed')

    def __init__(self, bridge, session, subject_person, subject_identity, coach_name, field):
        if not self._supports_field(field):
            raise core.SourceUnavailable(f'Only the proved {self.FIELD_SCOPE} caller is supported')
        self.bridge, self.session, self.coach_name, self.field = bridge, session, coach_name, field
        self.process = deepcopy(bridge._current(session))
        self.tables = bridge._player_layout(self.process)
        self.base = self.tables[0] - players.RVA[0]
        self.plugin = deepcopy(bridge.plugin_identity)
        if not self.plugin:
            raise core.SourceUnavailable('Missing genuine Bridge plugin identity')
        self.read, self.save, self.world_identity = bridge._world_state(self.process, self.tables)
        if not isinstance(self.read, world.ReadSet):
            raise core.SourceUnavailable('Bridge-owned consumed-byte read scope required')
        self.save, self.world_identity = deepcopy(self.save), deepcopy(self.world_identity)
        self.coach = deepcopy(bridge._select_coach(self.save, coach_name))
        _, human = prepared_tactics_source._team_and_human(self.read, self.base, self.coach)
        self.reader = transfer._Reader(self.read, self.base)
        self.snapshots, self.rows = [], set()
        self.people = database.table(self.read, self.base, 'people')
        core.verify_native(self.read, self.base)
        transfer.verify_native(self.read, self.base)
        prepared_tactics_source.verify_native(self.read, self.base)
        for rva, size, digest in EXTRA_GUARDS:
            if hashlib.sha256(self.read(self.base + rva, size)).hexdigest() != digest:
                raise core.SourceUnavailable(f'K collector native source changed at {rva:#x}')
        self.human = human
        owner_person = human + 0x548
        primary, delta, _, uid, secondary = assessment_people._person(self.read, self.base, self.people, owner_person)
        if primary != human or delta != 0x548:
            raise core.SourceUnavailable('Selected HUMAN canonical PERSON projection differs')
        index = self.u32(owner_person + 8)
        owner = core.Person(core.Ref(owner_person, 'human_person', (index, uid, secondary)), human)
        self._human_routes(owner)
        primary, common, kind, identity = self.reader.person(subject_person)
        if type(subject_identity) is not tuple or identity != subject_identity:
            raise core.SourceUnavailable('Subject canonical identity differs from requested source')
        self._ordinary_primary_casts()
        subject = core.Person(core.Ref(subject_person, 'actual_person' if kind == 'actual' else 'combined_person', identity), primary)
        self.route(self.ptr(primary), 0xf0, 0xd19eb0)
        self._verify_field_metadata()
        self.subject_common = common
        self.owner, self.subject = owner, subject
        self.owner_club = self.entity(self.ptr(self.coach['team_address'] + 0x30), 'club')
        self.fow_record = self._fow_owner(owner)
        raw_date = self.read(self.base + world.CURRENT_DATE, 4)
        day, year = struct.unpack('<HH', raw_date)
        self._lifetime_identity = (self.process.pid, json.dumps(self.world_identity, separators=(',', ':')),
            players.SHA256, session, json.dumps(asdict(self.process), sort_keys=True),
            repr(self.plugin), self.base, self.save['save_count'], self.save['current_date'],
            human, self.coach['team_address'], self.owner_club.address, subject_person, *identity, field)
        observation = hashlib.sha256(repr(self._lifetime_identity).encode()).hexdigest()
        self.context = core.Context(observation, players.SHA256, owner, subject, core.NativeDate(year, day))
        if self.current_club(owner) != self.owner_club:
            raise core.SourceUnavailable('K owner CLUB differs from selected coach source')
        self.lifetime()

    def u8(self, at):
        return self.read(at, 1)[0]

    def u16(self, at):
        return int.from_bytes(self.read(at, 2), 'little')

    def u32(self, at):
        return int.from_bytes(self.read(at, 4), 'little')

    def i16(self, at):
        return struct.unpack('<h', self.read(at, 2))[0]

    def ptr(self, at):
        return self.reader.ptr(at)

    def route(self, table, slot, target):
        self.reader.route(table, slot, target)

    def entity(self, address, kind):
        if not address:
            return None
        actual, identity = self.reader.entity(address, (kind,))
        return core.Ref(address, actual, identity)

    def team(self, address, national_only=False):
        if not address:
            return None
        kind, identity = self.reader.entity(address, ('national_team',) if national_only else ('team', 'national_team'))
        marker = self.u8(address + 0x2f)
        if marker != (1 if kind == 'national_team' else 0):
            raise core.SourceUnavailable('TEAM native kind disagrees with canonical family')
        owner_kind = 'national_team_container' if kind == 'national_team' else 'club'
        owner = self.entity(self.ptr(address + 0x30), owner_kind)
        if owner is None:
            raise core.SourceUnavailable('Canonical TEAM owner is missing')
        # Ownership headers are checked once; payloads remain lazy at native
        # visitation points. No unrelated TEAM names/profiles are decoded.
        start, count = self.reader.bounds(owner.address + 0x18, 8, 4096)
        if not any(self.ptr(start + index * 8) == address for index in range(count)):
            raise core.SourceUnavailable('Canonical TEAM is absent from owning vector')
        return core.Ref(address, kind, identity)

    def _human_routes(self, owner):
        table = self.base + 0x55ad820
        common_table = self.base + 0x55acb30
        prepared_tactics_source._typed(self.read, self.base, owner.primary + 0x438,
            0x55acb30, world.TYPES['manager'][1], -0x438)
        for slot, target in ((0x230, 0xca4744), (0x3c8, 0xcb3724),
                             (0x408, 0xc8cf20), (0x678, 0x1300060), (0x1d0, 0xca4674)):
            self.route(table, slot, target)
        self.route(common_table, 0x438, 0x12ffe58)
        for at, value in ((self.base + world.TYPES['manager'][0] - 0x18, 0x438),
                          (table - 0x3d8, -0x110),
                          (table - 0x688, -0x548), (table - 0x418, -0x548),
                          (table - 0x1e0, -0x110), (common_table - 0x18, 0x110)):
            if struct.unpack('<q', self.read(at, 8))[0] != value:
                raise core.SourceUnavailable('HUMAN K subobject displacement changed')

    def _ordinary_primary_casts(self):
        # K itself consumes these primary[-20]/[-18] rows. The transfer lower
        # adapter can also visit either ordinary PERSON class, so bind both
        # accepted class ABIs before fixed COMMON/PERSON offsets are used.
        for table, common, person in ((players.RVA[0], 0x278, 0x388),
                                      (players.STAFF_RVA[0], 0x370, 0x480)):
            if struct.unpack('<qq', self.read(self.base + table - 0x20, 16)) != (common, person):
                raise core.SourceUnavailable('PLAYER primary COMMON/PERSON cast rows changed')

    def _fow_owner(self, owner):
        if self.u8(self.base + 0x56d4980) != 1 or self.u8(self.base + 0x56d4981) & 1:
            raise core.SourceUnavailable('FOW owner route is bypassed; no field permission inferred')
        if self.u8(owner.primary + 0x3fc) & 16:
            raise core.SourceUnavailable('Selected HUMAN FOW owner flag excludes record')
        manager = self.ptr(self.base + 0x56a8430)
        prepared_tactics_source._typed(self.read, self.base, manager, 0x55f5d80, b'18FOG_OF_WAR_MANAGER')
        index = struct.unpack('<i', self.read(owner.primary + 0x3e4, 4))[0]
        start, count = self.reader.bounds(manager + 0x18, 8, 4096)
        if not 0 <= index < count:
            raise core.SourceUnavailable('Selected HUMAN FOW ordinal is invalid')
        record = self.ptr(start + 8 * index)
        if not record or self.ptr(record + 0x18) != owner.person.address:
            raise core.SourceUnavailable('FOW owner record PERSON differs from selected HUMAN')
        return record

    def common(self, person):
        if person == self.owner:
            return person.primary + 0x438
        if person == self.subject:
            return self.subject_common
        raise core.SourceUnavailable('Operand PERSON is outside bound owner/subject')

    def stored_team(self, person):
        self.common(person)
        return None if person == self.owner else self.team(self.ptr(person.primary + 0x128))

    def contract(self, address, person=None):
        if not address:
            return None
        table = self.ptr(address)
        kind = next((name for name in transfer.CONTRACTS if table == self.base + world.TYPES[name][0]), None)
        if kind is None:
            raise core.SourceUnavailable('Unproved K contract family')
        world.typed(self.read, self.base, address, kind)
        if person is not None and self.ptr(address + 8) != person.person.address:
            raise core.SourceUnavailable('Contract PERSON owner differs')
        category_rva, category, loan_rva, _ = transfer.CONTRACTS[kind]
        self.route(table, 0x90, category_rva)
        self.route(table, 0x98, loan_rva)
        self.route(table, 0xa0, 0x1006b4c if kind == 'trial_contract' else 0x12a0004 if kind == 'full_contract' else 0xd88c94)
        return core.Contract(address, kind.removesuffix('_contract'))

    def main(self, person):
        return self.contract(self.ptr(self.common(person) + 0x78), person)

    def accepted(self, contract):
        if self.u8(contract.address + 0x26) > 1:
            return True
        table = self.ptr(contract.address)
        self.route(table, 0x70, 0x129a4b8 if contract.kind == 'full' else 0xd88c6c)
        return contract.kind == 'full' and self.u8(contract.address + 0xc2) >= 2

    def eligible_team(self, person):
        main = self.main(person)
        return self.team(self.ptr(main.address + 0x10)) if main and self.accepted(main) else None

    def current_club(self, person):
        # K dispatches both selected PERSONs through slot240 before this
        # 1489900 implementation. A pinned callee body alone cannot establish
        # the observed runtime dispatch that chose it.
        self.route(self.ptr(person.person.address), 0x240, 0x1489900)
        stored = self.stored_team(person)
        if stored and stored.kind == 'team':
            return self.entity(self.ptr(stored.address + 0x30), 'club')
        team = self.eligible_team(person)
        return self.entity(self.ptr(team.address + 0x30), 'club') if team and team.kind == 'team' else None

    def selected_contract(self, person, club):
        common = self.common(person)
        if club is None:
            return None  # cb85fc x1-null entry.
        seen = set()
        for _ in range(64):
            if club.address in seen:
                raise core.SourceUnavailable('Cyclic club-specific contract selector')
            seen.add(club.address)
            def candidates():
                yield self.ptr(common + 0x78)
                holder = self.ptr(common + 0x80)
                if holder:
                    for offset in (0, 8, 0x10, 0x18):
                        yield self.ptr(holder + offset)
            for address in candidates():
                contract = self.contract(address, person)
                if contract is None:
                    continue
                team = self.team(self.ptr(contract.address + 0x10))
                raw_owner = self.ptr(team.address + 0x30) if team else 0
                # Four proved categories exclude native kind3 alias handling.
                self.u8(club.address + 0xba)
                if raw_owner == club.address:
                    return contract
            if self.u8(club.address + 0xba):
                return None
            address = self.reader.parent(club.address)
            if not address:
                return None
            club = self.entity(address, 'club')
        raise core.SourceUnavailable('Contract selector exceeds bounded parent depth')

    def secondary_team(self):
        if self.u8(self.base + 0x56d4993) != 1:
            return None
        if struct.unpack('<q', self.read(self.base + 0x55acb30 - 0x450, 8))[0] != -0x438:
            raise core.SourceUnavailable('HUMAN DATA438 owning-primary cast changed')
        wrapper = self.ptr(self.common(self.owner) + 0x80)
        contract = self.contract(self.ptr(wrapper + 0x10)) if wrapper else None
        return self.team(self.ptr(contract.address + 0x10)) if contract else None

    def national(self):
        table = self.ptr(self.subject.person.address)
        self.route(table, 0x220, 0xd5c560)
        if struct.unpack('<q', self.read(table - 0x230, 8))[0] != self.subject.primary - self.subject.person.address:
            raise core.SourceUnavailable('PERSON220 national assignment projection changed')
        return self.team(self.ptr(self.subject.primary + 0x120), national_only=True)

    def stored_context(self, person):
        table = self.ptr(person.person.address)
        self.route(table, 0x238, 0xca474c)
        if struct.unpack('<q', self.read(table - 0x248, 8))[0] != -0x110:
            raise core.SourceUnavailable('PERSON238 COMMON+D8 alias changed')
        return self.entity(self.ptr(self.common(person) + 0xd8), 'club')

    def first_team(self, club):
        self.entity(club.address, club.kind)
        start, count = self.reader.bounds(club.address + 0x18, 8, 4096)
        return self.team(self.ptr(start)) if count else None

    def association(self, person):
        # Exact148a068(...,1) direct normal stored/eligible-contract CLUB route.
        club = self.current_club(person)
        if club:
            nation = self.entity(self.ptr(club.address + 0xd8), 'nation')
            if nation:
                container = self.entity(self.ptr(nation.address + (0x118 if self.u8(club.address + 0xb9) else 0x110)), 'national_team_container')
                if container:
                    if self.ptr(container.address + 0x170) != nation.address:
                        raise core.SourceUnavailable('Association container NATION backlink changed')
                    return container
        raise core.SourceUnavailable('Unproved148a068 fallback PERSON4e0/658/238/1d0 mode selection')

    def primary_predicate(self, slot):
        self.route(self.ptr(self.subject.primary), slot, 0xcffffc if slot == 0x2e8 else 0xcfff70)
        holder = self.ptr(self.common(self.subject) + 0x80)
        contract = self.contract(self.ptr(holder), self.subject) if holder else None
        if contract is None:
            return 0
        if slot == 0x300:
            return int(contract.category == 2)  # kind4 remains outside typed classes.
        if contract.category != 1:
            return 0
        team = self.team(self.ptr(contract.address + 0x10))
        if team is None or team.kind != 'team':
            return 1
        club = self.ptr(team.address + 0x30)
        if not club:
            return 1
        start, count = self.reader.bounds(club + 0x118, 8, 4096)
        for index in range(count):
            row = self.ptr(start + 8 * index)
            if not row:
                raise core.SourceUnavailable('Null consumed primary2e8 relation row')
            if self.ptr(row + 8) == club and self.u8(row + 0x30) == 18:
                return 0
        return 1

    def relation_mask(self):
        owner, subject = self.current_club(self.owner), self.current_club(self.subject)
        if not self.u8(self.owner.primary + 0x422) & 1:
            if self.u8(self.base + 0x56d34e0) == 1 and self.u8(self.base + 0x56d498a) == 1 and self.u8(self.base + 0x56d498b) & 1:
                return 0x5fe
        if owner is not None and subject == owner:
            return 0
        raise core.SourceUnavailable('Unproved20ee608 auxiliary/fanout17bb4c0 and assessment selector composition')

    def range_helper(self, subject, owner, club, definition, nation):
        if (subject, owner) != (self.subject, self.owner):
            raise core.SourceUnavailable('Range helper observer/subject differs')
        self.entity(club.address, 'club'); self.entity(definition.address, 'competition')
        personal = self.ptr(owner.primary + 0x388)
        if not personal:
            raise core.SourceUnavailable('Missing owned HUMAN personal range source')
        return scouting_range.admitted(self.reader,club.address,personal+0xbd8,
                                       definition.address,nation.address if nation else 0)

    def native_age(self, person):
        if person != self.subject:
            raise core.SourceUnavailable('Native age subject differs')
        table = self.ptr(person.person.address)
        self.route(table, 0x138, 0x148f4c0)
        self.route(table, 0x1b8, 0xca4640)
        if struct.unpack('<q', self.read(table - 0x1c8, 8))[0] != -0x110:
            raise core.SourceUnavailable('PERSON DOB COMMON projection changed')
        birth = age.NativeDate.from_bytes(self.read(self.common(person) + 0x58, 4))
        core.NativeDate(birth.year, birth.day_word).validate_calendar()
        if birth.default:
            return 0
        return self._age_from_birth(birth)

    # The date-dependent steps of K are separate methods so that a caller can record which
    # date facts one evaluation used (knowledge_fast). Their behaviour is unchanged.
    def date_passed(self, parts):
        return parts <= self.context.today.parts

    def days_since_exceeds(self, year, day, limit):
        now_year, now_day = self.context.today.parts
        return core._signed((now_year - year) * 365 + now_day - (day & 511), 32) > limit

    def date_escape(self):
        return None

    def _age_from_birth(self, birth):
        at_date = age.NativeDate.from_bytes(self.read(self.base + 0x52efdf0, 4))
        mode, current, alternate, fallback = None, None, None, None
        selected = at_date
        if at_date.default:
            mode = self.u8(self.base + 0x56d4951)
            # Native loads the alternate root before CSEL even in mode0. Only
            # its selected DATE is dereferenced/type-bound in modes1/2.
            rules = players.u64(self.read(self.base + 0x56d57d0, 8))
            if mode in (1, 2):
                prepared_tactics_source._typed(self.read, self.base, rules, 0x55dd068, b'23GAME_RULE_GROUP_MANAGER')
                alternate = selected = age.NativeDate.from_bytes(self.read(rules + 0x184, 4))
            else:
                current = selected = age.NativeDate.from_bytes(self.read(self.base + world.CURRENT_DATE, 4))
        core.NativeDate(selected.year, selected.day_word).validate_calendar()
        if selected.year == 1900:
            fallback = self.u16(self.base + 0x56b3390)
        return age.person_age(birth, at_date, mode=mode, current_date=current,
                              alternate_date=alternate, fallback_year=fallback)

    def lifetime(self):
        process = self.bridge._current(self.session)
        tables = self.bridge._player_layout(process)
        snapshot, save, identity = self.bridge._world_state(process, tables)
        self.snapshots.append(snapshot)
        coach = self.bridge._select_coach(save, self.coach_name)
        if (process != self.process or tables != self.tables or self.bridge.plugin_identity != self.plugin
                or save != self.save or identity != self.world_identity or coach != self.coach):
            raise core.SourceUnavailable('Bridge process/plugin/save/date/selected coach changed')
        if self.ptr(coach['team_address'] + 0x80) != self.human or self.ptr(coach['team_address'] + 0x30) != self.owner_club.address:
            raise core.SourceUnavailable('Selected HUMAN/TEAM/CLUB backlink changed')
        snapshot.verify()
        return self._lifetime_identity

    def verify(self):
        self.read.verify()
        self.lifetime()  # Final callback precedes every consumed-byte recheck.
        for snapshot in self.snapshots:
            snapshot.verify()
        self.read.verify()

    def operand(self, name, *args):
        # There is no external named-operand provider. All aliases resolve back
        # to the same checked field and ReadSet; repeated reads cannot disagree.
        value = self._operand(name, *args)
        return core.Operand(self.context, value)

    def _operand(self, name, *args):
        if name == 'subject_common102':
            return self.u16(self.common(args[0]) + 0x102)
        if name == 'current_club':
            return self.current_club(args[0])
        if name == 'owner408_team':
            return self.secondary_team()
        if name == 'player120_national':
            return self.national()
        if name in ('national_e2', 'national_b8'):
            if args[0] != self.national():
                raise core.SourceUnavailable('National source pointer changed')
            if name == 'national_e2':
                return self.u8(args[0].address + 0xe2)
            day, year = struct.unpack('<HH', self.read(args[0].address + 0xb8, 4))
            return core.NativeDate(year, day)
        if name == 'stored_team':
            return self.stored_team(args[0])
        if name == 'team_owner':
            team = self.team(args[0].address)
            return self.entity(self.ptr(team.address + 0x30), 'club' if team.kind == 'team' else 'national_team_container')
        if name == 'team_definition':
            self.team(args[0].address)
            return self.entity(self.ptr(args[0].address + 0x50), 'competition')
        if name == 'first_team':
            return self.first_team(args[0])
        if name in ('club_d8', 'container170'):
            kind, offset = ('club', 0xd8) if name == 'club_d8' else ('national_team_container', 0x170)
            if self.entity(args[0].address, kind) != args[0]:
                raise core.SourceUnavailable('Association source canonical identity changed')
            return self.entity(self.ptr(args[0].address + offset), 'nation')
        if name == 'common38':
            table = self.ptr(args[0].person.address)
            self.route(table, 0x1d0, 0xca4674)
            if struct.unpack('<q', self.read(table - 0x1e0, 8))[0] != -0x110:
                raise core.SourceUnavailable('PERSON1d0 COMMON38 projection changed')
            return self.entity(self.ptr(self.common(args[0]) + 0x38), 'nation')
        if name == 'common_d8_pointer':
            return self.ptr(self.common(args[0]) + 0xd8)
        if name in ('subject238_context', 'proved_common_d8_club'):
            value = self.stored_context(args[0])
            if len(args) == 2 and (value.address if value else 0) != args[1]:
                raise core.SourceUnavailable('COMMON+D8 alias pointer changed')
            return value
        if name == 'selected_contract':
            return self.selected_contract(*args)
        if name == 'contract_expiry':
            contract = self.contract(args[0].address, self.subject)
            if contract != args[0] or contract.kind != 'trial':
                raise core.SourceUnavailable('Unproved reached contract E8 DATE family')
            self.route(self.ptr(contract.address), 0xe8, 0x1005c68)
            day, year = struct.unpack('<HH', self.read(contract.address + 0x44, 4))
            return core.NativeDate(year, day)
        if name == 'eligible_owner_contract_team':
            return self.eligible_team(args[0])
        if name in ('player25a', 'player258'):
            if args[0] != self.subject:
                raise core.SourceUnavailable('Internal scalar subject differs')
            return self.i16(self.subject.primary + (0x25a if name == 'player25a' else 0x258))
        if name == 'team28':
            self.team(args[0].address)
            return self.u8(args[0].address + 0x28)
        if name == 'native_age':
            return self.native_age(args[0])
        if name in ('primary2e8', 'primary300'):
            return self.primary_predicate(0x2e8 if name == 'primary2e8' else 0x300)
        if name == 'relevant_subject_club':
            team = self.team(self.reader.current_team(self.subject.person.address))
            return self.entity(self.ptr(team.address + 0x30), 'club') if team and team.kind == 'team' else None
        if name == 'relation_mask':
            return self.relation_mask()
        if name == 'transfer_predicate':
            person, club = args
            result = transfer.evaluate(self.read, self.base, person.person.address, person.person.identity,
                club.address, club.identity, check_current=self.lifetime)
            return result['native_predicate']
        if name == 'association_context':
            return self.association(args[0])
        if name == 'association1ea':
            self.entity(args[0].address, 'national_team_container')
            return self.i16(args[0].address + 0x1ea)
        if name == 'range_helper':
            return self.range_helper(*args)
        if name == 'club_score':
            club,nation,low,high,person=args
            if person!=self.subject or (low,high)!=(14,45):
                raise core.SourceUnavailable('Club-score subject/caller age frame differs')
            if self.entity(club.address,'club')!=club:
                raise core.SourceUnavailable('Club-score caller CLUB identity differs')
            result=club_score.observe(self.read,self.base,club.address,club.identity,
                nation.address if nation else 0,nation.identity if nation else None,
                person.person.address,person.person.identity,check_current=self.lifetime)
            return result['native_score']
        if name == 'club_aggregate':
            club, nation = args
            team = self.national()
            owner = self.entity(self.ptr(team.address + 0x30), 'national_team_container')
            actual_nation = self.entity(self.ptr(owner.address + 0x170), 'nation')
            if actual_nation != nation:
                raise core.SourceUnavailable('Aggregate K nation/PLAYER120 source differs')
            def binding(ref):
                return aggregate.EntityBinding(ref.address, ref.kind, ref.identity[0], core._signed(ref.identity[1], 32))
            context = aggregate.ContextBinding(binding(club), binding(team), binding(owner), self.lifetime())
            return aggregate.observe(self.read, self.base, context, check_current=self.lifetime).native_value
        if name in ('club163', 'club_relation_count', 'club_relation_row'):
            club = self.entity(args[0].address, 'club')
            if club != args[0]:
                raise core.SourceUnavailable('Relation CLUB identity changed')
            if name == 'club163':
                return self.u8(club.address + 0x163)
            start, count = self.reader.bounds(club.address + 0x118, 8, LIMIT)
            if name == 'club_relation_count':
                return count
            index = args[1]
            if type(index) is not int or not 0 <= index < count:
                raise core.SourceUnavailable('Relation row index is outside bound source')
            address = self.ptr(start + index * 8)
            if not address:
                raise core.SourceUnavailable('Null consumed relation row')
            self.rows.add(address)
            return core.RelationRow(address)
        if name.startswith('relation_'):
            row = args[0]
            if type(row) is not core.RelationRow or row.address not in self.rows:
                raise core.SourceUnavailable('Relation row lacks an owning bound vector')
            if name in ('relation_first', 'relation_second'):
                return self.entity(self.ptr(row.address + (8 if name == 'relation_second' else 0)), 'club')
            offset = {'relation_kind': 0x30, 'relation_byte15': 0x15, 'relation_word1c': 0x1c}.get(name)
            if offset is not None:
                return self.u32(row.address + offset) if name == 'relation_word1c' else self.u8(row.address + offset)
        missing = {'next_fixture': '17743b8 warm TEAM_IN_GAME_DATA+B8 fixture type producer',
                   'game_team98': '21eb7dc retained/staff/context fanouts'}
        raise core.SourceUnavailable('Unimplemented reached K source: ' + missing.get(name, name))


def collect(bridge, session_id, *, subject_person, subject_identity, coach_name=None, field=FIELD):
    """Private root/probe route. Never register this numeric result as a tool.

    Bridge itself owns process/session discovery and build verification. No
    arbitrary permission/lifetime callback or named facts are accepted here.
    Source construction failures reject the observation; reached lower gaps
    produce an unavailable K only after genuine final verification.
    """
    if not isinstance(bridge, bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock, collection_stream(bridge,session_id):
        source = _Source(bridge, session_id, subject_person, subject_identity, coach_name, field)
        result = core.evaluate(source)
        source.verify()
        return {'scope': 'private_byte_bound_passing18_K_not_field_permission',
                'field': field, 'score': result.score, 'unavailable_reason': result.reason,
                'current_date': source.save['current_date'],
                'owner_identity': source.owner.person.identity,
                'subject_identity': source.subject.person.identity,
                'fow_owner_record_bound': True, 'non_atomic_read': True,
                'field_state_or_permission_evaluated': False}


EXTRA_GUARDS = (
    (0x23871f0, 0xab8, '96ccf286063553b055db4d95e2cecb046e85cfb027c4676faba6489c8de77cec'),
    (0x26c3550, 0x78, '896bde7318ce7104123fafbb2f808143b7c0a87e10c7d0a33cffe69505979bcf'),
    (0x12ffe58, 0x44, '886c19702f1de55ea43b2858e54d30ca614142ec863c5fc31319727f3486c69c'),
    (0xcffffc, 0xc0, '0972c31c475891e8188d31f9c570eb2da64e2a657bb037fd86731859bfadcdd0'),
    (0xcfff70, 0x8c, '4b3ae0df2a246b650dc4c8f28045228276ff8ba8ebebf63c9b3bbe0c184df6f1'),
    (0x20ee608, 0x3f0, '838d53e5227bff6ff0a83e3d73ea3580c709406e0540078b126fd5f258785bd3'),
    # The older population span stopped two epilogue instructions early.
    # This complete LC_FUNCTION_STARTS body includes the final restore + RET.
    (0x148a068, 0x2cc, '92d0cfa708412a836ee68b5cd64c1456730a4577b0d3c6e1fda6a7dfa657005c'),
    (0xe1e354, 0x1d8, '1277c441fd97593e88a1c04286306bd7cf8fa5fe796941b1a8fd4f51ab546629'),
    (0x1fa72c4, 744, '9daa40a22b8a99833db2242ca38f9dce844474e6c82a6eab883c67f9ed66dd6a'),
    (0x169552c, 644, '114c335d315c5479e32146ec583b3abcd1fba7625e02dd4b4f7df32db795b370'),
    (0xe076bc, 580, '814a213ea4b5f7a8c59604aa7d3b76e319ea6c19597c3c14b81e318410492358'),
    (0x1fa64d8, 1664, 'b3e5b811fd6cdb270bee23596efd09c9d565565ff0df49cb52c71b36a1e301b8'),
    (0xd5c344, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x53b0998, 232, '2b21e60f0d7c171524109ae0f2094fa92270471f2d665b6ed580ab8e8db52f4f'),
    (0xf0f038, 228, '708c7de12ef3e33ce8ba3820a659cfe1fe1b9e84cc57f7b174ad513224af1482'),
    (0x3ab45dc, 32, '957b1ff4944a3b7cecee8e780c3b7ca7ef094a73eb8b8e1adb31c7ce988dd2b0'),
    (0xca474c, 0x18, '6384d050d1bd782506916ca8ee0d9fb1fa33ad7bbcbd4dc0aacfd3d3174c665d'),
    (0xd5c560, 0x18, 'b1dc53d36b46f17d51eb2f591c15fba72ef2c415de7e8528f3dfd6f4f0e94190'),
    (0x1300074, 0x14, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa'),
    (0x12a0004, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0xd88c94, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x1006b4c, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x129a4b8, 8, '23ba31bca6e99eeaeca35232f284c89f546e52d3ab4cc441902fc17db7fc1dc1'),
    (0xd88c6c, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x1005c68, 8, '1e846fca3969ce43ef7cade5f06eb84f9a6bc0afa2ce2a998b7907dfe1b6f6ed'),
    (0xca4744, 8, 'd3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3'),
    (0x26c3688, 0x100, '44c005348b6645700314e7e11ab1781548124f3ed6ae27f312fba9d705327198'),
    (0xd19eb0, 0x78, '8cf664225461c38119f9007fb7735bb3585839e49183fe6d43e957bbb9ac609b'),
    (0x4acf834, 0x24, 'f0b21cec26691de907c307936e46a342cdd2ca1a812ad2995a8b6c9de0f37325'),
    (0xca4640, 0x18, '0a3f211c122334f1ccd799afcee3155b50897632e8b5fa2d6a97f6c15006c8eb'),
    (0x148f4c0, 0x54, '0bbcb291971498f3812946f0484bef7bbd3cc1cef6299c9ddfb13971e8e8326e'),
    (0x3d574b0, 0x19c, '78b0d4b5f4560c664509fecaf04e43d17aa48dce579c84d5aa02e1fac5491664'),
)
