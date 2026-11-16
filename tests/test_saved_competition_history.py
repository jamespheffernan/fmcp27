"""Real compressed source framing; no substituted table or record decoder."""
from io import BytesIO
import os
import struct
import pytest
from fm_live_mcp import saved_competition_history as query, saved_competition_history_records as codec
from fm_live_mcp import saved_competition_records, snapshot_catalog
from fm_live_mcp.saved_component_stream import Reader
from test_saved_competition_records import record
from test_saved_competition_prefix import wire
from test_saved_league_tables import archive
from test_saved_squad_search import club, team


def comp(index=0,native=11,key=1,secondary=0):
    body=bytearray(record(ordinal=index,native_id=native,secondary_id=secondary))
    struct.pack_into('<i',body,len(wire())+1,key)
    return b'\0'+body


def row(year=2029,first=0,second=1,third=-1,competition=0,date=None):
    if date is None:date=2029<<16|143
    return struct.pack('<ihH7iiiBHhhI',competition,year,0,first,second,third,*([-1]*4),-1,-1,0,4,year-1,year,date)


def index(owners):
    raw=bytearray(bytes.fromhex('03017461642e0400')+struct.pack('<II',0,len(owners)))
    for offsets in owners:
        raw.extend(struct.pack('<I',len(offsets)));previous=0
        for offset in offsets:
            encoded=((offset-previous+2**31)%2**32)-2**31
            raw.extend(struct.pack('<i',encoded));previous=encoded
    empty=[i for i,offsets in enumerate(owners)if not offsets]
    raw.extend(struct.pack('<I',len(empty)))
    raw.extend(b''.join(struct.pack('<i',i)for i in empty))
    return bytes(raw)+struct.pack('<IH',55,3)


def save(tmp_path,*,rows=None,owners=None,key=1,missing=(),competitions=None,teams=None,members=None):
    rows=[row(2028),row(2029)]if rows is None else rows
    owners=[[0],[0,55,55]]if owners is None else owners
    parts={'rgman/comp_history_ls.dat':index(owners),'comp_history_dt.cmt':bytes.fromhex('0301746d632e0300')+b''.join(rows)}
    parts.update(members or{})
    for name in missing:parts.pop(name)
    return archive(tmp_path/'history.fm',members=parts,
        competitions=[comp(key=key)]if competitions is None else competitions,
        clubs=[club(0,602,name='Arsenal'),club(1,676,name='Liverpool')],
        teams=[team(0,602,owner=0),team(1,676,owner=1)]if teams is None else teams)


def get(path,competition_index=0,**kwargs):
    pin=snapshot_catalog.inspect_snapshot(path.name,directory=path.parent)['snapshot_id']
    return query.get_history(path.name,competition_index,pin,directory=path.parent,**kwargs)


def test_comp_owner_projection_is_additive_and_signed():
    raw=comp(key=-7)[1:]
    old_reader=Reader(BytesIO(raw),len(raw));new_reader=Reader(BytesIO(raw),len(raw))
    old=saved_competition_records.read_competition(old_reader,0,0)
    new=saved_competition_records.read_competition(new_reader,0,0,include_history_key=True)
    owner=new.pop('history_owner')
    assert new==old and old_reader.offset==new_reader.offset==len(raw)
    assert owner=={'value':-7,'source_offset':len(wire())+1,'source_field':'COMP+0xF0'}
    with pytest.raises(ValueError):saved_competition_records.read_competition(None,0,0,include_history_key=1)


def test_true_owner_canonical_labels_duplicate_order_and_all_complete_frames(tmp_path):
    result=get(save(tmp_path))
    assert result['state']=='available' and result['owner']['value']==1
    assert result['competition']['database_index']==0 and result['competition']['native_id']==11
    assert result['competition']['secondary_id']==0
    assert [r['entry_index']for r in result['rows']]==[0,1,2]
    assert [r['year']for r in result['rows']]==[2028,2029,2029]
    last=result['rows'][-1]
    assert last['date_decided']['value']=='2029-05-23'
    assert last['first_placed']['identity']['name']==''
    assert last['first_placed']['owner_club']['name']=='Arsenal'
    assert last['second_placed']['owner_club']['name']=='Liverpool'
    assert last['third_placed']['state']=='native_null_reference' and last['third_placed']['identity']is None
    assert result['complete_competition_history']is False and result['currentness']=='not_established_by_history_source'
    assert set(result['components'])=={'game_db.dat','comp_history_ls.dat','comp_history_dt.cmt'}
    assert all(r['state']=='complete_frame_and_packed_bytes_rechecked'for r in result['components'].values())


def test_year_filter_before_paging_and_exact_terminal(tmp_path):
    path=save(tmp_path)
    first=get(path,years=[2029],limit=1);last=get(path,years=[2029],offset=first['next_offset'],limit=1)
    assert [first['rows'][0]['entry_index'],last['rows'][0]['entry_index']]==[1,2]
    assert first['selected_row_count']==last['selected_row_count']==2 and last['next_offset']is None
    terminal=get(path,years=[2030]);assert terminal['state']=='available' and terminal['selected_row_count']==0 and terminal['rows']==[]
    assert get(path,offset=100)['rows']==[]


@pytest.mark.parametrize('key,owners,state',[(0,[[0]],'available'),(-1,[[0]],'no_history_index'),(-10,[[0]],'no_history_index'),(0,[[]],'available_empty'),(2,[[0]],'unavailable')])
def test_zero_empty_negative_and_outside_owner_distinctions(tmp_path,key,owners,state):
    result=get(save(tmp_path,key=key,owners=owners))
    assert result['state']==state
    assert result['selected_row_count']is None if state=='unavailable'else result['selected_row_count']==(1 if state=='available'else 0)


def test_row_COMP_is_resolved_independently_of_selected_owner(tmp_path):
    path=save(tmp_path,rows=[row(competition=1)],owners=[[0]],key=0,competitions=[comp(0,11,0),comp(1,999,-1)])
    result=get(path);assert result['competition']['native_id']==11
    assert result['rows'][0]['competition_reference']['identity']['native_id']==999


def test_null_second_and_independent_TEAM_owner_kind(tmp_path):
    path=save(tmp_path,rows=[row(second=-1,third=1)],owners=[[0]],key=0,
        teams=[team(0,602,owner=None),team(1,676,owner_kind=1,owner=0)])
    result=get(path)['rows'][0]
    assert result['second_placed']['identity']is None
    assert result['first_placed']['owner_club']is None
    assert result['third_placed']['owner_club']is None
    assert result['third_placed']['owner_club_state']=='national_owner_not_CLUB'


@pytest.mark.parametrize('value',[True,-1,2**31])
def test_input_validation_before_source(value):
    with pytest.raises(ValueError):query.get_history('missing.fm',value,'pin')


@pytest.mark.parametrize('kwargs',[{'years':[]},{'years':[True]},{'years':[-32769]},{'years':[32768]},{'offset':True},{'limit':201},{'expected_snapshot_id':''}])
def test_filters_and_page_validation_before_source(kwargs):
    args={'filename':'missing.fm','competition_index':0,'expected_snapshot_id':'pin',**kwargs}
    with pytest.raises(ValueError):query.get_history(**args)


@pytest.mark.parametrize('missing',[('comp_history_dt.cmt',),('rgman/comp_history_ls.dat',)])
def test_missing_is_unavailable_not_empty(tmp_path,missing):
    result=get(save(tmp_path,missing=missing))
    assert result['state']=='unavailable' and result['selected_row_count']is None
    assert result['reason']=='history_components_missing'


@pytest.mark.parametrize('raw',[row(first=-2),row(second=2),row(competition=-2),row(competition=2)])
def test_invalid_core_references_reject_even_unselected_year(tmp_path,raw):
    path=save(tmp_path,rows=[raw],owners=[[0]],key=0)
    with pytest.raises(ValueError):get(path,years=[1900])


def test_geometry_versions_late_trailing_and_table_identity_fail_closed(tmp_path):
    for members in [{'rgman/comp_history_ls.dat':index([[1]])},
                    {'rgman/comp_history_ls.dat':index([[0]])+b'x'},
                    {'comp_history_dt.cmt':bytes.fromhex('0301746d632e0200')+row()},
                    {'comp_history_dt.cmt':bytes.fromhex('0301746d632e0300')+row()[:-1]}]:
        with pytest.raises(ValueError):get(save(tmp_path,key=0,members=members))
    with pytest.raises(ValueError):get(save(tmp_path,competitions=[comp(index=1,key=0)]))


def test_snapshot_changes_during_row_decode_reject(tmp_path,monkeypatch):
    path=save(tmp_path);original=codec.decode;changed=False
    def mutate(raw):
        nonlocal changed
        result=original(raw)
        if not changed:
            st=path.stat();os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns+1000000));changed=True
        return result
    monkeypatch.setattr(codec,'decode',mutate)
    with pytest.raises(ValueError,match='changed'):get(path)


def test_unavailable_COMP_stale_pin_and_budget(tmp_path,monkeypatch):
    path=save(tmp_path)
    result=get(path,competition_index=9)
    assert result['state']=='unavailable' and result['selected_row_count']is None
    with pytest.raises(ValueError,match='identity changed'):query.get_history(path.name,0,'wrong',directory=tmp_path)
    monkeypatch.setattr(query,'MAX_RESPONSE_BYTES',1)
    with pytest.raises(ValueError,match='response exceeds'):get(path)


def test_negative_offset_and_duplicates_preserve_physical_entry_indices(tmp_path):
    result=get(save(tmp_path,owners=[[-1,0,0,55]],key=0))
    assert [r['entry_index'] for r in result['rows']]==[1,2,3]
    assert [r['native_offset'] for r in result['rows']]==[0,0,55]
    assert result['total_indexed_entries']==4 and result['decoded_row_count']==3
    assert result['skipped_entries']==[{'entry_index':0,'native_offset':-1,'reason':'native_negative_offset_skipped'}]


def test_duplicate_component_rejects_even_when_other_component_is_missing(tmp_path,monkeypatch):
    from contextlib import contextmanager
    original=query.snapshot_catalog.checked_snapshot
    path=save(tmp_path)
    @contextmanager
    def duplicate(*args,**kwargs):
        with original(*args,**kwargs) as (handle,entries,identity):
            history=next(e for e in entries if e.path.endswith('/comp_history_ls.dat'))
            yield handle,[e for e in entries if not e.path.endswith('/comp_history_dt.cmt')]+[history],identity
    monkeypatch.setattr(query.snapshot_catalog,'checked_snapshot',duplicate)
    with pytest.raises(ValueError,match='Ambiguous'):get(path)


def test_comp_optional_key_flag_is_exact_bool_and_default_keys_remain_legacy():
    raw=comp(key=0)[1:]
    result=saved_competition_records.read_competition(Reader(BytesIO(raw),len(raw)),0,0)
    assert 'history_owner' not in result
    for flag in (None,0,1,[],{},'true'):
        with pytest.raises(ValueError):
            saved_competition_records.read_competition(Reader(BytesIO(raw),len(raw)),0,0,include_history_key=flag)
