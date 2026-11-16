"""Closed-pair inventory and raw paging through genuine compressed snapshots."""
import os
import struct
import pytest
from fm_live_mcp import saved_history_inventory as inventory, snapshot_catalog
import test_saved_competition_state as builder


def vector(values):
    return struct.pack('<I',len(values))+b''.join(struct.pack('<i',v)for v in values)


def index(spec,owners,free=(),empty=None):
    if empty is None:empty=[i for i,row in enumerate(owners)if not row]
    body=inventory.fixed.LIST_HEADER+vector(free)+struct.pack('<I',len(owners))
    for values in owners:
        encoded=[];previous=0
        for value in values:
            previous=((value-previous+2**31)%2**32)-2**31;encoded.append(previous)
        body+=vector(encoded)
    return body+vector(empty)+struct.pack('<IH',spec.width,spec.version)


def save(tmp_path,monkeypatch,name='award_club_hist',*,owners=None,free=None,ls=None,dt=None,missing=()):
    spec=inventory.FAMILIES[name]
    owners=[(),(spec.width,2*spec.width,spec.width,-1),()]if owners is None else owners
    free=(0,)if free is None else free
    data=b'\x03\x01tmc.'+struct.pack('<H',spec.version)+b'F'*spec.width+b'A'*spec.width+b'B'*spec.width
    members={spec.index_path:index(spec,owners,free)if ls is None else ls,
             spec.data_path:data if dt is None else dt}
    for path in missing:members.pop(path,None)
    monkeypatch.setattr(builder,'world_database',lambda _:b'NOT_A_DATABASE_AND_MUST_NOT_BE_LOADED')
    path=builder.archive(tmp_path/'inventory.fm',[],members)
    pin=snapshot_catalog.inspect_snapshot(path.name,directory=tmp_path,limit=1)['snapshot_id']
    return path,pin


def query(source,**kwargs):
    path,pin=source
    return inventory.get_inventory(path.name,pin,directory=path.parent,**kwargs)


@pytest.mark.parametrize('family',list(inventory.FAMILIES))
def test_all_closed_profiles_count_unique_references_and_free(tmp_path,monkeypatch,family):
    result=query(save(tmp_path,monkeypatch,family),family=family)
    row=result['families'][0];counts=row['counts']
    assert row['state']=='indexed'and result['all_requested_pairs_validated']
    assert counts['owner_count']==3 and counts['empty_owner_count']==2
    assert counts['indexed_entry_count']==4 and counts['negative_indexed_entries']==1
    assert counts['indexed_record_reference_count']==3 and counts['indexed_record_count']==2
    assert counts['duplicate_indexed_references']==1 and counts['free_record_count']==1
    assert counts['physical_record_count']==3 and counts['partition_complete_and_disjoint']
    assert len(row['components'])==2 and all(x['state']=='complete_frame_and_packed_bytes_rechecked'for x in row['components'].values())


def test_raw_page_preserves_duplicates_holes_and_source_extents(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch);spec=inventory.FAMILIES['award_club_hist']
    first=query(source,family='award_club_hist',owner_index=1,limit=2)['families'][0]
    second=query(source,family='award_club_hist',owner_index=1,offset=first['selected_owner']['next_offset'],limit=2)['families'][0]
    assert first['selected_owner']['state']=='indexed_owner'
    assert first['selected_owner']['entries'][0]['raw_hex']==(b'A'*spec.width).hex()
    assert first['selected_owner']['entries'][1]['data_start']==8+2*spec.width
    assert second['selected_owner']['entries'][0]['raw_hex']==first['selected_owner']['entries'][0]['raw_hex']
    assert second['selected_owner']['entries'][1]['state']=='negative_offset_no_record'
    assert second['selected_owner']['next_offset']is None
    assert first['owner_namespace'].startswith('source_local')and first['row_semantics'].startswith('opaque')


def test_empty_owner_outside_owner_and_past_page_are_distinct(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch)
    empty=query(source,family='award_club_hist',owner_index=0)['families'][0]['selected_owner']
    outside=query(source,family='award_club_hist',owner_index=99)['families'][0]['selected_owner']
    past=query(source,family='award_club_hist',owner_index=1,offset=99)['families'][0]['selected_owner']
    assert empty['state']=='empty_owner'and empty['total_entry_count']==0
    assert outside['state']=='outside_owner_table'and outside['total_entry_count']is None
    assert past['state']=='indexed_owner'and past['total_entry_count']==4 and past['entries']==[]


def test_closed_inventory_missing_is_unknown_count_not_zero(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch)
    result=query(source)
    assert len(result['families'])==16 and result['allowlisted_family_count']==16
    missing=[row for row in result['families']if row['state']=='missing_components']
    assert len(missing)==15 and all(row['counts']is None for row in missing)
    assert not result['all_requested_pairs_validated']


@pytest.mark.parametrize('kind',['index_header','width','data_header'])
def test_unsupported_profiles_fully_validated_without_fake_counts(tmp_path,monkeypatch,kind):
    spec=inventory.FAMILIES['award_club_hist'];ls=index(spec,[()],free=(0,37,74))
    dt=b'\x03\x01tmc.'+struct.pack('<H',spec.version)+bytes(3*spec.width)
    if kind=='index_header':ls=b'unknown!'+ls[8:]
    elif kind=='width':ls=ls[:-6]+struct.pack('<IH',spec.width+1,spec.version)
    else:dt=b'unknown!'+dt[8:]
    row=query(save(tmp_path,monkeypatch,ls=ls,dt=dt),family='award_club_hist')['families'][0]
    assert row['state']=='unsupported'and row['counts']is None and len(row['components'])==2


def test_empty_data_and_free_data_are_distinct(tmp_path,monkeypatch):
    spec=inventory.FAMILIES['award_club_hist']
    empty=query(save(tmp_path,monkeypatch,owners=[()],free=(),dt=b'\x03\x01tmc.'+struct.pack('<H',spec.version)),family='award_club_hist')['families'][0]
    free=query(save(tmp_path,monkeypatch,owners=[()],free=(0,37,74)),family='award_club_hist')['families'][0]
    assert empty['state']=='empty_data'and empty['counts']['physical_record_count']==0
    assert free['state']=='all_slots_free'and free['counts']['free_record_count']==3


@pytest.mark.parametrize('kind',['count','truncated','trailing','empty_owner','unaligned','outside'])
def test_corrupt_index_rejects_without_partial_success(tmp_path,monkeypatch,kind):
    spec=inventory.FAMILIES['award_club_hist'];ls=index(spec,[()],free=(0,37,74))
    if kind=='count':ls=ls[:8]+struct.pack('<I',0xffffffff)+ls[12:]
    elif kind=='truncated':ls=ls[:-1]
    elif kind=='trailing':ls+=b'x'
    elif kind=='empty_owner':ls=index(spec,[(37,)],free=(0,74),empty=[0])
    elif kind=='unaligned':ls=index(spec,[(1,)],free=(0,74))
    else:ls=index(spec,[(111,)],free=(0,37,74))
    with pytest.raises(ValueError):query(save(tmp_path,monkeypatch,ls=ls),family='award_club_hist')


def test_unaccounted_or_overlapping_slots_are_explicit(tmp_path,monkeypatch):
    row=query(save(tmp_path,monkeypatch,owners=[(37,)],free=(37,)),family='award_club_hist')['families'][0]
    assert row['state']=='inconsistent_partition'
    assert row['counts']['free_indexed_overlap_count']==1
    assert row['counts']['unaccounted_record_count']==2


@pytest.mark.parametrize('kwargs',[{'family':'../../file'},{'family':'game_db.dat'},{'owner_index':0},{'owner_index':True},{'owner_index':-1},{'offset':1},{'limit':201},{'offset':True}])
def test_arguments_reject_before_source_access(kwargs):
    with pytest.raises(ValueError):inventory.get_inventory('missing.fm','pin',**kwargs)


def test_late_data_frame_corruption_rejects_even_inventory_only(tmp_path,monkeypatch):
    compress=builder.compress
    monkeypatch.setattr(builder,'compress',lambda raw:compress(raw)+(b'x'if raw.startswith(b'\x03\x01tmc.')else b''))
    source=save(tmp_path,monkeypatch)
    with pytest.raises(ValueError):query(source,family='award_club_hist')


def test_stale_pin_and_source_change_reject(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch);path,pin=source
    with pytest.raises(ValueError,match='identity changed'):inventory.get_inventory(path.name,'stale',directory=tmp_path)
    read=inventory.fixed.read_rows
    def changed(reader,offsets,**kwargs):
        value=read(reader,offsets,**kwargs);info=path.stat();os.utime(path,ns=(info.st_atime_ns,info.st_mtime_ns+1_000_000));return value
    monkeypatch.setattr(inventory.fixed,'read_rows',changed)
    with pytest.raises(ValueError,match='changed'):query(source,family='award_club_hist')


def test_aggregate_budgets_fail_before_unbounded_work(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch)
    monkeypatch.setattr(inventory,'MAX_QUERY_WORK',2)
    with pytest.raises(ValueError,match='work|owner count'):query(source,family='award_club_hist')
    monkeypatch.setattr(inventory,'MAX_QUERY_WORK',12_000_000)
    monkeypatch.setattr(inventory,'MAX_QUERY_RAW_BYTES',1)
    with pytest.raises(ValueError,match='byte budget'):query(source,family='award_club_hist')


def test_offline_slot_budget_is_not_zero_or_empty(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch)
    monkeypatch.setattr(inventory,'MAX_FAMILY_SLOTS',2)
    row=query(source,family='award_club_hist')['families'][0]
    assert row['state']=='unsupported'and row['counts']is None
    assert 'budget'in row['reason']and len(row['components'])==2
