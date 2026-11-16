"""Real compressed archives and genuine typed PLAYER fixture bodies."""
from dataclasses import dataclass
import json
from pathlib import Path
import struct
import os
import pytest
from fm_live_mcp import saved_player_history as history, saved_population as population, snapshot_catalog
from fm_live_mcp.person_wire import parse_record
import test_saved_competition_state as archive_builder

FIXTURES=json.loads(Path(__file__).with_name('person_wire_fixtures.json').read_bytes())

@dataclass(frozen=True)
class Layout:
    _data: object = None
    person_count: int = 1
    person_offset: int = 0
    person_records_offset: int = 0
    provenance: str = 'synthetic explicit original PLAYER start'
    @property
    def name_counts(self): return {'first':0,'second':0,'common':0}

def player(owner=0):
    f=next(f for f in FIXTURES if f['expected']['signed_tag']==2)
    raw=bytearray.fromhex(f['raw_hex']);raw[-12:-8]=struct.pack('<I',0)
    row=parse_record(raw,0,0,limit=len(raw),_include_history=True)
    at=row['_history']['source_offset'];raw[at:at+4]=struct.pack('<i',owner)
    return bytes(raw)+bytes(9)

def stored(year,category,goals=0):
    raw=bytearray(168);struct.pack_into('<i',raw,1,10);struct.pack_into('<h',raw,5,7)
    struct.pack_into('<H',raw,11,year);raw[31]=category;raw[27]=goals
    return bytes(raw)

def vector(values): return struct.pack('<I',len(values))+b''.join(struct.pack('<i',v)for v in values)
def index(offsets=(0,168,168)):
    previous=0;encoded=[]
    for value in offsets:
        previous=((value-previous+2**31)%2**32)-2**31;encoded.append(previous)
    return history.LIST_HEADER+vector(())+struct.pack('<I',1)+vector(encoded)+vector((0,)if not offsets else())+struct.pack('<IH',168,7)

@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:Layout(data))
    monkeypatch.setattr(population,'_LAST_LAYOUT',None);population._PREFIXES.clear()
    yield
    population._PREFIXES.clear()

def save(tmp_path,monkeypatch,*,owner=0,offsets=(0,168,168),ls=None,dt=None,name='history.fm',database=None):
    monkeypatch.setattr(archive_builder,'world_database',lambda comps:player(owner) if database is None else database)
    members={'rgman/player_stats_hist_ls.dat':index(offsets)if ls is None else ls,
             'player_stats_hist_dt.cmt':history.DATA_HEADER+stored(2030,1)+stored(2029,2,255)if dt is None else dt}
    path=archive_builder.archive(tmp_path/name,[],members)
    pin=snapshot_catalog.inspect_snapshot(path.name,directory=tmp_path,limit=1)['snapshot_id']
    return path,pin

def query(source,**kwargs):
    path,pin=source
    return history.get_history(path.name,0,pin,directory=path.parent,**kwargs)

def test_genuine_player_owner_key_and_default_person_omission():
    raw=player(0);row=parse_record(raw,0,0,limit=len(raw))
    assert '_history' not in row
    checked=parse_record(raw,0,0,limit=len(raw),_include_history=True)
    assert checked['_history']['owner_index']==0
    assert struct.unpack_from('<i',raw,checked['_history']['source_offset'])[0]==0

def test_zero_unknown_duplicates_and_same_pin_provenance(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch);r=query(source)
    assert r['state']=='available' and r['total_indexed_entries']==3 and r['selected_row_count']==3
    assert [row['entry_index']for row in r['rows']]==[0,1,2]
    assert [row['native_offset']for row in r['rows']]==[0,168,168]
    assert r['rows'][0]['statistics']['goals']==0 and r['rows'][0]['statistics']['total_appearances']==0
    assert r['rows'][1]['statistics']['goals'] is None
    assert r['rows'][1]['record_sha256']==r['rows'][2]['record_sha256']
    assert r['snapshot_id']==source[1] and len(r['components'])==3
    assert all(c['state']=='complete_frame_and_packed_bytes_rechecked'for c in r['components'].values())

def test_filters_before_paging_preserve_native_duplicates(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch);a=query(source,years=[2029],category_codes=[2],limit=1)
    b=query(source,years=[2029],category_codes=[2],limit=1,offset=a['next_offset'])
    assert a['selected_row_count']==b['selected_row_count']==2
    assert [a['rows'][0]['entry_index'],b['rows'][0]['entry_index']]==[1,2]
    assert b['next_offset'] is None
    empty=query(source,years=[2000]);assert empty['state']=='available'and empty['selected_row_count']==0 and empty['rows']==[]

@pytest.mark.parametrize('owner,offsets,state',[(-1,(0,),'no_history_index'),(-10,(0,),'no_history_index'),(0,(),'available_empty')])
def test_no_index_and_checked_empty_are_distinct(tmp_path,monkeypatch,owner,offsets,state):
    r=query(save(tmp_path,monkeypatch,owner=owner,offsets=offsets))
    assert r['state']==state and r['rows']==[] and r['selected_row_count']==0

@pytest.mark.parametrize('owner,offsets',[(1,(0,)),(0,(1,)),(0,(336,))])
def test_invalid_owner_and_offsets_not_empty(tmp_path,monkeypatch,owner,offsets):
    source=save(tmp_path,monkeypatch,owner=owner,offsets=offsets)
    with pytest.raises(ValueError):query(source)
    assert not population._PREFIXES and population._LAST_LAYOUT is None

def test_negative_offsets_skipped_after_native_reconstruction(tmp_path,monkeypatch):
    r=query(save(tmp_path,monkeypatch,offsets=(-1,0,-1)))
    assert r['total_indexed_entries']==3 and r['decoded_row_count']==1 and len(r['skipped_entries'])==2
    assert r['rows'][0]['entry_index']==1

@pytest.mark.parametrize('kw',[{'years':[]},{'category_codes':[]},{'years':[True]},{'years':[65536]},{'category_codes':[6]},{'offset':True},{'limit':201}])
def test_strict_filters_fail_before_archive_access(kw):
    with pytest.raises(ValueError):history.get_history('missing.fm',0,'pin',**kw)

@pytest.mark.parametrize('field',['list_tail','data_tail','data_header'])
def test_late_invalid_components_do_not_commit_progress(tmp_path,monkeypatch,field):
    kwargs={'ls':index()+b'bad'}if field=='list_tail'else {'dt':history.DATA_HEADER+stored(2030,1)+b'x'}if field=='data_tail'else {'dt':b'wronghdr'+stored(2030,1)}
    source=save(tmp_path,monkeypatch,**kwargs)
    with pytest.raises(ValueError):query(source)
    assert not population._PREFIXES and population._LAST_LAYOUT is None

def test_stale_pin_and_replacement_reject(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch)
    replacement=save(tmp_path,monkeypatch,name='replacement.fm',owner=-1)[0]
    os.replace(replacement,source[0])
    with pytest.raises(ValueError,match='identity changed'):query(source)

def test_trailing_packed_data_frame_rejects_even_empty_filter_result(tmp_path,monkeypatch):
    compress=archive_builder.compress
    monkeypatch.setattr(archive_builder,'compress',lambda raw:compress(raw)+(b'x'if raw.startswith(history.DATA_HEADER)else b''))
    source=save(tmp_path,monkeypatch)
    with pytest.raises(ValueError):query(source,years=[2000])
    assert not population._PREFIXES

@pytest.mark.parametrize('field,value', [('team',-3),('competition',-3),('competition',-2)])
def test_reference_transport_rejects_invalid_or_extended_indices(field,value):
    raw=bytearray(stored(2030,1))
    struct.pack_into('<i'if field=='team'else'<h',raw,1 if field=='team'else 5,value)
    with pytest.raises(ValueError):history._decode(bytes(raw))

def test_null_reference_words_are_null_not_other_snapshot_links():
    raw=bytearray(stored(2030,1));struct.pack_into('<ih',raw,1,-1,-1)
    row=history._decode(bytes(raw))
    assert row['team_reference']['stored_index'] is None
    assert row['competition_reference']['state']=='null_reference'

def test_bounded_same_query_advances_original_slots(tmp_path,monkeypatch):
    first=player(0)[:-9];second=bytearray(first);second[-12:-8]=struct.pack('<I',1)
    source=save(tmp_path,monkeypatch,database=first+second+bytes(9))
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:Layout(data,person_count=2))
    monkeypatch.setattr(history,'MAX_ADVANCE',1)
    path,pin=source
    first_result=history.get_history(path.name,1,pin,directory=tmp_path)
    assert first_result['state']=='stopped' and first_result['selected_row_count'] is None
    assert first_result['PERSON_coverage']['retry_same_query_to_advance']
    assert set(first_result['components'])=={'game_db.dat'}
    final=history.get_history(path.name,1,pin,directory=tmp_path)
    assert final['state']=='available' and final['person']['ordinal']==1
    assert final['PERSON_coverage']['footer']['state']=='source_footer_read'

def test_unsupported_class_is_not_no_history(tmp_path,monkeypatch):
    f=next(f for f in FIXTURES if f['expected']['signed_tag']==16)
    raw=bytearray.fromhex(f['raw_hex']);raw[-12:-8]=bytes(4)
    result=query(save(tmp_path,monkeypatch,database=bytes(raw)+bytes(9)))
    assert result['state']=='unavailable' and result['owner'] is None
    assert result['total_indexed_entries'] is None and result['selected_row_count'] is None
    assert set(result['components'])=={'game_db.dat'}

def test_final_snapshot_change_rejects_without_new_cache(tmp_path,monkeypatch):
    source=save(tmp_path,monkeypatch);read=history._rows
    def changed(reader,offsets):
        rows=read(reader,offsets)
        info=source[0].stat();os.utime(source[0],ns=(info.st_atime_ns,info.st_mtime_ns+1_000_000))
        return rows
    monkeypatch.setattr(history,'_rows',changed)
    with pytest.raises(ValueError,match='changed'):query(source)
    assert not population._PREFIXES and population._LAST_LAYOUT is None
