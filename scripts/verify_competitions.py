"""Verify competition enumeration, search and readback through public stdio."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    census = json.loads((root / 'evidence/competition-survey.json').read_text())
    assert census['complete_native_table_scan'] and not census['errors']
    expected = census['competitions']
    layout = json.loads((root / 'evidence/competition-context-layout-verification.json').read_text())
    assert layout['verified']
    receipt = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(), 'queries': []}
    started = time.monotonic()
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root / 'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                assert {'fm_find_competitions', 'fm_get_competition'} <= {t.name for t in tools}
                assert all(t.annotations.readOnlyHint for t in tools)
                async def call(tool, **args):
                    result = await client.call_tool(tool, args)
                    assert not result.isError and result.structuredContent is not None, (tool, result.content)
                    return result.structuredContent
                status = await call('fm_status')
                sid = (await call('fm_attach'))['session_id']
                catalog = await call('fm_get_database_catalog', session_id=sid)
                assert catalog['native_table_counts']['competitions'] == len(expected)
                assert catalog['native_table_counts']['continents'] == len(layout['geography']['continent'])
                assert catalog['native_table_counts']['nations'] == len(layout['geography']['nation'])
                async def scan(**criteria):
                    cursor, rows, next_index, pages, empty = None, [], 0, 0, 0
                    cursors = set()
                    while True:
                        result = await call('fm_find_competitions', session_id=sid, max_matches=100,
                                            record_budget=1000, cursor=cursor, **criteria)
                        assert result['start_index'] == next_index
                        assert result['scanned_records'] == result['next_index'] - next_index
                        assert 0 < result['scanned_records'] <= 1000
                        assert result['total_competition_records'] == len(expected)
                        assert result['count'] == len(result['competitions']) <= 100
                        next_index = result['next_index']
                        rows.extend(result['competitions'])
                        pages += 1
                        empty += not result['count']
                        cursor = result['next_cursor']
                        if cursor is None:
                            assert next_index == len(expected) and result['stop_reason'] == 'table_end'
                            break
                        assert cursor not in cursors
                        cursors.add(cursor)
                    receipt['queries'].append({'criteria': criteria, 'pages': pages, 'empty_pages': empty, 'matches': len(rows)})
                    print(f'Query {criteria}: {len(rows)} records across {pages} pages', flush=True)
                    return rows
                def without_ref(rows):
                    return [{k: v for k, v in row.items() if k != 'competition_ref'} for row in rows]
                all_rows = await scan()
                assert without_ref(all_rows) == expected
                assert len({r['native_id'] for r in all_rows}) == len(expected)
                samples = [all_rows[0], all_rows[-1],
                    next(r for r in all_rows if r['name'] is None),
                    next(r for r in all_rows if r['name'] and not r['name'].isascii())]
                for predicate in (
                    lambda c: c['competition_type']['native_code'] == 30,
                    lambda c: c['competition_type']['native_code'] == 40,
                    lambda c: c['competition_type']['native_code'] == 41,
                    lambda c: c['competition_type']['state'] == 'not_specified',
                    lambda c: c['gender']['name'] == 'Female',
                    lambda c: c['level'] == 0,
                    lambda c: c['level'] is None,
                    lambda c: c['parent_competition'] is not None,
                    lambda c: c['nation'] is None,
                    lambda c: c['continent'] is None,
                    lambda c: c['is_extinct'],
                ):
                    row = next(r for r in all_rows if predicate(r['context']))
                    if row not in samples:
                        samples.append(row)
                for row in samples:
                    fresh = await call('fm_get_competition', session_id=sid, competition_ref=row['competition_ref'])
                    assert fresh['competition'] == row and fresh['save_identity'] == 'native_binding_rechecked'
                for query in ('premier league', samples[3]['name'].swapcase(), 'zzzz_no_competition_zzzz'):
                    found = await scan(name=query)
                    wanted = [r for r in expected if any(query.casefold() in (r[k] or '').casefold()
                              for k in ('name', 'short_name', 'abbreviation'))]
                    assert without_ref(found) == wanted
                # Native IDs also address unnamed entries and loan-condition identities.
                serie_a = next(r for r in expected if r['name'] == 'Italian Serie A')
                found_player = await call('fm_find_save_players', session_id=sid, name='Vítězslav Jaroš')
                player = next(p for p in found_player['players'] if p['name'] == 'Vítězslav Jaroš')
                loan = await call('fm_get_loan_contract', session_id=sid, player_ref=player['player_ref'])
                condition = loan['loan_contract']['purchase']['competition_condition']
                assert condition['competition'] == {k: v for k, v in serie_a.items() if k != 'context'}
                for row in (samples[2], serie_a):
                    found = await scan(native_id=row['native_id'])
                    assert without_ref(found) == [next(r for r in expected if r['native_id'] == row['native_id'])]
                filters = [
                    ({'nation': 'England', 'type_code': 0, 'gender': 'male', 'is_extinct': False},
                     lambda c: (c['nation'] or {}).get('short_name') == 'England' and
                         c['competition_type']['native_code'] == 0 and c['gender']['native_code'] == 0 and not c['is_extinct']),
                    ({'continent': 'eur', 'type_code': 21}, lambda c:
                         (c['continent'] or {}).get('abbreviation') == 'EUR' and c['competition_type']['native_code'] == 21),
                    ({'nation': 'eng', 'gender': 'female'}, lambda c:
                         (c['nation'] or {}).get('abbreviation') == 'ENG' and c['gender']['native_code'] == 1),
                    ({'type_code': 41}, lambda c: c['competition_type']['native_code'] == 41),
                ]
                for criteria, predicate in filters:
                    found = await scan(**criteria)
                    assert without_ref(found) == [r for r in expected if predicate(r['context'])]
                receipt['context_states'] = {
                    'types': sorted({r['context']['competition_type']['state'] for r in all_rows}),
                    'unmapped_codes': sorted({r['context']['competition_type']['native_code'] for r in all_rows
                                             if r['context']['competition_type']['state'] == 'unmapped'}),
                    'missing_level': sum(r['context']['level'] is None for r in all_rows),
                    'zero_level': sum(r['context']['level'] == 0 for r in all_rows),
                }
                # Invalid criteria/cursors must produce tool errors, never empty success.
                for arguments in ({'name': ''}, {'native_id': True}, {'record_budget': 1001}, {'cursor': 'invented'},
                                  {'nation': ''}, {'type_code': True}, {'gender': 'unknown'}, {'is_extinct': 1}):
                    bad = await client.call_tool('fm_find_competitions', {'session_id': sid, **arguments})
                    assert bad.isError
                await call('fm_detach')
                bad = await client.call_tool('fm_get_competition', {'session_id': sid, 'competition_ref': samples[0]['competition_ref']})
                assert bad.isError
                receipt.update(verified=True, installed_version=status['server_version'], tool_count=len(tools),
                    enumerated_count=len(all_rows), samples=samples, foreground_ui_used=False,
                    elapsed_seconds=round(time.monotonic() - started, 2),
                    scope='Complete paginated identity/name/context enumeration agrees with the independent census; name/ID/geography/type/gender/extinction searches, exceptional native states, fresh membership-bound reads, catalog and input/session rejection. Native semantics have a separate layout proof. No standings, rules, activity or UI comparison.')
    finally:
        (root / 'evidence/live-competitions-mcp.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps({k: v for k, v in receipt.items() if k not in ('samples', 'queries')}))


if __name__ == '__main__':
    asyncio.run(verify())
