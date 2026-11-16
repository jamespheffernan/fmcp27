"""Compare public weather queries and geographic links with independent native censuses."""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import tomllib

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

ROOT = Path(__file__).resolve().parents[1]


def check(row, source):
    for key in ('native_id', 'database_index', 'name'):
        assert row[key] == source[key], (key, row, source)
    assert row['weather_ref'] and row['complete_native_periods'] and row['period_count'] == 4
    for actual, expected in zip(row['periods'], source['periods'], strict=True):
        assert actual['native_index'] == expected['native_index']
        assert actual['start_day']['native_value'] == expected['start_day_native']
        for kind in ('wind', 'precipitation', 'temperature'):
            assert [c['native_weight'] for c in actual[kind]['categories']] == expected[kind + '_native']
            assert actual[kind]['native_weight_total'] == sum(expected[kind + '_native'])
        value = expected['day_night_drop_native']
        assert actual['day_night_variance'] == {'native_value': value, 'value': None if value == 100 else value,
                                               'unit': None, 'state': 'not_specified' if value == 100 else 'unit_unverified'}


async def verify():
    names = ('weather-profile-survey.json', 'weather-layout-verification.json',
             'language-region-detail-survey.json', 'city-survey.json')
    sources = {name: json.loads((ROOT / 'evidence' / name).read_text()) for name in names}
    assert all(s['verified'] for s in sources.values())
    raw = sources[names[0]]['records']; by_id = {r['native_id']: r for r in raw}
    by_address = {int(r['address'], 16): r for r in raw}
    cities = sources[names[3]]['cities']; regions = sources[names[2]]['records']['local_region']
    files = sorted((ROOT / 'fm_live_mcp').glob('*.py')) + [ROOT / 'evidence' / name for name in names]
    identity = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    receipt = {'verified': False, 'server_version': '0.32.0', 'source_identity': identity,
               'started_at': datetime.now(timezone.utc).isoformat()}
    readback_ids = {r['native_id'] for i, r in enumerate(raw) if i < 10 or i % 20 == 0 or i == len(raw)-1}
    for value in {p['day_night_drop_native'] for r in raw for p in r['periods']}:
        readback_ids.add(next(r['native_id'] for r in raw if any(p['day_night_drop_native'] == value for p in r['periods'])))
    checkpoint = ROOT / 'evidence/weather-verification-checkpoint.json'
    def save_checkpoint():
        checkpoint.write_text(json.dumps(receipt, indent=2) + '\n')
    config = tomllib.loads((Path.home() / '.codex/config.toml').read_text())['mcp_servers']['fm-live']
    async with stdio_client(StdioServerParameters(command=config['command'], args=config['args'])) as (read, write):
        async with ClientSession(read, write) as client:
            await client.initialize()
            async def call(tool, **args):
                for attempt in range(5):
                    result = await client.call_tool(tool, args)
                    if not result.isError or 'changed during read' not in str(result.content) or attempt == 4: break
                    await asyncio.sleep(.2)
                assert not result.isError and result.structuredContent is not None, (tool, result.content)
                return result.structuredContent
            status = await call('fm_status')
            assert status['server_version'] == '0.32.0' and status['capabilities']['weather_profile_query']
            assert not status['capabilities']['memory_writes']
            tools = (await client.list_tools()).tools
            assert len(tools) == 47 and all(t.annotations.readOnlyHint for t in tools)
            sid = (await call('fm_attach'))['session_id']; dates = set()
            async def pages(tool, key, **args):
                cursor = None; scanned = 0
                while True:
                    page = await call(tool, session_id=sid, max_matches=100, record_budget=1000, cursor=cursor, **args)
                    dates.add(page['save']['current_date']); assert page['start_index'] == scanned
                    scanned += page['scanned_records']
                    yield page[key]
                    cursor = page['next_cursor']
                    if cursor is None: break
                assert scanned == page['total_city_records' if key == 'cities' else 'total_records']
            try:
                count = readbacks = unspecified = 0
                async for rows in pages('fm_find_weather_profiles', 'weather_profiles'):
                    for row in rows:
                        source = by_id[row['native_id']]; check(row, source)
                        if row['native_id'] in readback_ids:
                            fresh = (await call('fm_get_weather_profile', session_id=sid, weather_ref=row['weather_ref']))['weather_profile']
                            check(fresh, source); readbacks += 1
                        count += 1
                        unspecified += sum(p['day_night_variance']['value'] is None for p in row['periods'])
                        if count % 100 == 0: print('Weather records:', count, flush=True)
                assert count == len(raw)
                receipt['weather_profiles'] = {'records_checked': count, 'readbacks': readbacks, 'periods_checked': count * 4,
                                                'unspecified_variances': unspecified, 'complete_scan': True}
                print('Weather profiles:', count, 'readbacks:', readbacks, flush=True)
                save_checkpoint()
                for kind, key, source_rows, offset in (('local_region', 'local_regions', regions, None), ('city', 'cities', cities, 0x28)):
                    checked = links = nulls = 0; opened = set()
                    async for rows in pages('fm_find_' + key, key):
                        for row in rows:
                            source = source_rows[checked]; assert row['native_id'] == source['native_id']
                            target = source['weather'] if offset is None else by_address.get(struct.unpack_from('<Q', bytes.fromhex(source['raw']), offset)[0])
                            if target is None:
                                if offset is not None: assert struct.unpack_from('<Q', bytes.fromhex(source['raw']), offset)[0] == 0
                                assert row['weather'] is None; nulls += 1
                            else:
                                assert row['weather']['native_id'] == target['native_id']
                                assert row['weather']['weather_ref']; links += 1
                                if target['native_id'] in readback_ids and target['native_id'] not in opened:
                                    detail = (await call('fm_get_weather_profile', session_id=sid, weather_ref=row['weather']['weather_ref']))['weather_profile']
                                    check(detail, by_id[target['native_id']]); opened.add(target['native_id'])
                            checked += 1
                        if checked % 10000 == 0: print(key, checked, flush=True)
                    assert checked == len(source_rows)
                    receipt[key] = {'records_checked': checked, 'weather_links': links, 'null_weather_links': nulls,
                                    'distinct_weather_targets_opened': len(opened), 'complete_scan': True}
                    print(key, receipt[key], flush=True)
                    save_checkpoint()
                checks = []
                for args in ({'name': 'English'}, {'native_id': raw[0]['native_id']}, {'name': 'English', 'native_id': raw[0]['native_id']}, {'name': 'no weather profile with this name'}):
                    actual = []
                    async for rows in pages('fm_find_weather_profiles', 'weather_profiles', **args): actual.extend(r['native_id'] for r in rows)
                    expected = [r['native_id'] for r in raw if ('name' not in args or args['name'].casefold() in (r['name'] or '').casefold()) and ('native_id' not in args or r['native_id'] == args['native_id'])]
                    assert actual == expected; checks.append({'criteria': args, 'matched_records': len(actual), 'complete_scan': True})
                receipt['weather_filters'] = checks
                save_checkpoint()
                target_id = raw[0]['native_id']
                for key, source_rows in (('cities', cities), ('local_regions', regions)):
                    actual = []
                    async for rows in pages('fm_find_' + key, key, weather_native_id=target_id): actual.extend(r['native_id'] for r in rows)
                    if key == 'cities':
                        expected = [r['native_id'] for r in source_rows if by_address.get(struct.unpack_from('<Q', bytes.fromhex(r['raw']), 0x28)[0], {}).get('native_id') == target_id]
                    else: expected = [r['native_id'] for r in source_rows if (r['weather'] or {}).get('native_id') == target_id]
                    assert actual == expected
                    receipt[key + '_weather_filter'] = {'weather_native_id': target_id, 'matched_records': len(actual), 'complete_scan': True}
                    print(key, 'weather filter:', len(actual), flush=True)
                    save_checkpoint()
            finally: await call('fm_detach')
    assert identity == {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    receipt.update(verified=True, completed_at=datetime.now(timezone.utc).isoformat(), save_dates=sorted(dates),
                   foreground_ui_used=False, native_execution=False)
    (ROOT / 'evidence/live-weather-mcp.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print('Verified all weather profiles, geographic links and filters.', flush=True)


if __name__ == '__main__': asyncio.run(verify())
