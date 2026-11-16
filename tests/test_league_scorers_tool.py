import asyncio

import pytest

from fm_live_mcp import server


def test_public_readonly_contract_and_forwarding(monkeypatch):
    tool = next(t for t in asyncio.run(server.mcp.list_tools())
                if t.name == 'fm_get_league_scorers')
    assert set(tool.inputSchema['properties']) == {'session_id', 'competition_ref', 'limit'}
    assert set(tool.inputSchema['required']) == {'session_id', 'competition_ref'}
    assert tool.inputSchema['properties']['limit']['default'] == 10
    assert tool.inputSchema['properties']['limit']['maximum'] == 50
    assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint
    calls = []
    monkeypatch.setattr(server.bridge, 'get_league_scorers',
                        lambda *args: calls.append(args) or {'state': 'fixture'})
    assert server.fm_get_league_scorers('session', 'competition', 5) == {'state': 'fixture'}
    assert calls == [('session', 'competition', 5)]


@pytest.mark.parametrize('limit', [True, 0, 51, '10', None])
def test_invalid_public_limit_uses_tool_error(limit):
    from mcp.server.fastmcp.exceptions import ToolError
    with pytest.raises(ToolError):
        asyncio.run(server.mcp.call_tool('fm_get_league_scorers', {
            'session_id': 'invalid', 'competition_ref': 'invalid', 'limit': limit,
        }))
