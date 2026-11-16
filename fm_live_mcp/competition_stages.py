"""Build-pinned runtime stages and native stored league tables."""
import struct

from . import competitions, database, players, teams, world

RUNTIME_TYPES = {
    0x566C2B8: b'N7sicomps11ACTUAL_COMPE',
    0x5673998: b'N7sicomps13FRIENDLY_COMPE',
    0x566D458: b'N7sicomps12UNDER_X_COMPE',
    0x56946E8: b'N7sicomps22WWCLUB_WORLD_CHAMP_CUPE',
    0x5679940: b'N7sicomps18RESERVE_CHILD_COMPE',
    0x56944E0: b'N7sicomps20WWCLUB_VIAREGGIO_CUPE',
    0x5679D50: b'N7sicomps19RESERVE_PARENT_COMPE',
    0x56736A8: b'N7sicomps20FRIENDLY_ACTUAL_COMPE',
}
STAGE_TYPES = {
    'league': (0x56759F8, b'N7sicomps12LEAGUE_STAGEE'),
    'group': (0x5673FE0, b'N7sicomps11GROUP_STAGEE'),
    'cup': (0x5671128, b'N7sicomps9CUP_STAGEE'),
    'empty': (0x567A6A0, b'N7sicomps11EMPTY_STAGEE'),
    'cup_group': (0x5670D60, b'N7sicomps15CUP_GROUP_STAGEE'),
}
SETTINGS = (0x5675F28, b'N7sicomps15LEAGUE_SETTINGSE')
MAX_STAGES = 1024
SCOPE = ('Stored runtime stages and league tables, including league children of group stages. '
         'Competitions may share a runtime owner; runtime_competition identifies that owner. '
         'Stage paths are zero-based vector slots, not named rounds or seasons. Null stage/team slots remain explicit. '
         'native_season_code is a stored discriminator, not a decoded season date range. '
         'Cup, cup-group contents, localized stage names, season dates and active/completed status '
         'are not decoded. An absent runtime or empty vector does not prove no competition or participants. '
         'Reads are non-atomic with consumed-byte rechecks; references expire after save/build, season-code or membership changes.')
TABLE_SCOPE = (SCOPE + ' Table order is the native stored order, not a recomputed ranking or proof of freshness. '
               'Played includes games carried from other stages. Wins/losses exclude penalty decisions; '
               'draws_or_penalty_wins combines ordinary draws and penalty wins, while penalty_losses is separate. '
               'Points are stored totals, including native adjustments; do not recompute them from results. '
               'Home/away statistics share the overall table order and are not separate rankings.')


def typed(read, base, address, expected):
    rva, name = expected
    table = base + rva
    if world.pointer(read, address) != table:
        raise ValueError('Unexpected runtime competition or stage type')
    metadata = read(table-16, 16)
    if struct.unpack_from('<q', metadata)[0] != 0:
        raise ValueError('Unexpected runtime type displacement')
    info = players.u64(metadata, 8)
    text = players.u64(read(info+8, 8))
    if text < 4096 or read(text, len(name)+1) != name+b'\0':
        raise ValueError('Unexpected runtime type RTTI')


def vector(read, address, limit, *, entry_alignment=8):
    header = struct.unpack('<QQQ', read(address, 24))
    start, end, capacity = header
    if header == (0, 0, 0):
        return (), header
    if (start < 4096 or any(p % 8 for p in header) or not start <= end <= capacity
            or capacity-start > limit*8):
        raise ValueError('Invalid runtime stage vector bounds')
    # Native stage vectors can contain nulls and repeated objects.
    entries = tuple(v for (v,) in struct.iter_unpack('<Q', read(start, end-start))) if end > start else ()
    if any(v and (v < 4096 or v % entry_alignment) for v in entries):
        raise ValueError('Invalid runtime stage vector pointer')
    return entries, header


def runtime_context(read, base, saved):
    info = database.table(read, base, 'competitions')
    competition = competitions.by_index(read, base, saved['database_index'], include_context=True)
    address = world.pointer(read, info['start'] + saved['database_index']*8)
    if address != saved['address'] or (competition['native_id'], competition['random_id']) != (saved['native_id'], saved.get('random_id')):
        raise ValueError('Competition identity or membership changed')
    runtime = players.u64(read(address+0xB0, 8))
    context = {'competition': competition, 'runtime_competition': None,
               'shared_runtime': False, 'runtime_state': 'absent', 'native_season_code': None}
    if not runtime:
        return context, None, None
    if runtime < 4096 or runtime % 8:
        raise ValueError('Invalid runtime competition pointer')
    rva = world.pointer(read, runtime)-base
    if rva not in RUNTIME_TYPES:
        raise ValueError('Unsupported runtime competition type')
    typed(read, base, runtime, (rva, RUNTIME_TYPES[rva]))
    owner_address = world.pointer(read, runtime+0x138)
    owner_index = int.from_bytes(read(owner_address+8, 4), 'little')
    owner = competitions.by_index(read, base, owner_index)
    if world.pointer(read, info['start']+owner_index*8) != owner_address:
        raise ValueError('Runtime competition owner membership changed')
    season_code = int.from_bytes(read(runtime+0x3B0, 2), 'little')
    context.update(runtime_competition=owner, shared_runtime=owner_address != address,
                   runtime_state='decoded', native_season_code=season_code)
    return context, runtime, (runtime, rva, owner_address, owner_index, owner['native_id'], season_code)


def catalog(read, base, saved):
    context, runtime, identity = runtime_context(read, base, saved)
    if runtime is None:
        return context, []
    owner_address = identity[2]
    entries, header = vector(read, runtime+0x1D8, 256)
    root = identity + (header,)
    queue = [((i,), stage, (root,)) for i, stage in enumerate(entries)]
    results = []
    for path, stage, chain in queue:
        if not stage:
            results.append(({'path': list(path), 'kind': None, 'state': 'null_slot',
                             'standings_available': False}, None))
            continue
        vtable = world.pointer(read, stage)
        kind = next((k for k, (rva, _) in STAGE_TYPES.items() if vtable == base+rva), None)
        if kind is None:
            raise ValueError('Unsupported runtime stage type')
        typed(read, base, stage, STAGE_TYPES[kind])
        if world.pointer(read, stage+0x70) != owner_address:
            raise ValueError('Stage competition backlink changed')
        tag = read(stage+0x48, 8)
        current = chain + ((stage, kind, tag),)
        binding = {'path': path, 'chain': current, 'address': stage, 'kind': kind}
        row = {'path': list(path), 'kind': kind, 'state': 'decoded',
               'standings_available': kind == 'league',
               'contents_state': 'league_table' if kind == 'league' else
                                 'nested_league_stages' if kind == 'group' else 'not_decoded'}
        if kind == 'group':
            if len(path) != 1:
                raise ValueError('Unsupported nested group stage')
            children, child_header = vector(read, stage+0xD0, 256)
            if len(queue)+len(children) > MAX_STAGES:
                raise ValueError('Runtime stage enumeration exceeds bounded limit')
            row['child_slots'] = len(children)
            queue.extend((path+(i,), child, current+(child_header,)) for i, child in enumerate(children))
        elif len(path) > 1 and kind != 'league':
            raise ValueError('Unexpected group child type')
        results.append((row, binding))
    return context, results


def standings(read, base, binding):
    if binding['kind'] != 'league':
        raise ValueError('This stage has no decoded league table; select a league stage')
    address = binding['address']
    settings = world.pointer(read, address+0xF0)
    typed(read, base, settings, SETTINGS)
    point_values = struct.unpack('<6b', read(settings+0x98, 6))
    point_rules = dict(zip(('win', 'extra_time_win', 'penalty_win', 'draw', 'loss', 'penalty_loss'), point_values))
    entries, _ = vector(read, address+0xC0, 1024)
    count, view = struct.unpack('<bb', read(address+0x100, 2))
    if count != len(entries):
        raise ValueError('League row count changed')
    info = teams.lookup(read, base)
    pending = []
    for index, row_address in enumerate(entries):
        if not row_address:
            raise ValueError('Unexpected null league row pointer')
        raw = read(row_address, 0xF8)
        position = raw[0xF7]
        if view == 0 and position != index:
            raise ValueError('Stored league position disagrees with table order; retry')
        team_address = players.u64(raw, 0x88)
        team = team_binding = None
        if team_address:
            if team_address < 4096 or team_address % 8:
                raise ValueError('Invalid league team pointer')
            team_index = int.from_bytes(read(team_address+8, 4), 'little')
            team, team_binding = teams.by_index(read, base, team_index, info=info)
            if team_binding['address'] != team_address:
                raise ValueError('League team membership changed')
        stats = {}
        for name, offset in (('overall', 0), ('home', 0x18), ('away', 0x30)):
            goals_for, goals_against, points = struct.unpack_from('<hhh', raw, offset+8)
            played = struct.unpack_from('<b', raw, offset+0xE)[0]
            wins, draws, losses, penalty_losses = struct.unpack_from('<4b', raw, offset+0x10)
            # Match the getter's signed-16 result even if native goals overflow.
            difference = (goals_for-goals_against+32768) % 65536-32768
            stats[name] = dict(played=played, wins=wins, draws_or_penalty_wins=draws,
                               losses=losses, penalty_losses=penalty_losses,
                               goals_for=goals_for, goals_against=goals_against,
                               goal_difference=difference, points=points)
        pending.append(({'row_index': index, 'position': index+1 if view == 0 else None,
                         'team': team, 'team_state': 'decoded' if team else 'unassigned', **stats}, team_binding))
    return {'count': len(pending), 'native_order_view_code': view,
            'ordering': 'native_stored_overall' if view == 0 else 'native_other_view_unmapped',
            'point_rules': point_rules, 'unassigned_team_rows': sum(row['team'] is None for row, _ in pending)}, pending
