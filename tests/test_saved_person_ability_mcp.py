import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from fm_live_mcp import server


def test_wrapper_forwards_strict_optional_ability(monkeypatch):
    calls = []
    monkeypatch.setattr(server.saved_person_search, 'get_name_candidates',
                        lambda *args, **kwargs: calls.append((args, kwargs)) or {'checked': True})
    assert server.fm_get_saved_person_name_candidates('career.fm', [7], 'pin') == {'checked': True}
    assert calls[-1][1]['include_ability'] is False
    server.fm_get_saved_person_name_candidates('career.fm', [7], 'pin', include_ability=True)
    assert calls[-1][1]['include_ability'] is True


def test_configured_stdio_schema_and_strict_ability_type():
    async def check():
        root = Path(__file__).resolve().parents[1]
        parameters = StdioServerParameters(command=sys.executable,
                                           args=['-m', 'fm_live_mcp.server'], cwd=str(root))
        async with stdio_client(parameters) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tool, = [t for t in (await client.list_tools()).tools
                         if t.name == 'fm_get_saved_person_name_candidates']
                field = tool.inputSchema['properties']['include_ability']
                assert field['type'] == 'boolean' and field['default'] is False
                assert 'include_ability' not in tool.inputSchema['required']
                assert tool.annotations.readOnlyHint
                for bad in (0, 1, 'true', None):
                    reply = await client.call_tool(tool.name, {
                        'filename': 'missing.fm', 'person_indices': [7],
                        'expected_snapshot_id': 'pin', 'include_ability': bad,
                    })
                    assert reply.isError
                    assert 'include_ability' in str(reply.content)
    asyncio.run(check())
