"""Build-pinned resident fixture buckets; never materialize archived groups."""
from datetime import date, timedelta
import struct

from . import competition_stages, competitions, database, players, stage_names, stadiums, teams, world

TYPES = {
    'root': (0x55DD068, b'23GAME_RULE_GROUP_MANAGER'),
    'store': (0x55DC600, b'17GAME_COMP_MANAGER'),
    'fixture': (0x5672C88, b'N7sicomps7FIXTUREE'),
    'result': (0x5672E00, b'N7sicomps14FIXTURE_RESULTE'),
    'name': (0x55AB970, b'N2db12FIXTURE_NAMEE'),
}
SCOPE = ('Existing materialized fixture groups only; unloaded groups and missing years are unavailable, '
         'not empty. Calendar years are not competition seasons. No lazy loads or native function calls. '
         'Result-record presence does not prove match completion. Scores preserve stored normal-time, '
         'extra-time, penalty and aggregate values; final_score follows extra-time then normal-time fallback '
         'and excludes penalties. Kickoff time is the native stored clock time with no verified timezone; '
         'zero, unset-date and unmapped time codes remain explicit, not midnight. '
         'days_from_current_date is a calendar-day difference from the response save.current_date, '
         'not a completion or kickoff-countdown status. Half-time scores, match events '
         'and complete archived history/future scheduling remain undecoded. Competition is the stored '
         'fixture-name link. fixture_name preserves three stored stage-name slots and a secondary competition, without generated/localized formatting or fixed stage/round/leg semantics. Optional stage_link resolves top-level runtime stages '
         'only when the native fixture/runtime season codes match; unavailable links remain explicit. '
         'It does not identify group children or reconstruct historical stages. Stored name components do not prove runtime-stage membership. Null opponents and stadiums remain explicit. Stadium references expose the stored venue, not suitability or final match location. '
         'Order is calendar day, native group, native slot; same-day order is not kickoff order. '
         'Continue every next_cursor with identical selectors, including after empty pages. '
         'Reads are non-atomic within/across pages, with consumed-byte rechecks; references expire '
         'after detach, save/build, cache eviction, route or record identity changes. An empty filtered result does not '
         'establish absence from the full save.')


def typed(read, base, address, kind):
    competition_stages.typed(read, base, address, TYPES[kind])


def kickoff_time(packed):
    """Decode the fdte time bits used by the native fixture kickoff formatter."""
    code = (packed >> 9) & 127
    clock, state = None, 'unmapped_time_code'
    if packed >> 16 == 1900 and packed & 511 == 1:
        state = 'unset_date'
    elif code == 0:
        state = 'no_time_code'
    elif code == 127:
        clock, state = '17:55', 'decoded'
    elif 1 <= code <= 72:
        minutes = 360 + (code-1)*15
        clock, state = f'{minutes//60:02d}:{minutes%60:02d}', 'decoded'
    return {'time': clock, 'state': state, 'native_code': code, 'timezone': None}


def catalog(read, base):
    root = world.pointer(read, base+0x56D57D0)
    typed(read, base, root, 'root')
    store = world.pointer(read, root+0x158)
    typed(read, base, store, 'store')
    main = store+8
    pending = [('main', main)]
    links = []
    for offset, label in ((0, 'linked'), (8, 'archived')):
        header = players.u64(read(main+offset, 8))
        entries = world.vector(read, header, 100) if header else ()
        links.append((header, entries))
        pending.extend((label, address) for address in entries)
    rows, bindings, seen = [], {}, set()
    for source, address in pending:
        year = int.from_bytes(read(address+0x40, 2), 'little')
        if not 1 <= year <= 9999 or year in bindings or address in seen:
            raise ValueError('Invalid or ambiguous resident fixture year')
        seen.add(address)
        groups = world.vector(read, address+0x10, 1024)
        flags = tuple(read(group+0xB70, 1)[0] for group in groups)
        unloaded = [i for i, flag in enumerate(flags) if not flag & 1]
        row = {'year': year, 'source': source, 'group_count': len(groups),
               'loaded_group_count': len(groups)-len(unloaded),
               'unavailable_group_indices': unloaded,
               'all_groups_materialized': not unloaded}
        rows.append(row)
        bindings[year] = {'address': address, 'groups': groups, 'flags': flags, 'coverage': row}
    identity = (root, store, tuple(links), tuple(
        (row['year'], bindings[row['year']]['address'], bindings[row['year']]['groups'],
         bindings[row['year']]['flags']) for row in rows))
    return {'main_year': rows[0]['year'], 'years': rows}, bindings, identity


def date_bounds(year, date_from, date_to):
    start, end = date(year, 1, 1), date(year, 12, 31)
    parsed = []
    for value, default in ((date_from, start), (date_to, end)):
        if value is None:
            parsed.append(default)
            continue
        if not isinstance(value, str):
            raise ValueError('Fixture dates must use YYYY-MM-DD')
        try:
            d = date.fromisoformat(value)
        except ValueError as exc:
            raise ValueError('Fixture dates must use YYYY-MM-DD') from exc
        if d.isoformat() != value or d.year != year:
            raise ValueError('Fixture dates must be YYYY-MM-DD within the selected calendar year')
        parsed.append(d)
    if parsed[0] > parsed[1]:
        raise ValueError('Fixture date_from must not follow date_to')
    return tuple((d-start).days+1 for d in parsed)


def bucket(read, binding, day, group):
    address = binding['groups'][group]
    if not binding['flags'][group] & 1:
        return (), None
    header = players.u64(read(address+(day-1)*8, 8))
    if not header:
        return (), None
    entries = world.vector(read, header, 2000)
    return entries, (header, struct.unpack('<QQQ', read(header, 24)), entries)


def record(read, base, address, year, day, cache, *, selector_prefilter=None, ordered_team_addresses=None):
    raw = read(address, 0x58)
    vtable = players.u64(raw)-base
    kind = next((k for k in ('fixture', 'result') if vtable == TYPES[k][0]), None)
    if kind is None:
        raise ValueError('Unsupported fixture record type')
    type_key = ('fixture_type_proof', kind)
    if (not selector_prefilter and ordered_team_addresses is None) or type_key not in cache:
        typed(read, base, address, kind)
        cache[type_key] = True
    packed = struct.unpack_from('<I', raw, 0x4C)[0]
    if packed >> 16 != year or packed & 511 != day:
        raise ValueError('Fixture date disagrees with its calendar bucket')
    if selector_prefilter and selector_prefilter[2] is not None and kind != selector_prefilter[2]:
        return {'filter_match': False}
    team_addresses = (players.u64(raw, 8), players.u64(raw, 16))
    if ordered_team_addresses is not None and team_addresses != ordered_team_addresses:
        return {'filter_match': False}
    team_ids = []
    for team in team_addresses:
        if not team:
            team_ids.append(None)
            continue
        key = ('team_identity', team)
        if key not in cache:
            data = read(team, 20)
            index, native_id = struct.unpack_from('<II', data, 8)
            info = database.table(read, base, 'teams')
            if not native_id or index >= info['count'] or world.pointer(read, info['start']+index*8) != team:
                raise ValueError('Fixture team membership changed')
            team_kind = 'team' if players.u64(data) == base+world.TYPES['team'][0] else 'national_team'
            world.typed(read, base, team, team_kind)
            cache[key] = (index, native_id)
        team_ids.append(cache[key])
    if selector_prefilter and selector_prefilter[0] is not None and not any(t and t[1] == selector_prefilter[0] for t in team_ids):
        return {'filter_match': False}
    name = players.u64(raw, 0x20)
    competition = competition_address = None
    name_identity = None
    if name:
        key = ('fixture_name', name)
        if key not in cache:
            typed(read, base, name, 'name')
            data = read(name+8, 64)
            index, native_id, random_id = struct.unpack_from('<III', data)
            info = database.table(read, base, 'fixture_names')
            if index >= info['count'] or world.pointer(read, info['start']+index*8) != name:
                raise ValueError('Fixture-name membership changed')
            comp = players.u64(data, 16)
            linked = None
            if comp:
                comp_index = int.from_bytes(read(comp+8, 4), 'little')
                linked = competitions.by_index(read, base, comp_index)
                comp_info = database.table(read, base, 'competitions')
                if world.pointer(read, comp_info['start']+comp_index*8) != comp:
                    raise ValueError('Fixture competition membership changed')
            components = struct.unpack_from('<QQQ', data, 24)
            secondary_comp = players.u64(data, 56)
            cache[key] = ((name, index, native_id, random_id, components, secondary_comp), comp, linked)
        name_identity, competition_address, competition = cache[key]
    if selector_prefilter and selector_prefilter[1] is not None and (competition is None or competition['native_id'] != selector_prefilter[1]):
        return {'filter_match': False}
    stadium = players.u64(raw, 0x28)
    stadium_binding = None
    if stadium:
        key = ('stadium_identity', stadium)
        if key not in cache:
            cache[key] = stadiums.identity(read, base, stadium)
        stadium_binding = cache[key]
    identity = (address, raw, tuple(team_ids), name_identity,
                tuple(stadium_binding.values()) if stadium_binding else None, competition_address,
                None if competition is None else (competition['database_index'], competition['native_id']))
    return {'kind': kind, 'teams': team_addresses, 'team_ids': team_ids,
            'kickoff_time': kickoff_time(packed),
            'season_code': struct.unpack_from('<H', raw, 0x30)[0],
            'stage_index': struct.unpack_from('<b', raw, 0x38)[0],
            'name_identity': name_identity, 'stadium_binding': stadium_binding,
            'competition': competition, 'competition_address': competition_address,
            'identity': identity}


def name_details(read, base, decoded, cache):
    identity = decoded['name_identity']
    if identity is None:
        return None
    key = ('fixture_name_details', identity)
    if key not in cache:
        _, index, native_id, _, pointers, secondary = identity
        components = []
        for address in pointers:
            if not address:
                components.append(None)
                continue
            stage_key = ('stage_name', address)
            if stage_key not in cache:
                cache[stage_key] = stage_names.record(read, base, address)
            components.append(cache[stage_key])
        competition = None
        if secondary:
            if secondary < 4096 or secondary % 8:
                raise ValueError('Invalid secondary fixture competition pointer')
            secondary_index = int.from_bytes(read(secondary+8, 4), 'little')
            competition = competitions.by_index(read, base, secondary_index)
            info = database.table(read, base, 'competitions')
            if world.pointer(read, info['start']+secondary_index*8) != secondary:
                raise ValueError('Secondary fixture competition membership changed')
        cache[key] = {'database_index': index, 'native_id': native_id,
                      'stage_names': components, 'secondary_competition': competition,
                      'name_source': 'stored_native_components'}
    return cache[key]


def stage_link(read, base, decoded, cache):
    result = {'state': 'no_competition', 'fixture_season_code': decoded['season_code'],
              'runtime_season_code': None, 'native_stage_index': decoded['stage_index'],
              'runtime_competition': None, 'shared_runtime': False, 'stage': None}
    comp = decoded['competition']
    if comp is None:
        return result, None
    saved = {'address': decoded['competition_address'], 'database_index': comp['database_index'],
             'native_id': comp['native_id']}
    key = ('stage_runtime', saved['address'])
    if key not in cache:
        cache[key] = competition_stages.runtime_context(read, base, saved)
    context, runtime, _ = cache[key]
    result.update(runtime_season_code=context['native_season_code'],
                  runtime_competition=context['runtime_competition'], shared_runtime=context['shared_runtime'])
    if runtime is None:
        return {**result, 'state': 'runtime_absent'}, None
    if decoded['season_code'] != context['native_season_code']:
        return {**result, 'state': 'different_season'}, None
    if decoded['stage_index'] < 0:
        return {**result, 'state': 'unassigned_stage'}, None
    key = ('stage_catalog', saved['address'])
    if key not in cache:
        cache[key] = competition_stages.catalog(read, base, saved)[1]
    match = next((entry for entry in cache[key] if entry[0]['path'] == [decoded['stage_index']]), None)
    if match is None:
        return {**result, 'state': 'stage_index_out_of_range'}, None
    row, binding = match
    if binding is None:
        return {**result, 'state': 'null_stage_slot'}, None
    if row['kind'] == 'empty':
        return {**result, 'state': 'empty_stage'}, None
    return {**result, 'state': 'decoded', 'stage': row}, binding


def detail(read, base, address, year, day, decoded, cache, include_stage=False):
    linked_teams, bindings = [], []
    for team, identity in zip(decoded['teams'], decoded['team_ids']):
        if team is None or not team:
            linked_teams.append(None)
            bindings.append(None)
            continue
        key = ('team', team)
        if key not in cache:
            row, binding = teams.by_index(read, base, identity[0])
            if binding['address'] != team or row['native_id'] != identity[1]:
                raise ValueError('Fixture team identity changed')
            cache[key] = (row, binding)
        row, binding = cache[key]
        linked_teams.append(row)
        bindings.append(binding)
    scores = None
    if decoded['kind'] == 'result':
        raw = read(address+0x64, 10)
        scores = {}
        for offset, label in enumerate(('normal_time', 'extra_time', 'penalties', 'aggregate')):
            pair = [None if raw[start+offset] == 255 else raw[start+offset] for start in (0, 5)]
            scores[label] = dict(zip(('home', 'away'), pair))
        scores['final_score'] = {side: scores['extra_time'][side] if scores['extra_time'][side] is not None
                                else scores['normal_time'][side] for side in ('home', 'away')}
    row = {'date': (date(year, 1, 1)+timedelta(days=day-1)).isoformat(),
           'kickoff_time': decoded['kickoff_time'],
           'record_kind': decoded['kind']+'_record', 'home_team': linked_teams[0],
           'away_team': linked_teams[1], 'competition': decoded['competition'], 'scores': scores,
           'fixture_name': name_details(read, base, decoded, cache), 'stadium': None}
    if decoded['stadium_binding'] is not None:
        stadium = decoded['stadium_binding']['address']
        key = ('stadium_summary', stadium)
        if key not in cache:
            cache[key] = stadiums.record(read, base, stadium)[0]
        row['stadium'] = cache[key]
    stage_binding = None
    if include_stage:
        row['stage_link'], stage_binding = stage_link(read, base, decoded, cache)
    return row, bindings, stage_binding


def scan(read, base, binding, year, bounds, team_id, competition_id, record_kind,
         position, bucket_identity, max_matches, record_budget, bucket_budget, include_stage=False, selector_prefilter=False):
    day, group, slot = position
    group_count = len(binding['groups'])
    pending, cache, scanned, buckets = [], {}, 0, 0
    next_bucket_identity = None
    while day <= bounds[1] and group_count:
        if group >= group_count:
            day, group, slot = day+1, 0, 0
            continue
        if buckets >= bucket_budget or scanned >= record_budget or len(pending) >= max_matches:
            break
        entries, route = bucket(read, binding, day, group)
        buckets += 1
        if slot and route != bucket_identity:
            raise ValueError('Fixture cursor bucket changed; repeat the query')
        if slot > len(entries):
            raise ValueError('Fixture cursor is outside its bucket')
        while slot < len(entries):
            address = entries[slot]
            decoded = record(read, base, address, year, day, cache,
                             selector_prefilter=(team_id, competition_id, record_kind) if selector_prefilter else None)
            current_slot = slot
            slot += 1
            scanned += 1
            matches = (decoded.get('filter_match') is not False and (team_id is None or any(t and t[1] == team_id for t in decoded['team_ids']))
                       and (competition_id is None or decoded['competition'] is not None
                            and decoded['competition']['native_id'] == competition_id)
                       and (record_kind is None or decoded['kind'] == record_kind))
            if matches:
                row, team_bindings, stage_binding = detail(read, base, address, year, day, decoded, cache, include_stage)
                saved = {'year': year, 'day': day, 'group': group, 'slot': current_slot,
                         'group_address': binding['groups'][group], 'route': route,
                         'identity': decoded['identity'], 'address': address}
                pending.append((row, team_bindings, decoded['competition_address'], stage_binding, decoded['stadium_binding'], saved))
            if scanned >= record_budget or len(pending) >= max_matches:
                break
        if slot < len(entries):
            next_bucket_identity = route
            break
        group, slot, bucket_identity = group+1, 0, None
    if group >= group_count and group_count:
        day, group, slot = day+1, 0, 0
    finished = day > bounds[1] or not group_count
    return pending, {
        'position': (day, group, slot), 'bucket_identity': next_bucket_identity,
        'scanned_records': scanned, 'examined_buckets': buckets, 'finished': finished,
        'stop_reason': 'resident_range_end' if finished else 'match_limit' if len(pending) >= max_matches
                       else 'record_budget' if scanned >= record_budget else 'bucket_budget',
    }
