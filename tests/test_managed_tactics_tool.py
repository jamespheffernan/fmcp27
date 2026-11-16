"""Public schema and failure contract for the prepared-tactics read."""
import asyncio

import pytest

from fm_live_mcp import server


def test_managed_tactics_tool_schema_and_semantic_boundary():
    tools = asyncio.run(server.mcp.list_tools())
    tool = next(t for t in tools if t.name == 'fm_get_managed_tactics')
    assert set(tool.inputSchema['required']) == {'session_id'}
    assert set(tool.inputSchema['properties']) == {'session_id', 'coach_name', 'include_formation', 'include_instructions', 'include_roles'}
    for flag in ('include_formation', 'include_instructions', 'include_roles'):
        assert tool.inputSchema['properties'][flag]['type'] == 'boolean'
        assert tool.inputSchema['properties'][flag]['default'] is False
    assert tool.inputSchema['properties']['coach_name']['default'] is None
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False
    assert 'primary trained' in tool.description.lower()
    assert 'match' in tool.description.lower()
    assert 'null' in tool.description.lower()


def test_managed_tactics_invalid_session_uses_mcp_error_contract():
    async def check():
        blocks, structured = await server.mcp.call_tool('fm_get_managed_tactics', {'session_id':'invalid'})
        return blocks, structured
    # FastMCP's direct call raises ToolError; the stdio contract serializes it.
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError, match='session|Attach|attach'):
        asyncio.run(check())
