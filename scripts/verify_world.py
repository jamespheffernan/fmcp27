"""Exercise loaded-save and managed-squad tools through the configured stdio launcher."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    oracle = json.loads((root / 'tests/fixtures/save_ui_oracle.json').read_text())
    profiles = json.loads((root / 'tests/fixtures/player_profile_oracles.json').read_text())
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    params = StdioServerParameters(command='/bin/sh', args=[str(root / 'scripts/run_mcp.sh')])
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                evidence['tools'] = [t.name for t in (await client.list_tools()).tools]
                async def call(name, args):
                    response = await client.call_tool(name, args)
                    evidence['steps'].append({'tool': name, 'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None:
                        raise RuntimeError(str(response.content))
                    return response.structuredContent
                session = (await call('fm_attach', {}))['session_id']
                save = (await call('fm_get_save', {'session_id': session}))['save']
                for field in ('name', 'created_date', 'created_version', 'save_count', 'last_saved_date'):
                    assert save[field] == oracle[field], (field, save[field], oracle[field])
                assert len(save['coaches']) == 1
                assert ' '.join(save['coaches'][0]['name'].split()) == oracle['coach_display_name']
                assert save['coaches'][0]['club']['short_name'] == oracle['club_short_name']
                squad = await call('fm_get_managed_squad', {'session_id': session, 'coach_name': oracle['coach_display_name']})
                assert squad['save'] == save
                assert squad['count'] == oracle['senior_count_label']
                assert set(oracle['visible_member_names']) <= {p['display_name'] for p in squad['players']}
                nick = next(p for p in squad['players'] if p['name'] == 'Nick Woltemade')
                expected = next(p for p in profiles['players'] if p['name'] == nick['name'])
                assert nick['birth_date'] == expected['birth_date']
                assert nick['attributes'] == expected['attributes']
                fresh = await call('fm_get_player', {'session_id': session, 'player_ref': nick['player_ref']})
                assert fresh['player']['attributes'] == nick['attributes']
                bad = await client.call_tool('fm_get_managed_squad', {'session_id': session, 'coach_name': 'not this coach'})
                assert bad.isError
                await call('fm_detach', {})
                assert (await client.call_tool('fm_get_save', {'session_id': session})).isError
                evidence['verified'] = True
                print(f"Verified native save identity, manager-to-club links, {squad['count']} roster players, sampled UI names and fresh Woltemade attributes.")
    finally:
        path = root / 'evidence/live-world-mcp.json'
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(evidence, indent=2) + '\n')
        print(path)


if __name__ == '__main__':
    asyncio.run(verify())
