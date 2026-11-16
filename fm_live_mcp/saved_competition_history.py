"""Source-bound retained competition history; never a current league-table claim."""
from functools import partial
from hashlib import sha256
import json
from threading import Lock

from . import (saved_club_records, saved_competition_records, saved_currency_records,
               saved_database, saved_database_header, saved_database_tables,
               saved_fixed_history_index as fixed, saved_national_containers,
               saved_nations, saved_name_vectors, saved_player_history as transport,
               saved_region_tables, saved_squad_tables, saved_team_records,
               saved_competition_history_records as codec, snapshot_catalog)
from .saved_component_stream import Reader

_LOCK = Lock()
MAX_CONTEXT_BYTES = 32 * 1024**2
MAX_RESPONSE_BYTES = 2 * 1024**2
SCOPE = ('Retained fixed competition-history rows in original stored order. Year, Start Year, '
         'End Year and Date Decided are named stored fields; no automatic season convention, '
         'current table, latest-completed season, individual match completion or complete history is inferred. '
         'TEAM/CLUB labels are same-snapshot names, not historical event-time names.')


def _years(values):
    if values is None:
        return None
    if (not isinstance(values, list) or not 1 <= len(values) <= 100 or
            any(type(value) is not int or not -32768 <= value <= 32767 for value in values)):
        raise ValueError('years must contain 1–100 exact signed16 native Year values')
    return set(values)


def _competition_context(data):
    reader = Reader(saved_name_vectors._Source(data), len(data))
    header = saved_database_header.read_header(reader)
    saved_database_tables.reach_clubs(reader)
    clubs = {}
    context_bytes = 0
    for row in saved_database.table(reader, 'CLUB', saved_club_records.read_club):
        context_bytes += 128 + (len(row['name'].encode('utf8')) if row['name'] is not None else 0)
        if context_bytes > MAX_CONTEXT_BYTES:
            raise ValueError('Competition history CLUB context exceeds budget')
        clubs[row['database_index']] = {key: row[key] for key in ('database_index','native_id','secondary_id','name')}
    competitions = []
    decode = partial(saved_competition_records.read_competition, include_history_key=True)
    for row in saved_database.table(reader, 'COMP', decode):
        context_bytes += len(json.dumps(row, ensure_ascii=True))
        if context_bytes > MAX_CONTEXT_BYTES:
            raise ValueError('Competition history canonical context exceeds budget')
        competitions.append(row)
    return reader, header, clubs, competitions


def _team_context(reader, wanted):
    """Continue the same checked GAME_DB; retain only requested TEAM objects."""
    for label, decode in (
        ('CONTINENT', saved_currency_records.skip_continent),
        ('CURRENCY', saved_currency_records.read_currency),
        ('INJURY', saved_squad_tables.skip_injury),
        ('MEDIA_SOURCE', saved_squad_tables.skip_media_source),
        ('LANGUAGE', saved_squad_tables.skip_language),
        ('NATION', saved_nations.skip_nation),
        ('NATIONAL_TEAM_CONTAINER', saved_national_containers.skip_national_container),
    ):
        saved_database.skip_table(reader, label, decode)
    saved_region_tables.skip_name_tables(reader)
    for label, decode in (
        ('REGION', saved_region_tables.skip_region),
        ('LOCAL_REGION', saved_region_tables.skip_local_region),
        ('STADIUM', saved_squad_tables.skip_stadium),
        ('STADIUM_CHANGE', saved_squad_tables.skip_stadium_change),
        ('STAGE_NAME', saved_squad_tables.skip_stage_name),
    ):
        saved_database.skip_table(reader, label, decode)
    teams = {}
    count = context_bytes = 0
    decode = partial(saved_team_records.read_team, include_roster=False)
    for row in saved_database.table(reader, 'TEAM_BASE', decode):
        count += 1
        if row['database_index'] in wanted:
            context_bytes += len(json.dumps(row, ensure_ascii=True))
            if context_bytes > MAX_CONTEXT_BYTES:
                raise ValueError('Competition history TEAM context exceeds budget')
            teams[row['database_index']] = row
    return teams, count


def _competition_reference(word, competitions):
    if word == -1:
        return {'stored_index': word, 'state': 'native_null_reference', 'identity': None}
    if not 0 <= word < len(competitions):
        raise ValueError('Competition-history COMP reference is outside its canonical table')
    identity = {key: value for key, value in competitions[word].items() if key != 'history_owner'}
    return {'stored_index': word, 'state': 'same_snapshot_canonical', 'identity': identity}


def _team_reference(word, teams, clubs):
    if word == -1:
        return {'stored_index': word, 'state': 'native_null_reference', 'identity': None,
                'owner_club': None, 'owner_club_state': 'not_applicable'}
    team = teams[word]
    club = clubs.get(team['owner_index']) if team['owner_kind'] == 'club' else None
    club_state = ('same_snapshot_canonical' if club is not None else
                  'national_owner_not_CLUB' if team['owner_kind'] != 'club' else
                  'native_null_owner' if team['owner_index'] is None else 'outside_same_snapshot_CLUB')
    return {'stored_index': word, 'state': 'same_snapshot_canonical', 'identity': team,
            'owner_club': club, 'owner_club_state': club_state}


def get_history(filename, competition_index, expected_snapshot_id, *, years=None,
                offset=0, limit=50, directory=None):
    selected_years = _years(years)
    if (type(competition_index) is not int or not 0 <= competition_index < 2**31 or
            type(offset) is not int or not 0 <= offset < 2**31 or
            type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError('Invalid saved competition-history index or page')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the same-save snapshot ID')
    if not _LOCK.acquire(blocking=False):
        raise ValueError('Another saved competition-history lookup is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since competition-history request')
            root = entries[0].path.split('/')[0]
            receipts = {}
            data = transport._load_database(handle, transport._entry(entries,root,'game_db.dat'),receipts)
            reader, header, clubs, competitions = _competition_context(data)
            result = {'source':'on-disk save snapshot','filename':filename,'snapshot_id':pin,
                      'saved_metadata':snapshot_catalog._metadata(handle,entries),'database_format':header,
                      'competition_index':competition_index,'competition':None,'owner':None,
                      'state':'unavailable','reason':None,'rows':[],'offset':offset,'limit':limit,'next_offset':None,
                      'total_indexed_entries':None,'decoded_row_count':None,'selected_row_count':None,
                      'filters':{'native_years':None if selected_years is None else sorted(selected_years)},
                      'components':receipts,'scope':SCOPE,'currentness':'not_established_by_history_source',
                      'complete_competition_history':False,'canonical_COMP_slots':len(competitions)}
            if competition_index >= len(competitions):
                result['reason'] = 'outside_same_snapshot_COMP_table'
            else:
                competition = dict(competitions[competition_index])
                result['owner'] = competition.pop('history_owner')
                result['competition'] = competition
                paths = ['rgman/comp_history_ls.dat','comp_history_dt.cmt']
                counts = {name: sum(e.path == root+'/'+name for e in entries) for name in paths}
                if any(count > 1 for count in counts.values()):
                    raise ValueError('Ambiguous competition-history component path')
                missing = [name for name, count in counts.items() if count == 0]
                if missing:
                    result.update(reason='history_components_missing',missing_components=missing)
                else:
                    with transport._component(handle,transport._entry(entries,root,paths[0]),receipts) as stream:
                        offsets, summary = fixed.read_index(stream,result['owner']['value'],width=codec.WIDTH,data_version=codec.VERSION)
                    with transport._component(handle,transport._entry(entries,root,paths[1]),receipts) as stream:
                        raw_rows = fixed.read_rows(stream,offsets,width=codec.WIDTH,data_version=codec.VERSION)
                    result['index_summary'] = summary
                    if summary['state'] == 'outside_owner_table':
                        result['reason'] = 'owner_key_outside_saved_index'
                    else:
                        decoded, skipped, page = [], [], []
                        matched = 0
                        for entry_index, at in enumerate(offsets):
                            if at < 0:
                                skipped.append({'entry_index':entry_index,'native_offset':at,'reason':'native_negative_offset_skipped'})
                                continue
                            raw = raw_rows[at]
                            row = codec.decode(raw)
                            _competition_reference(row['competition_index_word'],competitions)
                            if any(row[key] < -1 for key in ('first_placed_team_index','second_placed_team_index','third_placed_team_index')):
                                raise ValueError('Competition-history TEAM reference has an invalid negative index')
                            decoded.append(row)
                            if selected_years is not None and row['year'] not in selected_years:
                                continue
                            if offset <= matched < offset+limit:
                                page.append({**row,'entry_index':entry_index,'native_offset':at,
                                             'data_start':at+8,'data_end':at+8+codec.WIDTH,
                                             'record_sha256':sha256(raw).hexdigest()})
                            matched += 1
                        if decoded:
                            wanted = {row[key] for row in page for key in ('first_placed_team_index','second_placed_team_index','third_placed_team_index') if row[key] >= 0}
                            teams, team_count = _team_context(reader,wanted)
                            if any(row[key] >= team_count for row in decoded for key in ('first_placed_team_index','second_placed_team_index','third_placed_team_index')):
                                raise ValueError('Competition-history TEAM reference is outside its canonical table')
                            result['canonical_TEAM_slots'] = team_count
                            for row in page:
                                row['competition_reference'] = _competition_reference(row.pop('competition_index_word'),competitions)
                                for name in ('first_placed','second_placed','third_placed'):
                                    row[name] = _team_reference(row.pop(name+'_team_index'),teams,clubs)
                        result.update(state='no_history_index' if summary['state']=='no_history_index' else 'available_empty' if not offsets else 'available',
                                      reason='native_negative_COMP_history_key' if summary['state']=='no_history_index' else None,
                                      rows=page,total_indexed_entries=len(offsets),decoded_row_count=len(decoded),selected_row_count=matched,
                                      skipped_entries=skipped,next_offset=offset+limit if offset+limit<matched else None)
            if len(json.dumps(result,ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
                raise ValueError('Competition-history response exceeds budget; lower limit')
        return result
    finally:
        _LOCK.release()
