"""Private local composition of FM27's contextual K, not a field permission.

Source: evidence/knowledge-field-visibility-20261108/context/full-score and its
independent/type-bridge receipts. This module does not collect live operands.
A future collector must supply typed canonical operands from one checked
observer/subject/save/date/read lifetime, pin native code and verify all consumed
bytes. Lower dependency results are explicit, context-bound operands; absent,
cold, unproved or changed sources remain unavailable. No native invocation,
cache materialization, getter value, profile, public API or Manager mode.
"""
from dataclasses import dataclass
from datetime import date, timedelta
import hashlib
import math
import struct
from typing import Callable, Protocol

PLUGIN_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
SCORE_SOURCE_SHA256 = '05ffe01b9431a13dc851b3f113ff8403d3f9792426bbfbb2edb7cbe1fff219c1'
TYPE_BRIDGE_SHA256 = 'c0c7e8b72fb9c4442c73d6ea5ef0529edf256d508d93475428120f8643b13488'
VECTOR_LIMIT = 4096


class SourceUnavailable(ValueError):
    """A reached source is missing, malformed, changed or not passively proved."""


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high:
        raise SourceUnavailable('Invalid native integer operand')
    return value


def _signed(value, bits):
    return (value + (1 << (bits - 1))) % (1 << bits) - (1 << (bits - 1))


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def _fcvtzs32(value):
    # A64 FCVTZS saturates out-of-domain finite inputs to signed32.
    return min(max(math.trunc(value), -(1 << 31)), (1 << 31) - 1)


@dataclass(frozen=True)
class Ref:
    """Canonical identity operand; its construction does not verify live bytes."""
    address: int
    kind: str
    identity: tuple[int, int, int]

    def __post_init__(self):
        _integer(self.address, 4096, (1 << 64) - 1)
        if self.address % 8 or type(self.kind) is not str or not self.kind:
            raise SourceUnavailable('Invalid canonical reference')
        if type(self.identity) is not tuple or len(self.identity) != 3:
            raise SourceUnavailable('Expected native ordinal/UID/raw-secondary identity')
        for value in self.identity:
            _integer(value, 0, (1 << 32) - 1)
        if self.identity[0] == 0xffffffff or not self.identity[1]:
            raise SourceUnavailable('Invalid canonical reference identity')


@dataclass(frozen=True)
class Person:
    person: Ref
    primary: int

    def __post_init__(self):
        _integer(self.primary, 4096, (1 << 64) - 1)
        offset = {'human_person': 0x548, 'actual_person': 0x388,
                  'combined_person': 0x480}.get(self.person.kind)
        if offset is None or self.person.address != self.primary + offset:
            raise SourceUnavailable('Unproved PERSON to full-primary projection')


@dataclass(frozen=True, order=True)
class NativeDate:
    year: int
    low_half: int

    def __post_init__(self):
        _integer(self.year, 0, 65535)
        _integer(self.low_half, 0, 65535)

    @property
    def parts(self):
        return self.year, self.low_half & 511

    def validate_calendar(self):
        # Match the existing canonical packed-DATE reader's supported domain.
        year, day = self.parts
        if not 1850 <= year <= 2200 or not 1 <= day <= 366:
            raise SourceUnavailable('Unproved native DATE domain')
        if (date(year, 1, 1) + timedelta(days=day - 1)).year != year:
            raise SourceUnavailable('Unproved native day-of-year')


@dataclass(frozen=True)
class Contract:
    """Checked four-class contract reference; dates are separately lazy operands."""
    address: int
    kind: str

    def __post_init__(self):
        _integer(self.address, 4096, (1 << 64) - 1)
        if self.kind not in ('full', 'basic', 'loan', 'trial') or self.address % 8:
            raise SourceUnavailable('Unproved contract virtual family')

    @property
    def category(self):
        return {'full': 0, 'basic': 5, 'loan': 1, 'trial': 2}[self.kind]

    @property
    def active(self):
        return self.kind == 'trial'  # Checked virtual A0, not an English status.


@dataclass(frozen=True)
class RelationRow:
    """Owned plain relation-row pointer; payload fields are fetched on demand."""
    address: int

    def __post_init__(self):
        _integer(self.address, 4096, (1 << 64) - 1)
        if self.address % 8:
            raise SourceUnavailable('Invalid native relation row pointer')


@dataclass(frozen=True)
class Context:
    observation: str
    plugin_sha256: str
    owner: Person | None
    subject: Person | None
    today: NativeDate

    def __post_init__(self):
        if type(self.observation) is not str or not self.observation:
            raise SourceUnavailable('Missing source read-lifetime binding')
        if self.plugin_sha256 != PLUGIN_SHA256 or type(self.today) is not NativeDate:
            raise SourceUnavailable('Unsupported source build or current native date')
        self.today.validate_calendar()
        if self.owner is not None and (type(self.owner) is not Person or self.owner.person.kind != 'human_person'):
            raise SourceUnavailable('Selected owner must be a checked HUMAN PERSON')
        if self.subject is not None and (type(self.subject) is not Person or self.subject.person.kind not in ('actual_person', 'combined_person')):
            raise SourceUnavailable('Ordinary actual/combined PLAYER required')


@dataclass(frozen=True)
class Operand:
    context: Context
    value: object


class Source(Protocol):
    context: Context

    def operand(self, name: str, *arguments: object) -> Operand:
        """Resolve this exact named source lazily or raise SourceUnavailable.

        Ref/Person values require actual canonical type/identity/backlink checks;
        national PLAYER120 additionally requires kind1 and canonical container.
        Lower callee results require their proved passive producer, not a native
        call or an externally supplied unbound Boolean/score. There is no default
        value for a missing result. Null means checked native absence only.
        """
        ...

    def verify(self) -> None:
        """Recheck consumed bytes AND the caller's process/build/save lifetime."""
        ...


@dataclass(frozen=True)
class Result:
    score: int | None
    reason: str | None
    scope: str = 'private_local_contextual_K_composition_not_field_permission'


def relation_score(mask):
    _integer(mask, 0, 65535)
    if mask & 128:
        return 100
    return next((score for bit, score in ((6, 91), (5, 81), (4, 71),
                 (3, 61), (2, 41), (1, 21)) if mask & (1 << bit)), 0)


def date_contribution(today, expiry):
    if type(today) is not NativeDate or type(expiry) is not NativeDate:
        raise SourceUnavailable('Unproved contract DATE operand')
    delta = 250 if today.parts == (1900, 1) else (
        (today.year - expiry.year) * 365 + today.parts[1] - expiry.parts[1])
    return min(_signed(min(_signed(delta, 16), 10) * 10, 8), 100)


def score_threshold(raw_score, context_scalar):
    _integer(raw_score, -(1 << 31), (1 << 31) - 1)
    _integer(context_scalar, -32768, 32767)
    difference = _signed(100 - raw_score, 32)
    return _fcvtzs32(_f32(_f32(_f32(difference) / _f32(100)) * _f32(min(context_scalar, 7000))))


def scaled_score_base(raw_score, scalar258):
    _integer(raw_score, -(1 << 31), (1 << 31) - 1)
    _integer(scalar258, -32768, 32767)
    raw = b'\xcd\xcc\x4c\x3e' if scalar258 >= 5000 else b'\x9a\x99\x19\x3e' if scalar258 >= 4000 else b'\xcd\xcc\xcc\x3d' if scalar258 >= 3000 else b'\xcd\xcc\x4c\x3d'
    factor = struct.unpack('<f', raw)[0]
    return _signed(_fcvtzs32(_f32(_f32(raw_score) * factor)) + 10, 8)


class _Score:
    def __init__(self, source):
        self.source, self.context = source, source.context
        if type(self.context) is not Context:
            raise SourceUnavailable('Explicit source context required')
        self.owner, self.subject = self.context.owner, self.context.subject
        self.references = {p.person.address: p.person for p in (self.owner, self.subject) if p is not None}

    def ask(self, name, *args):
        operand = self.source.operand(name, *args)
        if type(operand) is not Operand or operand.context != self.context:
            raise SourceUnavailable('Operand belongs to another observer/subject/date/read lifetime')
        return operand.value

    def integer(self, name, low, high, *args):
        return _integer(self.ask(name, *args), low, high)

    def boolean(self, name, *args):
        value = self.ask(name, *args)
        if type(value) is not bool:
            raise SourceUnavailable('Expected proved native Boolean dependency')
        return value

    def ref(self, name, kinds, *args):
        value = self.ask(name, *args)
        if value is not None and (type(value) is not Ref or value.kind not in kinds):
            raise SourceUnavailable('Unexpected canonical source family: ' + name)
        if value is not None:
            previous = self.references.setdefault(value.address, value)
            if previous != value:
                raise SourceUnavailable('Canonical identity changed within source context')
        return value

    @staticmethod
    def same(first, second):
        return (first.address if first else 0) == (second.address if second else 0)

    def contract(self, club):
        value = self.ask('selected_contract', self.subject, club)
        if value is not None and type(value) is not Contract:
            raise SourceUnavailable('Unproved selected-contract family')
        return value

    def rows(self, club):
        count = self.integer('club_relation_count', 0, VECTOR_LIMIT, club)
        # Header geometry is a collector prerequisite. Fetch only the visited
        # pointer/payload; a later malformed or unavailable row is not consumed.
        for index in range(count):
            row = self.ask('club_relation_row', club, index)
            if type(row) is not RelationRow:
                raise SourceUnavailable('Malformed visited native relation row')
            yield row

    def parent(self, club):
        # A source may share this pure function of the club between evaluations (bulk engine).
        shared = getattr(self.source, 'shared_score', None)
        if shared is not None:
            return shared(('parent', club), lambda: self._parent(club))
        return self._parent(club)

    def _parent(self, club):
        if self.integer('club163', 0, 255, club) & 16:
            return None
        for row in self.rows(club):
            second = self.ref('relation_second', ('club',), row)
            if self.same(second, club) and self.integer('relation_kind', 0, 255, row) in (4, 5, 6, 7, 8, 20):
                return self.ref('relation_first', ('club',), row)
        return None

    def club_relation(self, first, second):
        shared = getattr(self.source, 'shared_score', None)
        if shared is not None:
            return shared(('club_relation', first, second), lambda: self._club_relation(first, second))
        return self._club_relation(first, second)

    def _club_relation(self, first, second):
        if second is None or self.same(first, second):
            return False
        parent = self.parent(first)
        if self.same(parent, second):
            return True
        other = self.parent(second)
        if other:
            if self.same(other, first) or self.same(other, parent):
                return True
            second = other
        left = parent or first
        if self.same(second, left):
            return False
        for row in self.rows(left):
            if self.integer('relation_kind', 0, 255, row) in (17, 24):
                continue
            if self.integer('relation_byte15', 0, 255, row) & 32:
                continue
            flags = self.integer('relation_word1c', 0, 0xffffffff, row)
            if flags & (1 << 30):
                continue
            first = self.ref('relation_first', ('club',), row)
            if self.same(first, second) or self.same(self.ref('relation_second', ('club',), row), second):
                return bool(flags & 2)  # First qualifying false also stops.
        return False

    def projection(self, team):
        if team is None:
            return None
        # TEAM30 is a canonical CLUB or NATIONAL_TEAM_CONTAINER according to
        # the already checked TEAM kind; a shape-only family is unavailable.
        owner = self.ref('team_owner', ('club', 'national_team_container'), team)
        if owner is None:
            return None
        field = 'club_d8' if team.kind == 'team' else 'container170'
        return self.ref(field, ('nation',), owner)

    def first_team(self, club):
        # The collector validates vector header and first-pointer ownership;
        # this does not scan for an English first-team label.
        return self.ref('first_team', ('team', 'national_team'), club)

    def definition(self, team):
        if team is None or self.ref('team_owner', ('club', 'national_team_container'), team) is None:
            return None
        return self.ref('team_definition', ('competition',), team)

    def adjust(self, base):
        # Local2388658. The lower association/range helper is reached only after
        # the definition and eligible normal owner TEAM have been established.
        base = max(_integer(base, -(1 << 31), (1 << 31) - 1), 0)
        stored = self.ref('stored_team', ('team', 'national_team'), self.subject)
        definition = None
        if stored is not None and stored.kind == 'team':
            club = self.ref('team_owner', ('club',), stored)
            if club:
                definition = self.definition(self.first_team(club))
        if definition is None:
            context = self.ref('subject238_context', ('club',), self.subject)
            if context:
                definition = self.definition(self.first_team(context))
        owner_team = self.ref('eligible_owner_contract_team', ('team', 'national_team'), self.owner)
        if owner_team is not None and owner_team.kind == 'team' and definition:
            owner_club = self.ref('team_owner', ('club',), owner_team)
            if owner_club:
                association = self.ref('association_context', ('national_team_container',), self.subject)
                nation = self.ref('container170', ('nation',), association) if association else None
                if self.boolean('range_helper', self.subject, self.owner, owner_club, definition, nation):
                    base = min(base, 90) + 10
        return min(base & 255, 100)

    def game_team(self, first, second):
        fixture = self.ref('next_fixture', ('fixture', 'fixture_result'), first, 365)
        return self.boolean('game_team98', first, second, fixture)

    def merged(self, prior, base, byte=False):
        adjusted = self.adjust(base)
        return _signed(max(prior & (255 if byte else 0xffffffff), adjusted), 8)

    def same_club_predicate(self, club):
        primary_flag = self.integer('primary2e8', 0, 0xffffffff, self.subject)
        if not primary_flag & 1 and not self.integer('primary300', 0, 0xffffffff, self.subject):
            return False
        stored = self.ref('stored_team', ('team', 'national_team'), self.subject)
        if stored is None or stored.kind != 'team':
            return False
        stored_club = self.ref('team_owner', ('club',), stored)
        if stored_club is None:
            return False
        first = self.first_team(club)
        if first is None:
            return False
        first_owner = self.ref('team_owner', ('club', 'national_team_container'), first)
        contract = self.contract(first_owner)
        if contract is None or contract.category == 5:
            return False
        if self.same(stored_club, club):
            return True
        parent = self.parent(stored_club) or stored_club
        other = self.parent(club) or club
        return self.same(parent, club) or self.same(parent, other)

    def evaluate(self):
        if self.owner is None or self.subject is None:
            return 100  # Native K value only, never observer permission.
        if self.integer('subject_common102', 0, 65535, self.subject) & 128:
            return 0
        subject_club = self.ref('current_club', ('club',), self.subject)
        club = self.ref('current_club', ('club',), self.owner)
        different = club is None or not self.same(subject_club, club)
        if not different:
            if not self.same_club_predicate(club):
                return 100
            contract = self.contract(club)
            if contract is None or contract.category in (5, 4) or not contract.active:
                return 100
        owner_team = self.ref('owner408_team', ('team', 'national_team'), self.owner)
        auxiliary = self.ref('player120_national', ('national_team',), self.subject)
        if auxiliary:
            active = self.integer('national_e2', 0, 255, auxiliary) == 1
            if active:
                expiry = self.ask('national_b8', auxiliary)
                if type(expiry) is not NativeDate:
                    raise SourceUnavailable('Unproved national assignment DATE')
                expiry.validate_calendar()
                passed = getattr(self.source, 'date_passed', None)
                active = (not passed(expiry.parts)) if passed is not None \
                    else expiry.parts > self.context.today.parts
            if not active:
                auxiliary = None  # Native E2 clear stays local, never a write.
        if auxiliary and owner_team:
            if self.same(self.ref('team_owner', ('national_team_container',), auxiliary),
                         self.ref('team_owner', ('club', 'national_team_container'), owner_team)):
                return 100
        relevant = self.ref('relevant_subject_club', ('club',), self.subject)
        stored_context = self.integer('common_d8_pointer', 0, (1 << 64) - 1, self.subject)
        prior = 0
        if club:
            if self.same(relevant, club) or relevant is not None and self.club_relation(relevant, club):
                return 100
            prior = relation_score(self.integer('relation_mask', 0, 65535, self.owner, self.subject))
            if prior == 100:
                return 100
            if stored_context == club.address or self.boolean('transfer_predicate', self.subject, club):
                return self.merged(prior, 50)
        scalar = self.integer('player25a', -32768, 32767, self.subject)
        if scalar >= 8000:
            return self.merged(prior, 80)
        if scalar >= 6500:
            return self.merged(prior, 50)
        if owner_team and self.same(self.projection(owner_team), self.ref('common38', ('nation',), self.subject)):
            return self.merged(prior, 50)
        if not different:
            contract = self.contract(club)
            contribution = 0
            if contract is not None and contract.category != 5 and contract.active:
                escape = getattr(self.source, 'date_escape', None)
                if escape is not None:
                    escape()        # the date itself is consumed below (trial contract contribution)
                expiry = self.context.today if self.context.today.parts == (1900, 1) else self.ask('contract_expiry', contract)
                if type(expiry) is not NativeDate:
                    raise SourceUnavailable('Unproved selected contract DATE')
                expiry.validate_calendar()
                contribution = date_contribution(self.context.today, expiry)
            prior = max(prior, contribution)
        if owner_team and auxiliary and self.game_team(owner_team, auxiliary):
            return self.merged(prior, 50, byte=True)
        if scalar >= 5000:
            return self.merged(prior, 30, byte=True)
        stored = self.ref('stored_team', ('team', 'national_team'), self.subject)
        youth = bool(stored and self.integer('team28', 0, 255, stored) and
                     self.integer('native_age', -(1 << 31), (1 << 31) - 1, self.subject) < 22)
        if club is not None and not youth:
            if auxiliary:
                projection = self.projection(auxiliary)
                if projection:
                    aggregate = self.integer('club_aggregate', -(1 << 31), (1 << 31) - 1, club, projection)
                    if aggregate >= 80:
                        return self.merged(prior, ((aggregate & 255) * 171) >> 9, byte=True)
            first_definition = self.definition(self.first_team(club))
            if stored and first_definition and self.same(self.definition(stored), first_definition):
                return self.merged(prior, 30, byte=True)
            if stored_context and first_definition:
                # No shape-based CLUB guess. The new source supplement/collector
                # must bind this distinct nonnull stored reference first.
                context = self.ref('proved_common_d8_club', ('club',), self.subject, stored_context)
                if context is None or context.address != stored_context:
                    raise SourceUnavailable('Nonnull COMMON+D8 family is unproved')
                if self.same(self.definition(self.first_team(context)), first_definition):
                    return self.merged(prior, 30, byte=True)
            association = self.ref('association_context', ('national_team_container',), self.subject)
            if association:
                nation = self.ref('container170', ('nation',), association)
                raw = self.integer('club_score', -(1 << 31), (1 << 31) - 1, club, nation, 14, 45, self.subject)
                context_scalar = self.integer('association1ea', -32768, 32767, association)
                scalar258 = self.integer('player258', -32768, 32767, self.subject)
                if score_threshold(raw, context_scalar) <= scalar258:
                    return self.merged(prior, scaled_score_base(raw, scalar258), byte=True)
            if subject_club:
                subject_first = self.first_team(subject_club)
                if subject_first:
                    owner_first = self.first_team(club)
                    if owner_first and self.game_team(owner_first, subject_first):
                        return self.merged(prior, 15, byte=True)
        owner_association = self.ref('common38', ('nation',), self.owner)
        if owner_association and auxiliary:
            # Native still consumes this projection when youth is true.
            if self.same(self.projection(auxiliary), owner_association) and not youth:
                return self.merged(prior, 10, byte=True)
        subject_association = self.ref('common38', ('nation',), self.subject)
        if owner_association and subject_association and self.same(subject_association, owner_association) and not youth:
            return self.merged(prior, 10, byte=True)
        if club:
            # LDR C+D8 precedes the CCMP even when subject association is null.
            club_association = self.ref('club_d8', ('nation',), club)
            if subject_association and club_association and self.same(subject_association, club_association) and not youth:
                return self.merged(prior, 10, byte=True)
        return self.merged(prior, 0, byte=True)


def evaluate(source: Source) -> Result:
    """Compute the proved local composition; all missing reached inputs refuse.

    A returned numeric K has no field-permission meaning. This is not a passive
    producer collector, a complete current score oracle or a public adapter.
    Every result, including unavailable, ends with the source lifetime check.
    """
    context = source.context
    try:
        score = _Score(source).evaluate()
        result = Result(score, None)
    except (SourceUnavailable, ValueError) as error:
        result = Result(None, str(error))
    try:
        if source.verify() is not None or source.context != context:
            raise SourceUnavailable('Source context or verification contract changed')
    except (SourceUnavailable, ValueError) as error:
        return Result(None, 'Source verification failed: ' + str(error))
    return result


def verify_native(read: Callable[[int, int], bytes], base: int) -> None:
    """Collector prerequisite for local source bytes; not a lifetime check."""
    _integer(base, 4096, (1 << 64) - 1 - 0x5389a20)
    for rva, size, digest in NATIVE_GUARDS:
        raw = read(base + rva, size)
        if type(raw) is not bytes or len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise SourceUnavailable(f'Contextual score native source changed at {rva:#x}')
    for rva, expected in FLOAT_GUARDS:
        if read(base + rva, len(expected)) != expected:
            raise SourceUnavailable(f'Contextual score native scalar factor changed at {rva:#x}')


NATIVE_GUARDS = (
    (0x2386548, 0x964, '24a4c661832b66673e9286cc9691e27b30fe1d406e26e8977704e83d647f1b18'),
    (0x1300060, 0x14, 'c62b747862d1cf16fb01c5408524041f7d9c9e27edb97fc458d3338ac9ee7b8d'),
    (0xc8cf20, 0x40, '207979a4160eb708962c03bc99109154b678bbdc473a42eda955a3f5b70861b3'),
    (0xca4674, 0x18, '64164ca1568787b841601d69f3ceda841316cad0e4423bb8dd9b7768d7206047'),
    (0x1489900, 0x9c, '1380ba829175f60e50738055f659e90df057dbde0bcaedb80b31932638f1b0dc'),
    (0xe14c9c, 0x160, '1e8022686c8cc970b25899bc58e19e45b943ce3efd2a168f004c77dd19a16a41'),
    (0x14fdcb0, 0x1c8, 'e143e04ec31fb4d16f6b07f8030fb7a541ac645fe1444a4e2ab3d02bf4435aba'),
    (0x2388658, 0x180, '66edfafb7de0a715b4a57901475e21b9da8090bd2546756acb62f5f728a060cd'),
)

FLOAT_GUARDS = ((0x52f6ff0, b'\xcd\xcc\x4c\x3e'),
                (0x5388818, b'\x9a\x99\x19\x3e'),
                (0x538773c, b'\xcd\xcc\xcc\x3d'),
                (0x5389a1c, b'\xcd\xcc\x4c\x3d'))
