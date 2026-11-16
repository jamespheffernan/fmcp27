"""Guarded reconstruction of the current club injury-property estimate.

Only the audited type2/negative-byte33/before-minimum/same-year branch is
supported. PPMi/PPMa are signed remaining calendar days. Converted dates are
arithmetic estimates, never stored return dates, report timestamps or clearance.
No native game function, report creation or player refresh is executed.
"""
import hashlib
import struct
from datetime import date, timedelta

from . import database, players, staff, world

NATIVE_GUARDS = (
    (0xd5c578, 128, '91a2d68c9150ca256ac801c5e17977a02efed953d5df233ac2249715ea5393a1'),
    (0x129a4b8, 96, 'b937292e0b081418e2c97d951a95127cf85859a9b1eda0cb9a33ba114bf48602'),
    (0x129fffc, 96, '44d6f843d7af2160272dab6a5dcee33cab69a7abb59439e23d936e104a360586'),
    (0xd88c6c, 96, '4a074000f802753c5b6594b3f49dfe5ae1c8dbcd65e04e0229f0328081ab305a'),
    (0xd8c3d0, 96, 'b4077dc23a4b5aad177419bbbfd52b54034ba93de6ec53b575ade0d44a9a1ad2'),
    (0xcb85fc, 1664, '469bb49191044a24cdedee68a0efe82828f8582b1aacbe5e97ca034742c9de51'),
    (0x17c7eb0, 1024, '8411eb36325a9bf6f7fa6ce83fd885e31a68958086650b388ebbba32c36b9b94'),
    (0xd2c7b0, 448, '3d3a29f9adbd6fde6b6501f39344e219dcad74eab15a4e59b2641c825d110248'),
    (0x154c694, 1792, 'dc4e6e8d02eba14a21afbbf06745c3d4a833413759e8c784926bc080da507b4d'),
    (0x1f55ba8, 8192, 'ea3c5aa98a822f630913af79cadfdf78c15e4beb2eb19830d6298a3d63ca64ed'),
    (0x135727c, 1024, 'aedb05a803735a60790b7d2b7b939c2155b95674e2a23c8dede250d5c3bac80f'),
    (0x20b29d0, 640, '1d7a24512dd3c3a7caf4a3f3425621de8350a413d516f569cd5c1d9b0a14bb47'),
)

MAX_INJURIES = 128
MAX_STAFF = 1000
SCOPE = {
    'source': 'reconstructed_current_club_medical_estimate_inputs',
    'resident_report_observed': False,
    'displayed_wording_verified': False,
    'native_game_functions_executed': False,
    'medical_clearance': 'not_assessed',
    'match_eligibility': 'not_assessed',
    'date_conversion': 'remaining_calendar_days_added_to_current_date_not_stored_return_DATE',
    'supported_branch': 'type2_negative_byte33_current_no_later_than_minimum_same_year_w5_zero',
}


class UnsupportedEstimate(ValueError):
    """A legitimate native branch outside the independently audited scope."""


def verify_native(read, base):
    for rva, length, expected in NATIVE_GUARDS:
        if hashlib.sha256(read(base + rva, length)).hexdigest() != expected:
            raise ValueError(f'Injury estimate native code changed at RVA {rva:#x}')


def _date(raw):
    if len(raw) != 4:
        raise UnsupportedEstimate('invalid_native_date_width')
    word = int.from_bytes(raw, 'little')
    year, day = word >> 16, word & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366 or (year, day) == (1900, 1):
        raise UnsupportedEstimate('unset_or_unsupported_native_date')
    value = date(year, 1, 1) + timedelta(days=day - 1)
    if value.year != year:
        raise UnsupportedEstimate('invalid_native_day_of_year')
    return value


def _remaining(raw, current):
    if len(raw) != 56:
        raise UnsupportedEstimate('invalid_injury_instance_width')
    if not int.from_bytes(raw[8:16], 'little'):
        raise UnsupportedEstimate('missing_injury_definition')
    if raw[0x30] != 2:
        raise UnsupportedEstimate('unsupported_treatment_branch')
    if struct.unpack_from('<b', raw, 0x33)[0] >= 0:
        raise UnsupportedEstimate('unsupported_nonnegative_byte33_branch')
    start, now = _date(raw[0x20:0x24]), _date(current)
    low, high = struct.unpack_from('<h', raw, 0x2A)[0], struct.unpack_from('<h', raw, 0x28)[0]
    if not 0 <= low <= high <= 366:
        raise UnsupportedEstimate('unsupported_signed_duration_bounds')
    minimum, maximum = start + timedelta(days=low), start + timedelta(days=high)
    if not start <= now <= minimum <= maximum:
        raise UnsupportedEstimate('unsupported_before_start_or_after_minimum_date_branch')
    if now.year != minimum.year or now.year != maximum.year:
        raise UnsupportedEstimate('unsupported_cross_year_date_branch')
    return now, (minimum - now).days, (maximum - now).days


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


def reconstruct(raw, current, skill, mode):
    """Pure audited scalar branch; no identity, staff selection or source I/O."""
    now, low, high = _remaining(raw, current)
    if type(mode) is not int or mode not in (0, 1, 2, 3):
        raise UnsupportedEstimate('unsupported_medical_mode')
    values = [skill.get(key) for key in ('native_DA_u16', 'physiotherapy_raw_signed8', 'people_management_raw_signed8')]
    if (any(type(value) is not int for value in values)
            or not 0 <= values[0] < 32768 or any(not 0 <= value <= 100 for value in values[1:])):
        raise UnsupportedEstimate('unsupported_signed_medical_skill_inputs')
    da, physio, people = values
    physio = max(1, min(20, (physio + 2) // 5))
    people = max(1, min(20, (people + 2) // 5))
    score = max(1, min(70, ((da // 2) * (4 * physio + people)) // 100))
    uncertainty = 0.0 if mode in (1, 2) else _f32(_f32(100 - score) / _f32(100))
    a, b = max(1, low), max(1, high)
    if high >= 5:
        a += int(_f32(_f32(a // 2) * uncertainty))
        b += int(_f32(_f32(b // 2) * uncertainty))
        if a < int(_f32(_f32(b / 100) * _f32(30))):
            a = b // 2
    return {
        'state': 'reconstructed_club_medical_estimate',
        'as_of': now.isoformat(),
        'remaining_calendar_days': {'minimum': a, 'maximum': b},
        'native_property_keys': {'minimum': 'PPMi', 'maximum': 'PPMa'},
        'calendar_conversion': {'earliest': (now + timedelta(days=a)).isoformat(),
                                'latest': (now + timedelta(days=b)).isoformat(),
                                'state': 'derived_estimated_dates_not_stored_return_dates'},
        'native_inputs': {'base_remaining_days': [low, high], 'staff_score': score,
                          'uncertainty_float32': uncertainty, 'medical_mode': mode},
        'scope': dict(SCOPE),
    }


def _nullable_vector(read, address, limit):
    """These two native loops explicitly skip null entries; preserve their slots."""
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if start == end == capacity == 0:
        return ()
    if (start < 4096 or any(value % 8 for value in (start, end, capacity))
            or not start <= end <= capacity or capacity - start > limit * 8):
        raise ValueError('Invalid or over-budget injury estimate vector')
    count = (end - start) // 8
    values = struct.unpack(f'<{count}Q', read(start, count * 8)) if count else ()
    actual = [value for value in values if value]
    if any(value < 4096 or value % 8 for value in actual) or len(set(actual)) != len(actual):
        raise ValueError('Invalid or duplicate injury estimate vector entry')
    return values


def _canonical(read, table, address):
    index, native, secondary = struct.unpack('<III', read(address + 8, 12))
    if not native or index >= table['count'] or world.pointer(read, table['start'] + index * 8) != address:
        raise ValueError('Injury estimate canonical table membership changed')
    return {'database_index': index, 'native_id': native, 'secondary_id': secondary}


def _medical_service(read, base):
    service = players.u64(read(base + 0x56D2CB0, 8))
    if not service:
        raise UnsupportedEstimate('medical_service_unavailable')
    vtable = world.pointer(read, service)
    typeinfo = world.pointer(read, vtable - 8)
    name = players.u64(read(typeinfo + 8, 8))
    if name < 4096:
        raise ValueError('Injury estimate service RTTI name pointer changed')
    expected = b'22GAME_ACTUAL_NON_PLAYER\0'
    if read(name, len(expected)) != expected or players.u64(read(vtable + 0x98, 8)) != base + 0x1F55BA8:
        raise ValueError('Injury estimate medical service dispatch changed')


def _affiliations_simple(read, club):
    # CB85FC skips affiliation substitution under bit4 or an empty vector.
    return bool(read(club + 0x163, 1)[0] & 16) or not world.vector(read, club + 0x118, 1024)


def _head_physio(read, base, club, people):
    if read(club + 0xBA, 1) != b'\0' or not _affiliations_simple(read, club):
        raise UnsupportedEstimate('unsupported_club_affiliation_or_owner_branch')
    for slot, address in enumerate(_nullable_vector(read, club + 0x60, MAX_STAFF)):
        if not address:
            continue
        try:
            kind, fields = staff.layout(read, base, address)
        except ValueError as error:
            raise UnsupportedEstimate('unsupported_staff_class_before_native_selection') from error
        person = address + fields[2]
        index = int.from_bytes(read(person + 8, 4), 'little')
        database.staff_membership(read, base, people, index, address)
        vtable = world.pointer(read, address)
        delta = struct.unpack('<q', read(vtable - 0x18, 8))[0]
        if delta != fields[2] - 0x110:
            raise ValueError('Injury estimate staff PERSON_DATA adjustment changed')
        person_data = address + delta
        contract = players.u64(read(person_data + 0x78, 8))
        if not contract:
            if players.u64(read(person_data + 0x80, 8)):
                raise UnsupportedEstimate('unsupported_auxiliary_staff_contract_before_selection')
            continue
        contract_table = world.pointer(read, contract)
        kind_name = next((name for name in ('full_contract', 'basic_contract')
                          if contract_table == base + world.TYPES[name][0]), None)
        if kind_name is None:
            raise UnsupportedEstimate('unsupported_staff_contract_before_selection')
        world.typed(read, base, contract, kind_name)
        expected_type = 0x129FFFC if kind_name == 'full_contract' else 0xD8C3D0
        if players.u64(read(contract_table + 0x90, 8)) != base + expected_type:
            raise ValueError('Injury estimate staff contract type getter changed')
        if world.pointer(read, contract + 8) != person:
            raise ValueError('Injury estimate staff contract owner changed')
        team = players.u64(read(contract + 0x10, 8))
        if not team:
            raise UnsupportedEstimate('unsupported_missing_staff_contract_team')
        world.typed(read, base, team, 'team')
        _canonical(read, database.table(read, base, 'teams'), team)
        other_club = world.pointer(read, team + 0x30)
        if other_club != club:
            # Native CB85FC can inspect affiliation and auxiliary contracts here.
            raise UnsupportedEstimate('unsupported_foreign_staff_contract_before_selection')
        role = read(contract + 0x26, 1)[0]
        selected_role = role
        if role & 254 != 50:
            alternate = players.u64(read(contract_table + 0x70, 8))
            if alternate == base + 0xD88C6C:
                selected_role = 0
            elif alternate == base + 0x129A4B8:
                selected_role = read(contract + 0xC2, 1)[0]
            else:
                raise UnsupportedEstimate('unsupported_staff_alternate_role_getter')
            if selected_role & 254 != 50:
                continue
        # 17C7EB0 returns the first matching physical staff slot, not the best skill.
        if kind != 'staff':
            raise UnsupportedEstimate('unsupported_selected_medical_staff_class')
        decoded, _ = staff.decode(read, base, address)
        nonplayer = address + fields[3] - 8
        skill = {
            'native_DA_u16': int.from_bytes(read(nonplayer + 0xDA, 2), 'little'),
            'physiotherapy_raw_signed8': struct.unpack('<b', read(nonplayer + 0x30, 1))[0],
            'people_management_raw_signed8': struct.unpack('<b', read(nonplayer + 0x2E, 1))[0],
        }
        return {'native_identity': _canonical(read, people, person), 'display_name': decoded['display_name'],
                'native_staff_slot': slot, 'native_role_code': selected_role,
                'selection': 'native_first_matching_current_club_head_physio',
                'raw_medical_inputs': skill}
    raise UnsupportedEstimate('native_no_head_physio_fallback_not_supported')


def _club_physio(read, base, primary, cache):
    vtable = world.pointer(read, primary)
    if players.u64(read(vtable + 28 * 8, 8)) != base + 0xD2C7B0:
        raise ValueError('Injury property producer dispatch changed')
    delta = struct.unpack('<q', read(vtable - 0x18, 8))[0]
    person_data_table = world.pointer(read, primary + delta)
    if players.u64(read(person_data_table + 0x230, 8)) != base + 0xD5C578:
        raise ValueError('Injury estimate current-team getter changed')
    team = players.u64(read(primary + 0x128, 8))
    if not team:
        raise UnsupportedEstimate('no_current_team_for_club_estimate')
    world.typed(read, base, team, 'team')
    _canonical(read, database.table(read, base, 'teams'), team)
    if read(team + 0x2F, 1) != b'\0':
        raise UnsupportedEstimate('unsupported_current_team_classification')
    club = players.u64(read(team + 0x30, 8))
    if not club:
        raise UnsupportedEstimate('no_current_club_for_estimate')
    world.typed(read, base, club, 'club')
    identity = _canonical(read, database.table(read, base, 'clubs'), club)
    if team not in world.vector(read, club + 0x18, 64):
        raise ValueError('Injury estimate current team is absent from club teams')
    if club not in cache:
        selected = _head_physio(read, base, club, database.table(read, base, 'people'))
        cache[club] = {'club': {**identity, **world.club(read, base, club)[0]}, 'selected_staff': selected}
    return cache[club]


def project(read, base, primary, record_kind, *, current_date, club_cache):
    """Read every independent injury; unsupported rows never erase supported rows.

    Caller owns player binding, native guards, one request-scoped ReadSet/cache,
    final byte rechecks and loaded-career consistency before publishing anything.
    """
    result = {'state': 'unsupported', 'reason': None, 'injury_source': None,
              'injury_record_count': None, 'records': None, 'scope': dict(SCOPE)}
    if record_kind != 'actual':
        result['reason'] = 'unsupported_player_record_kind'
        return result
    container = players.u64(read(primary + 0xF0, 8))
    pointers = _nullable_vector(read, container, MAX_INJURIES) if container else ()
    result['injury_source'] = 'present_vector' if container else 'absent_optional_container'
    result['injury_record_count'] = len(pointers)
    result['records'] = []
    if not pointers:
        result['state'] = 'no_stored_injury_records'
        return result
    raw_date = read(base + world.CURRENT_DATE, 4)
    if _date(raw_date).isoformat() != current_date:
        raise ValueError('Injury estimate current date differs from loaded career')
    table = database.table(read, base, 'injuries')
    pending = []
    for index, address in enumerate(pointers):
        if not address:
            result['records'].append({'injury_index': index, 'state': 'unsupported', 'reason': 'null_injury_instance', 'estimate': None})
            continue
        raw = read(address, 56)
        row = {'injury_index': index, 'state': 'unsupported', 'reason': None,
               'definition': None, 'estimate': None}
        result['records'].append(row)
        definition = players.u64(raw, 8)
        if definition:
            world.typed(read, base, definition, 'injury')
            row['definition'] = {**_canonical(read, table, definition),
                                 'name': world.string(read, players.u64(read(definition + 0x18, 8)))}
        try:
            _remaining(raw, raw_date)
        except UnsupportedEstimate as error:
            row['reason'] = str(error)
        else:
            pending.append((row, raw))
    if pending:
        try:
            _medical_service(read, base)
            context = _club_physio(read, base, primary, club_cache)
            mode = read(base + 0x56D4951, 1)[0]
            result['medical_context'] = context
            for row, raw in pending:
                try:
                    row['estimate'] = reconstruct(raw, raw_date, context['selected_staff']['raw_medical_inputs'], mode)
                except UnsupportedEstimate as error:
                    row['reason'] = str(error)
                else:
                    row.update(state='reconstructed', reason=None)
        except UnsupportedEstimate as error:
            for row, _ in pending:
                row['reason'] = str(error)
    supported = sum(row['state'] == 'reconstructed' for row in result['records'])
    result['state'] = ('reconstructed' if supported == len(pointers) else 'partial' if supported else 'unsupported')
    result['supported_estimate_count'] = supported
    result['aggregate_return_date'] = None
    result['aggregate_return_date_state'] = 'not_combined_across_independent_injury_records'
    return result
