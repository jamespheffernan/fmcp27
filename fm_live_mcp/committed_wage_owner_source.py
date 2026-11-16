"""Private v138 owner/queue inputs and proved zero branches, never game calls.

Nonempty kind40 queues and retained offers require further native monetary
helpers. This component never supplies a guessed contribution for them.
"""
from dataclasses import dataclass
import hashlib
import struct

from . import assessment_people, players, world

PLUGIN_SHA = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
FULL_ROOT, FULL_TABLE = 0x56D2C68, 0x55DFCF8
SOURCE = (
    (0x1FEBC8C, 3664, 'ed1fb8dbc0aab6078fc986229c0e56a5a6d6ba3a67f09c6c5114e24d25a1a616'),
    (0x1FECADC, 1204, 'fde7208520adffb70580da901d4e5ea9e851dfa7bd7c157f5bc683ae5b5cf1db'),
    (0x175E508, 540, '0d8dde257ac7dcdac3e2370540d9030e533b9b8780c388cfdfd066745e5a849e'),
    (0xEAEB44, 352, '5fd4eb2bcd0274ab17fac830526eb0f647aaf8d52034cd92b0e3045c022d1dd1'),
)
FALSE = bytes.fromhex('00008052c0035fd6')
TRUE = bytes.fromhex('20008052c0035fd6')
HUMAN_CAST = bytes.fromhex('080040f908011cd1080140f90000088bc0035fd6')
MAX_TEAMS, MAX_QUEUE = 128, 4096
# NON_PLAYER vtable, PERSON delta, full-primary delta, PERSON table, native kind.
NONPLAYER = {
    0x5583660: (0x208, 0, 0x55849D8, 'staff'),
    0x55AC480: (0x548, 0, 0x55AD820, 'human_manager'),
    0x558F568: (0x208, -0x278, 0x55908E0, 'player_staff'),
}


class UnsupportedSource(ValueError):
    """A genuine source branch cannot yet be replayed without native work."""


@dataclass(frozen=True)
class CanonicalRef:
    address: int
    index: int
    native_id: int
    secondary: int


@dataclass(frozen=True)
class Context:
    process_id: int
    save_identity: str
    session_identity: str
    plugin_sha256: str
    native_date: bytes
    club: CanonicalRef


@dataclass(frozen=True)
class QueueEntry:
    ordinal: int
    address: int
    native_kind: int | None
    table: int | None
    getter: int | None


@dataclass(frozen=True)
class QueuePopulation:
    offset: int
    entries: tuple[QueueEntry, ...]
    kind40: tuple[int, ...]


@dataclass(frozen=True)
class V138Inputs:
    state: str
    reason: str
    native_return: int | None
    out_amount: int | None
    human: CanonicalRef | None = None
    queue218: QueuePopulation | None = None
    queue200: QueuePopulation | None = None
    selections: tuple = ()
    complete_v138_branch: bool = False
    selections_complete: bool = False
    first_team: CanonicalRef | None = None


def _address(value, *, null=False, alignment=8):
    if type(value) is not int:
        raise ValueError('Invalid v138 pointer type')
    if value == 0 and null:
        return 0
    if not 4096 <= value < 1 << 64 or value % alignment:
        raise ValueError('Invalid v138 pointer')
    return value


def _pointer(read, address):
    return _address(players.u64(read(address, 8)), null=True)


def _function_pointer(read, address):
    return _address(players.u64(read(address, 8)), alignment=4)


def _vector(read, address, limit):
    start, end, cap = struct.unpack('<QQQ', read(address, 24))
    if start == end == cap == 0:
        return ()
    if (start < 4096 or any(p % 8 for p in (start, end, cap))
            or not start <= end <= cap or cap-start > limit*8):
        raise ValueError('Invalid v138 vector geometry or bound')
    raw = b''.join(read(at, min(8192, end-at)) for at in range(start, end, 8192))
    values = struct.unpack(f'<{len(raw)//8}Q', raw)
    for value in values:
        _address(value, null=True)
    return values


def _ref(read, address):
    _, index, native, secondary = struct.unpack('<QIII', read(address, 20))
    return CanonicalRef(address, index, native, secondary)


def _verify(read, base):
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base+rva, size)).hexdigest() != digest:
            raise ValueError('v138 native source changed')
    # __text (addr, size) in the loaded header. Written with the section's end address, which the
    # address map translates (the size 0x4AE8344 is not an address: 27.0.1's is 0x4B82208).
    if read(base+0x88, 16) != struct.pack('<QQ', 0x55F0, 0x4AED934 - 0x55F0):
        raise ValueError('Plugin native text section changed')
    service = _pointer(read, base+FULL_ROOT)
    if not service:
        raise UnsupportedSource('missing_full_game_club_finance_service')
    if _pointer(read, service) != base+FULL_TABLE:
        raise UnsupportedSource('unsupported_full_game_club_finance_type')
    displacement, info = struct.unpack('<qQ', read(base+FULL_TABLE-16, 16))
    if displacement != 0 or info != base+0x55DFF18:
        raise ValueError('Full GAME_CLUB_FINANCE metadata changed')
    if (_address(players.u64(read(info+8, 8)), alignment=1) != base+0x53B1011
            or read(base+0x53B1011, 20) != b'17GAME_CLUB_FINANCE\0'):
        raise ValueError('Full GAME_CLUB_FINANCE RTTI changed')
    # Native byte offsets, respectively vtable ordinals17 and39.
    for offset, getter in ((0x88, 0x1FE8AF8), (0x138, 0x1FEBC8C)):
        if _function_pointer(read, base+FULL_TABLE+offset) != base+getter:
            raise ValueError('Full GAME_CLUB_FINANCE producer slot changed')


def _owner(read, base, source, manager):
    table = _pointer(read, manager)
    fields = NONPLAYER.get(table-base)
    if fields is None:
        raise UnsupportedSource('unproved_manager_nonplayer_type')
    delta, primary_delta, person_table, expected_kind = fields
    if (struct.unpack('<q', read(table-0x20, 8))[0] != delta
            or struct.unpack('<q', read(table-0x10, 8))[0] != primary_delta):
        raise ValueError('Manager NON_PLAYER displacement changed')
    person = manager+delta
    kind = source.person(person)
    if kind != expected_kind or _pointer(read, person) != base+person_table:
        raise ValueError('Manager canonical PERSON type changed')
    primary, offset, _, _, _ = assessment_people._person(read, base, source.people, person)
    if primary != manager+primary_delta or person-offset != primary:
        raise ValueError('Manager full-primary identity changed')
    primary_table = base+{'staff':0x5583660, 'human_manager':0x55AC480,
                         'player_staff':0x558EF38}[kind]
    if _pointer(read, table-8) != _pointer(read, primary_table-8):
        raise ValueError('Manager NON_PLAYER RTTI family changed')
    getter = 0x1300058 if kind == 'human_manager' else 0xCA4638
    expected = TRUE if kind == 'human_manager' else FALSE
    if (_function_pointer(read, base+person_table+0x1B0) != base+getter
            or read(base+getter, 8) != expected):
        raise ValueError('Manager PERSON HUMAN predicate changed')
    if kind != 'human_manager':
        return None
    if (_function_pointer(read, base+person_table+0x6F0) != base+0x1300074
            or read(base+0x1300074, len(HUMAN_CAST)) != HUMAN_CAST
            or struct.unpack('<q', read(base+person_table-0x700, 8))[0] != -delta):
        raise ValueError('Manager PERSON HUMAN cast changed')
    return _ref(read, person)


def _queue(read, base, human, offset):
    entries, selected = [], []
    for ordinal, address in enumerate(_vector(read, human+offset, MAX_QUEUE)):
        if not address:
            entries.append(QueueEntry(ordinal, 0, None, None, None))
            continue
        table = _pointer(read, address)
        displacement, info = struct.unpack('<qQ', read(table-16, 16))
        if displacement != 0:
            raise UnsupportedSource('unproved_queue_nonprimary_object')
        _address(info)
        parent = _pointer(read, info+0x10)
        if table == base+0x55E6488:
            # Actual TEAM_SETTINGS_EDIT_SESSION inherits EDIT_SESSION through
            # EDIT_SESSION_WITH_HISTORY<TEAM_SETTINGS_STATE>, not directly.
            # Bind this complete observed chain and its literal-kind23 getter;
            # other indirect ancestry remains unavailable.
            leaf_name = b'26TEAM_SETTINGS_EDIT_SESSION'
            history_name = b'N2db25EDIT_SESSION_WITH_HISTORYI19TEAM_SETTINGS_STATEEE'
            if (info != base+0x55E6510 or parent != base+0x55E55B0
                    or _address(players.u64(read(info+8, 8)), alignment=1) != base+0x53B560F
                    or read(base+0x53B560F, len(leaf_name)+1) != leaf_name+b'\0'
                    or _address(players.u64(read(parent+8, 8)), alignment=1) != base+0x53B51B9
                    or read(base+0x53B51B9, len(history_name)+1) != history_name+b'\0'
                    or _pointer(read, parent+0x10) != base+0x55A44F0
                    or _function_pointer(read, table+0x10) != base+0x22D3820
                    or read(base+0x22D3820, 8) != bytes.fromhex('e0028052c0035fd6')):
                raise ValueError('History-backed TEAM settings source changed')
        elif parent != base+0x55A44F0:
            raise UnsupportedSource('unproved_queue_edit_session_ancestry')
        text = _address(players.u64(read(info+8, 8)), alignment=1)
        # Bind a nonempty RTTI name without assigning an English message class.
        if not text or read(text, 1) == b'\0':
            raise ValueError('Queue primary RTTI name missing')
        getter = _function_pointer(read, table+0x10)
        if not base+0x55F0 <= getter <= base+0x4AED934-8:
            raise UnsupportedSource('unproved_queue_kind_getter_location')
        raw = read(getter, 8)
        instruction, ret = struct.unpack('<II', raw)
        if instruction & 0xFFE0001F != 0x52800000 or ret != 0xD65F03C0:
            raise UnsupportedSource('unproved_queue_kind_getter')
        if table == base+0x55E5380:
            name = b'29CONTRACT_DETAILS_EDIT_SESSION'
            if (info != base+0x55E5408 or text != base+0x53B4D15
                    or read(text, len(name)+1) != name+b'\0'
                    or getter != base+0x227DB10
                    or raw != bytes.fromhex('00058052c0035fd6')):
                raise ValueError('Contract edit-session native kind getter changed')
        native_kind = (instruction >> 5) & 0xFFFF
        entries.append(QueueEntry(ordinal, address, native_kind, table, getter))
        if native_kind == 40:
            name = b'29CONTRACT_DETAILS_EDIT_SESSION'
            if (table != base+0x55E5380 or info != base+0x55E5408
                    or text != base+0x53B4D15 or read(text, len(name)+1) != name+b'\0'
                    or getter != base+0x227DB10):
                raise UnsupportedSource('unproved_kind40_contract_edit_session_type')
            selected.append(address)
    return QueuePopulation(offset, tuple(entries), tuple(selected))


def _same_context(observed, expected):
    if type(observed) is not Context:
        return False
    for field in ('process_id', 'save_identity', 'session_identity',
                  'plugin_sha256', 'native_date'):
        if type(getattr(observed, field)) is not type(getattr(expected, field)):
            return False
    if type(observed.club) is not CanonicalRef:
        return False
    for field in ('address', 'index', 'native_id', 'secondary'):
        if type(getattr(observed.club, field)) is not int:
            return False
    return observed == expected


def observe(read, base, context, *, lifetime):
    """Observe this producer's exact owner/queues and resolve proved zero cases.

    This is the EAEB44 specialization: native x2=null and x3=0.
    The caller must supply a genuine Bridge process/plugin/save/session callback,
    and keep its outer source read scope around this entire call. No financial
    amount or helper answer is accepted from the caller. Unknown is never zero.
    """
    from . import committed_wage_offer_selection as offers

    _address(base)
    if (type(context) is not Context or type(context.process_id) is not int
            or context.process_id <= 0 or type(context.save_identity) is not str
            or not context.save_identity or type(context.session_identity) is not str
            or not context.session_identity or type(context.plugin_sha256) is not str
            or context.plugin_sha256 != PLUGIN_SHA
            or type(context.native_date) is not bytes or len(context.native_date) != 4
            or type(context.club) is not CanonicalRef or not callable(lifetime)):
        raise ValueError('Invalid v138 source context')
    _address(context.club.address)
    if (any(type(value) is not int for value in (context.club.index, context.club.native_id, context.club.secondary))
            or not 0 <= context.club.index < 1 << 32
            or not 1 <= context.club.native_id < 1 << 32
            or not 0 <= context.club.secondary < 1 << 32):
        raise ValueError('Invalid v138 selected CLUB reference')
    if not _same_context(lifetime(), context):
        raise ValueError('v138 process/save/session lifetime changed')
    snapshot = world.ReadSet(read)
    result = None
    human = queue218 = queue200 = None
    first_team = None
    selections = []
    selections_complete = False
    try:
        _verify(snapshot, base)
        if snapshot(base+world.CURRENT_DATE, 4) != context.native_date:
            raise ValueError('v138 current native date changed')
        world.packed_date(context.native_date)
        source = offers._Source(snapshot, base)
        source.club(context.club.address)
        if _ref(snapshot, context.club.address) != context.club:
            raise ValueError('v138 selected CLUB identity changed')
        native_teams = _vector(snapshot, context.club.address+0x18, MAX_TEAMS)
        if not native_teams or not native_teams[0]:
            reason = 'empty_club_team_vector' if not native_teams else 'null_first_club_team'
            result = V138Inputs('native_zero', reason, 0, 0, complete_v138_branch=True)
        else:
            first = native_teams[0]
            source.team(first)
            first_team = _ref(snapshot, first)
            if _pointer(snapshot, first+0x30) != context.club.address:
                raise ValueError('v138 first TEAM owner changed')
            # On this exact first-CLUB-TEAM input,175e508's kind44 special path
            # either returns the same checked HUMAN or falls to this stored80.
            snapshot(first+0x28, 1)
            snapshot(first+0x2F, 1)
            manager = _pointer(snapshot, first+0x80)
            if not manager:
                raise UnsupportedSource('cold_175e508_manager_selection_unimplemented')
            human = _owner(snapshot, base, source, manager)
            if human is None:
                result = V138Inputs('native_zero', 'manager_is_not_human', 0, 0,
                                    complete_v138_branch=True, first_team=first_team)
            else:
                human_primary = human.address-0x548
                queue218 = _queue(snapshot, base, human_primary, 0x218)
                queue200 = _queue(snapshot, base, human_primary, 0x200)
                selections = []
                for team in native_teams:
                    if not team:
                        raise ValueError('Null later v138 TEAM entry')
                    source.team(team)
                    if _pointer(snapshot, team+0x30) != context.club.address:
                        raise ValueError('v138 TEAM belongs to another CLUB')
                    kind = snapshot(team+0x28, 1)[0]
                    if kind <= 44 and (1 << kind) & 0x100007C000F0:
                        continue
                    selection = offers.select_offers(snapshot, base, team,
                        exclude_native_states=True, skip_state19=True, mode=0)
                    if selection.state != 'selected' or selection.selected is None:
                        raise UnsupportedSource(selection.reason or 'offer_selection_unavailable')
                    selections.append((team, selection))
                selections_complete = True
                if queue218.kind40 or queue200.kind40:
                    result = V138Inputs('unavailable', 'nonempty_kind40_monetary_helper_unimplemented',
                        None, None, human, queue218, queue200, tuple(selections),
                        selections_complete=True, first_team=first_team)
                elif any(selection.selected for _, selection in selections):
                    result = V138Inputs('unavailable', 'nonempty_selected_offer_monetary_path_unimplemented',
                        None, None, human, queue218, queue200, tuple(selections),
                        selections_complete=True, first_team=first_team)
                else:
                    result = V138Inputs('native_zero', 'checked_empty_contribution_sources',
                        0, 0, human, queue218, queue200, tuple(selections), True, True, first_team)
    except (UnsupportedSource, offers.UnsupportedSelection) as error:
        result = V138Inputs('unavailable', str(error), None, None, human,
                            queue218, queue200, tuple(selections),
                            selections_complete=selections_complete, first_team=first_team)
    finally:
        snapshot.verify()
        if not _same_context(lifetime(), context):
            raise ValueError('v138 process/save/session lifetime changed')
        # The lifetime callback can itself perform reads while state changes.
        # Recheck every consumed byte after it before publishing any result.
        snapshot.verify()
    return result
