"""Read-only Manager-visible attribute view (fog of war) for ordinary players.

For each requested player and attribute field this reports what the selected
manager sees: ``exact`` value, ``range`` (minimum and maximum) or ``unknown``,
or ``unavailable`` with an explicit reason. It is a separate view; the default
tools keep returning stored full information.

The answer is computed from game memory by the Python source modules in
``knowledge_*`` (the native PERSON_UI report selection, H state and Range
projection, replayed from the original code and proved against it offline).
A capture runs on its own journalled bridge with the attribute-byte firewall
from ``knowledge_field_firewall``: every stored attribute byte of every primary
record is forbidden, and a single byte is read only after the source recomputed
the native H state for that player and field and found it known (state 1 or 2).
A source error never yields a guess: the field becomes ``unavailable`` or the
whole call is rejected.
"""
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import struct
import time

from . import (assessment_people, bridge as bridge_module, database, live_transfer_offers, players,
               prepared_tactics_source, world)
from . import knowledge_attribute_ui_caller as ui_source
from . import knowledge_club_info_overlay as club_info
from . import knowledge_field_catalog as catalog
from . import knowledge_field_firewall as firewall
from . import knowledge_generation_transport as generation
from . import knowledge_native_scope as scope
from . import knowledge_relation_fixes as relation_fixes
from . import knowledge_relation_mask_source as relation
from . import knowledge_search_population_source as population
from . import knowledge_structural_operand as structural
from . import knowledge_transfer_predicate as transfer
from . import knowledge_used_range_overlay as used_range
from .bridge import BridgeError
from .live_international_duty import _bound_person

MAX_PLAYERS = 28
MAX_CELLS = 700  # player x field cells per call, about 0.13 s each
FIELD_COUNT = len(catalog.FIELDS)
STATES = ('exact', 'range', 'unknown', 'unavailable')
# What the offline oracle replay covered (original UI prefix, H and Range code).
VERIFIED_SCOPE = dict(
    coach='Cesar Jules', club='Newcastle United', current_date='2030-12-08',
    subjects='ordinary all_actual PLAYER and PLAYER_STAFF records',
    fields='all 47 compiled attribute fields',
    result='28 players x 47 fields: exact 120, range 900, unknown 296, unavailable 0')
SCOPE = ('What the selected manager sees of an ordinary player attribute, from the native fog-of-war '
         'selection (report, H state, Range). Per field: exact value, range minimum/maximum, unknown or '
         'unavailable with a reason. Not the stored full-information value, not perceived stars, CA/PA or '
         'report contents, and not a Manager search-population check. Compact/virtual and other unproved '
         'subjects are unavailable. Replay against the original code covers one manager, club and date '
         f'({VERIFIED_SCOPE["coach"]}, {VERIFIED_SCOPE["club"]}, {VERIFIED_SCOPE["current_date"]}); '
         'other contexts use the same code unverified.')


class _Rejected(BridgeError):
    pass


def field_ids(fields):
    """Native field ids for an optional list of compiled names or ids."""
    if fields is None:
        return tuple(range(FIELD_COUNT))
    if type(fields) is not list or not 1 <= len(fields) <= FIELD_COUNT:
        raise BridgeError(f'fields must list 1 through {FIELD_COUNT} attribute names.')
    by_name = {name.lower(): index for index, (name, _, _) in enumerate(catalog.FIELDS)}
    result = []
    for field in fields:
        if type(field) is int and not isinstance(field, bool) and 0 <= field < FIELD_COUNT:
            index = field
        elif type(field) is str and field.lower() in by_name:
            index = by_name[field.lower()]
        else:
            raise BridgeError('Unknown attribute field; use compiled names such as "Passing" '
                              'or native ids 0 through 46.')
        if index in result:
            raise BridgeError('Attribute fields must be distinct.')
        result.append(index)
    return tuple(result)


# The approved typed source: the PERSON_UI attribute source with the reviewed overlays.
_approved = used_range.source_type(ui_source.AttributeUiCallerSource, ui_source.core)
_approved = club_info.source_type(_approved, relation)
Approved = relation_fixes.source_type(_approved, relation)
FieldJournal = firewall.journal_type(firewall.Journal, Approved, ui_source.catalog)


def _journal_bridge(helper):
    """A private bridge restricted to read-only helper commands and unreadable profiles."""
    class JournalBridge(bridge_module.Bridge):
        def __init__(self):
            self.journal = None
            self.journal_process = None
            self.snapshots = []
            self.transport_segments = []
            self.image_cache = None
            self.kernel_identity = self.kernel_baseline = None
            self.fast_checks = None
            super().__init__(helper=helper)

        def _read_memory(self, process, address, length):
            if self.journal is None:
                self.journal_process = process
                physical = lambda a, n: bridge_module.Bridge._read_memory(self, self.journal_process, a, n)
                self.journal = FieldJournal(physical, None, self)
            if process is not self.journal_process and process != self.journal_process:
                raise ValueError('Physical process identity changed')
            return self.journal.read(address, length)

        def _current(self, session_id):
            if self.kernel_identity is None:
                return super()._current(session_id)
            # Inside the per-field loop the kernel incarnation token (pid, unique id,
            # pid version, executable UUID) replaces one `ps` launch per lifetime
            # callback. The outer context checks before, after and at the end still
            # use the ordinary process check.
            if not self.process or session_id != self.session:
                raise BridgeError('Unknown session.')
            generation.require_generation(self.kernel_identity(self.process.pid), self.kernel_baseline)
            return self.process

        def _world_state(self, process, tables):
            read, save, identity = super()._world_state(process, tables)
            self.snapshots.append(read)
            return read, save, identity

        def _run(self, command, process, *args):
            if command not in ('probe', 'images', 'read-bytes'):
                raise ValueError('Non-read-only helper operation forbidden')
            if command == 'images' and self.image_cache is not None:
                # Inner per-field lifetime callbacks reuse one loaded-image answer. The
                # outer context checks (before, after, final) always ask the helper again.
                key = (process.pid, args)
                if key not in self.image_cache:
                    self.image_cache[key] = super()._run(command, process, *args)
                return deepcopy(self.image_cache[key])
            return super()._run(command, process, *args)

        def _decode_player(self, *args, **kwargs):
            raise AssertionError('Rich player profile decoding is forbidden')

        @staticmethod
        def _roster_player(*args, **kwargs):
            raise AssertionError('Roster profile decoding is forbidden')

    return JournalBridge




def _capture(main, session_id, player_refs, fields, coach_name):
    started = time.monotonic()
    process = main._current(session_id)
    bindings = {}
    for reference in player_refs:
        binding = main.player_refs.get(reference)
        if type(binding) is not dict:
            raise _Rejected('Unknown or expired player reference')
        bindings[reference] = deepcopy(binding)
    relation_fixes.RECEIPTS.clear()
    JournalBridge = _journal_bridge(main.helper)
    bridge = JournalBridge()
    original_stream = scope.ReadStream
    if original_stream is not bridge_module.ReadStream:
        raise _Rejected('Private stream transport changed')
    detach = None
    result = None
    try:
        intended = bridge_module.process_info(process.pid)
        if intended is None or intended != process:
            raise _Rejected('The game process changed since fm_attach')
        kernel = generation.KernelIdentity()
        baseline = kernel(process.pid)
        sid = bridge.attach(pid=process.pid)['session_id']
        generation.require_generation(kernel(process.pid), baseline)
        if bridge.process != process:
            raise _Rejected('Intended attachment process changed')
        stream_type = generation.bound_stream_type(firewall.SegmentedStream, kernel, baseline)
        scope.ReadStream = lambda helper, pid: stream_type(bridge, bridge_module.ReadStream, helper, pid)
        bridge.fast_checks = (kernel, baseline)
        result = _read_all(bridge, sid, process, bindings, player_refs, fields, coach_name)
        result['cost'] = dict(
            seconds=round(time.monotonic() - started, 1),
            distinct_regions=result['journal']['region_count'],
            physical_reads=result['journal']['physical_reads'],
            native_ports=len(bridge.transport_segments))
    finally:
        scope.ReadStream = original_stream
        try:
            detach = bridge.detach()
        except Exception as exc:
            raise _Rejected(f'Private bridge detach failed: {exc}') from exc
        if detach != {'detached': True}:
            raise _Rejected('Private bridge detach was not verified')
        if any(not row['closed'] for row in bridge.transport_segments):
            raise _Rejected('Native port closure was not verified')
    for segment in bridge.transport_segments:
        checks = segment.get('kernel_generation_checks', {})
        if (segment.get('kernel_generation_errors')
                or set(checks) != {'before_lazy_port_open', 'after_first_physical_read', 'before_port_close'}):
            raise _Rejected('Incomplete kernel generation receipt')
        for observed in checks.values():
            generation.require_generation(observed, baseline)
    return result


def _read_all(bridge, sid, process, bindings, player_refs, fields, coach_name):
    journal_of = lambda: bridge.journal
    with bridge.lock, scope.collection_stream(bridge, sid):
        process = deepcopy(bridge._current(sid))
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        plugin = deepcopy(bridge.plugin_identity)

        def context():
            now = bridge._current(sid)
            layout = bridge._player_layout(now)
            if now != process or layout != tables or bridge.plugin_identity != plugin:
                raise ValueError('Process/plugin/session/layout changed')
            read, save, identity = bridge._world_state(now, layout)
            coach = deepcopy(bridge._select_coach(save, coach_name))
            team, human = prepared_tactics_source._team_and_human(read, base, coach)
            read.verify()
            return dict(save=deepcopy(save), world=deepcopy(identity), coach=coach, team=team, human=human)

        before = context()
        journal = journal_of()
        journal.forbidden = firewall.attribute_intervals(journal, base, players)
        if any(journal.forbidden.intersects(a, n) for a, n in journal.observed):
            raise ValueError('Attribute byte consumed before forbidden geometry binding')
        # Players are resolved only after the attribute geometry is bound, so
        # resolving an identity cannot read a hidden attribute byte.
        read = journal
        people = database.table(read, base, 'people')
        assessment_people.verify_native(read, base)
        population.verify_native(read, base)
        subjects = []
        for reference in player_refs:
            subjects.append(_subject(read, base, tables, people, reference, bindings[reference]))
        intervals = list(journal.forbidden.ranges)
        for row in subjects:
            if row.get('person') is not None:
                intervals.append((row['primary'] + firewall.ATTRIBUTE_BLOCK_START,
                                  row['primary'] + firewall.ATTRIBUTE_BLOCK_END))
        journal.forbidden = firewall.Intervals(intervals)
        if any(journal.forbidden.intersects(a, n) for a, n in journal.observed):
            raise ValueError('Attribute byte consumed before forbidden geometry binding')
    structural_receipts = {}
    Observed = firewall.source_type(Approved, journal)
    Controlled = structural.source_type(Observed, transfer, live_transfer_offers, journal, structural_receipts)
    bridge.image_cache = {}
    bridge.kernel_identity, bridge.kernel_baseline = bridge.fast_checks
    try:
        _evaluate(bridge, sid, subjects, fields, journal, Controlled, coach_name)
    finally:
        bridge.image_cache = None
        bridge.kernel_identity = bridge.kernel_baseline = None
    with bridge.lock, scope.collection_stream(bridge, sid):
        after = context()
        if after != before:
            raise ValueError('Selected context changed during the capture')
        final = context()
        if final != before or bridge._current(sid) != process:
            raise ValueError('Final context/process changed')
        if bridge.world_identity != before['world'] or bridge.plugin_identity != plugin:
            raise ValueError('Final world/plugin differs')
        for snapshot in bridge.snapshots:
            snapshot.verify()
        journal.verify(1)
        journal.verify(2)
        if players.disk_uuid(Path(plugin[0][0])) != plugin[1]:
            raise ValueError('Full plugin disk fingerprint changed')
        record = journal.record()
    states = [v['state'] for row in subjects for v in row['fields']]
    if any(s not in STATES for s in states):
        raise ValueError('Invalid permitted field state')
    return dict(before=before, subjects=subjects, journal=record, structural_receipts=len(structural_receipts),
                state_counts={s: states.count(s) for s in STATES})


def _evaluate(bridge, sid, subjects, fields, journal, Controlled, coach_name):
    for row in subjects:
        values = []
        for field in fields:
            catalog_field = ui_source.catalog.field(field)
            if row.get('person') is None:
                value = dict(state='unavailable', reason=row['reason'])
            else:
                value = _field(bridge, sid, Controlled, journal, row, field, coach_name)
            values.append(dict(native_field_id=field, name=catalog_field['compiled_name'], **value))
        row['fields'] = values


def _subject(read, base, tables, people, reference, binding):
    row = dict(player_ref=reference, person=None, primary=None)
    try:
        _, kind, name, display = _bound_person(read, base, tables, people, binding)
    except ValueError as exc:
        raise _Rejected(f'Player reference rejected: {exc}') from exc
    row.update(record_kind=kind, name=name, display_name=display)
    if kind not in ('actual', 'player_staff'):
        row['reason'] = 'unsupported_record_kind_compact_or_generated'
        return row
    primary = binding['address']
    try:
        ordinary = population._base_identity(read, base, people, primary)
    except population.SourceUnavailable:
        row['reason'] = 'unsupported_all_actual_source_family'
        return row
    person = ordinary['person']
    assessment_people._address(person, 20)
    _, index, uid, secondary = struct.unpack('<QIII', read(person, 20))
    expected = dict(database_index=index, native_id=uid, random_id=None if secondary == uid else secondary)
    if (ordinary['primary'] != primary or ordinary['record_kind'] not in ('actual', 'player_staff')
            or ordinary['native_identity'] != expected or not uid):
        raise ValueError('Canonical ordinary identity changed')
    row.update(person=person, primary=primary, subject_identity=(index, uid, secondary),
               native_identity=expected)
    return row


def _field(bridge, sid, Controlled, journal, row, field, coach_name):
    with bridge.lock, scope.collection_stream(bridge, sid):
        bound = None
        try:
            bound = Controlled(bridge, sid, row['person'], tuple(row['subject_identity']), coach_name, field)
            value = bound.permitted()
        except ui_source.core.SourceUnavailable as exc:
            value = dict(state='unavailable', reason='unavailable_source', detail=str(exc)[:200])
        except ValueError as exc:
            if bound is None:
                raise
            value = dict(state='unavailable', reason='unavailable_source', detail=str(exc)[:200])
        if bound is not None:
            bound.verify()
        journal.healthy()
    return value


def get_manager_visible_attributes(bridge, session_id, player_refs, fields=None, coach_name=None):
    """Public entry: validate, capture, and return only permitted per-field states."""
    if (type(player_refs) is not list or not 1 <= len(player_refs) <= MAX_PLAYERS
            or any(type(ref) is not str or not ref for ref in player_refs)
            or len(set(player_refs)) != len(player_refs)):
        raise BridgeError(f'Supply 1 through {MAX_PLAYERS} distinct nonempty player references.')
    if coach_name is not None and (type(coach_name) is not str or not 1 <= len(coach_name) <= 256):
        raise BridgeError('coach_name must be a name returned by fm_get_save.')
    ids = field_ids(fields)
    if len(player_refs) * len(ids) > MAX_CELLS:
        raise BridgeError(f'At most {MAX_CELLS} player-field cells per call (about 0.13 s each); '
                          'request fewer players or fields.')
    try:
        with bridge.lock:
            raw = _capture(bridge, session_id, player_refs, ids, coach_name)
    except (ValueError, IndexError, KeyError, TypeError, AssertionError, BridgeError, OSError) as exc:
        raise BridgeError(f'Manager-visible attribute query rejected; no partial result returned: {exc}') from exc
    return _public(raw, session_id)


def _public(raw, session_id):
    before = raw['before']
    players_out = []
    for row in raw['subjects']:
        entry = dict(player_ref=row['player_ref'], record_kind=row['record_kind'],
                     name=row['name'], display_name=row['display_name'],
                     native_identity=row.get('native_identity'),
                     fields=row['fields'])
        entry['state_counts'] = {s: sum(f['state'] == s for f in row['fields']) for s in STATES}
        players_out.append(entry)
    coach = before['coach']
    matches = (coach['name'].split() == VERIFIED_SCOPE['coach'].split()
               and coach['club']['name'] == VERIFIED_SCOPE['club']
               and before['save']['current_date'] == VERIFIED_SCOPE['current_date'])
    return dict(session_id=session_id, observed_at=datetime.now(timezone.utc).isoformat(),
                view='manager_visible_attributes', default_mode_unchanged=True,
                save=dict(name=before['save']['name'], current_date=before['save']['current_date']),
                coach=coach['name'], club=coach['club'], players=players_out, count=len(players_out),
                state_counts=raw['state_counts'], scope=SCOPE,
                oracle_verified_scope=VERIFIED_SCOPE, context_matches_oracle_verified_scope=matches,
                firewall=dict(forbidden_attribute_intervals=raw['journal']['forbidden_attribute_intervals'],
                              attribute_bytes_authorised=raw['journal']['authorized_attribute_bytes'],
                              unpermitted_attribute_bytes_read=False,
                              final_physical_fences=raw['journal']['final_fence_passes']),
                cost=raw['cost'], atomic=False, game_writes=False)
