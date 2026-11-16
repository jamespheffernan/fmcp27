import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_public_saved_match_schema_and_validation_without_attach():
    async def check():
        root = Path(__file__).resolve().parents[1]
        params = StdioServerParameters(command=sys.executable, args=['-m', 'fm_live_mcp.server'], cwd=str(root))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tools = (await client.list_tools()).tools
                tool, = [t for t in tools if t.name == 'fm_get_saved_match_player_statistics']
                assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
                schema = tool.inputSchema
                assert set(schema['required']) == {'filename', 'fixture_key', 'person_index', 'expected_snapshot_id'}
                for field in ('fixture_key', 'person_index'):
                    assert schema['properties'][field]['minimum'] == 0
                    assert schema['properties'][field]['exclusiveMaximum'] == 2**31
                for invalid in ({'fixture_key': True}, {'fixture_key': -1}, {'person_index': '13009'}, {'person_index': 2**31}):
                    result = await client.call_tool(tool.name, {'filename': 'missing.fm', 'fixture_key': 135195, 'person_index': 13009, 'expected_snapshot_id': 'a'*64, **invalid})
                    assert result.isError
                    assert 'validation error' in ' '.join(getattr(c, 'text', '') for c in result.content).lower()
                status = await client.call_tool('fm_status')
                assert not status.isError
                assert status.structuredContent['session_id'] is None
    asyncio.run(check())
