"""Pinned starting debt/FFP inputs, selected by the native CLUB ID predicate.

These are original inputs, not the current loan/balance ledger. No game calls.
"""
from array import array
from functools import partial
import hashlib
import json
import math
import struct
from threading import Lock

from . import (saved_club_records, saved_competition_records, saved_component_stream,
               saved_currency_records, saved_database, saved_national_containers,
               saved_nations, saved_region_tables, saved_squad_tables,
               saved_team_records, world)

MAX_ROWS = 250_000
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CONTEXT_DETAILS = 64
MAX_CONTEXT_TEXT_BYTES = 256 * 1024
_SLOT = Lock()
_FIELDS = ((0x18,4),(0x28,4),(0x5c,2),(0x2c,4),(0x5e,1),(0x30,4),
           (0x38,4),(0x3c,4),(0x40,4),(0x61,1),(0x34,4),(0x44,4),
           (0x48,4),(0x4c,4),(0x50,4),(0x54,4),(0x58,4),(0x5f,1),
           (0x60,1),(0x20,4))
DEBT_SOURCES = {1:'Bank',2:'Chairperson',3:'CVA',4:'PFA',5:'State',6:'Supporters Trust',
                 7:'Gift Repayable Once Profitable',8:'Gift Repayable On Departure',
                 9:'Gift Non-Repayable',10:'Loan Repayable On Promotion To Top Division',
                 11:'Loan Repayable When Established In Top Division',12:'Director',
                 13:'PIK Loan (Total amount of loan repayable on maturity)',
                 14:'Lump Sum Paid On Promotion To Top Division',15:'Miscellaneous'}


def _section(code):
    #16EB38C mode0 excludesFD,00,FB; mode1 includesFD only.
    if code == -3:
        return 'financial_fair_play'
    return None if code in (0,-5) else 'debts'


def stored_date(raw):
    day, year = struct.unpack('<HH', raw)
    out = {'value':None, 'raw_hex':raw.hex(), 'stored_year':year,
           'stored_day_of_year':day & 511, 'unmapped_low_word_flags':day & 0xfe00}
    if (day,year) == (1,1900):
        out['state'] = 'native_default_sentinel'
        return out
    try:
        out['value'] = world.packed_date(raw)
    except ValueError:
        out['state'] = 'unmapped_stored_date'
    else:
        out['state'] = 'stored_date'
    return out


def _read_row(reader, ordinal):
    start = reader.offset
    raw = reader.take(79)
    if raw[0] != 0:
        raise ValueError('Unsupported starting finances record subtype')
    at = 1
    fields = {}
    for off,width in _FIELDS:
        fields[off] = raw[at:at+width]
        at += width
    stored,native,secondary = struct.unpack_from('<III', raw,67)
    if stored != ordinal:
        raise ValueError('Starting finances original ordinal mismatch')
    return {'start':start, 'end':reader.offset, 'ordinal':ordinal, 'fields':fields,
            'native_id':native, 'secondary_id':secondary,
            'team_index':int.from_bytes(fields[0x18],'little',signed=True),
            'competition_index':int.from_bytes(fields[0x20],'little',signed=True),
            'source_code':int.from_bytes(fields[0x5e],'little',signed=True),
            'wire_sha256':hashlib.sha256(raw).hexdigest()}


def _project(row, team_native_ids, competitions):
    f = row['fields']
    amount = int.from_bytes(f[0x28],'little',signed=True)
    section = _section(row['source_code'])
    rate = struct.unpack('<f',f[0x40])[0]
    if not math.isfinite(rate):
        interest = {'value':None,'state':'unmapped_float_encoding'}
    elif rate == -1.0:
        interest = {'value':None,'state':'native_unset'}
    elif rate == -99.0:
        #16EA264..2CC creates the native real0 value for this stored sentinel.
        interest = {'value':0.0,'state':'native_sentinel_to_zero'}
    elif 0.0<=rate<=50.0:
        interest = {'value':rate,'state':'stored_native_real'}
    else:
        interest = {'value':None,'state':'outside_supported_editor_domain'}
    interest.update(stored_value=rate if math.isfinite(rate) else None,
                    native_getter_value=(0.0 if rate==-99.0 else None if rate==-1.0 or not math.isfinite(rate) else rate),
                    raw_hex=f[0x40].hex())
    comp = row['competition_index']
    return {'original_record_index':row['ordinal'], 'native_id':row['native_id'],
            'secondary_id':row['secondary_id'], 'section':section,
            'source_code':row['source_code'],
            'source_name':DEBT_SOURCES.get(row['source_code']) if section=='debts' else None,
            'source_name_state':('installed_pregame_editor_enum' if row['source_code'] in DEBT_SOURCES
                                 else 'ffp_branch' if section=='financial_fair_play' else 'unmapped_enum'),
            'team':{'database_index':row['team_index'],
                    'native_id':team_native_ids[row['team_index']], 'namespace':'TEAM_BASE'},
            'competition':None if comp==-1 else competitions[comp],
            'cash':{'value':amount,'stored_signed32':amount,'currency_code':None,
                    'currency_state':'starting_component_currency_not_proved',
                    'meaning':'Original Debt' if section=='debts' else 'Financial Fair Play Records amount'},
            'start_date':stored_date(f[0x38]), 'end_date':stored_date(f[0x3c]),
            'year':struct.unpack('<H',f[0x38][2:])[0] if section=='financial_fair_play' else None,
            'interest_rate':interest if section=='debts' else None,
            'unmapped_stored_fields':{hex(off):raw.hex() for off,raw in f.items()
                                     if off not in (0x18,0x28,0x38,0x3c,0x40,0x5e,0x20)},
            'source_start':row['start'],'source_end':row['end'],'source_sha256':row['wire_sha256'],
            'current_obligation_state':'not_established'}


def read_starting_finances(reader, *, club_native_id, team_native_ids, competitions,
                           include_ffp=False, offset=0, limit=50):
    """Consume a complete component and project one bounded source-order page."""
    if reader.take(6) != bytes.fromhex('0301746d632e') or reader.u16()!=3754:
        raise ValueError('Unsupported starting finances component format/version')
    count = reader.u32()
    if reader.u8()!=0 or count>MAX_ROWS or count*79+9>reader.size-reader.offset:
        raise ValueError('Starting finances count/flags/extent exceed supported profile')
    selected=[]
    counts={'debts':0,'financial_fair_play':0,'excluded_native_categories':0}
    qualified=source_matches=0
    for ordinal in range(count):
        row=_read_row(reader,ordinal)
        index=row['team_index']
        comp=row['competition_index']
        if not -1<=index<len(team_native_ids) or not -1<=comp<len(competitions):
            raise ValueError('Starting finances original reference outside canonical same-file table')
        if index==-1 or team_native_ids[index]!=club_native_id:
            continue
        source_matches+=1
        section=_section(row['source_code'])
        if section is None:
            counts['excluded_native_categories']+=1
            continue
        counts[section]+=1
        if section=='financial_fair_play' and not include_ffp:
            continue
        if offset<=qualified<offset+limit:
            selected.append(_project(row,team_native_ids,competitions))
        qualified+=1
    footer_start=reader.offset
    auxiliary=reader.u32()
    if auxiliary>MAX_ROWS or auxiliary*12+5>reader.size-reader.offset:
        raise ValueError('Starting finances footer exceeds supported bounds')
    reader.skip(auxiliary*12)
    footer_byte,footer_word=reader.u8(),reader.u32()
    if reader.offset!=reader.size or reader.source.read(1) or not reader.source.finished:
        raise ValueError('Starting finances component did not close at its declared end')
    return {'state':'available','rows':selected,'matched_count':qualified,
            'native_debt_count':counts['debts'],
            'native_ffp_count':counts['financial_fair_play'] if include_ffp else None,
            'ffp_state':'included' if include_ffp else 'not_requested',
            'matching_starting_record_count':source_matches,
            'excluded_native_category_count':counts['excluded_native_categories'],
            'table_count':count,'complete_component':True,
            'footer':{'start':footer_start,'auxiliary_count':auxiliary,'byte':footer_byte,'word':footer_word},
            'offset':offset,'limit':limit,
            'next_offset':offset+limit if offset+limit<qualified else None}


def _reach_teams(reader):
    competitions=[]
    text_bytes=0
    for row in saved_database.table(reader,'COMP',saved_competition_records.read_competition):
        # Keep only canonical identity/names, not unrelated competition fields.
        entry={key:row.get(key) for key in ('database_index','native_id','secondary_id','name','short_name')}
        entry['namespace']='COMP'
        text_bytes+=sum(len(v.encode('utf8')) for v in (entry['name'],entry['short_name']) if v)
        if text_bytes>16*1024*1024:
            raise ValueError('Starting finances competition text context budget exhausted')
        competitions.append(entry)
    for label,decoder in (
        ('CONTINENT',saved_currency_records.skip_continent),('CURRENCY',saved_currency_records.read_currency),
        ('INJURY',saved_squad_tables.skip_injury),('MEDIA_SOURCE',saved_squad_tables.skip_media_source),
        ('LANGUAGE',saved_squad_tables.skip_language),('NATION',saved_nations.skip_nation),
        ('NATIONAL_TEAM_CONTAINER',saved_national_containers.skip_national_container),
    ):
        saved_database.skip_table(reader,label,decoder)
    saved_region_tables.skip_name_tables(reader)
    for label,decoder in (
        ('REGION',saved_region_tables.skip_region),('LOCAL_REGION',saved_region_tables.skip_local_region),
        ('STADIUM',saved_squad_tables.skip_stadium),('STADIUM_CHANGE',saved_squad_tables.skip_stadium_change),
        ('STAGE_NAME',saved_squad_tables.skip_stage_name),
    ):
        saved_database.skip_table(reader,label,decoder)
    return competitions


def get_starting_finances(filename,club_index,expected_snapshot_id,*,include_ffp=False,
                          offset=0,limit=50,directory=None):
    if type(club_index)is not int or not 0<=club_index<2**31:
        raise ValueError('Supply an original saved CLUB index')
    if not isinstance(expected_snapshot_id,str) or not expected_snapshot_id:
        raise ValueError('Supply the snapshot ID that issued the CLUB index')
    if type(include_ffp)is not bool or type(offset)is not int or offset<0 or type(limit)is not int or not 1<=limit<=100:
        raise ValueError('Invalid starting finances page or FFP selection')
    if not _SLOT.acquire(blocking=False):
        raise ValueError('Another saved starting finances lookup is in progress; retry after it finishes')
    try:
        with saved_database.open_archive_at_clubs(filename,expected_snapshot_id,directory) as (reader,source,handle,entries):
            selected=None
            clubs=[]
            for club in saved_database.table(reader,'CLUB',saved_club_records.read_club):
                # Native-ID array permits all same-ID CLUB alias counts without labels.
                clubs.append(club['native_id'])
                if club['database_index']==club_index:
                    selected=club
            if selected is None:
                raise ValueError('CLUB index outside the complete canonical table')
            competitions=_reach_teams(reader)
            team_ids=array('I')
            teams=[]
            matched_teams=labels=0
            decode=partial(saved_team_records.read_team,include_roster=False)
            for team in saved_database.table(reader,'TEAM_BASE',decode):
                team_ids.append(team['native_id'])
                if team['native_id']==selected['native_id']:
                    matched_teams+=1
                    if len(teams)<MAX_CONTEXT_DETAILS:
                        labels+=sum(len(v.encode('utf8')) for v in (team['name'],team['short_name']) if v)
                        if labels>MAX_CONTEXT_TEXT_BYTES:
                            raise ValueError('Starting finances TEAM label context budget exhausted')
                        teams.append({k:team[k] for k in ('database_index','native_id','secondary_id','owner_kind','owner_index','name','short_name')})
            root=entries[0].path.split('/')[0]
            matches=[entry for entry in entries if entry.path==root+'/starting_club_debt_db.cmt']
            context={'club':selected,'matching_team_count':matched_teams,'matching_teams':teams,
                     'matching_team_details_complete':matched_teams==len(teams),
                     'same_native_id_club_count':sum(value==selected['native_id'] for value in clubs),
                     'club_identity_state':('unique_native_id' if sum(value==selected['native_id'] for value in clubs)==1 else 'shared_native_id_native_predicate_only'),
                     'reciprocal_TEAM_ownership_required_by_native_filter':False,
                     'selection':'native TEAM.native_id == selected CLUB.native_id; all matching TEAM indices retained',
                     'canonical_club_count':len(clubs),'canonical_team_count':len(team_ids)}
            common={**source,'identity_context':context,'include_ffp':include_ffp,
                    'scope':'stored starting finance inputs; not the current obligation or balance ledger',
                    'current_obligations_available':False,'currency_code':None,
                    'currency_state':'starting_component_currency_not_proved'}
            if not matches:
                return {**common,'state':'unavailable','reason':'starting_club_debt_component_not_stored',
                        'rows':[],'matched_count':None,'native_debt_count':None,'native_ffp_count':None,
                        'complete_component':False,'ffp_state':'unavailable' if include_ffp else 'not_requested',
                        'offset':offset,'limit':limit,'next_offset':None}
            if len(matches)!=1:
                raise ValueError('Ambiguous starting finances components')
            entry=matches[0]
            with saved_component_stream.open_component(handle,entry) as debt_reader:
                result=read_starting_finances(debt_reader,club_native_id=selected['native_id'],
                        team_native_ids=team_ids,competitions=competitions,include_ffp=include_ffp,offset=offset,limit=limit)
            result.update(common,component={'path':entry.path,'uncompressed_size':entry.uncompressed_size})
            if len(json.dumps(result,ensure_ascii=True,separators=(',',':')).encode())>MAX_RESPONSE_BYTES:
                raise ValueError('Starting finances response budget exhausted; reduce limit')
        return result
    finally:
        _SLOT.release()
