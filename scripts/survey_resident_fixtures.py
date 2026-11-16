"""Census existing calendar-year fixture buckets without loading archived groups.

Run with --year YYYY to select a resident year, or omit it for the main manager.
Evidence contains private addresses and raw bytes and must remain untracked.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import competition_stages, database, players, world
from fm_live_mcp.bridge import Bridge


def managers(read, base):
    root = world.pointer(read, base+0x56D57D0)
    competition_stages.typed(read, base, root, (0x55DD068, b'23GAME_RULE_GROUP_MANAGER'))
    store = world.pointer(read, root+0x158)
    competition_stages.typed(read, base, store, (0x55DC600, b'17GAME_COMP_MANAGER'))
    main = store+8
    rows = [('main', main)]
    for offset, label in ((0, 'linked'), (8, 'archived')):
        header = players.u64(read(main+offset, 8))
        if header:
            rows.extend((label, address) for address in world.vector(read, header, 100))
    result = []
    for label, address in rows:
        year, flags = struct.unpack('<H2s', read(address+0x40, 4))
        groups = world.vector(read, address+0x10, 1024)
        result.append((label, address, year, flags.hex(), groups))
    assert len({row[1] for row in result}) == len(result), 'Repeated year manager'
    assert len({row[2] for row in result}) == len(result), 'Ambiguous resident year'
    return tuple(result)


def survey(year=None):
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    rows = []
    counts = Counter()
    types = Counter()
    seen = set()
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge._current(sid)
            tables = bridge._player_layout(process)
            base = tables[0]-players.RVA[0]
            read, save, _ = bridge._world_state(process, tables)
            inventory = managers(read, base)
            if year is None:
                year = inventory[0][2]
            selected = [row for row in inventory if row[2] == year]
            assert len(selected) == 1, f'Year {year} has no resident manager'
            source, manager, _, _, groups = selected[0]
            read.verify()

        for index, group in enumerate(groups):
            with bridge.lock, bridge._read_scope(sid):
                process = bridge._current(sid)
                tables = bridge._player_layout(process)
                current_base = tables[0]-players.RVA[0]
                read, current_save, _ = bridge._world_state(process, tables)
                assert current_base == base and current_save == save, 'Save/build changed'
                assert managers(read, base) == inventory, 'Fixture manager inventory changed'
                flag = read(group+0xB70, 1)[0]
                row = {'index': index, 'loaded': bool(flag & 1), 'flag_b70': flag, 'records': []}
                # Do not follow day pointers at all when native materialization is required.
                if flag & 1:
                    days = struct.unpack('<366Q', read(group, 366*8))
                    table = database.table(read, base, 'teams')
                    team_cache = {}
                    name_table = database.table(read, base, 'fixture_names')
                    comp_table = database.table(read, base, 'competitions')
                    name_cache = {}

                    def team_id(address):
                        if not address:
                            return None
                        if address not in team_cache:
                            data = read(address, 20)
                            team_index, native_id = struct.unpack_from('<II', data, 8)
                            assert team_index < table['count']
                            assert world.pointer(read, table['start']+team_index*8) == address
                            team_cache[address] = (team_index, native_id)
                        return team_cache[address]

                    def fixture_competition(address):
                        if not address:
                            return None
                        if address not in name_cache:
                            competition_stages.typed(read, base, address, (0x55AB970, b'N2db12FIXTURE_NAMEE'))
                            data = read(address, 0x20)
                            index = struct.unpack_from('<I', data, 8)[0]
                            assert index < name_table['count']
                            assert world.pointer(read, name_table['start']+index*8) == address
                            comp = players.u64(data, 0x18)
                            name_cache[address] = None
                            if comp:
                                world.typed(read, base, comp, 'competition')
                                comp_index, native_id = struct.unpack('<II', read(comp+8, 8))
                                assert comp_index < comp_table['count']
                                assert world.pointer(read, comp_table['start']+comp_index*8) == comp
                                name_cache[address] = (comp_index, native_id)
                        return name_cache[address]

                    for day, header in enumerate(days, 1):
                        if not header:
                            continue
                        for address in world.vector(read, header, 2000):
                            vtable = world.pointer(read, address)-base
                            assert vtable in (0x5672C88, 0x5672E00), hex(vtable)
                            name = (b'N7sicomps7FIXTUREE' if vtable == 0x5672C88
                                    else b'N7sicomps14FIXTURE_RESULTE')
                            competition_stages.typed(read, base, address, (vtable, name))
                            raw = read(address, 0x80 if vtable == 0x5672E00 else 0x58)
                            date = struct.unpack_from('<I', raw, 0x4C)[0]
                            assert date >> 16 == year and date & 511 == day, (index, day, hex(date))
                            assert address not in seen, 'Repeated fixture across buckets'
                            seen.add(address)
                            row['records'].append({
                                'address': hex(address), 'day': day, 'vtable': hex(vtable),
                                'team_8': team_id(players.u64(raw, 8)),
                                'team_10': team_id(players.u64(raw, 16)),
                                'competition': fixture_competition(players.u64(raw, 0x20)), 'raw': raw.hex(),
                            })
                            types[hex(vtable)] += 1
                            if vtable == 0x5672E00:
                                for offset, label in enumerate(('normal_time', 'extra_time', 'penalties', 'aggregate', 'unknown')):
                                    present = sum(raw[at+offset] != 255 for at in (0x64, 0x69))
                                    counts[f'{label}_both_set'] += present == 2
                                    counts[f'{label}_partial'] += present == 1
                read.verify()
            rows.append(row)
            print(f'year {year}, group {index+1}/{len(groups)}: '
                  f'{len(row["records"])} records; {len(seen)} total', flush=True)
    finally:
        bridge.detach()
    return {
        'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'year': year, 'source': source,
        'resident_years': [{'source': r[0], 'year': r[2], 'flags': r[3], 'group_count': len(r[4])}
                           for r in inventory],
        'record_count': len(seen), 'unique_fixtures': len(seen), 'types': dict(types),
        'score_presence': dict(counts), 'groups': rows,
        'scope': ('Existing loaded calendar-year groups only. An unloaded group or missing year is '
                  'unavailable, not empty. Non-atomic per-group consumed-byte rechecks; no proof '
                  'of complete history or future schedule, match completion or current date.'),
        'foreground_ui_used': False, 'native_execution': False,
    }


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--year', type=int)
    args = parser.parse_args()
    result = survey(args.year)
    destination = ROOT/f'evidence/resident-fixtures-{result["year"]}.json'
    destination.write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({key: value for key, value in result.items() if key != 'groups'}, indent=2))
