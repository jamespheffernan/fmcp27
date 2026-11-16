"""Pinned searched retained fixture records, with original side/source order."""
import datetime
import json
from collections import OrderedDict
from pathlib import Path
from threading import Lock

from . import (
    saved_club_records, saved_component_stream, saved_database,
    saved_fixture_records, saved_squad_tables, saved_team_records, snapshot_catalog,
)

MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_LABEL_BYTES = 16 * 1024 * 1024
# Cache complete small query results, never whole components or unbounded tables.
MAX_CACHED_ROWS = 500
MAX_CACHE_ENTRY_BYTES = 4 * 1024 * 1024
MAX_CACHE_ENTRIES = 2
_CACHE = OrderedDict()
_CACHE_LOCK = Lock()


def _page_result(result, offset, limit):
    result['rows'] = result['rows'][offset:offset + limit]
    result.update(offset=offset, limit=limit,
                  next_offset=offset + limit if offset + limit < result['matched_count'] else None)
    if len(json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()) > MAX_RESPONSE_BYTES:
        raise ValueError('Selected fixture page exceeds response budget; reduce limit')
    return result


def _cached(key, filename, pin, directory, offset, limit):
    with _CACHE_LOCK:
        blob = _CACHE.get(key)
        if blob is None:
            return None
        _CACHE.move_to_end(key)
    try:
        # Same archive identity contract as the cold path, before and after use.
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (_, _, identity):
            if snapshot_catalog.snapshot_id(identity) != pin:
                raise ValueError('Snapshot identity changed between fixture pages')
            result = _page_result(json.loads(blob), offset, limit)
    except (ValueError, OSError):
        with _CACHE_LOCK:
            _CACHE.pop(key, None)
        raise
    return result


def _remember(key, result):
    blob = json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()
    if len(blob) > MAX_CACHE_ENTRY_BYTES:
        return
    with _CACHE_LOCK:
        _CACHE[key] = blob
        _CACHE.move_to_end(key)
        while len(_CACHE) > MAX_CACHE_ENTRIES:
            _CACHE.popitem(last=False)


def _calendar(value):
    if not isinstance(value, str):
        raise ValueError('Supply an ISO calendar date YYYY-MM-DD')
    try:
        day = datetime.date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('Supply an ISO calendar date YYYY-MM-DD') from error
    if day.isoformat() != value or not 1850 <= day.year <= 2200:
        raise ValueError('Unsupported calendar date; use YYYY-MM-DD within1850..2200')
    return value


def _canonical(reader, selected, queried_index, maximum_reference, *, cache_rows=None):
    """One prefix walk; retain page identities and optional bounded prefetch."""
    clubs = {}
    label_bytes = 0
    for row in saved_database.table(reader, 'CLUB', saved_club_records.read_club):
        compact = {key: row.get(key) for key in ('database_index', 'native_id', 'secondary_id', 'name', 'short_name')}
        label_bytes += sum(len(value.encode('utf8')) for value in compact.values() if isinstance(value, str))
        if label_bytes > MAX_LABEL_BYTES:
            raise ValueError('Saved fixture canonical CLUB label budget exceeded')
        clubs[row['database_index']] = compact
    saved_squad_tables.reach_teams_after_clubs(reader)
    wanted = {queried_index}
    for row in selected + (cache_rows or []):
        wanted.update(ref['database_index'] for ref in row['team_references'] if ref['database_index'] is not None)
    teams = {}
    count = 0
    for team in saved_database.table(reader, 'TEAM_BASE',
                                     lambda r, i, k: saved_team_records.read_team(r, i, k, include_roster=False)):
        count += 1
        if team['database_index'] in wanted:
            compact = {key: team[key] for key in ('database_index', 'native_id', 'secondary_id', 'team_type_code',
                                                  'owner_kind', 'owner_index', 'name', 'short_name')}
            compact['table'] = 'TEAM_BASE'
            compact['identity_scope'] = 'original same-snapshot table ordinal'
            compact['club_owner'] = clubs.get(team['owner_index']) if team['owner_kind'] == 'club' else None
            teams[team['database_index']] = compact
    if queried_index >= count:
        raise ValueError('Requested TEAM index is outside the checked same-snapshot table')
    if maximum_reference >= count:
        raise ValueError('Saved fixture TEAM reference is outside the checked same-snapshot table')
    def resolve(row):
        ordered = []
        for ref in row['team_references']:
            index = ref['database_index']
            team = teams.get(index) if index is not None else None
            if index is not None and team is None:
                raise ValueError('Selected TEAM identity unavailable')
            if team is not None and ref['identity_word'] is not None and ref['identity_word'] != team['native_id']:
                raise ValueError('Saved fixture TEAM transport identity differs from canonical table')
            ordered.append(team)
        row['teams'] = ordered
    for row in selected:
        resolve(row)
    if cache_rows is not None:
        try:
            for row in cache_rows:
                resolve(row)
        except ValueError:
            # Optional prefetch must not introduce a new cold-page failure.
            cache_rows.clear()
    return teams[queried_index], count


def find_fixture_results(filename, team_index, date_from, date_to, *, expected_snapshot_id,
                         offset=0, limit=50, include_competition=False,
                         include_historical=False, directory=None):
    """Search source retained groups; stable pagination preserves duplicate rows.

    The date selector is native FIXTURE+4C stored Kick Off, not a played date.
    All indices are original same-file ordinals pinned by expected_snapshot_id.
    """
    snapshot_catalog.check_filename(filename)
    snapshot_catalog._page(offset, limit)
    if type(team_index) is not int or not 0 <= team_index < 1 << 31:
        raise ValueError('Invalid same-snapshot TEAM index')
    if (not isinstance(expected_snapshot_id, str) or len(expected_snapshot_id) != 64
            or any(c not in '0123456789abcdef' for c in expected_snapshot_id)):
        raise ValueError('Supply the exact expected_snapshot_id for this saved TEAM index')
    if type(include_competition) is not bool or type(include_historical) is not bool:
        raise ValueError('Invalid fixture context selection')
    first, last = _calendar(date_from), _calendar(date_to)
    if first > last:
        raise ValueError('date_from must be on or before date_to')
    directory_key = str(Path(directory if directory is not None else snapshot_catalog.DEFAULT_DIRECTORY).expanduser().absolute())
    key = (directory_key, filename, expected_snapshot_id, team_index, first, last,
           include_competition, include_historical)
    hit = _cached(key, filename, expected_snapshot_id, directory, offset, limit)
    if hit is not None:
        return hit
    selected = []
    cache_rows = []
    matched = 0
    maximum_reference = -1
    team_occurrences = unknown_team_dates = unmapped_dates = 0
    def consume(row):
        nonlocal matched, maximum_reference, team_occurrences, unknown_team_dates, unmapped_dates
        refs = row['team_references']
        maximum_reference = max(maximum_reference, *(ref['database_index'] if ref['database_index'] is not None else -1 for ref in refs))
        date = row['stored_kickoff_date']
        has_team = team_index in [ref['database_index'] for ref in refs]
        team_occurrences += has_team
        unmapped_dates += date is None
        unknown_team_dates += has_team and date is None
        if (has_team
                and date is not None and first <= date <= last):
            if matched < MAX_CACHED_ROWS or offset <= matched < offset + limit:
                row['match_ordinal'] = matched
                row['completion_state'] = 'unresolved'
                row['actual_venue_state'] = 'unresolved'
                row['fixture_name'] = {'database_index': row['fixture_name_index'], 'table': 'FIXTURE_NAME',
                                       'state': 'null_reference' if row['fixture_name_index'] is None else 'not_requested' if include_competition else 'unresolved_index',
                                       'scope': 'original same-snapshot table index; not a COMP index'}
                if matched < MAX_CACHED_ROWS:
                    cache_rows.append(row)
                if offset <= matched < offset + limit:
                    selected.append(row)
            matched += 1
    with saved_database.open_archive_at_clubs(filename, expected_snapshot_id, directory) as (database, source, handle, entries):
        root = entries[0].path.split('/')[0]
        managers = [entry for entry in entries if entry.path == f'{root}/rgman/fix_man.dat']
        if len(managers) != 1:
            raise ValueError('Saved snapshot requires one root rgman/fix_man.dat')
        with saved_component_stream.open_component(handle, managers[0]) as reader:
            retained = saved_fixture_records.read_retained(reader, consume)
            if include_historical:
                from .saved_fixture_archive import read_historical
                historical = read_historical(reader, consume)
                if historical.get('next_cursor') is not None:
                    raise ValueError('Historical fixture scan budget exhausted; complete searched pagination unavailable')
            else:
                historical = {'state': 'not_searched', 'scope': 'separate indexed historical storage',
                              'absence_proved': False}
            parsed_end = reader.offset
            reader.skip(reader.size - reader.offset)
            if reader.source.read(1) != b'' or not reader.source.finished:
                raise ValueError('Saved fixture component frame did not finish')
            component = {'path': managers[0].path, 'uncompressed_size': reader.size,
                         'parsed_until': parsed_end, 'full_frame_validated': True}
        if matched > MAX_CACHED_ROWS:
            cache_rows.clear()
        team, team_count = _canonical(database, selected, team_index, maximum_reference,
                                      cache_rows=cache_rows)
    cache_ready = matched == len(cache_rows)
    # An empty/null-only original page did not require the optional provider.
    # Do not turn speculative prefetch into a new source requirement or failure.
    if (include_competition and cache_ready
            and not any(row['fixture_name_index'] is not None for row in selected)
            and any(row['fixture_name_index'] is not None for row in cache_rows)):
        cache_ready = False
    context_rows = cache_rows if cache_ready else selected
    competition_context = None
    if include_competition:
        from .saved_fixture_name_lookup import load_fixture_name_lookup
        indices = sorted({row['fixture_name_index'] for row in context_rows if row['fixture_name_index'] is not None})
        if indices:
            competition_context = load_fixture_name_lookup(filename, indices, expected_snapshot_id=expected_snapshot_id, directory=directory)
            if competition_context['snapshot_id'] != source['snapshot_id']:
                raise ValueError('Fixture competition context snapshot mismatch')
            by_index = {row['database_index']: row for row in competition_context['rows']}
            for row in context_rows:
                index = row['fixture_name_index']
                row['fixture_name'] = by_index.get(index, {'database_index': index, 'state': 'null_reference' if index is None else 'unavailable'})
    historical_count = historical.get('scanned_records', 0)
    complete_requested = (not include_historical or historical.get('complete_source') is True) and unknown_team_dates == 0
    coverage = {**retained, 'historical': historical, 'component': component,
                'retained_scope': retained['scope'],
                'scope': retained['scope'] + (' plus separately indexed historical storage' if include_historical else ''),
                'retained_scanned_records': retained['scanned_records'],
                'total_scanned_records': retained['scanned_records'] + historical_count,
                'complete_requested_scope': complete_requested,
                'groups': retained['groups'][:64], 'omitted_group_summaries': max(0, len(retained['groups']) - 64),
                'canonical_team_count': team_count, 'full_save_absence_proved': False,
                'team_rows_before_date_filter': team_occurrences,
                'unmapped_kickoff_date_rows': unmapped_dates,
                'selected_team_unmapped_kickoff_date_rows': unknown_team_dates,
                'source_order': 'base, initial, outer groups, then requested historical storage; duplicates preserved'}
    result = {**source, 'query': {'team_index': team_index, 'date_from': first, 'date_to': last,
                                 'date_field': 'FIXTURE+4C stored Kick Off',
                                 'include_competition': include_competition, 'include_historical': include_historical},
              'team': team, 'matched_count': matched,
              'matched_count_is_complete_for_requested_scope': complete_requested,
              'offset': offset, 'limit': limit,
              'next_offset': offset + limit if offset + limit < matched else None,
              'rows': selected, 'coverage': coverage}
    if competition_context is not None:
        result['fixture_name_context'] = competition_context['table']
    if cache_ready:
        full = {**result, 'rows': cache_rows}
        # Validate the requested page before publishing any reusable cache entry.
        page = _page_result({**full}, offset, limit)
        _remember(key, full)
        return page
    # Large match sets retain the original bounded cold-page path.
    if len(json.dumps(result, ensure_ascii=True, separators=(',', ':')).encode()) > MAX_RESPONSE_BYTES:
        raise ValueError('Selected fixture page exceeds response budget; reduce limit')
    return result
