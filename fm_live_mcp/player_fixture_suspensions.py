"""Native mode0 suspension predicate for an explicit canonical unplayed fixture.

The caller binds the resident fixture/COMP/date and canonical PLAYERs, then
rechecks every consumed byte before publishing. This projects 1F8AF7C on those
explicit inputs; it does not invoke the outer UI's competition lookup, predict
future ban changes, or evaluate other eligibility restrictions.
"""
from datetime import date, timedelta
import hashlib
import struct

from . import competition_stages, competitions, database, fixtures, players, teams, world

NATIVE_GUARDS = (
    (0x1F8AF7C, 0x1074, '9c5deec489e1e637de136d72a5d40e8f9e2b12ab5abda1e8e82d4dd36133ad41'),
    (0x3CC6904, 0xA1C, '06a2bc52b7fbb0339a6b4a4d3c651f92c594827393960b84206daeeced4753e9'),
    (0x4060580, 0x174, '39c69cba44b1ccf45a5083aba88823279b49ef5ce95b7a4ff71ec30005cf3379'),
    (0x108F88, 0x30, '3728d23d47c6535660b77e44b12b05cc533a24f51bf85980c2f05b3302dab198'),
)
SCOPE = ('Native ordinary mode0 suspension predicate for the explicit canonical stored '
         'fixture competition/date and current ban sources. Only unplayed FIXTURE objects, '
         'checked empty sources and the supported single kind1/no-finite-duration branch '
         'are decoded. Cross-competition phase/group and fallback COMP routes are checked. '
         'The supported native path does not gate on stored total-minus-served balance. '
         'Future results assume the currently recorded ban state remains unchanged; this '
         'does not evaluate the full outer availability decision or legal/medical clearance. '
         'No native game function, UI getter, simulation, cleanup or game write is executed.')


def _read(read, at, size):
    raw = read(at, size)
    if type(raw) is not bytes or len(raw) != size:
        raise ValueError('Incomplete fixture suspension source read')
    return raw


def _pointer(read, at):
    value = struct.unpack('<Q', _read(read, at, 8))[0]
    if value and (value < 4096 or value % 8):
        raise ValueError('Invalid fixture suspension source pointer')
    return value


def verify_native(read, base):
    for rva, size, expected in NATIVE_GUARDS:
        if hashlib.sha256(_read(read, base+rva, size)).hexdigest() != expected:
            raise ValueError(f'Fixture suspension native source changed at {rva:#x}')
    if _read(read, base+0x3D030D8, 8) != bytes.fromhex('00008052c0035fd6'):
        raise ValueError('Unplayed fixture suspension branch changed')


def _calendar(raw):
    low, year = struct.unpack('<HH', raw)
    day = low & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Unsupported fixture suspension date')
    value = date(year, 1, 1)+timedelta(days=day-1)
    if value.year != year:
        raise ValueError('Invalid fixture suspension year/day')
    return value


def _unknown(reason, count=None):
    return dict(state='unavailable', reason=reason, native_suspended=None,
                personal_record_count=count, record_context=None,
                overall_fixture_eligibility='not_evaluated')


def _checked(value, reason, count, record=None):
    return dict(state='checked', reason=reason, native_suspended=value,
                personal_record_count=count, record_context=record,
                overall_fixture_eligibility='not_evaluated')


def context(read, base, address, decoded, current_date):
    """Bind canonical stored FIXTURE inputs; retain unsupported runtime branches."""
    verify_native(read, base)
    public = dict(state='unavailable', reason=None, competition=decoded['competition'],
                  native_season_code=None, fixture_date=None,
                  competition_binding='canonical_stored_fixture_name',
                  future_condition='currently_recorded_ban_state_unchanged',
                  full_outer_availability_evaluated=False)
    private = dict(base=base, fixture_teams=decoded['teams'], unplayed=False,
                   runtime=None, discipline=None, fixture_date_raw=None,
                   unsupported_reason=None)
    if decoded['kind'] != 'fixture':
        public['reason'] = private['unsupported_reason'] = 'unsupported_score_bearing_fixture_branch'
        return public, private
    table = _pointer(read, address)
    if _pointer(read, table+0x108) != base+0x3D030D8:
        raise ValueError('Fixture suspension virtual108 changed')
    private['unplayed'] = True
    raw_date = _read(read, address+0x4C, 4)
    day = _calendar(raw_date)
    public['fixture_date'] = day.isoformat()
    private['fixture_date_raw'] = raw_date
    if day < date.fromisoformat(current_date):
        public['reason'] = private['unsupported_reason'] = 'past_fixture_current_state_only'
        return public, private
    comp = decoded['competition']
    if comp is None:
        public['reason'] = private['unsupported_reason'] = 'fixture_competition_absent'
        return public, private
    saved = dict(address=decoded['competition_address'], database_index=comp['database_index'],
                 native_id=comp['native_id'], random_id=comp['random_id'])
    source, runtime, identity = competition_stages.runtime_context(read, base, saved)
    public['native_season_code'] = source['native_season_code']
    if runtime is None or source['shared_runtime']:
        public['reason'] = private['unsupported_reason'] = 'unsupported_absent_or_shared_runtime'
        return public, private
    if decoded['season_code'] != source['native_season_code']:
        public['reason'] = private['unsupported_reason'] = 'fixture_runtime_season_mismatch'
        return public, private
    private['runtime'] = runtime
    kind = _read(read, runtime+0x3BE, 1)[0]
    # Kind21 shares the proved normal mode0/kind1 runtime path. The genuine
    # UCL source is separately checked against complete original1F8AF7C and
    # 3CC6904; activation, phase, scope and exemption guards still apply.
    if kind not in (0, 3, 21):
        public['reason'] = private['unsupported_reason'] = 'unsupported_runtime_kind'
        return public, private
    owner = _pointer(read, runtime+0x388)
    flags = struct.unpack('<I', _read(read, runtime+0x4C, 4))[0]
    special = struct.unpack('<i', _read(read, base+0x56D3518, 4))[0]
    parent = identity[4]
    if special != parent and (flags & ((1 << 6) | (1 << 17))
            or _read(read, runtime+0x4C0, 1)[0] == 3 or _pointer(read, runtime+0x510)
            or (owner and _read(read, owner+0x23C, 1)[0] in (1, 3))
            or struct.unpack('<h', _read(read, runtime+0x3B6, 2))[0] == -3):
        public['reason'] = private['unsupported_reason'] = 'unsupported_native_runtime_activation_branch'
        return public, private
    root = world.pointer(read, base+0x56D57D0)
    fixtures.typed(read, base, root, 'root')
    store = world.pointer(read, root+0x158)
    fixtures.typed(read, base, store, 'store')
    manager = _pointer(read, store+0x70)
    if not manager:
        public['reason'] = private['unsupported_reason'] = 'discipline_manager_absent'
        return public, private
    competition_stages.typed(read, base, manager, (0x55DCE28, b'15GAME_DISCIPLINE'))
    native = world.pointer(read, base+0x56D2D08)
    if players.u64(_read(read, world.pointer(read, native)+0x230, 8)) != base+0x1F8AF7C:
        raise ValueError('Native suspension manager method changed')
    private['discipline'] = manager
    public.update(state='available', reason='canonical_unplayed_fixture_mode0_inputs',
                  native_runtime_kind=kind,
                  global_queue='skipped_by_native_unplayed_fixture_branch')
    return public, private


def _kind1(read, base, raw, binding):
    """Exact supported 3CC6904 branch; no total/served activation inference."""
    result = dict(native_kind=raw[5], native_competition_date_predicate=None,
                  native_rule_index=struct.unpack_from('<h', raw, 0x14)[0],
                  native_scope_competition=None, trace=[])
    if raw[5] != 1:
        return result, 'unsupported_personal_ban_kind'
    if struct.unpack_from('<h', raw, 0x16)[0] >= 0:
        return result, 'unsupported_finite_duration_or_cleanup_branch'
    target = _calendar(binding['fixture_date_raw'])
    start = _calendar(raw[0x10:0x14])
    result['trace'].append('native_start_date_comparison')
    if target < start:
        result['native_competition_date_predicate'] = False
        return result, None
    rules, _ = competition_stages.vector(read, binding['discipline']+8, 4096)
    index = result['native_rule_index']
    if not 0 <= index < len(rules) or not rules[index]:
        result['native_competition_date_predicate'] = False
        result['trace'].append('native_rule_index_unavailable_returns_false')
        return result, None
    rule = rules[index]
    runtime = binding['runtime']
    phase = struct.unpack('<b', _read(read, runtime+0x48, 1))[0]
    owner = _pointer(read, runtime+0x388)
    bank = _pointer(read, owner+0x1F0) if owner else 0
    phase_rules, _ = competition_stages.vector(read, bank+0x48, 256) if bank else ((), None)
    if not 0 <= phase < len(phase_rules) or not phase_rules[phase]:
        return result, 'unsupported_default_phase_rule_fallback'
    default = phase_rules[phase]
    def group(record):
        parent = _pointer(read, record+0x30)
        return _pointer(read, parent+0x1F8) if parent else 0
    selector = raw[4]
    result.update(native_phase=phase, native_phase_selector=selector)
    if selector != 255 and selector == phase:
        result['trace'].append('native_explicit_phase_matches')
    else:
        if group(default) == group(rule):
            lo, hi, capacity = struct.unpack('<QQQ', _read(read, rule+0x40, 24))
            if (lo, hi, capacity) != (0, 0, 0) and (
                    lo < 4096 or not lo <= hi <= capacity or capacity-lo > 256):
                raise ValueError('Invalid suspension rule phase vector')
            values = _read(read, lo, hi-lo) if hi > lo else b''
            result['native_carryover_phase_list'] = list(values)
            if phase in values:
                result['native_competition_date_predicate'] = True
                result['trace'].append('native_shared_group_phase_carryover')
                return result, None
        if selector != 255:
            result['native_competition_date_predicate'] = False
            result['trace'].append('native_explicit_phase_mismatch')
            return result, None
    if selector != 255 and group(rule) == (_pointer(read, owner+0x1F8) if owner else 0):
        result['native_competition_date_predicate'] = True
        result['trace'].append('native_owner_phase_acceptance')
        return result, None
    index = struct.unpack_from('<i', raw)[0]
    if index < 0:
        result['native_competition_date_predicate'] = False
        result['trace'].append('native_negative_competition_scope')
        return result, None
    scope = competitions.by_index(read, base, index)
    table = database.table(read, base, 'competitions')
    pointer = world.pointer(read, table['start']+index*8)
    parent = _pointer(read, runtime+0x138)
    fallback = _pointer(read, runtime+0x7C8)
    result.update(native_scope_competition=scope,
                  direct_scope_matches=pointer == parent,
                  scope_runtime_matches=_pointer(read, pointer+0xB0) == runtime,
                  fallback_scope_matches=bool(fallback and _pointer(read, fallback+0x138) == pointer))
    result['native_competition_date_predicate'] = any(result[key] for key in (
        'direct_scope_matches', 'scope_runtime_matches', 'fallback_scope_matches'))
    result['trace'].append('native_kind1_competition_comparisons')
    return result, None


def project(read, base, primary, record_kind, binding):
    """Project the proved single-kind1/empty ordinary predicate subset."""
    if record_kind != 'actual':
        return _unknown('unsupported_player_record_kind')
    if world.pointer(read, primary) != base+players.RVA[0]:
        raise ValueError('Fixture suspension ordinary PLAYER type changed')
    current = _pointer(read, primary+0x128)
    if not current:
        return _unknown('player_current_team_absent')
    _, team = teams.by_index(read, base, int.from_bytes(_read(read, current+8, 4), 'little'))
    if team['address'] != current:
        raise ValueError('Fixture suspension current TEAM membership changed')
    if current not in binding['fixture_teams']:
        return _unknown('player_current_team_not_fixture_participant')
    if not binding['unplayed'] or binding['unsupported_reason'] == 'past_fixture_current_state_only':
        return _unknown(binding['unsupported_reason'])
    secondary = _pointer(read, primary+0xF0)
    if not secondary:
        return _checked(False, 'native_absent_personal_secondary', None)
    records, _ = competition_stages.vector(read, secondary+0x18, 64)
    if not records:
        return _checked(False, 'native_checked_empty_personal_ban_list', 0)
    if binding['unsupported_reason']:
        return _unknown(binding['unsupported_reason'], len(records))
    if len(records) != 1 or not records[0]:
        return _unknown('unsupported_multiple_or_null_personal_records', len(records))
    raw = _read(read, records[0], 32)
    record, unsupported = _kind1(read, base, raw, binding)
    if unsupported:
        answer = _unknown(unsupported, 1)
        answer['record_context'] = record
        return answer
    if not record['native_competition_date_predicate']:
        return _checked(False, 'native_record_not_applicable_to_fixture_context', 1, record)
    # 1F8B354→4060580 may admit a separate national exemption list. Only its
    # proved ordinary domestic kind1 false branch is supported here.
    index = struct.unpack_from('<i', raw)[0]
    if index < 0:
        return _unknown('unsupported_scope_for_native_special_exemption_gate', 1)
    scope = competitions.by_index(read, base, index)
    table = database.table(read, base, 'competitions')
    pointer = world.pointer(read, table['start']+index*8)
    if scope['native_id'] in (0x24DCC, 0x773A63B2):
        return _unknown('unsupported_special_competition_exemption_gate', 1)
    runtime = _pointer(read, pointer+0xB0)
    if not runtime:
        return _unknown('unsupported_scope_without_runtime_exemption_gate', 1)
    kind = _read(read, runtime+0x3BE, 1)[0]
    if kind not in (0, 3):
        return _unknown('unsupported_scope_runtime_exemption_gate', 1)
    if _read(read, base+0x52DFBD8+kind, 1) != b'\0':
        raise ValueError('Native suspension exemption category changed')
    record['match_balance_gate'] = 'not_read_on_supported_native_path'
    return _checked(True, 'native_applicable_kind1_suspension', 1, record)
