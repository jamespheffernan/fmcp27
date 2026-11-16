"""Native UCL rule operands, without a registration or age-exemption verdict.

The caller must bind the canonical fixture COMP, current season and runtime,
and supply the rule index obtained from that fixture's native phase selector.
Passing -1 asks for the runtime default only; it does not bind a fixture phase.
Every consumed byte must be rechecked by the caller before publication.
"""
import hashlib
import struct

from . import competition_stages, player_registration_source

NATIVE_GUARDS = (
    (0x3AA5A14, 0x998, 'adcb7e1f5126aebacfd954bcf3118b41da9524188bb160fd8794feb89ba842bb'),
    (0x3AB4274, 0x214, 'e456e0690072d9abcdaa728c04f5d90a171308fc62b96a96f2f5d0e8777d36c2'),
    (0x1B12A78, 0x1C90, '76aef84adf13e2c9a8a118ccbffe646d6782f4426faa1fe745bcd53bf3286dc2'),
    (0x14F9918, 0x688, '33ecd803b2ce36c5f6b5a4809f0e6039191f9957a82300bcb2d8818aace025c4'),
    (0x3f22f98, 0x8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x3b8c0a0, 0x8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x3f22f90, 0x8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x3f23068, 0x8, 'c722475f27d1559e22a1016eaa0b9e7955020853a913fb1f32807bd840e68b6b'),
    (0xd8c3d0, 0x8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8'),
    (0x129fffc, 0x8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a'),
    (0x13781b8, 0x8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x1006b44, 0x8, '0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a'),
    (0xca4640, 0x18, '0a3f211c122334f1ccd799afcee3155b50897632e8b5fa2d6a97f6c15006c8eb'),
    (0xcc83d4, 0x20, '8449cd7df507efee3e649b9e4c374d1b95ad1fac89779d2aa0627b21aa054d24'),
    (0xd5b2a0, 0x8, 'e81a727abb917c4cbced2008d7c3ae380a8682ec604cd132aa1c9553e863955b'),
    (0xd5c578, 0x18, '6e7663bd324f74dd5501be3fbb62c43fb3dbc93e85bb760cc631d976b41ff680'),
    (0x1300058, 0x8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac'),
    (0x1300074, 0x14, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa'),
    (0x148f4c0, 0x54, '0bbcb291971498f3812946f0484bef7bbd3cc1cef6299c9ddfb13971e8e8326e'),
    (0x14d2ef4, 0x34c, '82dc2f0c8aaf1936425ab0edd2eb287e5318467e661010ecf547cd0307542e19'),
    (0x14f9fa0, 0x1528, '59c84f3a93ce13e86b6f2922a28ed19325fc9df327e05a7be47201d9051e115c'),
    (0x22a8db8, 0x8, '9f994e1054a653b123d5ff17333c14762ce6d4ac276ee51422da8528c5dacdc5'),
    (0x22bef64, 0x8, '78583cb90ad13e712ee5163aea9c5efe9cbc3402f4096685a45821db97a1cd2a'),
    (0x22ced60, 0x8, '008816324250c06e66ca174f257c933b0d3a7d05ae19334ddb101a72517eaadd'),
    (0x22d3820, 0x8, '60412e60ca4fc60201ca565a5d2b7f777eb4abbd63057402fe49680855509a34'),
    (0x22dc800, 0x8, 'c56baecfc366185dc8c75e403b8ef95a8915c1c345814d4b75876b2a77097277'),
    (0x3d574b0, 0x19c, '78b0d4b5f4560c664509fecaf04e43d17aa48dce579c84d5aa02e1fac5491664'),
    (0x3d5764c, 0x4c8, 'ea7330fa0be825f7a6759af204a557029df4fe45481f199111c7a1538ac924ef'),
    (0x13b60fc, 0x100, 'f7cfa9f1da389b24db9a0cf74471eb48b57e4d7498acf060385a86e1de89c104'),
    (0x4224df4, 0xb8, '9e9d5381d5335197964cbd8d9f9d63948af46a575c64dc8be1d4400b2861173e'),
    (0x4266804, 0x388, '1c156b986c2bbc5567f997fa95f5b9641cebd52c4fc03879a2efad3225b4ef5e'),
    (0xd09bd0, 0x178, '0b25b581e88d61961e1420339d45cac9808c614037c6e14ff64f38d8cac580e5'),
    (0x9abf4, 0x9c, 'ee7ae4e072160bb054bd848e70ff625625352de6998ba71dbef6427f48e08d85'),
    (0x154d890, 0x330, 'cfb175fab06b9bb87b834698c01edd495d35196d331576a37de0a13bd9cd541c'),
    (0x42e9b44, 0xa8, 'e9e63096527a04ff3a26c89f46bb7d088e08981a3d7851bad49a813827c4ba85'),
    (0x52de700, 0x60, '7485c51d4228eeffe8ce8e01f5aff80bf302b869c975e67c4385ec4d678be237'),
)


def _read(read, at, size):
    raw = read(at, size)
    if type(raw) is not bytes or len(raw) != size:
        raise ValueError('Incomplete UCL registration source read')
    return raw


def _pointer(read, at):
    value = struct.unpack('<Q', _read(read, at, 8))[0]
    if value and (value < 4096 or value % 8):
        raise ValueError('Invalid UCL registration source pointer')
    return value


def verify_native(read, base):
    for rva, size, digest in NATIVE_GUARDS:
        if hashlib.sha256(_read(read, base+rva, size)).hexdigest() != digest:
            raise ValueError(f'UCL registration native layout changed at {rva:#x}')


def rule_context(read, base, runtime, rule_index=-1):
    """Mirror3AA5A14(runtime, TEAM, index, -1)'s direct kind21 subset.

    The TEAM argument is unused on this subset. Index255 triggers native state
    writes and is deliberately unsupported. Selector8's property postfilter is
    supported only when the rule's explicit bypass bit is present.
    """
    if type(rule_index) is not int or not -1 <= rule_index < 128:
        raise ValueError('Invalid UCL native rule index')
    result = dict(state='unavailable', reason=None, native_rule_index=None,
                  native_selector=None, requirement_codes=None,
                  registration_verdict=None, age_exempt=None,
                  fixture_phase_evaluated=False, full_eligibility_evaluated=False)
    competition_stages.typed(read, base, runtime,
                            (0x566C2B8, b'N7sicomps11ACTUAL_COMPE'))
    if _read(read, runtime+0x3BE, 1) != b'\x15':
        result['reason'] = 'unsupported_ucl_runtime_kind'
        return result, None
    if _read(read, runtime+0x4C, 1)[0] & 8:
        result['reason'] = 'unsupported_team_rule_override'
        return result, None
    parent = _pointer(read, runtime+0x138)
    if not parent or struct.unpack('<i', _read(read, parent+12, 4))[0] != 1301394:
        result['reason'] = 'not_ucl_runtime_owner'
        return result, None
    owner = _pointer(read, runtime+0x388)
    bank = _pointer(read, owner+0x1F0) if owner else 0
    if not bank:
        result['reason'] = 'native_rule_bank_absent'
        return result, None
    current = _read(read, runtime+0x49, 1)[0]
    if current == 255:
        result['reason'] = 'unsupported_mutating_rule_index_initialization'
        return result, None
    index = current if rule_index == -1 else rule_index
    rules, _ = competition_stages.vector(read, bank+0x60, 256)
    if index >= 128 or index >= len(rules) or not rules[index]:
        result['reason'] = 'native_rule_slot_absent'
        return result, None
    rule = rules[index]
    selector = struct.unpack('<b', _read(read, rule+0x125, 1))[0]
    if selector == 8 and not _read(read, rule+0x12C, 1)[0] & 1:
        result['reason'] = 'unsupported_selector8_property_postfilter'
        return result, None
    requirement = _pointer(read, rule+0x70)
    codes = None
    if requirement:
        count = _read(read, requirement+0x18, 1)[0]
        if count > 64:
            raise ValueError('UCL requirement vector exceeds bounded limit')
        codes = list(_read(read, requirement+0x19, count)) if count else []
    result.update(state='available', reason='native_ucl_rule_operands',
                  native_rule_index=index, native_selector=selector,
                  native_rule_competition_id=struct.unpack('<i', _read(read, rule+0x108, 4))[0],
                  native_restriction_mask=struct.unpack('<Q', _read(read, rule+0xE8, 8))[0],
                  native_secondary_selector=_read(read, rule+0xF1, 1)[0],
                  native_flags_f2=_read(read, rule+0xF2, 1)[0],
                  requirement_codes=codes)
    return result, dict(rule_address=rule, requirement_address=requirement,
                        selector=selector & 255)


def marker(read, primary, record_kind, team, binding):
    """Keep the exact selected-rule marker as a fact; false is not exclusion."""
    if binding is None:
        return dict(source_state='ucl_rule_context_unavailable',
                    registration_verdict=None, age_exempt=None)
    return player_registration_source.project(
        read, primary, record_kind, team, binding['selector'])


def _date(raw):
    from datetime import date, timedelta
    day, year = struct.unpack('<HH', raw)
    day &= 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid native UCL registration date')
    value = date(year, 1, 1)+timedelta(days=day-1)
    if value.year != year:
        raise ValueError('Invalid native UCL registration day')
    return value


def _phase_index(read, base, runtime, fixture, competition):
    """The original direct-index and ordinary LEAGUE_STAGE phase routes only."""
    from . import fixtures
    fixtures.typed(read, base, fixture, 'fixture')
    direct = struct.unpack('<b', _read(read, fixture+0x54, 1))[0]
    if direct != -1:
        return (direct, 'fixture_direct_rule') if 0 <= direct < 128 else (None, 'unsupported_fixture_rule_index')
    index = struct.unpack('<b', _read(read, fixture+0x38, 1))[0]
    stages, _ = competition_stages.vector(read, runtime+0x1D8, 256)
    if not 0 <= index < len(stages) or not stages[index]:
        return None, 'fixture_stage_absent'
    stage = stages[index]
    table = _pointer(read, stage)
    if table != base+competition_stages.STAGE_TYPES['league'][0]:
        return None, 'unsupported_fixture_registration_stage'
    competition_stages.typed(read, base, stage, competition_stages.STAGE_TYPES['league'])
    if _pointer(read, stage+0x70) != competition:
        raise ValueError('Fixture registration stage owner changed')
    for slot, function in ((0x2F8, 0x3F22F98), (0x2D8, 0x3B8C0A0),
                           (0x2C8, 0x3F22F90), (0x3E0, 0x3F23068)):
        if struct.unpack('<Q', _read(read, table+slot, 8))[0] != base+function:
            raise ValueError('Fixture registration phase dispatch changed')
    settings = _pointer(read, stage+0xF0)
    if not settings:
        return None, 'fixture_league_settings_absent'
    competition_stages.typed(read, base, settings, competition_stages.SETTINGS)
    phase = struct.unpack('<b', _read(read, settings+0x175, 1))[0]
    return (phase, 'fixture_league_settings') if -1 <= phase < 128 else (None, 'unsupported_league_rule_index')


def fixture_context(read, base, coach, fixture, decoded, current_date):
    """Bind current UCL selector0 to its actual fixture phase and getter context.

    The caller owns canonical fixture discovery and final consumed-byte/process
    verification. The native getter itself consults TEAM's current division in
    D2DCB8; that prerequisite never supplies the UCL selector or marker.
    """
    from datetime import date
    from . import world
    verify_native(read, base)
    player_registration_source.verify_native(read, base)
    public = dict(state='unavailable', reason=None, competition=decoded['competition'],
                  native_selector=None, native_season_code=None, requirement_codes=None,
                  current_read_date=current_date,
                  future_condition='currently_recorded_registration_and_exemption_inputs_unchanged',
                  fixture_phase_evaluated=False, full_eligibility_evaluated=False)
    if decoded['kind'] != 'fixture':
        public['reason'] = 'unsupported_score_bearing_fixture'
        return public, None
    comp = decoded['competition']
    if not comp or comp['native_id'] != 1301394:
        public['reason'] = 'unsupported_registration_competition'
        return public, None
    current = date.fromisoformat(current_date)
    if _date(_read(read, base+world.CURRENT_DATE, 4)) != current:
        raise ValueError('Current registration date changed')
    public['fixture_date'] = _date(_read(read, fixture+0x4C, 4)).isoformat()
    if public['fixture_date'] < current_date:
        public['reason'] = 'past_fixture_current_state_only'
        return public, None
    saved = dict(address=decoded['competition_address'], database_index=comp['database_index'],
                 native_id=comp['native_id'], random_id=comp['random_id'])
    runtime_source, runtime, _ = competition_stages.runtime_context(read, base, saved)
    public['native_season_code'] = runtime_source['native_season_code']
    if not runtime or runtime_source['shared_runtime']:
        public['reason'] = 'unsupported_absent_or_shared_ucl_runtime'
        return public, None
    if decoded['season_code'] != runtime_source['native_season_code']:
        public['reason'] = 'fixture_registration_season_mismatch'
        return public, None
    if coach['team_address'] not in decoded['teams']:
        public['reason'] = 'managed_team_outside_fixture'
        return public, None
    phase, route = _phase_index(read, base, runtime, fixture, decoded['competition_address'])
    if phase is None:
        public['reason'] = route
        return public, None
    rule, rule_binding = rule_context(read, base, runtime, phase)
    if rule_binding is None:
        public['reason'] = rule['reason']
        return public, None
    public.update(rule, competition=comp, native_season_code=runtime_source['native_season_code'],
                  fixture_phase_evaluated=True, native_phase_source=route)
    if (rule['native_selector'] != 0 or rule['requirement_codes'] != [14, 26]
            or rule['native_restriction_mask'] or rule['native_secondary_selector'] != 0
            or rule['native_flags_f2'] != 1):
        public.update(state='unavailable', reason='unsupported_ucl_registration_rule')
        return public, None
    getter_source, getter_binding = player_registration_source.current_league_context(
        read, base, coach, current_date)
    if getter_binding is None:
        public.update(state='unavailable', reason='native_getter_prerequisite_'+getter_source['reason'])
        return public, None
    public.update(state='available', reason='native_current_ucl_registration_context')
    return public, dict(getter_binding, selector=0, ucl_rule_address=rule_binding['rule_address'],
                        current_date=current_date, ucl_competition_native_id=1301394,
                        ucl_requirement_codes=(14,26))


CONTRACT_GETTERS = {89766392: 14205904, 89832808: 19529724, 89871592: 20414904, 89787688: 16804676}


def registered(read, primary, record_kind, binding):
    """Current exact UCL mode1 predicate; a false result is not an exclusion."""
    if binding is not None and (binding.get('selector') != 0
            or binding.get('ucl_competition_native_id') != 1301394):
        return dict(source_state='unavailable', reason='unverified_ucl_registration_context',
                    native_predicate_result=None, marker=None,
                    complete_submitted_population_evaluated=False, fixture_eligibility_evaluated=False)
    result = player_registration_source.current_predicate(read, primary, record_kind, binding)
    if binding is None or record_kind != 'actual' or result['source_state'] != 'available':
        return result
    contract = _pointer(read, primary+0x2F0)
    if contract:
        table = _pointer(read, contract)
        expected = CONTRACT_GETTERS.get(table-binding['base'])
        getter = struct.unpack('<Q', _read(read, table+0x90, 8))[0] if expected else None
        if expected is None or getter != binding['base']+expected:
            result.update(source_state='unavailable', reason='unsupported_contract_registration_getter',
                          native_predicate_result=None)
    return result


def _cutoff14(read, base, club):
    """Normal male nation runtime, cached date-spec, default template year only."""
    from datetime import date, timedelta
    from . import world
    if _read(read, base+0x56D34E0, 1) != b'\x01':
        return None, 'unsupported_nation_runtime_lookup'
    nation = _pointer(read, club+0xD8)
    if not nation:
        return None, 'nation_cutoff_context_absent'
    world.typed(read, base, nation, 'nation')
    runtime = _pointer(read, nation+0x128)
    season = _pointer(read, runtime+0x38) if runtime else 0
    bank = _pointer(read, season+0x1F0) if season else 0
    context = _pointer(read, bank+0x78) if bank else 0
    template = _pointer(read, context+0x1B8) if context else 0
    if not template or not _pointer(read, template+0x1F8):
        return None, 'unsupported_nation_cutoff_fallback'
    year = struct.unpack('<H', _read(read, template+0x234, 2))[0]
    previous = _pointer(read, template+0x1F0)
    if previous and struct.unpack('<H', _read(read, previous+4, 2))[0]-1 == year:
        return None, 'unsupported_cutoff_template_transition'
    settings = _pointer(read, base+0x56A49F8)
    if not settings:
        return None, 'cutoff_global_settings_absent'
    mode = _read(read, settings+0x80B, 1)[0]
    if mode == 1:
        if not previous:
            return None, 'cutoff_previous_template_absent'
        year = struct.unpack('<H', _read(read, previous+4, 2))[0]
    else:
        year += _read(read, template+0x240, 1)[0]
    cached = struct.unpack('<h', _read(read, context+0x1DE, 2))[0]
    month, offset = struct.unpack('<bb', _read(read, context+0x1F1, 2))
    year += offset
    # Larger/uninitialized date-spec cases use other native branches or write
    # a cache. The ordinary1..28 case is exact without leap-day normalization.
    if not 1 <= cached <= 28 or not 1 <= month <= 12 or not 2001 <= year <= 2099:
        return None, 'unsupported_cached_cutoff_date_spec'
    return (date(year, month, cached)-timedelta(days=1)).isoformat(), None


def _unaliased_club(read, club):
    if _read(read, club+0x163, 1)[0] & 16:
        return club
    affiliates, _ = competition_stages.vector(read, club+0x118, 128)
    return None if affiliates else club


def _club_days14(read, base, primary, club):
    from . import teams
    target = _unaliased_club(read, club)
    if target is None:
        return None, 'unsupported_club_affiliation_mapping'
    holder = _pointer(read, primary+0x2C0)
    if not holder:
        return 0, None
    history, _ = competition_stages.vector(read, holder+0x30, 512, entry_alignment=4)
    total = largest = 0
    for entry in history:
        if not entry:
            raise ValueError('Null native UCL club-history entry')
        raw = _read(read, entry, 16)
        if raw[11] & 1:
            return None, 'unsupported_club_history_index_transport'
        team = struct.unpack_from('<Q', raw)[0]
        if not team:
            continue
        if team < 4096 or team % 8:
            raise ValueError('Invalid native club-history TEAM pointer')
        kind = _read(read, team+0x2F, 1)[0]
        if kind == 1:
            continue
        if kind != 0:
            return None, 'unsupported_club_history_team_kind'
        index = struct.unpack('<I', _read(read, team+8, 4))[0]
        _, binding = teams.by_index(read, base, index)
        if binding['address'] != team:
            raise ValueError('Native club-history TEAM membership changed')
        owner = _pointer(read, team+0x30)
        if not owner:
            continue
        actual = _unaliased_club(read, owner)
        if actual is None:
            return None, 'unsupported_club_history_affiliation_mapping'
        if actual != target:
            continue
        days = struct.unpack_from('<h', raw, 8)[0]
        if raw[11] & 0xF6:
            largest = max(largest, days)
        else:
            total += days
    return max(total, largest), None


def requirement14(read, primary, record_kind, binding):
    """Native UCL requirement14 only: age/cutoff plus club-history days>730.

    A false first requirement does not evaluate requirement26. A positive first
    requirement is kept separate from current registration and full eligibility.
    """
    from . import league_age_exemptions, players, teams, world
    result = dict(state='unavailable', reason='ucl_registration_context_unavailable',
                  native_requirement14=None, registration_exempt=None, current_age=None,
                  age_at_cutoff=None, cutoff_date=None, native_club_history_days=None,
                  requirement26_evaluated=False, full_eligibility_evaluated=False)
    if binding is None:
        return result
    if (binding.get('selector') != 0 or binding.get('ucl_competition_native_id') != 1301394
            or binding.get('ucl_requirement_codes') != (14,26)):
        result['reason'] = 'unverified_ucl_requirement_context'
        return result
    if record_kind != 'actual':
        result['reason'] = 'unsupported_record_kind'
        return result
    base, club, current_date = (binding[k] for k in ('base', 'club_address', 'current_date'))
    person = primary+0x388
    table = _pointer(read, person)
    if (_pointer(read, primary) != base+players.RVA[0] or table != base+players.RVA[2]
            or struct.unpack('<Q', _read(read, table+0x138, 8))[0] != base+0x148F4C0
            or struct.unpack('<Q', _read(read, table+0x1B8, 8))[0] != base+0xCA4640
            or struct.unpack('<Q', _read(read, table+0x570, 8))[0] != base+0xCC83D4):
        raise ValueError('UCL requirement14 PLAYER dispatch changed')
    if (person+struct.unpack('<q', _read(read, table-0x1C8, 8))[0]+0x58 != primary+0x2D0
            or person+struct.unpack('<q', _read(read, table-0x580, 8))[0] != primary+0x278):
        raise ValueError('UCL requirement14 PLAYER virtual-base displacement changed')
    current = _pointer(read, primary+0x128)
    if (not current or _read(read, current+0x2F, 1) != b'\0'
            or _pointer(read, current+0x30) != club):
        result['reason'] = 'player_current_team_outside_target_club'
        return result
    index = struct.unpack('<I', _read(read, current+8, 4))[0]
    _, current_binding = teams.by_index(read, base, index)
    if current_binding['address'] != current or current_binding['owner_address'] != club:
        raise ValueError('UCL requirement14 current TEAM membership changed')
    if int.from_bytes(_read(read, person+0x18, 8), 'little') & (1 << 12):
        result['reason'] = 'unsupported_player_age_calendar'
        return result
    if _date(_read(read, base+world.CURRENT_DATE, 4)).isoformat() != current_date:
        raise ValueError('UCL requirement14 current date changed')
    born = _date(_read(read, primary+0x2D0, 4)).isoformat()
    age = league_age_exemptions.native_age(born, current_date)
    result['current_age'] = age
    if age is None:
        result['reason'] = 'native_current_age_unavailable'
        return result
    if age >= 24:
        result.update(state='available', reason='native_ucl_requirement14_age_limit', native_requirement14=False)
        return result
    if age >= 20:
        cutoff, reason = _cutoff14(read, base, club)
        if cutoff is None:
            result['reason'] = reason
            return result
        cutoff_age = league_age_exemptions.native_age(born, cutoff)
        result.update(cutoff_date=cutoff, age_at_cutoff=cutoff_age)
        if cutoff_age is None:
            result['reason'] = 'native_cutoff_age_unavailable'
            return result
        if cutoff_age > 20:
            result.update(state='available', reason='native_ucl_requirement14_cutoff_age_limit', native_requirement14=False)
            return result
    days, reason = _club_days14(read, base, primary, club)
    result['native_club_history_days'] = days
    if days is None:
        result['reason'] = reason
        return result
    value = days > 730
    result.update(state='available', reason='native_ucl_requirement14', native_requirement14=value,
                  registration_exempt=True if value else None)
    return result
