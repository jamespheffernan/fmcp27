"""Per-call sharing for the paged bulk knowledge engine.

The typed sources were written for one (player, field) cell: each constructs its whole context,
re-validates every canonical record it touches and re-reads per-call constants. In a bulk call
the journal serves a region's first bytes to every later read, so any function of its arguments
and of memory returns the same value each time it runs inside the call. This module uses that:

* one source is constructed in full (the prototype); every later player is a copy of it with
  only the subject-specific steps of the constructor run again, in the constructor's order;
* pure checks and lookups (canonical entity, TEAM, contract, the owner's club and teams, club
  relations, the emulated fixture helpers) run once per distinct argument (``journal.memo``);
* the date is consumed through three recorded facts (a date has passed, a date is more than N
  days old, an age) instead of as raw bytes, so a fingerprint does not change with the day
  unless one of those facts does.

Every skipped read is still attributed: a memo's consumed inputs are attached to each user.
Nothing here changes a result; ``engine='journal'`` runs the same sources without this module.
"""
from __future__ import annotations

import hashlib

from . import database, players, world
from . import knowledge_context_score as core
from . import knowledge_field_catalog as catalog
from . import knowledge_passing_range as ranges
from . import knowledge_transfer_predicate as transfer

SOURCE_ERRORS = (core.SourceUnavailable, ValueError)

# Operands of K that depend only on their arguments (canonical records), never on the subject.
SHARED_OPERANDS = frozenset((
    'team_owner', 'team_definition', 'first_team', 'club_d8', 'container170', 'team28',
    'association1ea', 'club163', 'club_relation_count'))
# Emulated helpers: their inputs change often (fixtures, dates), their outcome rarely.
FIREWALLED_OPERANDS = frozenset(('next_fixture', 'game_team98'))
RELATION_ROW_OPERANDS = frozenset(('relation_first', 'relation_second', 'relation_kind',
                                   'relation_byte15', 'relation_word1c'))

# transfer._Reader methods that may be shared, with the primitives each one calls on itself.
_READER_METHODS = {
    'entity': ('ptr', 'read', 'table'),
    'person': ('ptr', 'read', 'route', 'adjustment', 'table'),
    'team': ('entity', 'ptr', 'pointers', 'bounds', 'read'),
    'contract': ('ptr', 'route', 'read'),
    'parent': ('club', 'entity', 'u8', 'pointers', 'bounds', 'ptr', 'read'),
    'current_team': ('person', 'ptr', 'contract', 'team', 'u8', 'read'),
}
_READER_PRIMITIVES = ('u8', 'i32', 'ptr', 'route', 'adjustment', 'bounds', 'pointers', 'club')


class _NoCache(dict):
    """Stands in for a reader's private cache: it never answers, so no read is skipped without
    the call memo knowing (the memo is what attaches a skipped read's inputs to its user)."""

    def __contains__(self, key):
        return False

    def __setitem__(self, key, value):
        return None


_NO_CACHE = _NoCache()


def fact_outcome(outcome):
    """JSON-able form of (True, value) / (False, exception) for a derived fact."""
    ok, value = outcome
    return value if ok else ['raise', type(value).__name__, [str(a) for a in value.args]]


def reader_hook(journal):
    """Hook for ``transfer._Reader.__init__``: share its pure methods across the call."""
    memo, inputs = journal.memo, journal.inputs
    base_reader = transfer._Reader

    def hook(reader):
        cls = type(reader)
        reader.entities = reader.people = _NO_CACHE
        changed = {name for name in _READER_PRIMITIVES
                   if getattr(cls, name) is not getattr(base_reader, name)}
        if getattr(cls, 'table') is base_reader.table:
            reader.table = lambda kind: memo(
                ('r.table', kind), lambda: database.table(reader.read, reader.base, kind))

        def share(name):
            method = getattr(cls, name)
            if method is not getattr(base_reader, name) or changed.intersection(_READER_METHODS[name]):
                return
            setattr(reader, name, lambda *args: memo(('r.' + name,) + args, lambda: method(reader, *args)))

        for name in _READER_METHODS:
            share(name)
        if cls.resolve_placeholder is base_reader.resolve_placeholder:
            def resolve_placeholder(person):
                value = base_reader.resolve_placeholder(reader, person)
                if not value and person:
                    # "no PERSON at that index" can turn into one when the table grows
                    inputs.derive('people_count', (), reader.table('people')['count'])
                return value
            reader.resolve_placeholder = resolve_placeholder
        if cls.before_today is base_reader.before_today:
            def before_today(year, day):
                inputs.suspend()
                try:
                    value = base_reader.before_today(reader, year, day)
                finally:
                    inputs.resume()
                inputs.derive('date_lt', (year, day), value)
                return value
            reader.before_today = before_today
        native_age = getattr(cls, 'native_age_from_birth', None)
        if native_age is not None:
            def age_from_birth(birth):
                inputs.suspend()
                try:
                    try:
                        outcome = (True, native_age(reader, birth))
                    except SOURCE_ERRORS as exc:
                        outcome = (False, exc)
                finally:
                    inputs.resume()
                inputs.derive('age', (birth.day_word, birth.year), fact_outcome(outcome))
                if outcome[0]:
                    return outcome[1]
                raise outcome[1]
            reader.native_age_from_birth = age_from_birth

    return hook


def direct_read(journal):
    """The shared world read of a paged call: calling it is ``journal.read`` itself."""
    cls = type('_PagedRead', (world.ReadSet,), {
        '__call__': staticmethod(journal.read),
        'journalled': True,
        'verify': lambda self: None,
        'reader_hook': staticmethod(reader_hook(journal)),
        'call_memo': staticmethod(journal.memo),
    })
    read = cls.__new__(cls)
    read.read = journal.read
    read.observed = {}
    return read


def source_type(base, journal):
    """Subclass of the bulk approved source with per-call sharing (see the module docstring)."""
    memo, inputs = journal.memo, journal.inputs
    page_source = journal.source
    checked = [-1]

    class FastSource(base):
        _getter_mode = None

        # ---- process identity: checked again only after memory was actually read
        def lifetime(self):
            if page_source.fetches != checked[0]:
                base.lifetime(self)
                checked[0] = page_source.fetches
            return self._lifetime_identity

        # ---- canonical records
        def entity(self, address, kind):
            if not address:
                return None
            return memo(('entity', address, kind), lambda: base.entity(self, address, kind))

        def team(self, address, national_only=False):
            if not address:
                return None
            return memo(('team', address, national_only), lambda: base.team(self, address, national_only))

        def contract(self, address, person=None):
            if not address:
                return None
            return memo(('contract', address, None if person is None else person.person.address),
                        lambda: base.contract(self, address, person))

        def first_team(self, club):
            return memo(('first_team', club), lambda: base.first_team(self, club))

        def association_projection(self, team):
            if team is None:
                return None
            return memo(('association_projection', team), lambda: base.association_projection(self, team))

        def generic_eligible_club(self, person):
            if not person:
                return None
            return memo(('generic_eligible_club', person), lambda: base.generic_eligible_club(self, person))

        def resolve_team_handle(self, address):
            return memo(('team_handle', address), lambda: base.resolve_team_handle(self, address))

        # ---- the selected manager (the same for every player of the call)
        def eligible_team(self, person):
            if person is self.owner:
                return memo(('owner', 'eligible_team'), lambda: base.eligible_team(self, person))
            return base.eligible_team(self, person)

        def main(self, person):
            if person is self.owner:
                return memo(('owner', 'main'), lambda: base.main(self, person))
            return base.main(self, person)

        def current_club(self, person):
            if person is self.owner:
                return memo(('owner', 'current_club'), lambda: base.current_club(self, person))
            return base.current_club(self, person)

        def owner_eligible_club(self):
            return memo(('owner', 'eligible_club'), lambda: base.owner_eligible_club(self))

        def secondary_team(self):
            return memo(('owner', 'secondary_team'), lambda: base.secondary_team(self))

        # ---- club relations
        def _selected_parent(self, club):
            return memo(('selected_parent', club), lambda: base._selected_parent(self, club))

        def _special_club(self, club):
            return memo(('special_club', club), lambda: base._special_club(self, club))

        def _first_team_special(self, club):
            return memo(('first_team_special', club), lambda: base._first_team_special(self, club))

        def club150(self, club):
            return memo(('club150', club), lambda: base.club150(self, club))

        def select_person6f(self, club):
            # the retained-person lookup searches the people table by UID within its count
            inputs.derive('people_count', (), self.people['count'])
            return base.select_person6f(self, club)

        def _recent_nodes(self, club, team, expected_team):
            return memo(('recent_nodes', club, team, expected_team),
                        lambda: base._recent_nodes(self, club, team, expected_team), firewall=True)

        # ---- indexes over HUMAN-owned vectors: a player depends on its own lookup only
        def _primary_reports(self):
            return memo(('index', 'primary_reports'), lambda: base._primary_reports(self), firewall=True)

        def _report_rows(self, target):
            return memo(('report_rows', target), lambda: base._report_rows(self, target), firewall=True)

        def _alternate_reports(self):
            return memo(('index', 'alternate_reports'), lambda: base._alternate_reports(self), firewall=True)

        def _alternate_lookup(self, uid):
            return memo(('alternate_report', uid), lambda: base._alternate_lookup(self, uid), firewall=True)

        def _owner_nodes(self):
            return memo(('index', 'owner_nodes'), lambda: base._owner_nodes(self), firewall=True)

        def _owner_node_check(self, row):
            return memo(('owner_node', row), lambda: base._owner_node_check(self, row), firewall=True)

        # ---- date facts
        def date_passed(self, parts):
            value = base.date_passed(self, parts)
            inputs.derive('date_le', (parts[0], parts[1]), value)
            return value

        def days_since_exceeds(self, year, day, limit):
            value = base.days_since_exceeds(self, year, day, limit)
            inputs.derive('date_since_gt', (year, day & 511, limit), value)
            return value

        def date_escape(self):
            inputs.derive('date_raw', (), list(self.context.today.parts))

        def _age_from_birth(self, birth):
            inputs.suspend()
            try:
                try:
                    outcome = (True, base._age_from_birth(self, birth))
                except SOURCE_ERRORS as exc:
                    outcome = (False, exc)
            finally:
                inputs.resume()
            inputs.derive('age', (birth.day_word, birth.year), fact_outcome(outcome))
            if outcome[0]:
                return outcome[1]
            raise outcome[1]

        # ---- K composition: functions of two clubs / one club only
        def shared_score(self, key, compute):
            return memo(('k',) + key, compute)

        # ---- K operands
        def _operand(self, name, *args):
            if name in SHARED_OPERANDS:
                return memo(('op', name) + args, lambda: base._operand(self, name, *args))
            if name in RELATION_ROW_OPERANDS:
                row = args[0]
                if type(row) is core.RelationRow and row.address in self.rows:
                    return memo(('op', name, row), lambda: base._operand(self, name, *args))
            elif name == 'club_relation_row':
                row = memo(('op', name) + args, lambda: base._operand(self, name, *args))
                self.rows.add(row.address)
                return row
            elif name in FIREWALLED_OPERANDS:
                return memo(('op', name) + args, lambda: base._operand(self, name, *args), firewall=True)
            elif name == 'common38' and args[0] is self.owner:
                return memo(('owner', 'common38'), lambda: base._operand(self, name, *args))
            elif name == 'club_score':
                # The owner club's score store is re-sorted and rescored as scouting goes on, and
                # each lookup walks a search path through it: the player depends on the score
                # that came out, not on those rows.
                club, nation, low, high, person = args
                if person == self.subject and (low, high) == (14, 45):
                    return memo(('op', name, club, nation, person),
                                lambda: base._operand(self, name, *args), firewall=True)
            elif name == 'range_helper':
                subject, owner, club, definition, nation = args
                if subject == self.subject and owner is self.owner:
                    return memo(('op', name, club, definition, nation),
                                lambda: base._operand(self, name, *args))
            return base._operand(self, name, *args)

        # ---- granted attribute bytes: the per-player checks of the getter run once
        def getter_value(self, field):
            journal.authorize_cell(self, field)
            meta = catalog.field(field)
            mode = self._getter_mode
            if mode is None:
                self.ordinary_primary()
                self.route(self.ptr(self.subject.primary), 0xf0, 0xd19eb0)
                mode = self._getter_mode = self.u8(self.subject.primary + 0x270)
            stored = self.u8(self.subject.primary + meta['primary_offset'])
            return ranges.passing_getter(stored, mode)

        # ---- subject binding of a copied prototype (the constructor's subject-specific steps)
        def _bind_subject(self, subject_person, subject_identity, prefix, today):
            primary, common, kind, identity = self.reader.person(subject_person)
            if type(subject_identity) is not tuple or identity != subject_identity:
                raise core.SourceUnavailable('Subject canonical identity differs from requested source')
            subject = core.Person(core.Ref(subject_person, 'actual_person' if kind == 'actual'
                                           else 'combined_person', identity), primary)
            self.route(self.ptr(primary), 0xf0, 0xd19eb0)
            self.subject_common = common
            self.subject = subject
            self._lifetime_identity = prefix + (subject_person, *identity, self.field)
            observation = hashlib.sha256(repr(self._lifetime_identity).encode()).hexdigest()
            self.context = core.Context(observation, players.SHA256, self.owner, subject, today)
            self.snapshots, self.rows = [], set()
            self.assessment_record = None
            self.assessment_selected = False
            self._getter_mode = None
            self._node_present = False

    return FastSource


class SourceFactory:
    """Constructs one source in full, then binds copies of it to later subjects.

    The constructor's steps are either subject-specific (resolve the PERSON, compare the
    identity, build the subject, check its getter route) or the same for every subject of the
    call. Once one construction has succeeded, the constant steps are known to succeed on the
    journal's bytes, so a copy runs only the subject-specific steps, in the same order, and
    raises what the constructor would raise. Until one succeeds, every player is constructed
    in full. The regions the full construction consumed are attached to every copy.
    """

    def __init__(self, cls, bridge, session, coach_name, field, journal):
        self.cls, self.args = cls, (bridge, session)
        self.coach_name, self.field, self.journal = coach_name, field, journal
        self.template = None
        self.regions = ()
        self.prefix = self.today = None

    def __call__(self, person, identity):
        cls, journal = self.cls, self.journal
        collector = journal.inputs.stack[-1]
        if self.template is None:
            start = len(collector.log)
            source = cls(*self.args, person, identity, self.coach_name, self.field)
            date_region = (source.base + world.CURRENT_DATE, 4)
            regions = tuple(r for r in dict.fromkeys(collector.log[start:]) if r != date_region)
            del collector.log[start:]
            collector.log.extend(regions)
            self.regions = regions
            self.prefix = source._lifetime_identity[:-5]
            self.today = source.context.today
            self.template = {k: v for k, v in source.__dict__.items()
                             if k not in ('subject', 'subject_common', '_lifetime_identity', 'context',
                                          'snapshots', 'rows', 'assessment_record', 'assessment_selected',
                                          '_getter_mode', '_node_present', '_latest_decision')}
            return source
        source = object.__new__(cls)
        source.__dict__.update(self.template)
        collector.log.extend(self.regions)
        source._bind_subject(person, identity, self.prefix, self.today)
        return source
