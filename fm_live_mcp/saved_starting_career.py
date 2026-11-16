"""Bounded same-save starting playing history; not a complete runtime career."""
from array import array
from collections import OrderedDict
from dataclasses import replace
from hashlib import sha256
import json
import struct

from . import (saved_fixed_history_index as fixed, saved_fixture_name_lookup as fixture,
               saved_player_history as source, saved_population, snapshot_catalog,
               saved_starting_history_names as names)

ROW = struct.Struct('<hHBBBiIIIIbIII')
MAX_PAIRS = 2_000_000
_CONTEXT_COUNTS = OrderedDict()
_EMPTY = bytes.fromhex('0000000000000000000100000000')
SCOPE = ('Retained starting playing-history rows only; not complete career or season coverage. '
         'Native stored year convention, date sentinels and transfer-fee currency are unproved. '
         'TEAM_BASE/COMP words are native identity pairs, not original table indices.')


def locate_owner_map(data, *, competition_count, stage_name_count, native_id):
    """Require unique whole FIXTURE_NAME and three adjoining empty table grammars."""
    table = fixture.locate_fixture_name_table(data, competition_count=competition_count,
                                            stage_name_count=stage_name_count)
    start, end = table['start'], table['end']
    if start < 14 or bytes(data[start-14:start]) != _EMPTY:
        raise ValueError('Unsupported preceding STARTING_VISION_OBJECTIVE table; no owner selected')
    if bytes(data[end:end+14]) != _EMPTY:
        raise ValueError('Unsupported adjoining STARTING_PAST_TRANSFER table; no owner selected')
    if bytes(data[end+14:end+28]) != _EMPTY:
        raise ValueError('Unsupported adjoining STARTING_PAST_TRADE table; no owner selected')
    at = end + 28
    if at + 4 > len(data):
        raise ValueError('Truncated starting-history owner map header')
    count, = struct.unpack_from('<I', data, at)
    stop = at + 4 + 8*count
    if count > MAX_PAIRS or stop + 4 > len(data):
        raise ValueError('Starting-history owner map exceeds supported extent or work budget')
    previous = None
    owner = None
    for pos in range(at+4, stop, 8):
        primary, key = struct.unpack_from('<ii', data, pos)
        if previous is not None and primary <= previous:
            raise ValueError('Starting-history owner IDs are unsorted or duplicated')
        previous = primary
        if primary == native_id:
            owner = key
    return owner, {'state': 'matched_native_ID' if owner is not None else 'native_ID_not_in_saved_map',
                   'source_start': at, 'source_end': stop, 'pair_count': count,
                   'map_sha256': sha256(memoryview(data)[at:stop]).hexdigest(),
                   'native_id': native_id, 'owner_key': owner,
                   'fixture_name_anchor': table,
                   'adjoining_tables': 'three_complete_empty_current_writer_tables',
                   'scope': 'structural_conjunction_not_sequential_full_loader; native_map_assignment_to_common_PERSON_B4'}


def decode_row(raw):
    if len(raw) != ROW.size:
        raise ValueError('Starting-history v3 requires exactly40 bytes')
    year, unknown, flags, apps, goals, fee, t0,t1,c0,c1,order,joined,left,date = ROW.unpack(raw)
    def reference(table, first, second):
        return {'table': table, 'native_id_word': first, 'secondary_word': second,
                'state': 'stored_all_ones_identity_pair' if (first, second)==(0xffffffff,0xffffffff)
                         else 'unresolved_native_identity_pair', 'name': None}
    return {'native_year': year, 'native_order': order,
            'appearances': None if apps==255 else apps, 'appearances_raw_u8': apps,
            'goals': None if goals==255 else goals, 'goals_raw_u8': goals,
            'on_loan': bool(flags&1), 'youth_team': bool(flags&2), 'tribunal_fee': bool(flags&32),
            'flags_raw_u8': flags, 'extras_mask': flags&28,
            'transfer_fee_raw': None if fee<0 else fee, 'fee_or_other_code_raw_i32': fee,
            'transfer_fee_currency': None,
            'team_reference': reference('TEAM_BASE',t0,t1),
            'competition_reference': reference('COMP',c0,c1),
            'joined_date_raw_u32': joined, 'left_date_raw_u32': left,
            'unmapped_date_raw_u32': date, 'unmapped_u16': unknown}


def get_starting_history(filename, person_index, expected_snapshot_id, *, years=None,
                         offset=0, limit=50, include_names=False, directory=None):
    if type(include_names) is not bool:
        raise ValueError('Invalid starting-history name selection')
    selected_years = source._filters(years, 32767, 'years')
    if (type(person_index) is not int or not 0 <= person_index < 2**31 or
            type(offset) is not int or not 0 <= offset < 2**31 or
            type(limit) is not int or not 1 <= limit <= 200):
        raise ValueError('Invalid PERSON index or starting-history page')
    if type(expected_snapshot_id) is not str or not expected_snapshot_id:
        raise ValueError('Supply the saved snapshot ID')
    if not saved_population._LOCK.acquire(blocking=False):
        raise ValueError('Another saved population lookup is in progress; retry')
    try:
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            pin = snapshot_catalog.snapshot_id(identity)
            if pin != expected_snapshot_id:
                raise ValueError('Snapshot identity changed since starting-history request')
            root = entries[0].path.split('/')[0]
            receipts = {}
            context_for_cache = None
            name_context = None
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
                      'PERSON_profile':'existing_conditional_regular_PLAYER_source_wire_profile',
                      'owner_profile':'saved_root_6F0_eager_native_ID_assignment; no_ambient_flag_guess',
                      'saved_metadata':snapshot_catalog._metadata(handle,entries),
                      'filters':{'native_years':None if selected_years is None else sorted(selected_years)}}
            if person is None:
                result.update(state='unavailable' if coverage['state']=='outside_declared_PERSON_table' else 'stopped',
                              reason=coverage['state'])
            elif person['signed_tag'] != 2:
                result.update(reason='unsupported_PERSON_class_for_starting_history',
                              person=saved_population._project(data,layout,person))
            elif source._signed(person['identity']['native_id_word']) == -1:
                result.update(reason='native_null_ID_skipped_by_saved_map_loader',
                              person=saved_population._project(data,layout,person))
            else:
                result['person'] = saved_population._project(data,layout,person)
                native_id = source._signed(person['identity']['native_id_word'])
                context_for_cache = _CONTEXT_COUNTS.get(digest)
                if include_names:
                    name_context = names._CACHE.get(digest)
                    if name_context is None:
                        name_context = names.prepare(data)
                    context_for_cache = name_context.counts
                if context_for_cache is None:
                    header,competitions,stages,_ = fixture._canonical_context(data)
                    if (header['source_major'],header['source_minor']) != (3754,9):
                        raise ValueError('Unsupported starting-history source version')
                    context_for_cache = (len(competitions),len(stages))
                owner,proof = locate_owner_map(data,competition_count=context_for_cache[0],
                                              stage_name_count=context_for_cache[1],native_id=native_id)
                result['owner'] = proof
                if owner is None:
                    result.update(reason='native_ID_not_in_authoritative_saved_owner_map')
                else:
                    with source._component(handle,source._entry(entries,root,'pl_hist_ls.dat'),receipts) as reader:
                        offsets,summary = fixed.read_index(reader,owner,width=40,data_version=3)
                    with source._component(handle,source._entry(entries,root,'pl_hist_dt.cmt'),receipts) as reader:
                        raw_rows = fixed.read_rows(reader,offsets,width=40,data_version=3)
                    rows=[];matched=0;skipped=[]
                    for ordinal,value in enumerate(offsets):
                        if value<0:
                            skipped.append({'entry_index':ordinal,'native_offset':value,
                                            'reason':'native_negative_offset_skipped'})
                            continue
                        raw=raw_rows[value];row=decode_row(raw)
                        if selected_years is not None and row['native_year'] not in selected_years:
                            continue
                        if offset<=matched<offset+limit:
                            rows.append({**row,'entry_index':ordinal,'native_offset':value,
                                         'data_start':value+8,'data_end':value+48,
                                         'record_sha256':sha256(raw).hexdigest()})
                        matched+=1
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
            if name_context is not None:
                names.enrich(data, name_context, result['rows'])
            if len(json.dumps(result,ensure_ascii=True))>2*1024**2:
                raise ValueError('Starting-history response exceeds budget; lower limit')
        if name_context is not None:
            names.publish(digest, name_context)
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
