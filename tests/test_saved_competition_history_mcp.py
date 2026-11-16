import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_schema_read_only_and_strict_native_year_filter():
    async def check():
        params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tool=next(t for t in (await client.list_tools()).tools if t.name=='fm_get_saved_competition_history')
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is False and tool.annotations.openWorldHint is False
                schema=tool.inputSchema
                assert set(schema['required'])=={'filename','competition_index','expected_snapshot_id'}
                assert set(schema['properties'])=={'filename','competition_index','expected_snapshot_id','years','offset','limit'}
                assert schema['properties']['limit']['maximum']==200 and schema['properties']['limit']['default']==50
                assert schema['properties']['competition_index']['exclusiveMaximum']==2**31
                for extra in ({'competition_index':True},{'competition_index':-1},{'competition_index':2**31},
                              {'years':[]},{'years':[True]},{'years':[-32769]},{'years':[32768]},
                              {'limit':True},{'limit':201},{'offset':True}):
                    args={'filename':'missing.fm','competition_index':0,'expected_snapshot_id':'pin',**extra}
                    out=await client.call_tool(tool.name,args)
                    assert out.isError
                    assert 'missing.fm' not in ' '.join(getattr(c,'text','')for c in out.content)
    asyncio.run(check())


def test_public_dispatch_forwards_all_filters_without_game_access(monkeypatch):
    from fm_live_mcp import server
    seen=[]
    def get(*args,**kwargs):
        seen.append((args,kwargs));return {'state':'available','rows':[],'selected_row_count':0}
    monkeypatch.setattr(server.saved_competition_history,'get_history',get)
    out=server.fm_get_saved_competition_history('career.fm',7,'same-pin',years=[2028,2029],offset=1,limit=2)
    assert out['state']=='available'
    assert seen==[(('career.fm',7,'same-pin'),{'years':[2028,2029],'offset':1,'limit':2})]
