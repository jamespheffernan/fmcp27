"""Explicit live MCP acceptance steps; never advances or saves the career.

Run --stage dry first, then apply and restore as separate observed operations.
Only this named player, original Default255 and temporary Half0 are admitted.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


async def verify(stage):
    evidence = {'stage': stage, 'steps': []}
    destination = ROOT / 'evidence/training-edit-20261109' / f'{stage}.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(ROOT / 'scripts/run_mcp.sh')],
                                                     env={**os.environ, 'FMCP_EXTENSIONS': 'fm_live_write'})) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(name, **kwargs):
                    response = await client.call_tool(name, kwargs)
                    evidence['steps'].append(dict(tool=name, arguments=kwargs,
                                                  error=response.isError, result=response.structuredContent,
                                                  message=str(response.content) if response.isError else None))
                    if response.isError or response.structuredContent is None:
                        raise RuntimeError(str(response.content))
                    return response.structuredContent
                status = await call('fm_status')
                assert status['server_version'] == '0.159.0'
                listed = await client.list_tools()
                tool, = [t for t in listed.tools if t.name == 'fm_set_player_training_intensity']
                assert tool.annotations.readOnlyHint is False
                sid = (await call('fm_attach'))['session_id']
                squad = await call('fm_get_managed_squad', session_id=sid, profile_policy='available')
                player, = [p for p in squad['players'] if p['name'] == 'Nick Woltemade']
                ref = player['player_ref']
                before = await call('fm_get_player_individual_training', session_id=sid, player_refs=[ref])
                assert before['players'][0]['native_identity']['native_id'] == 91187791
                expected = 0 if stage == 'restore' else 255
                assert before['players'][0]['club_training_intensity']['raw_code'] == expected
                result = await call('fm_set_player_training_intensity', session_id=sid, player_ref=ref,
                                    intensity='default' if stage == 'restore' else 'half',
                                    expected_raw_code=expected, dry_run=stage == 'dry')
                after = await call('fm_get_player_individual_training', session_id=sid, player_refs=[ref])
                wanted = 255 if stage in ('dry', 'restore') else 0
                assert after['players'][0]['club_training_intensity']['raw_code'] == wanted
                evidence['verified'] = True
                print(json.dumps(dict(stage=stage, name=result['name'], state=result['state'],
                                      write_performed=result['write_performed'], after_raw=wanted,
                                      receipt_path=result.get('receipt_path'), evidence=str(destination)), indent=2))
    finally:
        destination.write_text(json.dumps(evidence, indent=2) + '\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['dry', 'apply', 'restore'], required=True)
    asyncio.run(verify(parser.parse_args().stage))
