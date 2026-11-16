"""Live canonical national-container discovery; no nationality-as-membership join."""
from datetime import datetime, timezone
import secrets
import struct

from . import database, geography, players, teams, world


def read_container(read, base, info, index):
    address = players.u64(read(info['start'] + index * 8, 8))
    if not address:
        return None, []
    teams._typed(read, base, address, ('national_team_container',))
    identity, raw = teams._identity(read, address)
    if identity['database_index'] != index:
        raise ValueError('National container canonical index changed')
    nation_address = players.u64(read(address + 0x170, 8))
    nation = geography.record(read, base, nation_address, 'nation') if nation_address else None
    result = {**identity, 'nation': nation, 'gender': None, 'gender_state': 'not_proved',
              'teams': [], 'team_membership_source': 'native_container_team_vector'}
    bindings = []
    for ordinal, team_address in enumerate(world.vector(read, address + 0x18, 64)):
        index = struct.unpack('<I', read(team_address + 8, 4))[0]
        row, binding = teams.by_index(read, base, index)
        if binding['address'] != team_address or row['kind'] != 'national_team':
            raise ValueError('Container entry is not the canonical national team')
        count = len(world.vector(read, team_address + 0x38, 256))
        label = teams.EDITOR_TYPE_NAMES.get(row['native_type_code'])
        result['teams'].append({**row, 'container_slot_index': ordinal,
            'team_type_label': label, 'team_type_label_source': 'installed_editor_tmty_enum' if label else None,
            'gender': None, 'gender_state': 'not_proved', 'roster_count': count,
            'roster_state': 'known_empty' if count == 0 else 'stored_members_available',
            'owner_matches_listed_container': binding['owner_address'] == address})
        bindings.append(binding)
    result['team_count'] = len(result['teams'])
    result['teams_state'] = 'known_empty' if not bindings else 'stored_members_available'
    return result, bindings


def find_national_teams(bridge, session_id, name=None, nation_native_id=None,
                        record_budget=16, next_cursor=None):
    if name is not None and (not isinstance(name, str) or not 1 <= len(name.strip()) <= 100):
        raise ValueError('Supply a nonempty nation name or abbreviation up to100 characters')
    if nation_native_id is not None and (type(nation_native_id) is not int or nation_native_id <= 0):
        raise ValueError('Nation native ID must be positive')
    if type(record_budget) is not int or not 1 <= record_budget <= 16:
        raise ValueError('National discovery record budget must be1–16')
    criteria = (name.strip().casefold() if name else None, nation_native_id, record_budget)
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, save, _ = bridge._world_state(process, tables)
        base = tables[0] - players.RVA[0]
        info = database.table(read, base, 'national_team_containers')
        identity = (session_id, process.pid, tables, bridge.world_identity, info['identity'])
        start = 0
        if next_cursor is not None:
            previous = bridge.database_cursors.get(next_cursor)
            if (previous is None or previous.get('kind') != 'national_teams'
                    or previous.get('criteria') != criteria or previous.get('identity') != identity):
                raise ValueError('National-team cursor expired or belongs to a different query/load')
            start = previous['index']
        end = min(start + record_budget, info['count'])
        pending, unclassified, nulls = [], [], []
        for index in range(start, end):
            # Read cheap identity/nation first; full teams only for matching nations.
            address = players.u64(read(info['start'] + index * 8, 8))
            if not address:
                nulls.append(index)
                continue
            teams._typed(read, base, address, ('national_team_container',))
            container, _ = teams._identity(read, address)
            if container['database_index'] != index:
                raise ValueError('National container canonical index changed')
            pointer = players.u64(read(address + 0x170, 8))
            nation = geography.record(read, base, pointer, 'nation') if pointer else None
            if nation is None and any(v is not None for v in criteria[:2]):
                unclassified.append({**container, 'reason': 'nation_reference_unavailable'})
                continue
            if nation_native_id is not None and nation['native_id'] != nation_native_id:
                continue
            if name is not None and not any(criteria[0] in (nation.get(k) or '').casefold()
                                            for k in ('short_name', 'abbreviation')):
                continue
            row, bindings = read_container(read, base, info, index)
            pending.append((row, bindings))
            if sum(len(p[1]) for p in pending) > 128:
                raise ValueError('National-team page exceeds128 teams; use a smaller record_budget')
        read.verify()
        bridge._current(session_id)
        if len(bridge.team_refs) + sum(len(p[1]) for p in pending) > 10000:
            bridge.team_refs.clear()
        rows = []
        for row, bindings in pending:
            for team, binding in zip(row['teams'], bindings, strict=True):
                ref = secrets.token_urlsafe(12)
                bridge.team_refs[ref] = {**binding, 'tables': tables, 'source': 'national',
                                        'label': team['team_type_label'] or 'Unmapped national team type'}
                team['team_ref'] = ref
            rows.append(row)
        cursor = None
        if end < info['count']:
            if len(bridge.database_cursors) >= 100:
                bridge.database_cursors.clear()
            cursor = secrets.token_urlsafe(12)
            bridge.database_cursors[cursor] = {'kind': 'national_teams', 'criteria': criteria,
                                               'identity': identity, 'index': end}
        return {'session_id': session_id, 'observed_at': datetime.now(timezone.utc).isoformat(),
            'save': bridge._public_save(save), 'containers': rows, 'count': len(rows),
            'start_index': start, 'next_index': end, 'total_container_slots': info['count'],
            'scanned_records': end-start, 'next_cursor': cursor, 'null_container_slots': nulls,
            'unclassified_containers': unclassified, 'complete_table_scan': start == 0 and end == info['count'],
            'source': 'canonical_national_container_nation_and_ordered_team_vectors',
            'atomic': False, 'saved_file_fallback': False,
            'limits': 'Read each next_cursor with identical filters and budget, including empty pages. '
                'Current stored national roster membership is read with fm_get_team_squad using each team_ref; '
                'it is not nationality, a match XI, duty absence, call-up date, eligibility or clearance. '
                'Gender remains unknown. A listed team can have another national container as its canonical owner; '
                'both relationships are preserved. Known-empty vectors are distinct from null nation references.'}
