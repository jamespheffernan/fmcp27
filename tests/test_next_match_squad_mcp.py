import asyncio
from fm_live_mcp import server


def test_next_match_read_schema_and_strict_limits():
    async def check():
        tool = next(t for t in await server.mcp.list_tools() if t.name == 'fm_get_next_match_squad')
        assert tool.annotations.readOnlyHint is True
        assert tool.annotations.destructiveHint is False and tool.annotations.openWorldHint is False
        fields = tool.inputSchema['properties']
        assert set(tool.inputSchema['required']) == {'session_id'}
        assert set(fields) == {'session_id', 'coach_name', 'window_days', 'position_minimum', 'max_fixture_pages'}
        assert fields['window_days']['default'] == 35 and fields['position_minimum']['default'] == 15
        assert fields['max_fixture_pages']['maximum'] == 50
        for bad in ({'window_days': True}, {'position_minimum': 0}, {'max_fixture_pages': 51}):
            try:
                await server.mcp.call_tool('fm_get_next_match_squad', {'session_id': 'not-a-session', **bad})
            except Exception as error:
                assert 'validation' in str(error).lower()
            else:
                raise AssertionError('Invalid input reached a successful tool result')
    asyncio.run(check())
