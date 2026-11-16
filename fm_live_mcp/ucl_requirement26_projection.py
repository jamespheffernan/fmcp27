"""Current native UCL requirement26, separate from complete fixture eligibility.

Every source is passive. The caller supplies canonical requested identities and
fixture operands, then rebinds the complete projection and verifies consumed
bytes after its last callback. Unsupported native branches remain unavailable.
"""
from copy import deepcopy
from datetime import date, timedelta
import struct

from . import competition_stages, competitions, players
from . import player_registration_source as registration, prepared_tactics_source, teams
from . import ucl_registration_source as ucl, ucl_requirement26_source as operands
from . import world

VIRTUAL_NULL = (0xCA49DC, bytes.fromhex('000080d2c0035fd6'))
CONTRACT_RESULTS = {0xD8C3D0: 5, 0x129FFFC: 0, 0x13781B8: 1, 0x1006B44: 2}
PENDING_LEAVES = {0x22A8DB8: 37, 0x22DC800: 17, 0x22CED60: 3,
                  0x22BEF64: 11, 0x22D3820: 23, 0x22A11B4: 12}
RESTRICTION_BITS = sum(1 << bit for bit in (14, 37, 3, 31))


class Unavailable(ValueError):
    """A valid native branch whose required operators are not proved here."""


def _read(read, at, size):
    raw = read(at, size)
    if type(raw) is not bytes or len(raw) != size:
        raise ValueError('Incomplete UCL requirement26 read')
    return raw


def _ptr(read, at):
    value = int.from_bytes(_read(read, at, 8), 'little')
    if value and (value < 4096 or value % 8):
        raise ValueError('Invalid UCL requirement26 object pointer')
    return value


def _method(read, base, at, expected):
    value = int.from_bytes(_read(read, at, 8), 'little')
    if value % 4 or value != base + expected:
        raise ValueError('UCL requirement26 native dispatch changed')


def verify_native(read, base):
    ucl.verify_native(read, base)
    registration.verify_native(read, base)
    operands.verify_native(read, base)
    rva, raw = VIRTUAL_NULL
    if _read(read, base + rva, len(raw)) != raw:
        raise ValueError('Compact native PLAYER cast changed')


def _calendar(raw):
    low, year = struct.unpack('<HH', raw)
    day = low & 511
    if not 2001 <= year <= 2099 or not 1 <= day <= 366:
        raise Unavailable('unsupported_native_medical_calendar')
    result = date(year, 1, 1) + timedelta(days=day - 1)
    if result.year != year:
        raise ValueError('Invalid native medical date')
    return result


def _end(raw):
    duration = struct.unpack_from('<h', raw, 0x28)[0]
    # Both original date-add and date-subtract loops match ordinary calendar
    # arithmetic on this bounded envelope, without their signed-overflow cases.
    if not -366 <= duration <= 366:
        raise Unavailable('unsupported_native_medical_duration')
    end = _calendar(raw[0x20:0x24]) + timedelta(days=duration)
    if not 2001 <= end.year <= 2099:
        raise Unavailable('unsupported_native_medical_end_calendar')
    return end


def _duration177(raw):
    weeks = struct.unpack_from('<b', raw, 0x33)[0]
    if weeks >= 0:
        return weeks * 7
    start, end = _calendar(raw[0x20:0x24]), _end(raw)
    if end < start:
        # Literal177AC94..ACAC: this reverse-order path multiplies whole
        # years by365. It intentionally does not use Gregorian absolute days.
        return (start.year - end.year) * 365 + start.timetuple().tm_yday - end.timetuple().tm_yday
    return (end - start).days


def medical(read, primary, current_date):
    """Exact D09BD0 selection and177AA7C duration on the proved date envelope."""
    now = date.fromisoformat(current_date)
    if not 2001 <= now.year <= 2099:
        raise Unavailable('unsupported_native_current_medical_calendar')
    header = _ptr(read, primary + 0xF0)
    entries, _ = competition_stages.vector(read, header, 64) if header else ((), None)
    public = dict(state='checked', source_state='holder_absent' if not header else
                  'checked_empty' if not entries else 'stored_records_present',
                  stored_record_count=len(entries), selected_stored_slot_index=None,
                  native_duration_days=None, native_record_present=False,
                  medical_clearance_evaluated=False)
    selected = None
    for slot in reversed(range(len(entries))):
        if not entries[slot]:
            raise Unavailable('null_native_medical_record')
        raw = _read(read, entries[slot], 0x40)
        end = _end(raw)
        if end < now:
            continue
        weeks = struct.unpack_from('<b', raw, 0x33)[0]
        remaining = weeks * 7 if weeks >= 0 else (end - now).days
        # Native reverse traversal retains the newer physical slot on ties.
        if selected is None or remaining > selected[0]:
            selected = (remaining, slot, raw)
    if selected is not None:
        _, slot, raw = selected
        weeks = struct.unpack_from('<b', raw, 0x33)[0]
        duration = _duration177(raw)
        public.update(native_record_present=True, selected_stored_slot_index=slot,
                      native_duration_days=duration,
                      duration_source='stored_week_byte_times7' if weeks >= 0 else
                                      'native_calendar_difference_operator')
    elif entries:
        public['source_state'] = 'checked_no_unexpired_native_record'
    return public


def _current_rule(read, base, primary, cache):
    """D2DCB8's independently bound current CLUB/COMP rule, never a UCL alias."""
    person = primary + 0x388
    vt = _ptr(read, person)
    _method(read, base, vt + 0x230, 0xD5C578)
    if struct.unpack('<q', _read(read, vt - 0x240, 8))[0] != -0x388:
        raise ValueError('Current TEAM PERSON cast changed')
    current = _ptr(read, primary + 0x128)
    if not current:
        return dict(state='checked_no_current_team', native_d2dcb8=False), None
    public_team, current_binding = teams.by_index(read, base, int.from_bytes(_read(read, current + 8, 4), 'little'))
    if current_binding['address'] != current:
        raise ValueError('PLAYER current TEAM membership changed')
    if _read(read, current + 0x2F, 1) != b'\0' or not current_binding['owner_address']:
        return dict(state='checked_nonclub_current_team', native_d2dcb8=False, team=public_team), None
    club = current_binding['owner_address']
    if club in cache:
        return deepcopy(cache[club])
    club_teams, _ = competition_stages.vector(read, club + 0x18, 64)
    if not club_teams or not club_teams[0]:
        return dict(state='checked_no_current_first_team', native_d2dcb8=False, team=public_team), None
    first = club_teams[0]
    first_public, first_binding = teams.by_index(read, base, int.from_bytes(_read(read, first + 8, 4), 'little'))
    if first_binding['address'] != first or first_binding['owner_address'] != club:
        raise ValueError('PLAYER current club first TEAM changed')
    comp = _ptr(read, first + 0x50)
    if not comp:
        raise Unavailable('current_club_competition_fallback_not_supported')
    index = int.from_bytes(_read(read, comp + 8, 4), 'little')
    competition = competitions.by_index(read, base, index)
    saved = dict(address=comp, database_index=index, native_id=competition['native_id'],
                 random_id=competition['random_id'])
    runtime_context, runtime, identity = competition_stages.runtime_context(read, base, saved)
    if not runtime or runtime_context['shared_runtime']:
        raise Unavailable('current_club_runtime_absent_or_shared')
    if identity[1] != 0x566C2B8:
        raise Unavailable('unsupported_current_club_runtime_type')
    if _read(read, runtime + 0x3BE, 1)[0] not in (0, 1):
        raise Unavailable('unsupported_current_club_runtime_kind')
    owner = _ptr(read, runtime + 0x388)
    if not owner:
        raise Unavailable('current_club_rule_owner_absent')
    parent = _ptr(read, runtime + 0x138)
    parent_id = struct.unpack('<i', _read(read, parent + 12, 4))[0] if parent else -1
    global_id = struct.unpack('<i', _read(read, base + 0x56D3518, 4))[0]
    flags = int.from_bytes(_read(read, runtime + 0x4C, 4), 'little')
    if global_id != parent_id and (flags & ((1 << 6) | (1 << 17))
            or _read(read, runtime + 0x4C0, 1)[0] == 3 or _ptr(read, runtime + 0x510)
            or _read(read, owner + 0x23C, 1)[0] in (1, 3)
            or struct.unpack('<h', _read(read, runtime + 0x3B6, 2))[0] == -3):
        raise Unavailable('unsupported_current_club_rule_selection_branch')
    # 3D46BF0 supplies TEAM=null to3AA5A14. Its optional TEAM override
    # therefore falls through to this same direct rule bank even with bit3.
    bank = _ptr(read, owner + 0x1F0)
    if not bank:
        raise Unavailable('current_club_rule_bank_absent')
    rules, _ = competition_stages.vector(read, bank + 0x60, 256)
    rule_index = _read(read, runtime + 0x49, 1)[0]
    if rule_index >= 128 or rule_index >= len(rules) or not rules[rule_index]:
        raise Unavailable('current_club_default_rule_absent_or_uninitialized')
    rule = rules[rule_index]
    selector = _read(read, rule + 0x125, 1)[0]
    if selector == 8 and not _read(read, rule + 0x12C, 1)[0] & 1 and not _ptr(read, comp + 0x60):
        raise Unavailable('unsupported_current_club_selector8_postfilter')
    mask = int.from_bytes(_read(read, rule + 0xE8, 8), 'little')
    if mask & RESTRICTION_BITS or _read(read, rule + 0xF2, 1) != b'\0':
        raise Unavailable('unsupported_current_club_registration_restriction_operators')
    public = dict(state='checked_current_club_rule', native_d2dcb8=False,
                  current_first_team=first_public, competition=competition,
                  native_season_code=runtime_context['native_season_code'],
                  native_runtime_kind=_read(read, runtime + 0x3BE, 1)[0],
                  native_rule_index=rule_index, native_selector=selector, native_restriction_mask=mask)
    result = (public, dict(rule_address=rule, runtime=runtime, club_address=club))
    cache[club] = deepcopy(result)
    return result


def registered(read, base, primary, target, context):
    """Original D32054(mode1) with contract/pending/current-rule operators closed."""
    if _ptr(read, primary) != base + players.RVA[0]:
        raise Unavailable('unsupported_aggregate_registration_player_kind')
    if struct.unpack('<q', _read(read, base + players.RVA[0] - 0x20, 8))[0] != 0x278:
        raise ValueError('Ordinary common PLAYER displacement changed')
    if not _ptr(read, primary + 0x2C0):
        return dict(native_result=False, state='checked_holder_absent', current_rule=None)
    contract = _ptr(read, primary + 0x2F0)
    if contract:
        table = _ptr(read, contract)
        expected = ucl.CONTRACT_GETTERS.get(table - base)
        if expected is None:
            raise Unavailable('unsupported_contract_registration_getter')
        _method(read, base, table + 0x90, expected)
        if CONTRACT_RESULTS[expected] == 0:
            employer = _ptr(read, contract + 0x10)
            employer_club = _ptr(read, employer + 0x30) if employer else 0
            if employer_club == _ptr(read, target + 0x30) and _read(read, contract + 0x28, 1)[0] & 8:
                return dict(native_result=False, state='checked_contract_override', current_rule=None)
    # context() independently checks14A6478's target first-TEAM HUMAN and
    # literal non-kind19 pending vectors. Every target here has the same owner.
    if _ptr(read, target + 0x30) != context['club']:
        raise Unavailable('aggregate_registration_target_outside_bound_club')
    current_rule, private = _current_rule(read, base, primary, context['current_rules'])
    marker = registration.project(read, primary, 'actual', target, 0)
    selected = marker['selected_marker']
    value = bool(selected and selected['native_kind'] in (25, 26))
    return dict(native_result=value, state='checked_native_registered_mode1', marker=marker,
                current_rule=current_rule)


def _registered_any(read, base, primary, context):
    club = context['club']
    nation = _ptr(read, club + 0xD8)
    if not nation:
        return dict(native_result=True, state='checked_native_target_nation_absent', attempts=[])
    world.typed(read, base, nation, 'nation')
    if _read(read, base + 0x56D34E0, 1) != b'\x01' or not _ptr(read, nation + 0x128):
        raise Unavailable('unsupported_aggregate_target_nation_runtime_lookup')
    attempts = [registered(read, base, primary, context['team'], context)]
    if attempts[0]['native_result']:
        return dict(native_result=True, state='checked_target_registration', attempts=attempts)
    if not _read(read, club + 0xBA, 1)[0] and not _read(read, club + 0x163, 1)[0] & 16:
        affiliations, _ = competition_stages.vector(read, club + 0x118, 128)
        if affiliations:
            raise Unavailable('unsupported_aggregate_club_affiliation_mapping')
    # Root virtual30 is the pinned false leaf1BDBC08. Therefore the second
    # stored vector contributes directly, without its alternate nation filter.
    root = _ptr(read, base + 0x56D57D0)
    _method(read, base, _ptr(read, root) + 0x30, 0x1BDBC08)
    extra, _ = competition_stages.vector(read, club + 0x30, 64)
    targets = context['club_teams'] + extra
    for target in targets:
        if target == context['team']:
            continue
        if not target:
            raise Unavailable('null_native_registration_fallback_team')
        public, binding = teams.by_index(read, base, int.from_bytes(_read(read, target + 8, 4), 'little'))
        if binding['address'] != target or binding['owner_address'] != club:
            raise Unavailable('unsupported_native_registration_fallback_team_owner')
        attempt = registered(read, base, primary, target, context)
        attempts.append(attempt)
        if attempt['native_result']:
            return dict(native_result=True, state='checked_club_team_registration', attempts=attempts)
    return dict(native_result=False, state='checked_no_club_team_registration', attempts=attempts)


def _rating(read, base, primary, kind):
    expected = players.RVA[0] if kind == 'actual' else players.STAFF_RVA[0] if kind == 'player_staff' else None
    if expected is None:
        raise Unavailable('unsupported_requested_player_position_dispatch')
    vt = _ptr(read, primary)
    if vt != base + expected:
        raise ValueError('Requested PLAYER type changed')
    _method(read, base, vt + 0x390, 0xD5B2A0)
    return struct.unpack('<b', _read(read, primary + 0x148, 1))[0]


def _pending_closed(read, base, human):
    for offset in (0x200, 0x218):
        sessions, _ = competition_stages.vector(read, human + offset, 128)
        for session in sessions:
            if not session:
                continue
            fn = registration._code_pointer(read, _ptr(read, session) + 0x10, base)
            kind = PENDING_LEAVES.get(fn - base)
            if kind is None:
                raise Unavailable('unsupported_pending_player_registration_context')
            if _read(read, fn, 8) != struct.pack('<II', 0x52800000 | (kind << 5), 0xD65F03C0):
                raise ValueError('Pending registration literal changed')


def aggregate(read, base, context):
    captured = operands.collect_operands(read, base, context['team'], 0)
    public = dict(state='checked', native_result=None, threshold=2, known_qualifying_stored_occurrences=0,
                  stored_player_slot_count=captured['stored_player_slot_count'],
                  unique_player_count=captured['unique_player_count'], rows=[],
                  teams=[dict(team_slot=t['team_slot'], player_slot_count=None if t['player_slots'] is None
                              else len(t['player_slots']), state='null_team' if t['player_slots'] is None
                              else 'captured_empty_roster' if not t['player_slots'] else 'captured_roster')
                         for t in captured['teams']], full_eligibility_evaluated=False)
    stopped = False
    for team in captured['teams']:
        if team['player_slots'] is None:
            if not stopped:
                public.update(state='unavailable', reason='null_native_aggregate_team')
            stopped = True
            continue
        for slot in team['player_slots']:
            primary, person = slot['primary'], slot['person']
            row = dict(team_slot=team['team_slot'], player_slot=slot['slot'],
                       native_identity=None if person is None else person['native_identity'],
                       record_kind=None if person is None else person['record_kind'],
                       state=('not_reached_after_native_return' if public['native_result'] is True else
                              'not_evaluated_after_unavailable_source') if stopped else None, native_qualifies=None)
            public['rows'].append(row)
            if stopped:
                continue
            try:
                if not primary or not person:
                    raise Unavailable('null_native_aggregate_player')
                if person['record_kind'] == 'virtual':
                    vt = _ptr(read, primary)
                    if struct.unpack('<q', _read(read, vt - 0x18, 8))[0] != 0x20:
                        raise ValueError('Compact PERSON displacement changed')
                    _method(read, base, _ptr(read, primary + 0x20) + 0x668, VIRTUAL_NULL[0])
                    row.update(state='checked_native_null_player_cast', native_qualifies=False)
                    continue
                offset = 0x388 if person['record_kind'] == 'actual' else 0x480
                person_table = _ptr(read, primary + offset)
                _method(read, base, person_table + 0x668, 0xD5C5FC)
                if struct.unpack('<q', _read(read, person_table - 0x678, 8))[0] != -offset:
                    raise ValueError('Aggregate PERSON PLAYER cast changed')
                rating = _rating(read, base, primary, person['record_kind'])
                row['goalkeeper_position_rating'] = rating
                if rating < 15:
                    row.update(state='checked_position_below15', native_qualifies=False)
                    continue
                if person['record_kind'] != 'actual':
                    raise Unavailable('unsupported_combined_aggregate_registration')
                vt = _ptr(read, primary)
                _method(read, base, vt + 0x250, 0xD56498)
                _method(read, base, vt + 0xC8, 0xD09BD0)
                registration_result = _registered_any(read, base, primary, context)
                row['registration'] = registration_result
                if not registration_result['native_result']:
                    row.update(state='checked_native_registration_false', native_qualifies=False)
                    continue
                medical_result = medical(read, primary, context['current_date'])
                row['medical'] = medical_result
                qualifies = medical_result['native_record_present'] and medical_result['native_duration_days'] >= 31
                row.update(state='checked_native_aggregate_filters', native_qualifies=qualifies)
                public['known_qualifying_stored_occurrences'] += int(qualifies)
                if public['known_qualifying_stored_occurrences'] >= 2:
                    public['native_result'] = True
                    stopped = True
            except Unavailable as exc:
                row.update(state='unavailable', reason=str(exc))
                public.update(state='unavailable', reason=str(exc))
                stopped = True
    if not stopped:
        public['native_result'] = False
    return public


def project(read, base, coach, fixture_address, decoded, current_date, subjects):
    """Return one shared current aggregate and ordered explicit subject results."""
    verify_native(read, base)
    fixture_date = world.packed_date(_read(read, fixture_address + 0x4C, 4))
    if fixture_date <= current_date:
        fixture_context = dict(state='unavailable', reason='fixture_not_on_later_calendar_date',
                               current_read_date=current_date, fixture_date=fixture_date)
        native = None
    else:
        fixture_context, native = ucl.fixture_context(read, base, coach, fixture_address, decoded, current_date)
    public = dict(fixture_context=fixture_context, aggregate=None, players=[], full_eligibility_evaluated=False)
    context = None
    if native is not None:
        _, human = prepared_tactics_source._team_and_human(read, base, coach)
        club = native['club_address']
        club_teams, _ = competition_stages.vector(read, club + 0x18, 64)
        if not club_teams or club_teams[0] != native['team_address']:
            raise ValueError('Requirement26 target first TEAM changed')
        # Re-run the physical pending literal controls independently of any
        # mutable cache supplied by the transport.
        try:
            _pending_closed(read, base, human)
        except Unavailable as exc:
            public['fixture_context'] = dict(fixture_context, state='unavailable', reason=str(exc))
        else:
            context = dict(team=native['team_address'], club=club, club_teams=club_teams,
                           current_date=current_date, current_rules={})
    for ref, primary, kind in subjects:
        row = dict(player_ref=ref, state='unavailable', native_requirement26=None,
                   registration_exemption=None, goalkeeper_position_rating=None,
                   full_eligibility_evaluated=False)
        public['players'].append(row)
        if context is None:
            row['reason'] = 'ucl_fixture_registration_context_unavailable'
            continue
        try:
            rating = _rating(read, base, primary, kind)
            row['goalkeeper_position_rating'] = rating
            if rating < 15:
                row.update(state='checked', reason='native_position_below15', native_requirement26=False)
                continue
            if public['aggregate'] is None:
                public['aggregate'] = aggregate(read, base, context)
            result = public['aggregate']['native_result']
            row.update(state='checked' if result is not None else 'unavailable',
                       reason='native_current_requirement26' if result is not None else public['aggregate']['reason'],
                       native_requirement26=result, registration_exemption=True if result else None)
        except Unavailable as exc:
            row['reason'] = str(exc)
    public['current_club_rule_sources'] = [deepcopy(v[0]) for v in context['current_rules'].values()] if context else []
    return public
