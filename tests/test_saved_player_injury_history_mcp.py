import asyncio
from pathlib import Path
import sys
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_schema_read_only_and_strict_filter_regression():
    async def check():
        params = StdioServerParameters(command=sys.executable, args=['-m', 'fm_live_mcp.server'],
                                       cwd=str(Path(__file__).resolve().parents[1]))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                tool = next(t for t in (await client.list_tools()).tools if t.name == 'fm_get_saved_player_injury_history')
                assert tool.annotations.readOnlyHint is True
                assert tool.annotations.destructiveHint is False and tool.annotations.openWorldHint is False
                schema = tool.inputSchema
                assert set(schema['required']) == {'filename', 'person_index', 'expected_snapshot_id'}
                assert set(schema['properties']) == {'filename', 'person_index', 'expected_snapshot_id', 'date_from', 'date_to', 'injury_native_ids', 'offset', 'limit', 'include_installed_names'}
                assert schema['properties']['include_installed_names']['type'] == 'boolean'
                assert schema['properties']['include_installed_names']['default'] is False
                assert schema['properties']['limit']['maximum'] == 200
                assert schema['properties']['limit']['default'] == 50
                assert schema['properties']['person_index']['exclusiveMaximum'] == 2**31
                for extra in ({'person_index': True}, {'person_index': -1}, {'person_index': 2**31},
                              {'injury_native_ids': []}, {'injury_native_ids': [True]}, {'injury_native_ids': [2**32]},
                              {'date_from': True}, {'date_from': '20300101'}, {'date_to': '2030-02-29'},
                              {'date_from': '2030-01-02', 'date_to': '2030-01-01'},
                              {'limit': True}, {'limit': 201}, {'offset': True},
                              {'include_installed_names': 1}, {'include_installed_names': 'true'}):
                    args = {'filename': 'missing.fm', 'person_index': 0, 'expected_snapshot_id': 'pin', **extra}
                    out = await client.call_tool(tool.name, args)
                    assert out.isError
                    assert 'missing.fm' not in ' '.join(getattr(c, 'text', '') for c in out.content)
    asyncio.run(check())


def test_public_dispatch_forwards_all_criteria(monkeypatch):
    from fm_live_mcp import server
    seen = []
    def get(*args, **kwargs):
        seen.append((args, kwargs))
        return {'state': 'available', 'rows': [], 'selected_row_count': 0}
    monkeypatch.setattr(server.saved_player_injury_history, 'get_injury_history', get)
    out = server.fm_get_saved_player_injury_history('career.fm', 13009, 'same-pin',
        date_from='2030-01-01', date_to='2030-10-23', injury_native_ids=[100], offset=1, limit=2,
        include_installed_names=True)
    assert out['state'] == 'available'
    assert seen == [(('career.fm', 13009, 'same-pin'),
                     {'date_from': '2030-01-01', 'date_to': '2030-10-23',
                      'injury_native_ids': [100], 'offset': 1, 'limit': 2,
                      'include_installed_names': True})]
