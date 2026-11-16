"""Compare public fixture naming components with independent native censuses."""
import asyncio
from collections import Counter
from datetime import datetime, timezone
import json
from pathlib import Path
import struct
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from verify_fixtures import expected

ROOT = Path(__file__).resolve().parents[1]


def check_name(actual, raw, names):
    if raw is None:
        assert actual is None
        return
    assert (actual['native_id'], actual['database_index']) == (raw['native_id'], raw['database_index'])
    assert actual['name_source'] == 'stored_native_components'
    assert len(actual['stage_names']) == 3
    for i, name in enumerate(actual['stage_names'], 1):
        link = raw[f'component_{i}']
        if link is None:
            assert name is None
        else:
            stored = names[link['database_index']]
            assert name == {**{key: stored[key] for key in ('native_id','database_index','name','short_name','plural_name')},
                            'name_source':'stored_native_strings'}
    secondary = raw['secondary_competition']
    if secondary is None:
        assert actual['secondary_competition'] is None
    else:
        assert {key:actual['secondary_competition'][key] for key in secondary} == secondary


async def verify():
    census = json.loads((ROOT/'evidence/fixture-name-survey.json').read_text())
    assert census['verified']
    fixture_names = {int(r['address'],16): r for r in census['fixture_names']}
    names = {r['database_index']: r for r in census['stage_names']}
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    receipt = {'verified':False, 'observed_at':datetime.now(timezone.utc).isoformat(), 'years':[], 'readbacks':[]}
    seen = set()
    async with stdio_client(StdioServerParameters(command=config['command'], args=config['args'])) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(tool, **args):
                value = await client.call_tool(tool,args)
                assert not value.isError and value.structuredContent is not None,(tool,value.content)
                return value.structuredContent
            status = await call('fm_status')
            receipt['server_version'] = status['server_version']
            assert status['capabilities']['stored_fixture_names']
            sid = (await call('fm_attach'))['session_id']
            try:
                catalog = await call('fm_get_database_catalog',session_id=sid)
                assert catalog['native_table_counts']['stage_names'] == len(names)
                for year in (2030,2025):
                    source, baseline = expected(year)
                    source_rows = sorted([(r['day'],g['index'],i,r) for g in source['groups'] for i,r in enumerate(g['records'])])
                    cursor, count, pages = None, 0, 0
                    cases = Counter()
                    unique = set()
                    while True:
                        page = await call('fm_find_fixtures',session_id=sid,year=year,max_matches=100,cursor=cursor)
                        for row in page['fixtures']:
                            raw_fixture = bytes.fromhex(source_rows[count][3]['raw'])
                            pointer = struct.unpack_from('<Q',raw_fixture,0x20)[0]
                            raw_name = fixture_names[pointer] if pointer else None
                            check_name(row['fixture_name'],raw_name,names)
                            prior = baseline[count]
                            assert row['date']==prior['date'] and row['scores']==prior['scores'] and row['kickoff_time']==prior['kickoff_time']
                            assert row['record_kind']==prior['kind']
                            assert (row['competition']['native_id'] if row['competition'] else None)==prior['competition']
                            for field,key in (('home_team','home'),('away_team','away')):
                                assert (row[field]['native_id'] if row[field] else None)==prior[key]
                            components = row['fixture_name']['stage_names'] if row['fixture_name'] else [None]*3
                            mask = ''.join('1' if x else '0' for x in components)
                            case = (mask,bool(row['fixture_name'] and row['fixture_name']['secondary_competition']))
                            cases[str(case)] += 1
                            unique.update(n['native_id'] for n in components if n)
                            if case not in seen:
                                fresh = (await call('fm_get_fixture',session_id=sid,fixture_ref=row['fixture_ref'],include_stage=True))['fixture']
                                check_name(fresh['fixture_name'],raw_name,names)
                                receipt['readbacks'].append({'year':year,'date':row['date'],'case':case,'fixture_name':fresh['fixture_name']})
                                seen.add(case)
                            count += 1
                        pages += 1
                        cursor = page['next_cursor']
                        if pages % 50 == 0: print(f'{year}: {count}/{len(baseline)}',flush=True)
                        if not cursor:break
                    assert count == len(baseline)
                    receipt['years'].append({'year':year,'fixtures_checked':count,'cases':dict(cases),
                                             'distinct_stage_names':len(unique),'unavailable_groups':len(page['coverage']['unavailable_group_indices'])})
            finally:
                await call('fm_detach')
    receipt.update(verified=True,foreground_ui_used=False,native_execution=False)
    (ROOT/'evidence/live-fixture-names-mcp.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='readbacks'},indent=2))


if __name__ == '__main__':
    asyncio.run(verify())
