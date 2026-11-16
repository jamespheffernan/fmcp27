"""Check simulation date and relative fixture days in the Newcastle validation career through MCP."""
import asyncio
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import struct
import sys
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge


def raw_date():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge._current(sid)
            tables = bridge._player_layout(process)
            snapshot, save, _ = bridge._world_state(process, tables)
            packed = struct.unpack('<I', snapshot(tables[0]-players.RVA[0]+0x56B1DB8, 4))[0]
            value = date(packed >> 16, 1, 1)+timedelta(days=(packed & 511)-1)
            snapshot.verify()
            bridge._current(sid)
            return value, save['name']
    finally:
        bridge.detach()


async def verify():
    expected, career = raw_date()
    config = tomllib.loads((Path.home()/'.codex/config.toml').read_text())['mcp_servers']['fm-live']
    receipt = {'verified': False, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'configured_launcher': {'command': config['command'], 'args': config['args']}, 'fixtures': []}
    params = StdioServerParameters(command=config['command'], args=config['args'])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(tool, **arguments):
                result = await client.call_tool(tool, arguments)
                assert not result.isError and result.structuredContent is not None, (tool, result.content)
                return result.structuredContent
            status = await call('fm_status')
            receipt['server_version'] = status['server_version']
            assert status['capabilities']['current_game_date']
            sid = (await call('fm_attach'))['session_id']
            try:
                saved = (await call('fm_get_save', session_id=sid))['save']
                assert saved['current_date'] == expected.isoformat() and saved['name'] == career
                receipt['save'] = saved
                coverage = await call('fm_get_fixture_coverage', session_id=sid)
                assert coverage['save']['current_date'] == expected.isoformat()
                for year in (expected.year-5, expected.year, expected.year+1):
                    if year == expected.year:
                        selectors = {'team_native_id': 688, 'date_from': f'{year}-09-01',
                                     'date_to': f'{year}-09-30', 'max_matches': 100}
                    else:
                        selectors = {'max_matches': 2}
                    cursor = None
                    while True:
                        page = await call('fm_find_fixtures', session_id=sid, year=year, cursor=cursor, **selectors)
                        assert page['save']['current_date'] == expected.isoformat()
                        for row in page['fixtures']:
                            difference = date.fromisoformat(row['date']).toordinal()-expected.toordinal()
                            assert row['days_from_current_date'] == difference
                            fresh = await call('fm_get_fixture', session_id=sid, fixture_ref=row['fixture_ref'])
                            assert fresh['save']['current_date'] == expected.isoformat()
                            assert fresh['fixture']['days_from_current_date'] == difference
                            assert fresh['fixture']['date'] == row['date']
                            assert fresh['fixture']['scores'] == row['scores']
                            receipt['fixtures'].append({'date': row['date'], 'days_from_current_date': difference,
                                                        'kickoff_time': row['kickoff_time'], 'kind': row['record_kind']})
                        cursor = page['next_cursor']
                        if year != expected.year or not cursor:
                            break
                assert any(r['days_from_current_date'] < 0 for r in receipt['fixtures'])
                assert any(r['days_from_current_date'] > 0 for r in receipt['fixtures'])
                # Existing roster reads carry the same independently checked simulation date.
                squad = await call('fm_get_managed_squad', session_id=sid)
                assert squad['save']['current_date'] == expected.isoformat()
                receipt['managed_roster_count'] = squad['count']
            finally:
                await call('fm_detach')
            assert (await client.call_tool('fm_get_save', {'session_id': sid})).isError
    assert raw_date() == (expected, career), 'Date or career changed across verification; repeat the check'
    receipt.update(verified=True, foreground_ui_used=False, native_execution=False,
                   comparison='Independent packed global bytes and native semantic proof; no new UI comparison')
    (ROOT/'evidence/live-current-date-mcp.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    asyncio.run(verify())
