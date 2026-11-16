"""Compare public language/region queries and city links against independent censuses."""
import argparse
import asyncio
from collections import Counter
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import struct
import tomllib

from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT=Path(__file__).resolve().parents[1]


def check_identity(actual,expected):
    if expected is None:
        assert actual is None
        return
    assert actual is not None
    for key,value in expected.items():
        if key in ('native_id','database_index','name','short_name','abbreviation'):assert actual[key]==value,(key,actual,expected)


def check_language(row,source,enums):
    check_identity(row,source)
    assert row['language_ref'] and row['kind']=='language' and row['name_source']=='stored_native_strings'
    assert row['is_deleted']==(source['family']==-1)
    for field,key in (('family','Lfam'),('group','Lgro'),('subgroup','Lsub')):
        code=source[field];label=enums[key].get(str(code))
        assert row[field]=={'native_code':code,'name':label,'state':'decoded' if label is not None else 'unmapped'}
    for field in ('difficulty','influence'):assert row[field]==source[field]
    check_identity(row['nation'],source['nation'])


def check_region(row,source):
    check_identity(row,source)
    assert row['local_region_ref'] and row['kind']=='local_region' and row['name_source']=='stored_native_strings'
    assert row['population']==source['population']
    for field in ('nation','weather'):check_identity(row[field],source[field])
    assert row['complete_native_language_vector'] and row['language_count']==len(source['languages'])==len(row['languages'])
    for i,(actual,expected) in enumerate(zip(row['languages'],source['languages'],strict=True)):
        check_identity(actual['language'],expected['language']);value=expected['percentage_native']
        assert actual['native_index']==i and actual['percentage_native']==value
        assert actual['percentage_state']==('stored' if 0<=value<=100 else 'out_of_range')
        if actual['language']:assert actual['language']['language_ref'] and actual['language']['kind']=='language'


def checkpoint(path,receipt,identity):
    temporary=path.with_suffix('.tmp');temporary.write_text(json.dumps({**receipt,'source_identity':identity},indent=2)+'\n');temporary.replace(path)


async def verify(resume=False):
    names=('language-region-detail-survey.json','language-region-layout-verification.json','city-survey.json','city-linked-record-survey.json')
    sources={name:json.loads((ROOT/'evidence'/name).read_text()) for name in names}
    assert all(s['verified'] for s in sources.values())
    records=sources[names[0]]['records'];enums=sources[names[1]]['language_enums'];cities=sources[names[2]]['cities']
    linked={kind:{int(r['address'],16):r for r in table['records']} for kind,table in sources[names[3]]['tables'].items()}
    languages_by_id={r['native_id']:r for r in records['language']};regions_by_id={r['native_id']:r for r in records['local_region']}
    files=sorted((ROOT/'fm_live_mcp').glob('*.py'))+[ROOT/'evidence'/name for name in names]
    identity={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    saved=ROOT/'evidence/language-region-verification-checkpoint.json'
    receipt={'verified':False,'server_version':'0.31.0','started_at':datetime.now(timezone.utc).isoformat()}
    if resume:
        receipt=json.loads(saved.read_text());assert receipt.pop('source_identity')==identity
    config=tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    async with stdio_client(StdioServerParameters(command=config['command'],args=config['args'])) as (read,write):
        async with ClientSession(read,write) as client:
            await client.initialize()
            async def call(tool,**args):
                for attempt in range(5):
                    result=await client.call_tool(tool,args)
                    if not result.isError or 'changed during read' not in str(result.content) or attempt==4:break
                    await asyncio.sleep(.2)
                assert not result.isError and result.structuredContent is not None,(tool,args,result.content)
                return result.structuredContent
            status=await call('fm_status');assert status['server_version']=='0.31.0'
            assert status['capabilities']['language_query'] and status['capabilities']['local_region_query'] and not status['capabilities']['memory_writes']
            tools=(await client.list_tools()).tools;assert len(tools)==45 and all(t.annotations.readOnlyHint for t in tools)
            sid=(await call('fm_attach'))['session_id']
            try:
                for kind,key,check in (('language','languages',lambda row,src:check_language(row,src,enums)),('local_region','local_regions',check_region)):
                    if key in receipt:continue
                    cursor=None;count=0;cases=set();dates=set();entries=0;children=set()
                    while True:
                        page=await call('fm_find_'+key,session_id=sid,max_matches=100,cursor=cursor)
                        assert page['start_index']==count
                        for row in page[key]:
                            source=records[kind][count];check(row,source)
                            case=(source['family'],source['group'],source['subgroup']) if kind=='language' else (
                                len(source['languages']),source['weather'] is None,source['population']==0,
                                sum(e['percentage_native'] for e in source['languages'])>100)
                            if case not in cases:
                                fresh=(await call('fm_get_'+kind,session_id=sid,**{kind+'_ref':row[kind+'_ref']}))[kind]
                                check(fresh,source);cases.add(case)
                            if kind=='local_region':
                                entries+=len(row['languages'])
                                for e in row['languages']:
                                    if e['language'] and e['language']['native_id'] not in children:
                                        child=(await call('fm_get_language',session_id=sid,language_ref=e['language']['language_ref']))['language']
                                        check_language(child,languages_by_id[child['native_id']],enums);children.add(child['native_id'])
                            count+=1
                        dates.add(page['save']['current_date']);cursor=page['next_cursor']
                        if count%500==0:print(f'{key}: {count}/{len(records[kind])}',flush=True)
                        if not cursor:break
                    assert count==len(records[kind])
                    receipt[key]={'records_checked':count,'readback_cases':len(cases),'language_entries':entries,
                                  'distinct_child_languages_opened':len(children),'complete_scan':True,'save_dates':sorted(dates)}
                    checkpoint(saved,receipt,identity);print(key,receipt[key],flush=True)
                if 'city_links' not in receipt:
                    cursor=None;count=0;totals=Counter();cases=set();dates=set()
                    while True:
                        page=await call('fm_find_cities',session_id=sid,max_matches=100,cursor=cursor);assert page['start_index']==count
                        for row in page['cities']:
                            source=cities[count];check_identity(row,source);raw=bytes.fromhex(source['raw'])
                            case=tuple(row[k] is None for k in ('language','local_region'))
                            for kind,offset in (('language',0x30),('local_region',0x38)):
                                pointer=struct.unpack_from('<Q',raw,offset)[0]
                                expected=linked[kind][pointer] if pointer else None;check_identity(row[kind],expected)
                                if expected:
                                    totals[kind]+=1;assert row[kind][kind+'_ref']
                                    if case not in cases:
                                        detail=(await call('fm_get_'+kind,session_id=sid,**{kind+'_ref':row[kind][kind+'_ref']}))[kind]
                                        if kind=='language':check_language(detail,languages_by_id[detail['native_id']],enums)
                                        else:check_region(detail,regions_by_id[detail['native_id']])
                            if case not in cases:
                                fresh=(await call('fm_get_city',session_id=sid,city_ref=row['city_ref']))['city']
                                for kind in ('language','local_region'):check_identity(fresh[kind],row[kind])
                                cases.add(case)
                            count+=1
                        dates.add(page['save']['current_date']);cursor=page['next_cursor']
                        if count%4000==0:print(f'City geographic links: {count}/{len(cities)}',flush=True)
                        if not cursor:break
                    assert count==len(cities)
                    receipt['city_links']={'records_checked':count,'linked_counts':dict(totals),'readback_cases':len(cases),'complete_scan':True,'save_dates':sorted(dates)}
                    checkpoint(saved,receipt,identity)
                if 'filters' not in receipt:
                    filters=[]
                    for kind,key,args in (
                        ('language','languages',{'name':'English'}),('language','languages',{'native_id':records['language'][0]['native_id']}),
                        ('language','languages',{'nation':'England','maximum_difficulty':10,'minimum_influence':1}),
                        ('language','languages',{'nation_native_id':records['language'][0]['nation']['native_id']}),
                        ('language','languages',{'is_deleted':True}),('local_region','local_regions',{'name':'Yorkshire'}),
                        ('local_region','local_regions',{'native_id':records['local_region'][0]['native_id']}),
                        ('local_region','local_regions',{'nation':'England','minimum_population':1}),
                        ('local_region','local_regions',{'nation_native_id':records['local_region'][0]['nation']['native_id']})):
                        def matches(r):
                            country=r['nation']
                            return (('name' not in args or args['name'].casefold() in (r['name'] or '').casefold()) and
                                ('native_id' not in args or r['native_id']==args['native_id']) and
                                ('nation_native_id' not in args or country is not None and country['native_id']==args['nation_native_id']) and
                                ('nation' not in args or country is not None and any(args['nation'].casefold() in (country[k] or '').casefold() for k in ('short_name','abbreviation'))) and
                                ('minimum_population' not in args or r['population']>=args['minimum_population']) and
                                ('maximum_difficulty' not in args or r['difficulty']<=args['maximum_difficulty']) and
                                ('minimum_influence' not in args or r['influence']>=args['minimum_influence']) and
                                ('is_deleted' not in args or (r['family']==-1)==args['is_deleted']))
                        ids=[];cursor=None;end=0
                        while True:
                            page=await call('fm_find_'+key,session_id=sid,max_matches=100,cursor=cursor,**args)
                            assert page['start_index']==end;end=page['next_index'];ids.extend(r['native_id'] for r in page[key]);cursor=page['next_cursor']
                            if not cursor:break
                        assert ids==[r['native_id'] for r in records[kind] if matches(r)]
                        filters.append({'kind':kind,'criteria':args,'matches':len(ids),'records_checked':end,'complete_scan':True})
                        print('Filter',kind,args,len(ids),flush=True)
                    newcastle=next(c for c in cities if c['native_id']==100065)
                    ptr=struct.unpack_from('<Q',bytes.fromhex(newcastle['raw']),0x38)[0];region_id=linked['local_region'][ptr]['native_id']
                    direct=next(c for c in cities if struct.unpack_from('<Q',bytes.fromhex(c['raw']),0x30)[0])
                    pointer=struct.unpack_from('<Q',bytes.fromhex(direct['raw']),0x30)[0];language_id=linked['language'][pointer]['native_id']
                    for args,offset,kind,complete in (({'local_region_native_id':region_id},0x38,'local_region',True),({'language_native_id':language_id},0x30,'language',False)):
                        ids=[];cursor=None;end=0;pages=0
                        while True:
                            page=await call('fm_find_cities',session_id=sid,max_matches=100,cursor=cursor,**args)
                            assert page['start_index']==end;end=page['next_index'];ids.extend(r['native_id'] for r in page['cities']);cursor=page['next_cursor'];pages+=1
                            if not cursor or not complete and pages==3:break
                        def matches_city(r):
                            pointer=struct.unpack_from('<Q',bytes.fromhex(r['raw']),offset)[0]
                            return bool(pointer) and linked[kind][pointer]['native_id']==next(iter(args.values()))
                        assert ids==[r['native_id'] for r in cities[:end] if matches_city(r)]
                        filters.append({'kind':'city','criteria':args,'matches':len(ids),'records_checked':end,'complete_scan':cursor is None})
                        print('Filter city',args,len(ids),'through',end,flush=True)
                    receipt['filters']=filters;checkpoint(saved,receipt,identity)
            finally:await call('fm_detach')
    assert identity=={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    receipt.update(verified=True,completed_at=datetime.now(timezone.utc).isoformat(),foreground_ui_used=False,native_execution=False)
    (ROOT/'evidence/live-language-regions-mcp.json').write_text(json.dumps({**receipt,'source_identity':identity},indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--resume',action='store_true')
    asyncio.run(verify(parser.parse_args().resume))
