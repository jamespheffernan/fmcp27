"""Real private server discovery/validation; deliberately never attach."""
import asyncio
from pathlib import Path
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_concern_history_stdio_discovery_schema_and_rejection_without_attachment():
    async def check():
        params = StdioServerParameters(command=sys.executable,
            args=['-m', 'fm_live_mcp.server'], cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                initialized = await client.initialize()
                assert 'fm_get_player_concern_history' in initialized.instructions
                tool = next(tool for tool in (await client.list_tools()).tools
                            if tool.name == 'fm_get_player_concern_history')
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is tool.annotations.openWorldHint is False
                schema = tool.inputSchema
                assert set(schema['required']) == {'session_id', 'player_refs'}
                assert set(schema['properties']) == {'session_id', 'player_refs', 'coach_name', 'include_templates', 'include_promises'}
                assert schema['properties']['include_templates']['default'] is False
                assert schema['properties']['include_promises']['default'] is False
                refs = schema['properties']['player_refs']
                assert (refs['minItems'], refs['maxItems'], refs['uniqueItems']) == (1, 100, True)
                for invalid in ({'player_refs': []}, {'player_refs': ['p'] * 101},
                        {'player_refs': ['']}, {'player_refs': [True]}, {'include_templates': 1},
                        {'include_templates': 'true'}, {'include_templates': None}, {'include_promises': 1}, {'include_promises': 'true'},
                        {'include_promises': None}, {'coach_name': True}):
                    result = await client.call_tool(tool.name,
                        {'session_id': 'deliberately-unattached', 'player_refs': ['p'], **invalid})
                    assert result.isError
                    assert 'validation error' in ' '.join(getattr(item, 'text', '') for item in result.content).lower()
                duplicate = await client.call_tool(tool.name,
                    {'session_id': 'deliberately-unattached', 'player_refs': ['p', 'p']})
                assert duplicate.isError and 'distinct' in duplicate.content[0].text
                unattached = await client.call_tool(tool.name,
                    {'session_id': 'deliberately-unattached', 'player_refs': ['p']})
                assert unattached.isError and 'Unknown session' in unattached.content[0].text
    asyncio.run(check())
