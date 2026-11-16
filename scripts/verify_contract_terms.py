"""Live stdio readback of contract terms; run survey_contract_terms.py first."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def verify():
    root = Path(__file__).resolve().parents[1]
    survey = json.loads((root/'evidence/contract-term-survey.json').read_text())
    assert not survey['errors'] and survey['complete_native_table_scan']
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'verified': False, 'sample_people': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    response = await client.call_tool(tool, args)
                    if response.isError or response.structuredContent is None: raise RuntimeError(str(response.content))
                    return response.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(t.annotations.readOnlyHint for t in tools)
                assert (await call('fm_status'))['capabilities']['contract_terms']
                sid = (await call('fm_attach'))['session_id']
                roster = await call('fm_get_club_staff', session_id=sid, include_contract_terms=True)
                for row in roster['staff']:
                    fresh = await call('fm_get_contract_terms', session_id=sid, staff_ref=row['staff_ref'])
                    assert fresh['contract_terms'] == row['contract']['terms']
                # Refind each survey sample by checked public identity, never by an address.
                samples = {r['database_index']: r for r in survey['samples'].values()}
                if survey['expiry_sample']: samples[survey['expiry_sample']['database_index']] = survey['expiry_sample']
                observed_kinds, expiry_dates = set(), []
                for sample in samples.values():
                    is_staff = sample['record_kind'] != 'player'
                    collection, refkey = ('staff', 'staff_ref') if is_staff else ('players', 'player_ref')
                    found = await call('fm_find_staff' if is_staff else 'fm_find_save_players', session_id=sid, name=sample['name'])
                    matches = [r for r in found[collection] if r['name'] == sample['name'] and r['birth_date'] == sample['birth_date']]
                    assert len(matches) == 1, sample['name']
                    args = {'session_id': sid, refkey: matches[0][refkey]}
                    result = await call('fm_get_contract_terms', **args)
                    again = await call('fm_get_contract_terms', **args)
                    terms = result['contract_terms']
                    assert terms == again['contract_terms'] == sample['contract_terms'], sample['name']
                    assert terms['native_entry_count'] == len(terms['terms']) + len(terms['unmapped_entries'])
                    observed_kinds.update(r['native_kind'] for r in terms['terms'] + terms['unmapped_entries'])
                    expiry_dates.extend(r['values']['expiry']['date'] for r in terms['terms'] if r['values'].get('expiry', {}).get('date'))
                    old = (await call('fm_get_staff' if is_staff else 'fm_get_player', **args, include_contract_bonuses=True))[collection[:-1] if collection == 'players' else collection]
                    bonuses = old['contract']['bonuses'] if is_staff else old['contract_bonuses']
                    for name, value in bonuses['bonuses'].items():
                        candidates = [r for r in terms['terms'] if r['kind'] == name and r['selected_by_native_property']]
                        assert len(candidates) <= 1
                        assert value['amount'] == (candidates[0]['values']['amount_gbp'] if candidates else None)
                    evidence['sample_people'].append({'name': sample['name'], 'record_kind': sample['record_kind'], 'contract_terms': terms})
                assert observed_kinds == {int(k) for k in survey['samples']}
                assert expiry_dates
                squads = await call('fm_get_club_squads', session_id=sid)
                player_count, virtual_count, seen = 0, 0, set()
                for team in squads['squads']:
                    squad = await call('fm_get_team_squad', session_id=sid, team_ref=team['team_ref'])
                    for row in squad['players']:
                        key = (row['name'], row['birth_date'])
                        if key in seen: continue
                        seen.add(key)
                        if row.get('record_kind') == 'virtual':
                            response = await client.call_tool('fm_get_contract_terms', {'session_id': sid, 'player_ref': row['player_ref']})
                            assert response.isError
                            virtual_count += 1
                            continue
                        result = await call('fm_get_contract_terms', session_id=sid, player_ref=row['player_ref'])
                        assert result['person']['name'] == row['name']
                        assert result['contract_terms']['state'] in ('decoded', 'no_contract', 'basic_contract_terms_unavailable')
                        player_count += 1
                for options in ({}, {'player_ref': 'p', 'staff_ref': 's'}, {'player_ref': ''}, {'staff_ref': 1}):
                    assert (await client.call_tool('fm_get_contract_terms', {'session_id': sid, **options})).isError
                assert (await client.call_tool('fm_get_club_staff', {'session_id': sid, 'include_contract_terms': 'true'})).isError
                # Combined player/staff parity through both supported reference types.
                found = await call('fm_find_staff', session_id=sid, name='Mohamed Salah')
                staff_ref = next(r['staff_ref'] for r in found['staff'] if r['birth_date'] == '1992-06-15')
                found = await call('fm_find_save_players', session_id=sid, name='Mohamed Salah')
                player_ref = next(r['player_ref'] for r in found['players'] if r['birth_date'] == '1992-06-15')
                assert (await call('fm_get_contract_terms', session_id=sid, staff_ref=staff_ref))['contract_terms'] == (await call('fm_get_contract_terms', session_id=sid, player_ref=player_ref))['contract_terms']
                await call('fm_detach')
                assert (await client.call_tool('fm_get_contract_terms', {'session_id': sid, 'player_ref': player_ref})).isError
                evidence.update(verified=True, tool_count=len(tools), staff_count=roster['count'], player_count=player_count,
                    virtual_rejections=virtual_count, sample_people_count=len(samples), live_entry_kinds=sorted(observed_kinds),
                    release_expiry_dates=expiry_dates, surveyed_person_count=survey['seen'],
                    surveyed_full_contracts=survey['counts']['full_contract'],
                    scope='Public reference searches, all observed entry kinds, repeated sample reads, bonus parity, native release-date calculation, managed club coverage, strict selectors, combined record parity and detach. No UI or activation evaluation.')
                print(json.dumps({k: evidence[k] for k in ('verified', 'staff_count', 'player_count', 'sample_people_count', 'live_entry_kinds', 'release_expiry_dates')}, indent=2))
    finally:
        path = root/'evidence/live-contract-terms-mcp.json'
        path.write_text(json.dumps(evidence, indent=2)+'\n')
        print(path)


if __name__ == '__main__': asyncio.run(verify())
