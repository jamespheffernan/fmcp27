"""Verify fresh stored staff ratings, native job titles and filtering through the real MCP transport."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def identity(person):
    return person['name'], person['birth_date'], person['record_kind']


def without_ref(person):
    return {key: value for key, value in person.items() if key != 'staff_ref'}


def check_ratings(person):
    assert len(person['attributes']) == 23
    assert len(person['tendencies']) == 12
    assert len(person['board_attributes']) == 4
    assert all(type(value) is int and 0 <= value <= 20
               for group in ('attributes', 'tendencies', 'board_attributes') for value in person[group].values())
    assert person['attribute_evidence'] == 'installed_editor_property_names_and_native_getter_mapping'


async def verify():
    root = Path(__file__).resolve().parents[1]
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'transport': 'stdio', 'steps': []}
    try:
        async with stdio_client(StdioServerParameters(command='/bin/sh', args=[str(root/'scripts/run_mcp.sh')])) as (read, write):
            async with ClientSession(read, write) as client:
                await client.initialize()
                async def call(tool, **args):
                    response = await client.call_tool(tool, args)
                    evidence['steps'].append({'tool': tool, 'error': response.isError, 'result': response.structuredContent})
                    if response.isError or response.structuredContent is None: raise RuntimeError(str(response.content))
                    return response.structuredContent
                tools = (await client.list_tools()).tools
                assert len(tools) == 28 and all(tool.annotations.readOnlyHint for tool in tools)
                sid = (await call('fm_attach'))['session_id']
                plain = await call('fm_get_club_staff', session_id=sid)
                full = await call('fm_get_club_staff', session_id=sid, include_attributes=True, include_job=True)
                assert [identity(p) for p in plain['staff']] == [identity(p) for p in full['staff']]
                assert all('attributes' not in p for p in plain['staff'])
                checked_kinds = set()
                for person in full['staff']:
                    check_ratings(person)
                    fresh = (await call('fm_get_staff', session_id=sid, staff_ref=person['staff_ref'],
                                        include_club=True, include_attributes=True, include_job=True))['staff']
                    assert fresh == without_ref(person)
                    checked_kinds.add(person['record_kind'])
                for minimum, sort_by, limit in (({'attacking': 15, 'motivating': 15}, 'determination', 5),
                                                 ({}, 'physiotherapy', 3), ({'attacking': 20}, None, 100)):
                    result = await call('fm_query_club_staff', session_id=sid, minimum_attributes=minimum,
                                        sort_by=sort_by, limit=limit)
                    expected = [p for p in full['staff'] if all(p['attributes'][key] >= value for key, value in minimum.items())]
                    expected.sort(key=lambda p: (-p['attributes'][sort_by] if sort_by else 0, p['display_name'].casefold(), p['birth_date']))
                    assert result['matched_count'] == len(expected)
                    assert result['returned_count'] == min(limit, len(expected))
                    assert result['truncated'] == (len(expected) > limit)
                    assert [without_ref(p) for p in result['staff']] == [without_ref(p) for p in expected[:limit]]
                assert all(person['contract']['job']['state'] == 'decoded' for person in full['staff'])
                assert next(p for p in full['staff'] if p['name'] == 'Paul Catterson')['contract']['job']['title'] == 'Chief Doctor'
                assert next(p for p in full['staff'] if p['record_kind'] == 'human_manager')['contract']['job']['title'] == 'Manager First Team'
                for job_text in ('physio', ' GK Coach ', 'Loan Manager'):
                    filtered = await call('fm_query_club_staff', session_id=sid, job_contains=job_text, limit=100)
                    expected = [p for p in full['staff'] if job_text.strip().casefold() in p['contract']['job']['title'].casefold()]
                    assert filtered['unmapped_job_count'] == 0 and filtered['matched_count'] == len(expected)
                    assert [without_ref(p) for p in filtered['staff']] == [without_ref(p) for p in expected]
                found = await call('fm_find_staff' , session_id=sid, name='Mohamed Salah')
                salah = next(p for p in found['staff'] if p['birth_date'] == '1992-06-15')
                combined = (await call('fm_get_staff', session_id=sid, staff_ref=salah['staff_ref'], include_attributes=True, include_job=True))['staff']
                check_ratings(combined)
                assert combined['contract']['job']['state'] == 'decoded'
                checked_kinds.add(combined['record_kind'])
                assert checked_kinds == {'staff', 'human_manager', 'player_staff'}
                clubs = await call('fm_find_clubs', session_id=sid, name='Liverpool', max_matches=100)
                club_counts = []
                for club in clubs['clubs']:
                    if club['name'] != 'Liverpool' or club['short_name'] != 'Liverpool': continue
                    roster = await call('fm_get_club_staff', session_id=sid, club_ref=club['club_ref'], include_attributes=True, include_job=True)
                    for person in roster['staff']:
                        check_ratings(person)
                        assert person['contract']['job']['state'] == 'decoded'
                    club_counts.append(roster['count'])
                assert len(club_counts) == 2
                for arguments in ({'minimum_attributes': {'attacking': True}}, {'sort_by': 'vision'}, {'limit': 0}):
                    assert (await client.call_tool('fm_query_club_staff', {'session_id': sid, **arguments})).isError
                await call('fm_detach')
                evidence.update(verified=True, managed_club_count=full['count'], other_club_counts=club_counts,
                                record_kinds=sorted(checked_kinds), tool_count=len(tools),
                                validation_scope='Native stored ratings and job titles, fresh readback and filter behavior. No role/UI suppression or foreground UI comparison.')
                print(f"Verified {full['count']} fresh staff reads, three record layouts, native jobs, filters, and other club counts {club_counts}.", flush=True)
    finally:
        output = root/'evidence/live-staff-attributes-mcp.json'
        output.write_text(json.dumps(evidence, indent=2)+'\n')
        print(output)


if __name__ == '__main__': asyncio.run(verify())
