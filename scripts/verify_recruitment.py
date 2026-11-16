"""Verify save-wide player criteria and pagination through real stdio MCP."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    start = time.monotonic()
                    response = await client.call_tool(tool, args)
                    evidence['steps'].append({'tool': tool, 'seconds': time.monotonic()-start,
                                              'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None: raise RuntimeError(str(response.content))
                    return response.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                sid = (await call('fm_attach'))['session_id']
                total = (await call('fm_get_database_catalog', session_id=sid))['native_table_counts']['people']
                exact = []
                for name in ('Nick Woltemade', 'Mohamed Salah'):
                    found = await call('fm_find_save_players', session_id=sid, name=name)
                    person = (await call('fm_get_player', session_id=sid, player_ref=found['players'][0]['player_ref'], include_profile=True))['player']
                    profile = {f'{group}.{key}': value for group in ('positions', 'goalkeeping', 'hidden_attributes', 'feet', 'personality')
                               for key, value in person['profile'][group].items()}
                    profile.update({f'ability.{k}': person['profile']['ability'][k] for k in ('current', 'potential')})
                    assert all(v is not None for v in profile.values())
                    query = await call('fm_query_save_players', session_id=sid, name_contains=name,
                        minimum_attributes=person['attributes'], maximum_attributes=person['attributes'],
                        minimum_profile=profile, maximum_profile=profile,
                        born_on_or_after=person['birth_date'], born_on_or_before=person['birth_date'])
                    assert query['complete_table_scan'] and query['count'] == 1 and not query['unclassified_players']
                    assert query['players'][0]['profile'] == person['profile']
                    assert query['players'][0]['attributes'] == person['attributes']
                    exact.append({'name': name, 'record_kind': person.get('record_kind', 'actual'), 'criteria_count': 79})
                criteria = {'minimum_profile': {'ability.current': 190}}
                whole = await call('fm_query_save_players', session_id=sid, max_matches=100, **criteria)
                assert whole['complete_table_scan'] and whole['scanned_records'] == total
                assert whole['actual_players_examined'] + whole['other_person_records'] == total
                assert whole['globally_ranked'] is False and whole['ordering'] == 'native_database_index'
                paged, scanned, pages, cursor = [], 0, 0, None
                while True:
                    page = await call('fm_query_save_players', session_id=sid, max_matches=2, record_budget=50000, cursor=cursor, **criteria)
                    paged.extend(page['players']); scanned += page['scanned_records']; pages += 1
                    cursor = page['next_cursor']
                    if not cursor: break
                    assert pages < 20
                def comparable(rows): return [{k: v for k, v in p.items() if k != 'player_ref'} for p in rows]
                assert comparable(paged) == comparable(whole['players']) and scanned == total
                for row in paged:
                    fresh = (await call('fm_get_player', session_id=sid, player_ref=row['player_ref'], include_profile=True))['player']
                    assert fresh['profile'] == row['profile'] and fresh['attributes'] == row['attributes']
                cases = [
                    {'born_on_or_after': '2010-01-01', 'minimum_profile': {'ability.potential':170, 'positions.striker':15},
                     'minimum_attributes': {'pace':15}, 'maximum_profile': {'hidden_attributes.injury_proneness':12}},
                    {'minimum_profile': {'ability.current':170, 'positions.goalkeeper':20, 'goalkeeping.reflexes':17, 'personality.professionalism':15}},
                    {'born_on_or_before':'1850-12-31', 'minimum_profile': {'ability.current':200}},
                ]
                summaries = []
                for args in cases:
                    result = await call('fm_query_save_players', session_id=sid, max_matches=100, **args)
                    assert result['next_cursor'] is None and result['scanned_records'] == total
                    for row in result['players']:
                        if 'born_on_or_after' in args: assert row['birth_date'] >= args['born_on_or_after']
                        if 'born_on_or_before' in args: assert row['birth_date'] <= args['born_on_or_before']
                        for label, lower in [('minimum_profile', True), ('maximum_profile', False)]:
                            for path, value in args.get(label, {}).items():
                                group, key = path.split('.')
                                actual = row['profile'][group][key]
                                assert actual >= value if lower else actual <= value
                        for key, value in args.get('minimum_attributes', {}).items(): assert row['attributes'][key] >= value
                    summaries.append({'criteria': args, 'matches': result['count'], 'unclassified': result['unclassified_count']})
                empty = await call('fm_query_save_players', session_id=sid, minimum_profile={'ability.current':200}, record_budget=1)
                assert not empty['players'] and empty['next_cursor'] and empty['scanned_records'] == 1
                assert (await client.call_tool('fm_query_save_players', {'session_id':sid, 'minimum_profile':{'ability.current':199}, 'cursor':empty['next_cursor']})).isError
                for invalid in ({'minimum_attributes':{'pace':True}}, {'minimum_profile':{'positions.striker':21}}, {'born_on_or_after':''}):
                    assert (await client.call_tool('fm_query_save_players', {'session_id':sid, **invalid})).isError
                await call('fm_detach')
                assert (await client.call_tool('fm_query_save_players', {'session_id':sid, 'cursor':empty['next_cursor']})).isError
                evidence.update(verified=True, person_records=total, supported_player_records=whole['actual_players_examined'],
                    other_person_records=whole['other_person_records'], high_ability_count=whole['count'],
                    exact_profile_cases=exact, pagination_pages=pages, query_cases=summaries, tool_count=len(tools),
                    scope='Native field-backed criteria, regular/combined full-profile equality, complete person-table traversal, cursor parity and fresh references. Synthetic tests cover negative potential and direct scaling; no live example of those states is claimed.', foreground_ui_used=False)
                print(f'Verified recruitment queries across {total} person records, {pages} pagination pages and both player layouts.')
    finally:
        path = root/'evidence/live-recruitment-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
