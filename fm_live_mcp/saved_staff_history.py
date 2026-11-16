"""Pinned saved non-playing histories; source rows do not establish employment."""
from array import array
from collections import OrderedDict
from dataclasses import replace
from hashlib import sha256
from functools import partial
import calendar
import datetime
import json
import struct

from . import (saved_fixed_history_index as fixed, saved_fixture_name_lookup as fixture,
               saved_player_history as source, saved_population, snapshot_catalog,
               saved_starting_career, saved_database, saved_database_header,
               saved_database_tables, saved_club_records, saved_squad_tables,
               saved_team_records, saved_component_stream, staff_jobs)

ROW = struct.Struct('<iIIIBHB')
_CONTEXT_COUNTS = OrderedDict()
SCOPE = ('Stored non-playing history rows; not complete runtime career or current employment. '
         'Joined/left dates can have year-only precision. TEAM words are native IDs, not ordinals. '
         'English role titles are a build-pinned baseline, not saved labels.')


def locate_owner_map(data, *, competition_count, stage_name_count, native_id):
    # The preceding playing-history map is independently validated in full.
    _, preceding = saved_starting_career.locate_owner_map(
        data, competition_count=competition_count, stage_name_count=stage_name_count,
        native_id=native_id)
    start = preceding['source_end']
    if start + 4 > len(data):
        raise ValueError('Truncated non-playing owner map')
    count, = struct.unpack_from('<I', data, start)
    end = start + 4 + count * 8
    if count > 2_000_000 or end > len(data):
        raise ValueError('Non-playing owner map exceeds bounded source')
    previous = None
    owner = None
    for at in range(start + 4, end, 8):
        primary, key = struct.unpack_from('<ii', data, at)
        if previous is not None and primary <= previous:
            raise ValueError('Non-playing native IDs unsorted or duplicated')
        previous = primary
        if primary == native_id:
            owner = key
    return owner, {'state': 'matched_native_ID' if owner is not None else 'native_ID_not_in_saved_map',
                   'native_id': native_id, 'owner_key': owner, 'pair_count': count,
                   'source_start': start, 'source_end': end,
                   'map_sha256': sha256(memoryview(data)[start:end]).hexdigest(),
                   'preceding_playing_owner_map': preceding,
                   'scope': 'unique_structural_conjunction_then_two_complete_native_ID_maps; source_root_708_to_common_PERSON_B8'}


def _date(word):
    year, day, flags = word >> 16, word & 511, (word >> 9) & 127
    out = {'raw_u32': word, 'native_year': year, 'day_low9': day, 'flags_high7': flags,
           'calendar_projection': None, 'state': 'unmapped_date',
           'precision': 'not_established; joined/left permit year-only dates'}
    if word == 0x076c0001:
        out['state'] = 'native_default_marker'
    elif 1 <= year <= 9999 and 1 <= day <= 365 + calendar.isleap(year):
        out.update(state='calendar_projected_precision_unproved',
                   calendar_projection=(datetime.date(year, 1, 1) + datetime.timedelta(days=day-1)).isoformat())
    return out


def decode_row(raw):
    if len(raw) != ROW.size:
        raise ValueError('Non-playing v3 history requires exactly20 bytes')
    team, joined, left, other, byte3c, job, byte3a = ROW.unpack(raw)
    getter_job = job or 11  # Native tjob getter146B288: zero falls back to11.
    label = staff_jobs.JOB_LABELS.get(getter_job)
    return {'team_reference': {'native_id_signed': team, 'state': 'native_null_reference' if team == -1
                              else 'unresolved_native_ID', 'matches': [], 'display_name': None},
            'joined_date': _date(joined), 'left_date': _date(left),
            'unmapped_date_0x30': _date(other), 'unmapped_byte_0x3c': byte3c,
            'job_type_raw_u16': job, 'native_getter_job_type': getter_job,
            'baseline_english_role': {'state': 'available' if label else 'unmapped_job_code',
                                     'text': label, 'source': 'native1358AC8_mj+c_build_pinned_English_baseline',
                                     'saved_label': False},
            'unmapped_byte_0x3a': byte3a, 'current_employment_assessed': False}


def resolve_teams(data, rows):
    wanted = {r['team_reference']['native_id_signed'] for r in rows
              if r['team_reference']['native_id_signed'] != -1}
    if not wanted:
        return
    reader = saved_component_stream.Reader(fixture._Source(data), len(data))
    saved_database_header.read_header(reader)
    saved_database_tables.reach_clubs(reader)
    clubs, links = {}, {}
    text_bytes = 0
    for club in saved_database.table(reader, 'CLUB', partial(saved_club_records.read_club, include_team_indices=True)):
        text_bytes += sum(len(club.get(k, '').encode('utf-8')) for k in ('name', 'short_name') if club.get(k) is not None)
        if text_bytes > 16 * 1024**2:
            raise ValueError('Staff history canonical labels exceed bounded context')
        key = club['database_index']
        clubs[key] = {k: club[k] for k in ('database_index', 'native_id', 'secondary_id', 'name', 'short_name')}
        for index in club['team_indices']:
            if index is not None:
                links.setdefault(index, []).append(key)
    saved_squad_tables.reach_teams_after_clubs(reader)
    found = {native: [] for native in wanted}
    for team in saved_database.table(reader, 'TEAM_BASE', partial(saved_team_records.read_team, include_roster=False)):
        if source._signed(team['native_id']) not in wanted:
            continue
        if len(found[source._signed(team['native_id'])]) >= 64:
            raise ValueError('Staff TEAM native ID ambiguity exceeds response budget')
        owners = links.get(team['database_index'], [])
        club = None
        if team['owner_kind'] == 'club' and len(owners) == 1 and team['owner_index'] in (None, owners[0]):
            club = clubs[owners[0]]
        found[source._signed(team['native_id'])].append({**{k: team[k] for k in ('database_index', 'native_id', 'secondary_id',
                                      'owner_kind', 'owner_index', 'name', 'short_name')}, 'club': club})
    for row in rows:
        ref = row['team_reference']
        if ref['native_id_signed'] == -1:
            continue
        matches = found[ref['native_id_signed']]
        ref.update(matches=matches, state='available' if len(matches) == 1 else 'ambiguous_native_ID' if matches else 'native_ID_not_in_saved_TEAM_table')
        if len(matches) == 1:
            ref['display_name'] = (matches[0]['club'] or {}).get('name') or matches[0]['name']


def get_staff_history(filename, person_index, expected_snapshot_id, *,
                         offset=0, limit=50, directory=None):
    if (type(person_index) is not int or not 0 <= person_index < 2**31 or
            type(offset) is not int or not 0 <= offset < 2**31 or
            type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError('Invalid PERSON index or staff-history page')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the saved snapshot ID')
    if not saved_population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population lookup is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since staff-history request')
            root = entries[0].path.split('/')[0]
            receipts = {}
            context_for_cache = None
            data = source._load_database(handle, source._entry(entries,root,'game_db.dat'), receipts)
            digest = bytes.fromhex(receipts['game_db.dat']['raw_sha256'])
            cached = saved_population._LAST_LAYOUT
            layout = (replace(cached[1],_data=data) if cached is not None and cached[0]==digest
                      else saved_population.saved_name_vectors.locate(data))
            cache_key = (pin,digest,layout.person_offset,layout.person_count)
            ends = saved_population._PREFIXES.get(cache_key,array('I'))
            person,new,coverage = source._person(data,layout,ends,person_index)
            result = {'filename':filename,'snapshot_id':pin,'person_index':person_index,
                      'state':'unavailable','PERSON_coverage':coverage,'components':receipts,
                      'rows':[],'offset':offset,'limit':limit,'next_offset':None,
                      'total_indexed_entries':None,'selected_row_count':None,
                      'owner':None,'scope':SCOPE,'wire_profile_is_conditional':True,
                      'native_loader_globals_proved':False,
                      'PERSON_profile':'existing_conditional_complete_ACTUAL_PERSON_wire_profile',
                      'owner_profile':'saved_root_708_native_ID_assignment; no_ambient_flag_guess',
                      'saved_metadata':snapshot_catalog._metadata(handle,entries)}
            if person is None:
                result.update(state='unavailable' if coverage['state']=='outside_declared_PERSON_table' else 'stopped',
                              reason=coverage['state'])
            elif person['signed_tag'] not in (1, 2, 3):
                result.update(reason='unsupported_PERSON_class_for_staff_history',
                              person=saved_population._project(data,layout,person))
            elif source._signed(person['identity']['native_id_word']) == -1:
                result.update(reason='native_null_ID_skipped_by_saved_map_loader',
                              person=saved_population._project(data,layout,person))
            else:
                result['person'] = saved_population._project(data,layout,person)
                native_id = source._signed(person['identity']['native_id_word'])
                context_for_cache = _CONTEXT_COUNTS.get(digest)
                if context_for_cache is None:
                    header,competitions,stages,_ = fixture._canonical_context(data)
                    if (header['source_major'],header['source_minor']) != (3754,9):
                        raise ValueError('Unsupported staff-history source version')
                    context_for_cache = (len(competitions),len(stages))
                owner,proof = locate_owner_map(data,competition_count=context_for_cache[0],
                                              stage_name_count=context_for_cache[1],native_id=native_id)
                result['owner'] = proof
                if owner is None:
                    result.update(reason='native_ID_not_in_authoritative_saved_owner_map')
                else:
                    if owner < -1:
                        raise ValueError('Unsupported negative non-playing owner key; only -1 sentinel proved')
                    with source._component(handle,source._entry(entries,root,'non_pl_hist_ls.dat'),receipts) as reader:
                        offsets,summary = fixed.read_index(reader,owner,width=20,data_version=3)
                    with source._component(handle,source._entry(entries,root,'non_pl_hist_dt.cmt'),receipts) as reader:
                        raw_rows = fixed.read_rows(reader,offsets,width=20,data_version=3)
                    rows=[];matched=0;skipped=[]
                    for ordinal,value in enumerate(offsets):
                        if value<0:
                            skipped.append({'entry_index':ordinal,'native_offset':value,
                                            'reason':'native_negative_offset_skipped'})
                            continue
                        raw=raw_rows[value];row=decode_row(raw)
                        if offset<=matched<offset+limit:
                            rows.append({**row,'entry_index':ordinal,'native_offset':value,
                                         'data_start':value+8,'data_end':value+28,
                                         'record_sha256':sha256(raw).hexdigest()})
                        matched+=1
                    resolve_teams(data, rows)
                    state=summary['state']
                    result.update(state=('unavailable' if state=='outside_owner_table' else
                                         'no_history_index' if state=='no_history_index' else
                                         'available_empty' if not offsets else 'available'),
                                  reason=state if state!='selected_owner' else None,
                                  rows=rows,index_summary=summary,total_indexed_entries=len(offsets),
                                  decoded_row_count=len(offsets)-len(skipped),selected_row_count=matched,
                                  skipped_entries=skipped,next_offset=offset+limit if offset+limit<matched else None)
                    if state=='outside_owner_table':
                        result.update(total_indexed_entries=None,decoded_row_count=None,selected_row_count=None)
            if len(json.dumps(result,ensure_ascii=True))>2*1024**2:
                raise ValueError('Staff-history response exceeds budget; lower limit')
        if context_for_cache is not None:
            _CONTEXT_COUNTS[digest] = context_for_cache
            _CONTEXT_COUNTS.move_to_end(digest)
            while len(_CONTEXT_COUNTS)>4:
                _CONTEXT_COUNTS.popitem(last=False)
        saved_population._LAST_LAYOUT=(digest,replace(layout,_data=None))
        ends.extend(new)
        saved_population._PREFIXES[cache_key]=ends
        saved_population._PREFIXES.move_to_end(cache_key)
        while len(saved_population._PREFIXES)>saved_population._MAX_CACHES:
            saved_population._PREFIXES.popitem(last=False)
        return result
    finally:
        saved_population._LOCK.release()
