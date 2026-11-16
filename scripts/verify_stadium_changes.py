"""Compare every public stadium-change record and filter with a fresh raw census."""
import asyncio
from datetime import date, datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import __version__


def census():
    subprocess.run([sys.executable, str(ROOT/'scripts/survey_stadium_changes.py')], cwd=ROOT, check=True)
    value = json.loads((ROOT/'evidence/stadium-change-survey.json').read_text())
    assert value['verified']
    return value


def check(actual, source, proof):
    raw = bytes.fromhex(source['raw'])
    assert actual['kind'] == 'stadium_change'
    assert actual['native_id'] == source['native_id'] and actual['database_index'] == source['database_index']
    assert actual['stadium_change_ref']
    code = struct.unpack_from('<b', raw, 0x64)[0]
    label = proof['type_labels'].get(str(code))
    assert actual['type'] == {'native_property': 'Styp', 'native_code': code, 'name': label,
                             'state': 'not_specified' if code == -1 else 'decoded' if label else 'unmapped'}
    assert actual['is_potential_move'] is bool(raw[0x65] & 4)
    for field, offset, prop in (('start', 0x30, 'Slea'), ('leave', 0x34, 'Ssta'), ('latest_move', 0x38, 'Slmd')):
        packed = struct.unpack_from('<I', raw, offset)[0]; year, day = packed >> 16, packed & 511
        state, value = 'invalid_native_date', None
        if (year, day) == (1900, 1):
            state = 'not_specified'
        elif 1 <= year <= 9999 and 1 <= day <= 366:
            try:
                native_date = date(year, 1, 1) + timedelta(days=day-1)
                if native_date.year == year: state, value = 'stored', native_date.isoformat()
            except OverflowError:
                pass
        assert actual['dates'][field] == {'native_property': prop, 'native_year': year, 'native_day': day,
                                          'date': value, 'state': state}
    fields = [('new_capacity', 0x3C, 'Scap', 'people'), ('new_seated_capacity', 0x40, 'Sscp', 'people'),
              ('future_development_fund', 0x44, 'Sceb', None), ('expected_attendance', 0x50, 'Snxa', 'people'),
              ('minimum_expected_attendance', 0x54, 'Snmn', 'people'), ('maximum_expected_attendance', 0x58, 'Snmx', 'people'),
              ('expected_season_tickets_sold', 0x5C, 'Stks', None), ('rental_cash', 0x60, 'Scam', None)]
    for field, offset, prop, unit in fields:
        value = struct.unpack_from('<i', raw, offset)[0]
        state = 'not_specified' if value == -1 else 'unit_unverified' if unit is None else 'out_of_range' if value < 0 else 'stored'
        assert actual[field] == {'native_property': prop, 'native_value': value, 'value': None if value == -1 else value,
                                 'unit': unit, 'state': state}
    for field, offset, prop, lo, hi in (('move_likelihood', 0x66, 'Slhm', 1, 100),
                                       ('new_training_level', 0x67, 'ScTL', 0, 20), ('new_youth_level', 0x68, 'ScYL', 0, 20)):
        value = struct.unpack_from('<b', raw, offset)[0]
        assert actual[field] == {'native_property': prop, 'native_value': value, 'value': None if value == -1 else value,
                                 'unit': 'native_level', 'state': 'not_specified' if value == -1 else 'stored' if lo <= value <= hi else 'out_of_range'}
    code = struct.unpack_from('<b', raw, 0x69)[0]; label = proof['condition_labels'].get(str(code))
    assert actual['stadium_condition'] == {'native_property': 'Scns', 'native_code': code, 'name': label,
                                          'state': 'not_specified' if code == -1 else 'decoded' if label else 'unmapped'}
    if source['team']:
        assert actual['team']['native_id'] == source['team']['native_id']
        assert actual['team']['database_index'] == source['team']['database_index'] and actual['team']['team_ref']
    else:
        assert actual['team'] is None
    for field in ('current', 'new', 'alternative'):
        expected = source['stadiums'][field]; child = actual[field+'_stadium']
        if expected:
            assert all(child[key] == value for key, value in expected.items()) and child['stadium_ref']
        else:
            assert child is None


async def main():
    started = datetime.now(timezone.utc).isoformat()
    proof = json.loads((ROOT/'evidence/stadium-change-layout-verification.json').read_text())
    assert proof['verified'] and len(proof['fields']) == 21
    before = census(); rows = before['records']; sources = {r['native_id']: r for r in rows}
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    assert config['command'] == '/bin/sh' and config['args'] == [str(ROOT/'scripts/run_mcp.sh')]
    paths = sorted((ROOT/'fm_live_mcp').glob('*.py')) + [ROOT/'scripts'/p for p in
        ('verify_stadium_change_layout.py', 'survey_stadium_changes.py', 'verify_stadium_changes.py')]
    source_identity = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    team_links = stadium_links = 0; filters = []; transient_retries = 0
    async with stdio_client(StdioServerParameters(command=config['command'], args=config['args'])) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(tool, **args):
                nonlocal transient_retries
                for attempt in range(5):
                    result = await client.call_tool(tool, args)
                    if not result.isError or 'changed during read' not in str(result.content) or attempt == 4:
                        break
                    transient_retries += 1
                    await asyncio.sleep(.2)
                assert not result.isError and result.structuredContent is not None, (tool, args, result.content)
                return result.structuredContent
            status = await call('fm_status'); assert status['server_version'] == __version__
            assert status['capabilities']['stadium_change_query'] and not status['capabilities']['memory_writes']
            tools = (await client.list_tools()).tools
            assert len(tools) == 49 and all(t.annotations.readOnlyHint for t in tools)
            sid = (await call('fm_attach'))['session_id']
            async def scan(**criteria):
                found = []; cursor = None; next_index = 0
                while True:
                    page = await call('fm_find_stadium_changes', session_id=sid, max_matches=7,
                                      record_budget=11, cursor=cursor, **criteria)
                    assert page['start_index'] == next_index and page['total_records'] == len(rows)
                    next_index = page['next_index']; found.extend(page['stadium_changes'])
                    cursor = page['next_cursor']
                    if cursor is None:
                        assert next_index == len(rows); break
                return found
            actual = await scan()
            assert [r['native_id'] for r in actual] == [r['native_id'] for r in rows]
            for row in actual:
                check(row, sources[row['native_id']], proof)
                fresh = (await call('fm_get_stadium_change', session_id=sid, stadium_change_ref=row['stadium_change_ref']))['stadium_change']
                check(fresh, sources[row['native_id']], proof)
                if fresh['team']:
                    team = (await call('fm_get_team_squad', session_id=sid, team_ref=fresh['team']['team_ref']))['team']
                    assert team['native_id'] == fresh['team']['native_id']; team_links += 1
                for field in ('current_stadium', 'new_stadium', 'alternative_stadium'):
                    child = fresh[field]
                    if child:
                        opened = (await call('fm_get_stadium', session_id=sid, stadium_ref=child['stadium_ref']))['stadium']
                        assert opened['native_id'] == child['native_id']; stadium_links += 1
            for code in sorted({r['type_native'] for r in rows} | {-1, 127}):
                result = await scan(type_code=code)
                expected = [r['native_id'] for r in rows if r['type_native'] == code]
                assert [r['native_id'] for r in result] == expected
                filters.append({'criteria': {'type_code': code}, 'matches': len(expected)})
            if rows:
                chosen = next(r for r in rows if r['team'] and any(r['stadiums'].values()))
                tid = chosen['team']['native_id']; stadium_id = next(s['native_id'] for s in chosen['stadiums'].values() if s)
                for criteria in ({'native_id': chosen['native_id']}, {'team_native_id': tid}, {'stadium_native_id': stadium_id},
                                 {'team_native_id': tid, 'stadium_native_id': stadium_id, 'type_code': chosen['type_native']},
                                 {'native_id': 4294967295}):
                    expected = [r['native_id'] for r in rows
                        if ('native_id' not in criteria or r['native_id'] == criteria['native_id'])
                        and ('team_native_id' not in criteria or r['team'] and r['team']['native_id'] == criteria['team_native_id'])
                        and ('stadium_native_id' not in criteria or any(s and s['native_id'] == criteria['stadium_native_id'] for s in r['stadiums'].values()))
                        and ('type_code' not in criteria or r['type_native'] == criteria['type_code'])]
                    result = await scan(**criteria); assert [r['native_id'] for r in result] == expected
                    filters.append({'criteria': criteria, 'matches': len(expected)})
            save = (await call('fm_get_save', session_id=sid))['save']
            await call('fm_detach')
    after = census()
    assert before['records'] == after['records'], 'Native records changed across validation; no successful receipt written'
    for p, digest in source_identity.items(): assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest() == digest
    receipt = {'verified': True, 'server_version': __version__, 'started_at': started,
               'completed_at': datetime.now(timezone.utc).isoformat(), 'save': save,
               'records_checked': len(rows), 'readbacks_checked': len(rows), 'complete_scan': True,
               'team_links_opened': team_links, 'stadium_links_opened': stadium_links, 'filters': filters,
               'tool_count': len(tools), 'source_identity': source_identity,
               'transient_read_retries': transient_retries,
               'proof_sha256': hashlib.sha256((ROOT/'evidence/stadium-change-layout-verification.json').read_bytes()).hexdigest(),
               'native_before_after_equal': True, 'foreground_ui_used': False, 'native_execution': False}
    (ROOT/'evidence/live-stadium-changes-mcp.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('source_identity', 'filters')}, indent=2))


if __name__ == '__main__':
    asyncio.run(main())
