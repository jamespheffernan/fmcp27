import asyncio
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def test_inventory_tool_is_read_only_and_paths_are_not_parameters():
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params)as(read,write):
            async with ClientSession(read,write)as client:
                await client.initialize();tools=(await client.list_tools()).tools
                tool=next(t for t in tools if t.name=='fm_get_saved_history_inventory')
                assert tool.annotations.readOnlyHint and tool.annotations.destructiveHint is False
                schema=tool.inputSchema
                assert set(schema['required'])=={'filename','expected_snapshot_id'}
                assert set(schema['properties'])=={'filename','expected_snapshot_id','family','owner_index','offset','limit'}
                assert schema['properties']['limit']['maximum']==200
                for extra in ({'family':'../../secret'},{'owner_index':0},{'owner_index':True},{'offset':1},{'limit':201}):
                    assert(await client.call_tool(tool.name,{'filename':'missing.fm','expected_snapshot_id':'pin',**extra})).isError
    asyncio.run(run())
