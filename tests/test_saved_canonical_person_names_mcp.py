import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_read_only_schema_strict_selectors_and_work_limits():
    async def check():
        params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tools=(await client.list_tools()).tools
                tool=next(t for t in tools if t.name=='fm_query_saved_people_by_name')
                assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
                props=tool.inputSchema['properties']
                assert set(tool.inputSchema['required'])=={'filename','expected_snapshot_id'}
                assert set(props)=={'filename','expected_snapshot_id','first_name','surname','common_name','any_name','match_mode','cursor','limit','scan_limit'}
                assert props['limit']['maximum']==50 and props['scan_limit']['maximum']==10000
                assert 'fm_find_saved_people' in {t.name for t in tools}
                for extra in ({'first_name':True},{'surname':''},{'match_mode':'bad'},{'limit':True},
                              {'limit':51},{'scan_limit':True},{'scan_limit':10001}):
                    out=await client.call_tool(tool.name,{'filename':'missing.fm','expected_snapshot_id':'pin','surname':'Silva',**extra})
                    assert out.isError
                    assert 'missing.fm' not in ' '.join(getattr(c,'text','')for c in out.content)
    asyncio.run(check())


def test_dispatch_keeps_canonical_and_existing_fast_paths_separate(monkeypatch):
    from fm_live_mcp import server
    seen=[]
    monkeypatch.setattr(server.saved_canonical_person_names,'find_people',lambda *a,**k:seen.append((a,k))or{'state':'partial'})
    def fast(*args,**kwargs):raise AssertionError('Canonical query must not run suffix-candidate discovery')
    monkeypatch.setattr(server.saved_person_name_search,'find_people',fast)
    assert server.fm_query_saved_people_by_name('save.fm','pin',first_name='Claudio',surname='Silva',any_name='Sil',match_mode='prefix',cursor='opaque',limit=2,scan_limit=10)=={'state':'partial'}
    assert seen==[(('save.fm','pin'),{'first_name':'Claudio','surname':'Silva','common_name':None,'any_name':'Sil','match_mode':'prefix','cursor':'opaque','limit':2,'scan_limit':10})]
