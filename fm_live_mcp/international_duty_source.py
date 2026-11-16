"""Private current-date national-duty/travel gate; no game calls or writes.

Source: evidence/international-duty-20261108/source-note.md, pinned FM27 plugin
774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1.
Replays d33c3c and204f5c0 for materialized actual/combined PLAYERs only.

The caller MUST verify the plugin fingerprint/UUID, process and loaded-save
identity before and after this call in its existing read scope. CanonicalRef
is an identity operand, not a session/lifetime token. Consumed-byte rereads here
are non-atomic and cannot establish process/save lifetime by themselves.

native_gate_reason is an input to final availability, not the current displayed
status, complete eligibility, physical geolocation or a return forecast. Native
fixture override supports retained future rows/direct inline descriptors and warm
bounds; central TLS selection and cold rebuilds remain unavailable. return_date
is the official UI's estimated return from NATIONAL_TEAM+B8, never INTDATA+A8.
No profile generation is attempted. Full fixture-return source and correction:
evidence/international-duty-20261108/fixture-return/source-note.md and
source-corrections.md; independent copied-instruction gate covers DATE edges.
"""
from dataclasses import dataclass
import struct

from . import competition_stages, database, players, world

PLUGIN_SHA256 = players.SHA256
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
INTDATA = (0x55B2A08, b'N2db25INTERNATIONAL_PLAYER_DATAE')
PROVIDER = (0x55E1208, b'30GAME_INTERNATIONAL_PLAYER_DATA')
PERSON_TYPES = {
    players.RVA[2]: (players.RVA[0], 0x388, b'N2db13ACTUAL_PLAYERE'),
    players.STAFF_RVA[2]: (players.STAFF_RVA[0], 0x480, b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE'),
}
FIXTURE_NAME = (0x55AB970, b'N2db12FIXTURE_NAMEE')
INTEGER_TRAIT = (0x569CC88, b'N6sicore16RAW_TYPED_TRAITSIiEE')
NULL_TRAIT = (0x569CA88, b'N6sicore17NULL_TYPED_TRAITSE')
RULE_GROUP_MANAGER = (0x55DD068, b'23GAME_RULE_GROUP_MANAGER')
COMP_MANAGER = (0x55DC600, b'17GAME_COMP_MANAGER')
DEFAULT_DATE = (1900 << 16) | 1
FIXTURE_EXCLUDED = frozenset((9, 13, 24, 104))
BOUND_RUNTIME_KINDS = frozenset((6, 10, 15, 17, 19, 25, 101, 102, 104))


class _Unavailable(Exception):
    """A reached native source branch lacks a passive equivalent."""


def _signed16(value):
    return (value + 32768) % 65536 - 32768


def _parts(raw):
    return raw >> 16, raw & 511


def _default(raw):
    return _parts(raw) == (1900, 1)


def _year_days(year):
    # Literal native leap predicate over the narrowed unsigned16 year.
    year &= 65535
    mask = 15 if (year * 0x5C29) & 65535 < 0xA3E else 3
    return 366 if year & mask == 0 else 365


def _native_sub(raw, delta):
    """9abf4, including signed16 intermediate narrowing and -32768 branch."""
    if delta < 0:
        return _native_add(raw, _signed16(-(32767 if delta == -32768 else delta)))
    year, day = _parts(raw)
    intermediate = (day - delta - 1) & 0xFFFFFFFF
    while intermediate & 0x8000:
        year = (year - 1) & 65535
        intermediate = (_signed16(intermediate) + _year_days(year)) & 0xFFFFFFFF
    return (year << 16) | (raw & 0xFE00) | ((intermediate + 1) & 511)


def _native_add(raw, delta):
    """42e9b44; deliberately preserves native overflow instead of timedelta."""
    if type(raw) is not int or not 0 <= raw < 1 << 32 or type(delta) is not int or not -(1 << 31) <= delta < 1 << 31:
        raise ValueError('Invalid native DATE arithmetic operand')
    if delta < 0:
        return _native_sub(raw, _signed16(-delta))
    year, day = _parts(raw)
    intermediate = (day + delta - 1) & 0xFFFFFFFF
    while _signed16(intermediate) >= _year_days(year):
        intermediate = (intermediate - _year_days(year)) & 0xFFFFFFFF
        year = (year + 1) & 65535
    return (year << 16) | (raw & 0xFE00) | ((intermediate + 1) & 511)


def _adjust_dates(baseline, start, end, bound):
    """1b65a4c local mutation; duration is low9 subtraction, not elapsed days."""
    if (_default(baseline) or _default(bound) or _parts(start) > _parts(baseline)
            or _parts(baseline) > _parts(bound)):
        return start, end
    duration = (end & 511) - (start & 511)
    new_start = _native_add(baseline, 1)
    new_end = _native_add(new_start, duration)
    if _parts(new_end) <= _parts(bound):
        return new_start, new_end
    if _parts(baseline) <= _parts(_native_sub(bound, 3)):
        return _native_sub(bound, 2), _native_sub(bound, 1)
    return _native_sub(bound, 1), bound


def _vector(read, address, limit, stride=8):
    _address(address, 24)
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (start, end, capacity) == (0, 0, 0):
        return 0, 0
    if (start < 4096 or any(p % 8 for p in (start, end, capacity))
            or not start <= end <= capacity or (end - start) % stride
            or (capacity - start) % stride or capacity - start > limit * stride):
        raise ValueError('Invalid international-duty vector bounds')
    return start, (end - start) // stride


def _pointers(read, header, limit=4096):
    if not header:
        return ()
    start, count = _vector(read, header, limit)
    rows = struct.unpack('<' + 'Q' * count, read(start, count * 8)) if count else ()
    for row in rows:
        _address(row, 8)
    return rows


def _raw_date(read, address):
    raw = read(address, 4)
    _date(raw)
    return int.from_bytes(raw, 'little')


def _team_data(read, team):
    data = players.u64(read(team + 0xA0, 8))
    if not data:
        raise _Unavailable('team_fixture_data_absent')
    return _address(data, 0x120)


def _any_team(read, base, address):
    table = players.u64(read(address, 8))
    kind = next((k for k in ('team', 'national_team') if table == base + world.TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported international-duty descriptor TEAM type')
    return _team(read, base, address, kind)


def _descriptor_owner(read, base, team, data, opponent):
    if players.u64(read(data + 0x30, 8)) != team:
        raise ValueError('International-duty inline descriptor TEAM owner changed')
    _any_team(read, base, opponent)


def _runtime(read, base, competition):
    runtime = players.u64(read(competition + 0xB0, 8))
    if not runtime:
        return None
    table = players.u64(read(_address(runtime), 8)) - base
    name = competition_stages.RUNTIME_TYPES.get(table)
    if name is None:
        raise _Unavailable('unsupported_fixture_runtime_type')
    _typed(read, base, runtime, (table, name))
    owner = players.u64(read(runtime + 0x138, 8))
    _typed(read, base, owner, world.TYPES['competition'])
    _canonical(read, base, 'competitions', owner)
    return runtime


def _competition(read, base, address):
    _typed(read, base, address, world.TYPES['competition'])
    _canonical(read, base, 'competitions', address)
    return _runtime(read, base, address)


def _excluded_competition(read, base, address):
    runtime = _competition(read, base, address)
    return read(runtime + 0x3BE, 1)[0] in FIXTURE_EXCLUDED if runtime else read(address + 0xF8, 1)[0] in (9, 24)


def _future_competition(read, base, index):
    if index < 0:
        return 0
    root_rva, table_rva, name = database.TABLES['competitions']
    root = players.u64(read(base + root_rva, 8))
    if not root:
        return 0
    _typed(read, base, root, (table_rva, name))
    if not read(base + 0x56D34E0, 1)[0] & 1:
        start, count = _vector(read, root + 0x68, 2_000_000)
        if index < count:
            address = players.u64(read(start + index * 8, 8))
            if address and int.from_bytes(read(_address(address) + 8, 4), 'little') != index:
                raise ValueError('International-duty future COMP ordinal changed')
            return address
    header = players.u64(read(root + 0x88, 8))
    start, count = _vector(read, header, 2_000_000)
    address = players.u64(read(start + index * 8, 8)) if index < count else 0
    if address and int.from_bytes(read(_address(address) + 8, 4), 'little') != index:
        raise ValueError('International-duty future COMP ordinal changed')
    return address


def _future_baseline(read, base, team, data, start):
    rows = _pointers(read, players.u64(read(data + 0x98, 8)))
    upper = _native_add(start, 20)
    selected = DEFAULT_DATE
    for row in rows:
        index = struct.unpack('<i', read(row + 0xC, 4))[0]
        competition = _future_competition(read, base, index)
        if competition and _excluded_competition(read, base, competition):
            continue
        value = _raw_date(read, row + 8)
        if (_parts(start) <= _parts(value) <= _parts(upper)
                and (_default(selected) or _parts(value) < _parts(selected))):
            selected = value
    return selected


def _baseline(read, base, primary, person, selected_club_team, today, start):
    # PERSON240's direct route: current kind0 TEAM30 CLUB. Contract fallback is
    # deliberately unneeded because this reader already checked PLAYER128 owner.
    person_table = players.u64(read(person.address, 8))
    for slot, fn in ((0x240, 0x1489900), (0x230, 0xD5C578)):
        if players.u64(read(person_table + slot, 8)) != base + fn:
            raise ValueError('International-duty current CLUB dispatch changed')
    club = players.u64(read(selected_club_team + 0x30, 8))
    first, count = _vector(read, club + 0x18, 4096)
    if not count:
        return DEFAULT_DATE
    team = players.u64(read(first, 8))
    if not team:
        return DEFAULT_DATE
    _team(read, base, team, 'team')
    if players.u64(read(team + 0x30, 8)) != club:
        raise ValueError('International-duty first club TEAM owner changed')
    data = _team_data(read, team)
    season = int.from_bytes(read(data + 0x10E, 2), 'little')
    opponent = players.u64(read(data + 0x38, 8))
    if not season or season + 1 < today[0] or not opponent:
        return _future_baseline(read, base, team, data, start)
    cached = _raw_date(read, data + 0x40)
    if _parts(cached) < today:
        return _future_baseline(read, base, team, data, start)
    _descriptor_owner(read, base, team, data, opponent)
    if _parts(cached) <= _parts(start):
        if (_parts(start)[0] - 1) > season:
            return DEFAULT_DATE
        raise _Unavailable('central_fixture_TLS_selection_unproved')
    name = players.u64(read(data + 0x28, 8))
    if not name:
        return DEFAULT_DATE
    _typed(read, base, name, FIXTURE_NAME)
    _canonical(read, base, 'fixture_names', name)
    competition = players.u64(read(name + 0x18, 8))
    if not competition:
        return DEFAULT_DATE
    return DEFAULT_DATE if _excluded_competition(read, base, competition) else cached


def _warm_descriptor(read, base, team, today):
    data = _team_data(read, team)
    season = int.from_bytes(read(data + 0x10E, 2), 'little')
    if not season or season + 1 < today[0]:
        return None
    opponent = players.u64(read(data + 0x38, 8))
    cached = _raw_date(read, data + 0x40)
    if not opponent or _parts(cached) < today:
        raise _Unavailable('cold_national_fixture_descriptor_unproved')
    _descriptor_owner(read, base, team, data, opponent)
    return cached


def _property(read, runtime, key):
    start, count = _vector(read, runtime + 0x50, 4096, 16)
    for index in range(count):
        row = start + index * 16
        if int.from_bytes(read(row, 4), 'little') == key:
            return players.u64(read(row + 8, 8))
    return 0


def _trait(read, base, handle):
    if not handle:
        return 0, 0
    descriptor = players.u64(read(_address(handle, 16), 8))
    table = players.u64(read(_address(descriptor, 9), 8))
    kind = read(descriptor + 8, 1)[0]
    if table == base + INTEGER_TRAIT[0]:
        _typed(read, base, descriptor, INTEGER_TRAIT)
        if kind != 1:
            raise ValueError('International-duty integer trait kind changed')
        if players.u64(read(table + 0x48, 8)) != base + 0x4406EF8:
            raise ValueError('International-duty integer trait getter changed')
        return kind, _signed16(struct.unpack('<i', read(handle + 8, 4))[0])
    if table == base + NULL_TRAIT[0]:
        _typed(read, base, descriptor, NULL_TRAIT)
        if kind:
            raise ValueError('International-duty null trait kind changed')
        if players.u64(read(table + 0x48, 8)) != base + 0x28E64:
            raise ValueError('International-duty null trait getter changed')
        return 0, 0
    raise _Unavailable('unsupported_runtime_rule_trait')


def _runtime_rule(read, base, runtime):
    table = players.u64(read(runtime, 8))
    for slot, fn in ((0x108, 0x3B4D5B0), (0x100, 0x3B4D4BC), (0xF0, 0x3B4D418)):
        if players.u64(read(table + slot, 8)) != base + fn:
            raise ValueError('International-duty runtime rule dispatch changed')
    handle = _property(read, runtime, 0x44624C6D)  # DbLm
    if handle:
        return _trait(read, base, handle)[1]
    kind, value = _trait(read, base, _property(read, runtime, 0x64626D75))
    if kind:
        return value
    if read(runtime + 0x3BE, 1)[0] in FIXTURE_EXCLUDED:
        return 1
    kind, value = _trait(read, base, _property(read, runtime, 0x64627373))
    return min(_signed16((value if kind else 19) - 1), 14)


def _bound(read, base, national, today):
    competition = players.u64(read(national + 0x50, 8))
    runtime = _competition(read, base, competition) if competition else None
    if runtime and read(runtime + 0x3BE, 1)[0] not in BOUND_RUNTIME_KINDS:
        runtime = None
    if not runtime:
        descriptor = _warm_descriptor(read, base, national, today)
        return _native_sub(descriptor, 1) if descriptor is not None else DEFAULT_DATE
    cache = players.u64(read(runtime + 0x510, 8))
    if not cache:
        raise _Unavailable('cold_runtime_fixture_date_unproved')
    cached = _raw_date(read, _address(cache, 0x7C) + 0x78)
    rule = _runtime_rule(read, base, runtime)
    return _native_sub(cached, rule) if rule >= 0 else _native_add(cached, -32767 if rule == -32768 else -rule)


def _override(read, base, primary, person, club_team, national, today, start, end, assignment_end):
    # 204f650..65c reads this contextual first argument before the wrapper;
    # the wrapper itself does not dereference or use it. Preserve that source
    # dependency without turning it into an invented permission/manager flag.
    root = players.u64(read(base + 0x56D57D0, 8))
    _typed(read, base, root, RULE_GROUP_MANAGER)
    manager = players.u64(read(root + 0x158, 8))
    _typed(read, base, manager, COMP_MANAGER)
    context = players.u64(read(manager + 0x60, 8))
    if context:
        _address(context)
    baseline = _baseline(read, base, primary, person, club_team, today, start)
    if (_default(baseline) or _parts(start) > _parts(baseline)
            or _parts(baseline) >= _parts(assignment_end)):
        return start, end
    bound = _bound(read, base, national, today)
    if _parts(assignment_end) < _parts(bound):
        descriptor = _warm_descriptor(read, base, national, today)
        bound = _native_sub(descriptor, 1) if descriptor is not None else DEFAULT_DATE
    return _adjust_dates(baseline, start, end, bound)


def _null_international_gate(read, national, today):
    data = _team_data(read, national)
    rows = _pointers(read, players.u64(read(data + 0xA0, 8)))
    found = False
    for row in reversed(rows):
        start = _parts(_raw_date(read, row))
        end = _parts(_raw_date(read, row + 4))
        if start <= today <= end:
            found = True
            if today >= _parts(_raw_date(read, row + 8)):
                return True
    return found


def _address(value, size=0, *, aligned=True):
    if (type(value) is not int or value < 4096 or value + size >= 1 << 64
            or (aligned and value % 8)):
        raise ValueError('Invalid international-duty source address')
    return value


@dataclass(frozen=True)
class CanonicalRef:
    """Expected canonical identity; secondary_id is the native raw word, even0."""
    address: int
    database_index: int
    native_id: int
    secondary_id: int

    def __post_init__(self):
        _address(self.address, 20)
        for value in (self.database_index, self.native_id, self.secondary_id):
            if type(value) is not int or not 0 <= value < 1 << 32:
                raise ValueError('Invalid international-duty canonical identity')
        if not self.native_id or self.database_index == 0xFFFFFFFF:
            raise ValueError('Invalid international-duty canonical identity')


def _checked_read(read, address, size):
    _address(address, size, aligned=False)
    raw = read(address, size)
    if type(raw) is not bytes or len(raw) != size:
        raise ValueError('Incomplete international-duty source read')
    return raw


def verify_native(read, base):
    """Verify exact supported branch code, typed casts and enum producer bridge."""
    _address(base)
    for rva, expected in NATIVE_SPANS:
        if _checked_read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'International-duty native source changed at RVA {rva:#x}')
    for slot, target in ((0x55DF1E8, 0x1F8DB6C), (0x55BA230, 0x153AD48)):
        if players.u64(_checked_read(read, base + slot, 8)) != base + target:
            raise ValueError('International-duty native reason bridge changed')


def _typed(read, base, address, layout, displacement=0):
    _address(address, 8)
    rva, name = layout
    table = base + rva
    if players.u64(read(address, 8)) != table:
        raise ValueError('International-duty native type changed')
    actual, info = struct.unpack('<qQ', read(table - 16, 16))
    if actual != displacement:
        raise ValueError('International-duty native displacement changed')
    _address(info, 16)
    text = players.u64(read(info + 8, 8))
    _address(text, len(name) + 1, aligned=False)
    if read(text, len(name) + 1) != name + b'\0':
        raise ValueError('International-duty native RTTI changed')
    return table


def _canonical(read, base, kind, address, expected=None):
    _address(address, 20)
    _, index, uid, secondary = struct.unpack('<QIII', read(address, 20))
    current = CanonicalRef(address, index, uid, secondary)
    if expected is not None and current != expected:
        raise ValueError('International-duty canonical identity is stale')
    table = database.table(read, base, kind)
    if (index >= table['count']
            or players.u64(read(table['start'] + index * 8, 8)) != address):
        raise ValueError('International-duty canonical membership changed')
    return current


def _public_identity(ref):
    return {'database_index': ref.database_index, 'native_id': ref.native_id,
            'random_id': None if ref.secondary_id == ref.native_id else ref.secondary_id}


def _date(raw, *, current=False):
    value = world.packed_date(raw)
    day, year = struct.unpack('<HH', raw)
    if current and (year, day & 511) == (1900, 1):
        raise ValueError('Current international-duty date is unset')
    return (year, day & 511), value


def _player(read, base, person):
    table = players.u64(read(person.address, 8))
    fields = PERSON_TYPES.get(table - base)
    if fields is None:
        raise ValueError('Unsupported international-duty PERSON type; materialized PLAYER required')
    primary_rva, offset, name = fields
    _typed(read, base, person.address, (table - base, name), -offset)
    primary = _address(person.address - offset, offset + 20)
    _typed(read, base, primary, (primary_rva, name))
    if struct.unpack('<q', read(base + primary_rva - 0x18, 8))[0] != offset:
        raise ValueError('International-duty primary PERSON base changed')
    _canonical(read, base, 'people', person.address, person)
    for slot, adjustment, fn in ((0x668, 0x678, 0xD5C5FC), (0x220, 0x230, 0xD5C560),
                                 (0x230, 0x240, 0xD5C578)):
        if (players.u64(read(table + slot, 8)) != base + fn
                or struct.unpack('<q', read(table - adjustment, 8))[0] != -offset):
            raise ValueError('International-duty PLAYER cast changed')
    return primary


def _team(read, base, address, kind, expected=None):
    _typed(read, base, address, world.TYPES[kind])
    ref = _canonical(read, base, 'teams', address, expected)
    native_kind = read(address + 0x2F, 1)[0]
    if native_kind != (1 if kind == 'national_team' else 0):
        raise ValueError('International-duty TEAM kind disagrees with native type')
    owner = players.u64(read(address + 0x30, 8))
    owner_kind, table_kind = ('national_team_container', 'national_team_containers') if kind == 'national_team' else ('club', 'clubs')
    _typed(read, base, owner, world.TYPES[owner_kind])
    _canonical(read, base, table_kind, owner)
    return ref


def read_current(read, base, *, person: CanonicalRef, club_team: CanonicalRef):
    """Read a scoped current-date gate, with explicit unsupported source states.

    The caller's verified build/process/save read scope is a required precondition;
    this helper rereads consumed bytes but does not substitute for that scope.
    The two references must contain raw native canonical identities. No supplied
    Boolean or score decides the result. Wrong owners/types/identities, drift and
    malformed dates fail. Checked native absence returns false; a reached
    unclosed selection/rebuild branch stays unavailable.
    """
    if type(person) is not CanonicalRef or type(club_team) is not CanonicalRef:
        raise ValueError('International-duty canonical references are required')
    _address(base)
    observed = world.ReadSet(lambda address, size: _checked_read(read, address, size))
    verify_native(observed, base)
    primary = _player(observed, base, person)
    _team(observed, base, club_team.address, 'team', club_team)
    if players.u64(observed(primary + 0x128, 8)) != club_team.address:
        raise ValueError('International-duty player belongs to another club TEAM')
    today, iso = _date(observed(base + world.CURRENT_DATE, 4), current=True)
    result = {'state': 'unavailable', 'reason': None, 'current_date': iso,
              'national_assignment_gate': None, 'native_gate_reason': None,
              'national_team_identity': None, 'return_date': None,
              'return_date_state': 'not_proved', 'eligibility_state': 'not_evaluated'}

    def finish(reason, gate=None, code=None):
        result['reason'] = reason
        if gate is not None:
            result.update(state='available', national_assignment_gate=gate)
            if gate and not _default(assignment_end_raw):
                result.update(return_date=assignment_end_iso,
                              return_date_state='native_estimated_return')
            else:
                result['return_date_state'] = 'not_applicable'
        if code is not None:
            result['native_gate_reason'] = {'code': code, 'key': 242665 if code == 4 else 260981,
                'text': 'On international duty' if code == 4 else 'Travelling',
                'scope': 'input_to_final_availability'}
        observed.verify()
        return result

    national = players.u64(observed(primary + 0x120, 8))
    assignment_end_raw, assignment_end_iso = DEFAULT_DATE, None
    if not national:
        return finish('national_assignment_absent', False)
    national_ref = _team(observed, base, national, 'national_team')
    result['national_team_identity'] = _public_identity(national_ref)
    # Native d33c3c early guards dominate travel. No native E2 reset is performed.
    if observed(national + 0xE2, 1)[0] != 1:
        return finish('native_assignment_flag_inactive', False)
    assignment_end_bytes = observed(national + 0xB8, 4)
    assignment_end, assignment_end_iso = _date(assignment_end_bytes)
    assignment_end_raw = int.from_bytes(assignment_end_bytes, 'little')
    if assignment_end <= today:
        return finish('native_assignment_expired', False)
    international = players.u64(observed(primary + 0x118, 8))
    if not international:
        try:
            gate = _null_international_gate(observed, national, today)
        except _Unavailable as error:
            return finish(str(error))
        return finish('native_retained_fixture_block' if gate else 'outside_native_retained_fixture_blocks', gate, 4 if gate else None)
    _typed(observed, base, international, INTDATA)
    provider = players.u64(observed(base + 0x56D2B30, 8))
    provider_table = _typed(observed, base, provider, PROVIDER)
    if players.u64(observed(provider_table + 0x38, 8)) != base + 0x204F5C0:
        raise ValueError('International-duty date provider dispatch changed')
    start_raw = observed(international + 0xA4, 4)
    travel_start, _ = _date(start_raw)
    travel_end, _ = _date(observed(international + 0xA8, 4))
    phase, mode = observed(international + 0xBB, 2)
    if phase not in (0, 1, 2, 3) or mode not in (0, 1):
        return finish('unsupported_native_phase_or_mode')
    low, year = struct.unpack('<HH', start_raw)
    needs_override = phase != 2 and mode == 1 and (year > 1900 or (year == 1900 and low & 0x1FE))
    if needs_override:
        try:
            start, end = _override(observed, base, primary, person, club_team.address,
                national, today, int.from_bytes(start_raw, 'little'),
                int.from_bytes(observed(international + 0xA8, 4), 'little'), assignment_end_raw)
        except _Unavailable as error:
            return finish(str(error))
        travel_start, travel_end = _parts(start), _parts(end)
    # 204f5c0: BB2 uses exclusive upper; other phases use inclusive upper.
    travel = travel_start <= today and (today < travel_end if phase == 2 else today <= travel_end)
    # Outside the interval native current-date BB1/2 is still true.
    travel = travel or phase in (1, 2)
    if travel:
        return finish('native_travel_window', True, 16 if mode == 0 else 15)
    # d33c3c false-travel branch: DC inclusive start; BB3 rejects; B8 inclusive
    # upper is already dominated by its current-date exclusive expiry guard.
    assignment_start, _ = _date(observed(national + 0xDC, 4))
    if today < assignment_start or phase == 3:
        return finish('outside_native_assignment_window', False)
    return finish('native_duty_window', True, 4)


# Exact code bytes from the frozen installed source capture. Runtime has no
# evidence-file dependency. Caller separately verifies whole plugin SHA/UUID.
NATIVE_SPANS = (
    (0xd33c3c, bytes.fromhex(
        'f657bda9f44f01a9fd7b02a9fd830091139040f9530100b4688a43391f050071e100005468764179e94b02d029755b79'
        '1f01096be20000547f8a033900008052fd7b42a9f44f41a9f657c3a8c0035fd6e40302aae20300aa0801005468724179'
        '08210012e94b02d029715b79292100121f01096b29feff54f50303aa548c40f9d40100b4e84c02f0009945f9080040f9'
        '081d40f9e30301aae10314aaf60303aa00013fd640020034950500b42800805288eda0720c000014e00313aa02008052'
        '030080120400805205008012060080520700805237db2894f50300b4c00300b468de40b9a80200b91c000014c9064079'
        '68be41793f01086b23faff54e80315aaca0240794a210012a80000546bba41796b2100125f010b6b23f9ff548bee4239'
        '7f0d0071c0f8ff546c7641796b7241796b2100129fb11d71410100547f05007101010054a80000b469de40b9090100b9'
        '0200001440f7ffb420008052b9ffff173f010c6bc8f6ff54e3feff545f010b6b68f6ff54f4ffff17'
    )),
    (0x204f5c0, bytes.fromhex(
        'ffc300d1f44f01a9fd7b02a9fd83009128ac5429eb23012929ec42390a7d10530c3d00123f0900714102005468044079'
        '690040792d2100121f010a6b880000548a210012a0214a7a630600546a7d10531f010a6ba30700546b3d00126b210012'
        '1f010a6ba2914b7a620500543700001428f042391f050071810200545fb11d7188000054881d1f120409407ae0010054'
        '28b401d008e943f908ad40f9003140f9e80302aae2330091f30303aae3230091f40301aae10308aa6957ec97e30313aa'
        'e10314aaea1f407968044079690040792b2100121f010a6b49010054ea1740791f010a6b2303005468010054ea134079'
        '4a2100127f010a6be800005413000014a3000054ea1b40794a2100127f010a6b62feff540ab301d04ae136914b014079'
        '6901094a292100124a0540793f01007100014a7ae100005428ec4239080500511f090071620000542000805202000014'
        '00008052fd7b42a9f44f41a9ffc30091c0035fd6'
    )),
    (0xd5c5fc, bytes.fromhex(
        '080040f908e119d1080140f90000088bc0035fd6'
    )),
    (0xd5c560, bytes.fromhex(
        '080040f908c108d1080140f90800088b009140f9c0035fd6'
    )),
    (0x1f8e644, bytes.fromhex(
        '760300b4c8be403928030035a20357f8e00314aae15f40f9030080d27795b69760020034818e40f9210400b4a40357f8'
        '28ba0190009945f9080040f9081d40f9e20314aae35f40f900013fd600030034ffaf00b9888e40f908f142391f010071'
        'e80180520815881a1300001428008052ff231529a80357f8081b00b4887a40f9280300b4083140f9e80200b408514039'
        '490180521f01096a60020054080118371b008052e8008052ad010014ffaf00b988008052e8ab00b9'
    )),
    (0x153f764, bytes.fromhex(
        '880c02f0008546f9080040f9083141f9ff230039ff0300f9e67f0091e10317aae20318aae3031aaae40319aa050080d2'
        '070080d200013fd6a0240037fc7f40399f230071'
    )),
    (0x153f8c0, bytes.fromhex(
        '9c620039'
    )),
    (0x408bbc, bytes.fromhex(
        '0163c039a0e302d1bb120094'
    )),
    (0x40d6d8, bytes.fromhex(
        'a80600712b0300541f9d017188140054097702d029712f918a0000102b6968384a090b8b40011fd6'
    )),
    (0x40d870, bytes.fromhex(
        'e8230091e00314aa217d96526100a0720e38ff94'
    )),
    (0x40dac4, bytes.fromhex(
        'e8230091e00314aaa16e9f526100a0727937ff94e8a30091e0230091010080521a18ff94e1a30091e00313aa83edfd94'
        '0fffff17e8230091e00314aaa16e9f526100a0726c37ff94'
    )),
    (0x52efbdc, bytes.fromhex(
        'bd28005c69839dd79d9d42b00076fef1'
    )),
)

# Full static fixture-return helpers, including DATE signed16 edges.
NATIVE_SPANS += (
    (0x1489900, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091f30300aa080040f9081941f900013fd6600000b408bc4039e8020034680240f908e541f9'
        'e00313aa00013fd6c00200b4089840391f05007128010054080040f9083940f9f30300aa00013fd6e80300aae00313aa'
        '1f090071a3000054080840f9680000b409bd4039c9000034000080d205000014001840f9600000b5e8ffff17001940f9'
        'fd7b41a9f44fc2a8c0035fd6'
    )),
    (0xd5c578, bytes.fromhex(
        '080040f9080109d1080140f90800088b009540f9c0035fd6'
    )),
    (0x1b6541c, bytes.fromhex(
        '610600b4ff4301d1f65702a9f44f03a9fd7b04a9fd030191f60304aaf30303aaf40302aaf50301aa280040f908815ef8'
        '296868f8292141f92000088b20013fd6601400b408a441a91f0109ebe0130054030140f9a31300b42800805288eda072'
        'e81b00b9960300b4e8dd0190000545f9a00200b4c11240f9610200b4080040f908e940f900013fd6e00100b4085840f9'
        'a80100b40000805208f94e391f610071290080522921c81a0a4084520a20a07229010a0a2499407aa11000541fa10171'
        '60100054c84e40b94100001400008052c0035fd6685040f9091d4279890600342a0500116bda01906c755b795f010c6b'
        'e30500540a1d40f9aa0500b40b8540790a8140794a2100127f010c6b490400548c0640797f010c6b2207005488050051'
        '1f01096b6c05005488db019008e943f9890240792a21001208ad40f94a4d00112b858b526d008052ee0180528f3d0012'
        '8c7d0b1b8c3d00129ff92871d0318d1a4c3d00131f020f6aa00000549fb505716b0700546cd29f52040000149fb90571'
        'eb0600544cd29f528a010a0bec050011efffff17c30000546cda01908c715b798c2100125f010c6b42fbff54e00303aa'
        'e10314aa8202805223008052040080d20ff88694600000b4080840b9e81b00b968024079082100128902407929210012'
        '0401094be1630091e00315aae20314aae30313aa3d00009435000014a80000548b0240796b2100125f010b6b89f8ff54'
        '091540f9a90500b4290d40f9690500b42a5940f9aa0400b40000805249f94e393f6100712a0080524a21c91a0b408452'
        '0b20a0724a010b0a4499407a010400543fa10171c0030054220000144a050011291917124921003329410f2ae91f00b9'
        'ff230079ff0700f9e91f8052e90b00790920805209e0bf72e90300b900210091e2730091e10314aa040080d2050080d2'
        '260080522700805243de869420f9ffb4084c40b9c6ffff1729e143393f2500712419587ae100005400008052fd7b44a9'
        'f44f43a9f65742a9ff430191c0035fd6084140b9baffff17'
    )),
    (0x1b65704, bytes.fromhex(
        '2a04407929004079292100125fb11d712009417ac0000054e80300aa4b0440797f010a6b82000054480100b500008052'
        'c0035fd600008052a80800b44c0040798c2100127f010a6b8291497a08080054ff4301d1f85f01a9f65702a9f44f03a9'
        'fd7b04a9fd030191179140f9d70700b4e87641795f01086bc2060054e81a40f9c80100b4e82a40f9880100b4085940f9'
        '480100b409f94e393f6500712a0080524a21c91a0b8890524b41a0724a010b0a4499407ae0080054f40301aaf60302aa'
        'f50303aaf30304aae00317aae10308aa4a000094e00f00b9e87641791f41406b62040054e00317aa01f4ef97400500b4'
        '0a344079083040790921001229090071c20100544a0500512b858b524b7d0b1b6b3d00126c008052ed0180527ff92871'
        'ab318c1a4a3d00127f010a6aab2d80526b158b1a6901090b081917122801080b08050011483d103315000014c0035fd6'
        'a8000054e8724179082100123f01086be3f8ff540000805214000014097c10531f01096bc800005408200012e9724179'
        '292100121f01096be8faff54e4330091050000142800805288eda072e80b00b9e4230091e00314aae10316aae20315aa'
        'e30313aa65000094fd7b44a9f44f43a9f65742a9f85f41a9ff430191c0035fd6f40301aaf60302aaf50303aaf30304aa'
        '299501513f0d00712499427ae1f6ff54080080d2b5ffff17'
    )),
    (0x1b658fc, bytes.fromhex(
        'ffc300d1f44f01a9fd7b02a9fd830091010500b4f30301aa2800805288eda072e80f00b9e1330091e00313aa02008012'
        '030080d20400801225008052060080d2aa607c94680240f9088540f9e00313aa00013fd6e005f837e81f4079e91b4079'
        '2a210012eb03202a4b010b0b6a3d00138b0478362b858b526c008052ed018052ae2d8052080500510f7d0b1bef3d0012'
        'fff92871af318c1a1f010f6acf158e1aef010a0bea3d0013effe7f371500001491f3ef97000400b40834407909304079'
        '2b2100126a0900517f050071a8010054080500512b858b520b7d0b1b6b3d00126c008052ed0180527ff92871ab318c1a'
        '1f010b6aab2d80526b158b1a6a010a0b291917124901090b200500110c0000141f204031e8ff8f520801801ae803084b'
        '013d0013e033009148109e94087c1053030000142000805288ed8052003d1033fd7b42a9f44f41a9ffc30091c0035fd6'
    )),
    (0x1b65a4c, bytes.fromhex(
        '8c044079880040790b2100129fb11d716009417a00030054f657bda9f44f01a9fd7b02a9fd830091f50300aa0a044079'
        '08004079092100125fb11d712009417a60010054f30304aaf40302aa2d044079bf010a6b430100542e004079ce210012'
        'bf010a6bc291497aa9000054000080527f00001400008052c0035fd65f010c6ba300005400008052280f00543f010b6b'
        'e80e00542b858b526c008052ed0180524e3d00124a7d0b1b4a3d00125ff92871af318c1a2a3d0013ff010e6aa0000054'
        '5fb505712b0100546ad29f52040000145fb90571ab0000544ad29f524901090bca050011efffff172905001108191712'
        '2821003308410e2a280000b9e00301aaf60301aae10303aafc0f9e94e90316aa800200b96b0640796a0240794c210012'
        '7f41406b03010054e80300aa200080527f41486bc8090054082100129f01086b62090054ad064079880d00519f090071'
        '69000054ee030baa0d0000146e0500512f858b52cf7d0f1bef3d001270008052f1018052fff928712f32901adf010f6a'
        'af2d8052ef158f1ae801080bbf212e6bc300005448030054ad024079ad210012bf21286bc802005488090071c2010054'
        '6b0500512c858b526c7d0c1b8c3d00126d008052ee0180529ff92871cc318d1a6b3d00129f010b6aac2d80528c158c1a'
        '8801080b4a19171208010a0b08050011683d1033aaff9f5203000014680240b9caff9f52880200b96b06407968024079'
        '0c2100128c010a0b8a3d0013cc0178366b0500512c858b526c7d0c1b8c3d00126d008052ee0180529ff92871cc318d1a'
        '6b3d00129f010b6aac2d80528c158c1a8a010a0b081917124801080b08050011683d1033280100b920008052fd7b42a9'
        'f44f41a9f657c3a8c0035fd6'
    )),
    (0x17627f0, bytes.fromhex(
        'ff4301d1f65702a9f44f03a9fd7b04a9fd0301910a5040f9481d4279c80000340b05001169fa01f029755b797f01096b'
        '02010054020080d2e00302aafd7b44a9f44f43a9f65742a9ff430191c0035fd642a100914b1d40f9ab0100b44c854079'
        '9f01096ba8feff544a8140794d210012430100546bfa01f06b715b796b210012bf010b6ba2fdff54040000144c854079'
        '4a8140794d2100120bbc4039bf050071610000549fb11d71400e00549f01096b29060054ed03292a8d010d0bad3d0012'
        'ae110011800d044ecc391e122ee101b0c105c33d0184a14ea00d044e03e4006f8d008052e2e7076f2e858b52c40d020e'
        'ae478152c50d020e6604004fe705004fae2d8052d10d044ece2d8052d20d044e7304006f701ca34e2384a24e7428610e'
        '949e640eb43c742e94a6100ff41c666e831e234e6398a04e431e716e6384b04e2184b34ead1100518e010d0bdf110071'
        '21feff54ec030d4b810d044eecdc01d082bdc03d211ca24e2034a06e001e636e30000014420600542e010c4bcd0d0011'
        'ad751e12800d020ecc0500512ee101b0c17d43fd0184610e800d044e02e4006f8c008052e3e7076f2e858b52c40d020e'
        'ae478152c50d020e6604004fe705004f8e2d8012d00d044eae2d8012d20d044e9384000f511ca24e2284630e54a4102f'
        '429c640ea23c622e42a4100fe21c666e421c344e4298a04e421e706e4284b14e2184730e8c110051ae010c0bdf110071'
        '21feff54ec030c4b810d044eecdc01d083bdc03d211ca34e2034a06e201e626e00b8b14e0c00261e020000140c008052'
        '4a2100126dfa01f0ad715b79ad2100124a010d4b8a010a0b0c1980520d3280527f050071ac018c1a5f010c6b4aeeff54'
        '0a1980520c3280527f05007194018a1a290500513f01086bf30300aa4c04005488fb01f008e943f916ad40f975fa01f0'
        'b5e23691e00315aae10314aa2a1cae94e01f00b9ff230079ff0700f9e81f8052e80b007908e0bf52e80300b9c0220091'
        'e2730091e10315aae30313aa040080d2050080d226008052270080523de99694e80300aae00313aa695240f922a10091'
        'a80000b4e10300aae00308aa8363969412000014e003679e5f0800f9e8ff9f5248400079880080520004186e48880039'
        '4000803d28e101d0003d43fd400c00fd155040f960fa01f000e03691e10314aa011cae94a04200b9685240f909a10091'
        '081d40f91f0100f1e203899a33ffff17'
    )),
    (0x176a9ec, bytes.fromhex(
        'fc6fbba9fa6701a9f85f02a9f65703a9f44f04a9085040f9085140f9482000b4082540a92c0108ebe01f00540b0080d2'
        '140080d2c91c00126a3c00128cfd43932d0440792e004079ce210012ef032d2a83ed805221008052f0ff9f52f1e001b0'
        '2006c33de1e7076f31858b52220e020ea0478152030c020e6404004fa02d8052050c044ee605004fc02d8052070c044e'
        '7004006fa0dc01d011bcc03de0e001b0127c43fd802d8012130c044ea02d8012140c044e9584000f66008052f3018052'
        '8c0500d100796cf85f01106b8000005415304079bf020a6bc1180054bf04003180000054151c40b9bf02056b21180054'
        '8900003415684039bf02096ba117005407010034f50300aab64e4178b7064079d6220012ffb21d71c00a417a41000054'
        'f50300aab50240b9840e0034b67e1053b7220012bf41556b620400548b0d00b4f841550b193f001238130011d60e044e'
        '183b1e12d786a04e360f044e19e4006f99008052381fb94ef986a14e3a2b610e5a9f620e7a3c7a2e5aa7100fda1c646e'
        '591f394e399ba04ef91c656e3987b84ef786b04e391300511a03190b5f13007121feff54f803194b170f044ef71eb14e'
        'f636b66e161f796ed6bab14ed802261e05000014e0924e7a890900540b0900b418008052ba21236b8203005479000f0b'
        '3a3f0012793c00125b130011360f044e793b1e12d786a04e560f044e19e4006f9a008052381fb94ef986a14e3a2b610e'
        '5a9f620e7a3c7a2e5aa7100fda1c646e591f394e399ba04ef91c656e3987b84ef786b04e5a1300513b031a0b7f130071'
        '21feff541a00001429040054590f001139771e12760c020e5a070051d786720e560f044e19e4006f9a008052381fb94e'
        'f986610e3aa7102f399f620e793c792e39a7100fd91c646e391f3a4e399ba04e991e736e3987b84ef786750e5a130051'
        '3b031a0b7f13007121feff54f9031a4b370f044ef71eb14ef636b66e161f796ed6bab14ed902261e0200001419008052'
        'f7020e4b1703170b3820001218030e4b3803180bff02186b8a000054e10315aae30316aaeb0300aac00700b4bf41556b'
        'a8000054b6220012bf41556bc021567a03070054160c4079bf01166b6201005402070034151c407917184079f7220012'
        'bfb21d7161010054ff0600712101005495ed8052260000144805005415084079b5220012df01156b49feff5425000014'
        'f7160011b87e111b183f00121ffb28717832861abf02186ac0000054f83e00131fb705714b01005478d29f5205000014'
        'f83e00131fbb0571ab00005458d29f521703170bb5060011efffff17f7060011f7220012df22356b28010054a3000054'
        '16084079d6220012ff02166b83000054160440b9d57e1053d7220012bf21356b88000054e3000054df01176ba9000054'
        'e00314aaf40300aa4ce6ffb50c00001414144079bf01146b63ffff54480100541410407994220012df01146bc3feff54'
        '05000014000080d20b0080d21f0000f16001809af44f44a9f65743a9f85f42a9fa6741a9fc6fc5a8c0035fd6'
    )),
    (0x3d23618, bytes.fromhex(
        'f657bda9f44f01a9fd7b02a9fd830091f30304aaf40303aaf50301aaf60300aae00301aae10302aa41191794c95240f9'
        '294d40f9e90d00b4292940a94b0109eb800d0054e80300aa000080d20a7d1053082100126ffd43936ccd00f08cc13491'
        '8b0140f98cc15e39ad064079ae024079ce210012ff0500f1ef859f9a30008052114084521120a072210140f934040034'
        '220c40b9e203f837cb0300b4ac000037639146a9840003cb5f0c84ebe3000054634540f9631040a9840003eba0020054'
        '5f0c84eb62020054620c028b420040f9020200b4435840f9430100b462f84e395f6000710322c21a6300110a6498407a'
        '810700545fa00171400700540500001442e043395f2400714418587aa0060054d30200b4030080d2220c40b92202f837'
        '0b0200b4ac000037639146a9840003cb5f0c84ebe3000054634540f9631040a9840003ebc00000545f0c84eb82000054'
        '620c028b430040f902000014030080d27f0013ebe103005422144079bf01026b220100545f000a6ba2010054800000b4'
        '031440795f00036be2010054e00301aa14000014680200542310407963200012df01036b89feff540e000014a8010054'
        '23104079632000121f01036b02feff5408000014e8000054221040794220001203104079632000125f00036b83fdff54'
        '29210091ef0500f101f5ff5402000014000080d2fd7b42a9f44f41a9f657c3a8c0035fd6'
    )),
    (0x3a7dbe4, bytes.fromhex(
        'ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191f70306aaf60305aaf80304aaf50303aa'
        'f90302aaf30301aaf40300aa7f0000f1fb179f1a5f040031e8079f1a460300b4b50400b4bf0200f9898a42f9490000b4'
        '96040037896e47793f070031610700544aff9f523f010a6b760d00344007005489aa4da93f010aeb60140054340140f9'
        '898a42f9e90200b5896ec7793f1900312006005489aa4da93f010aeb01ffff549800001420020054550000b4bf0200f9'
        '898a42f9490000b456010037886ec7791f190031800400541c0080522800805290000014898a42f9290300b416030036'
        '287940b91e000014f6040036d50a00b4bf0200f9898a42f949ffffb5886ec7791f1900318002005488a64da91f0109eb'
        '40310054140140f9898a42f929feffb5886ec7791f1900316001005488a64da91f0109eb01ffff5422000014896e4779'
        '3f070031600400544aff9f523f010a6ba10d00542800805288eda072680200b920008052fd7b46a9f44f45a9f65744a9'
        'f85f43a9fa6742a9fc6f41a9ffc30191c0035fd6550800b4bf0200f9886ec7791f19003100feff5488a64da91f0109eb'
        'c02c0054140140f9886ec7791f19003120fdff5488a64da91f0109eb41ffff541c008052080080521b00805240000014'
        '4aff9f523f010a6bf6070034c0fbff5489aa4da93f010aebe0080054340140f9898a42f969f7ffb5896ec7793f190031'
        'a0faff5489aa4da93f010aeb01ffff543c00001400faff5489aa4da93f010aeb20070054340140f9896ec7793f190031'
        '20f9ff5489aa4da93f010aeb41ffff5430000014898a42f9c9f4ffb5886ec7791f19003100f8ff5488a64da91f0109eb'
        '40270054140140f9898a42f9a9f3ffb5886ec7791f190031e0f6ff5488a64da91f0109eb01ffff540e000014886ec779'
        '1f19003100f6ff5488a64da91f0109eb40250054140140f9886ec7791f19003120f5ff5488a64da91f0109eb41ffff54'
        '1c008052080080523b008052180080121000001400f4ff5489aa4da93f010aeb20010054340140f9896ec7793f190031'
        '20f3ff5489aa4da93f010aeb41ffff5418008012899e40f93f0117ebfc079f1a3f0300714c0200541f07003101020054'
        'fc010037896247798afa4f795f01096b6101005489f64f793fb11d71a11100548aa65da93f010aeb4011005489f24f79'
        '292100123f050071c110005408030036d90d3837281f409289aa5da94a0109cb1f0d8aeb220d0054367968f8f60c00b4'
        'c80240f9087d41f9e00316aa00013fd61f1800714118005489a25da9080109cb1f2100f1c1170054c84a40f9681a00b4'
        '085d40b9680200b9d000001488a65da92a01084b0b20a0527f550a6b0c07005419008052370400b4390338373a1f4092'
        '290108cb5f0f89eba202005400797af8600200b4080040f9087d41f900013fd688ee40f91f180071a00100541a797af8'
        '7a0100b4889e40f91f0117eb400d0054480340f908b540f9e0031aaa00013fd61f0017eb800c005488ee40f939070011'
        '89f240f92a01084b4a2903135f81396b4cfcff5416000014f90138373a1f4092290108cb5f0f89eb6201005400797af8'
        '200100b4080040f9087d41f900013fd688ee40f91f180071600000541a797af8ba0900b53907001189f240f92a01084b'
        '4a2903135f81396b8cfdff5488265fa92a01084b4a290b530b20a0525f010b6b8b090054f70600b4190080522a1f4093'
        '1a796af87a0100b4889e40f91f0117eb20070054480340f908b540f9e0031aaa00013fd61f0017eb6006005488265fa9'
        '390700112a01084b4a2903135f81396becfdff543700001488ea5239e8030034e8ff9f52e8170079211f0013e22b0091'
        'e00314aa23008052dea3009440e1ffb4f60300aa080040f9082140f9e10318aa00013fd6600200b91b0d0037c01240f9'
        '400000b5809e40f9c11640f95e00001488fa47b9680200b9290080520a7d1053082100121f050071e8079f1a5fb11d71'
        '2011881af4feff1700008052f2feff17090080524a7d18532b1d40931a796bf8ba0000b5290500115f81296b6cffff54'
        '0c000014593b4139480340f9082941f9e0031aaa0100801200013fd6086010122900805289eda0721f01096ba1ebff54'
        '2800805288eda072680200b988ea5239a8040034150080523700805297eda072f70f00b9a21e0013e1330091e00314aa'
        '030080d204008012e50316aa060080d270feff97e81f4079e91b4079292100121fb11d712009417ae00100546a064079'
        '1f010a6b430100546b0240796b2100121f010a6b22914b7aa30000545fb11d71a10000547f05007161000054e80f40b9'
        '680200b9b506001188ea52391f01356b08fcff54bc03003620000014c80240f9082941f9e00316aae10318aa00013fd6'
        '600200b93b020037c80240f908b540f9e00316aa00013fd6f70300aac80240f908a540f9e00316aa00013fd6e10300aa'
        'e00317aa020080d2030080d2040080d25a225a97a00200f91f070031e10000543f1f0072a100005488624779690240b9'
        '89fa07b988fa0f79680640791fb11d7101d2ff5468024079082100121f050071e0079f1a8cfeff171c00805208008052'
        '1b008052f3feff171c008052080080523b008052effeff17'
    )),
    (0x3b4d418, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091082445a91f0109eb400100546a6e8e524a8cac720b0140b97f010a6ba000005408410091'
        '1f0109eb61ffff54050000141f0109eb60000054080540f902000014080080d249dc00b029010f911f0100f13301889a'
        '600240f9080040f9080940f9e10313aa00013fd6e0000034600240f9080040f9082540f9e10313aa00013fd602000014'
        '60028052003c0013fd7b41a9f44fc2a8c0035fd6'
    )),
    (0x3b4d4bc, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091f30300aa082445a91f0109eb40010054aaae8d524a8cac720b0140b97f010a6ba0000054'
        '084100911f0109eb61ffff54050000141f0109eb60000054080540f902000014080080d249dc00b029010f911f0100f1'
        '3401889a800240f9080040f9080940f9e10314aa00013fd6e0000034800240f9080040f9082540f9e10314aa00013fd6'
        '1500001468fa4e39200080521f610071c80000540920c81a0a4084520a20a0723f010a6a810100541fa1017140010054'
        '680240f9087940f9e00313aa00013fd608040051083d0013c90180521f39007100b1891a003c0013fd7b41a9f44fc2a8'
        'c0035fd6'
    )),
    (0x3b4d5b0, bytes.fromhex(
        'fd7bbfa9fd030091082445a9ea0308aa1f0109eb60010054ab8d89524b8ca872ea0308aa4c0140b99f010b6ba0000054'
        '4a4100915f0109eb61ffff54100000145f0109ebc00100544a0540f98a0100b41f0109ebc0010054aa8d89524a8ca872'
        '0b0140b97f010a6b20010054084100911f0109eb61ffff5409000014080040f9018140f9fd7bc1a820001fd61f0109eb'
        '60000054080540f902000014080080d249dc00b029010f911f0100f12101889a200040f9080040f9082540f900013fd6'
        '003c0013fd7bc1a8c0035fd6'
    )),
    (0x42e9b44, bytes.fromhex(
        '2104f83708004079092100122900090b0e0440792a0500512b858b526c008052ed01805203000014ca010a0b2e050011'
        'c93d0012ce7d0b1bce3d0012dff92871af318c1a4e3d0013ff01096aa0000054dfb50571eb0000546ed29f52f3ffff17'
        'dfb905716b0000544ed29f52efffff174a0500110019171240210033203d1033c0035fd6fd7bbfa9fd030091e803014b'
        '013d001307c4f696097c1053fd7bc1a8203d1033c0035fd6'
    )),
    (0x4406ef8, bytes.fromhex(
        '200880b9c0035fd6'
    )),
    (0x28e64, bytes.fromhex(
        '000080d2c0035fd6'
    )),
    (0x9abf4, bytes.fromhex(
        '6103f83708044079090040792a210012eb03212a4b010b0b6a3d0013eb0178362b858b526c008052ed018052ae2d8052'
        '080500510f7d0b1bef3d0012fff92871af318c1a1f010f6acf158e1a4f010f0bea3d0013effe7f374a05001120191712'
        '40210033003d1033c0035fd6fd7bbfa9fd0300913f204031e8ff8f520801811ae803084b013d0013b23b0995087c1053'
        'fd7bc1a8003d1033c0035fd6'
    )),
    (0x20ac7e4, bytes.fromhex(
        'a8b356381f410071290080522921c81a29311c12295511122499407a40060054a80240f908815ef8a96a68f8291141f9'
        'a002088b20013fd6f40300aa200500b493ba40b9d90e8994687a1f5308390f12683e093368221833a88318b8a00318f8'
        '20630091a20302d1814c8e52012ead72932e8d94a00358f8080040f9080d40f9a10302d100013fd6a80302d1e00314aa'
        '2a1dc497a8c302d1a00302d1c12fc49720630091a2c302d121ac8c52818eaa72832e8d94a00355f8080040f9'
    )),
)
