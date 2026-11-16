"""Read-only public health schema and validation before source access."""
import asyncio,sys
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client


def test_public_batch_schema_and_invalid_inputs():
    async def check():
        async with stdio_client(StdioServerParameters(command=sys.executable,args=['-m','fm_live_mcp.server'])) as (read,write):
            async with ClientSession(read,write) as client:
                await client.initialize()
                tool=next(t for t in (await client.list_tools()).tools if t.name=='fm_get_saved_player_health')
                assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
                props=tool.inputSchema['properties']
                assert props['person_indices']['maxItems']==32
                assert props['include_installed_names']['default'] is False
                base={'filename':'absent.fm','person_indices':[1],'expected_snapshot_id':'a'*64}
                for changed in [{'person_indices':[]},{'person_indices':[True]},{'person_indices':list(range(33))},{'include_installed_names':1},{'expected_snapshot_id':'stale'}]:
                    assert (await client.call_tool(tool.name,{**base,**changed})).isError
                assert (await client.call_tool('fm_status',{})).structuredContent['session_id'] is None
    asyncio.run(check())
