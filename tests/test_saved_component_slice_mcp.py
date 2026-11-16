import asyncio
from pathlib import Path
import sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def test_component_slice_staged_schema_and_strict_validation():
    async def run():
        params=StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'],cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as(read,write):
            async with ClientSession(read,write) as client:
                await client.initialize();tools=(await client.list_tools()).tools
                tool=next(t for t in tools if t.name=='fm_get_saved_component_slice')
                assert len(tools)==202 and tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is False
                schema=tool.inputSchema
                assert set(schema['required'])=={'filename','member_path','expected_snapshot_id'}
                assert set(schema['properties'])=={'filename','member_path','expected_snapshot_id','offset','limit'}
                assert schema['properties']['limit']['maximum']==16384
                for bad in [{'offset':True},{'offset':-1},{'limit':16385},{'member_path':1}]:
                    response=await client.call_tool(tool.name,{'filename':'none.fm','member_path':'career/unknown.bin','expected_snapshot_id':'pin',**bad})
                    assert response.isError
    asyncio.run(run())
