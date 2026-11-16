import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def test_saved_history_schema_and_strict_filters():
    async def check():
        params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params)as(read,write):
            async with ClientSession(read,write)as client:
                await client.initialize()
                tools=(await client.list_tools()).tools
                tool=next(t for t in tools if t.name=='fm_get_saved_player_statistics_history')
                assert tool.annotations.readOnlyHint and tool.annotations.destructiveHint is False
                assert set(tool.inputSchema['required'])=={'filename','person_index','expected_snapshot_id'}
                assert 'session_id'not in tool.inputSchema['properties']
                for extra in ({'years':[]},{'category_codes':[]},{'years':[True]},{'category_codes':[6]},{'person_index':True},{'limit':201}):
                    args={'filename':'missing.fm','person_index':0,'expected_snapshot_id':'pin',**extra}
                    assert(await client.call_tool(tool.name,args)).isError
    asyncio.run(check())
