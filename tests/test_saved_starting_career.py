import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import saved_starting_career as career, saved_population as population,snapshot_catalog
from fm_live_mcp.person_wire import parse_record
import test_saved_player_history as prior
import test_saved_competition_state as archives


def anchor(pairs=((9,0),)):
    rows=b''.join(struct.pack('<b5i3I',0,*([-1]*5),i,100+i,200+i)for i in range(4))
    return (career._EMPTY+struct.pack('<IB',4,0)+rows+struct.pack('<IBI',0,1,0)+career._EMPTY*2+
            struct.pack('<I',len(pairs))+b''.join(struct.pack('<ii',*p)for p in pairs)+bytes(4))


def wire(apps=255,goals=0,year=2025):
    return career.ROW.pack(year,7,1,apps,goals,-2,650,650,11,11,0,1,2,3)


def index(values=(0,40,40)):
    prev=0;encoded=[]
    for off in values:
        prev=((off-prev+2**31)%2**32)-2**31;encoded.append(prev)
    return (prior.history.LIST_HEADER+prior.vector(())+struct.pack('<I',1)+prior.vector(encoded)+
            prior.vector((0,)if not values else())+struct.pack('<IH',40,3))


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:prior.Layout(data))
    monkeypatch.setattr(population,'_LAST_LAYOUT',None);population._PREFIXES.clear();career._CONTEXT_COUNTS.clear()
    monkeypatch.setattr(career.fixture,'_canonical_context',lambda data:({'source_major':3754,'source_minor':9},[{}],[{}],0))
    yield
    population._PREFIXES.clear()


def save(tmp_path,monkeypatch,*,owner=0,values=(0,40,40),pairs=None,dt=None,ls=None,database=None):
    body=prior.player()
    identity=parse_record(body,0,0,limit=len(body))['identity']
    native=prior.history._signed(identity['native_id_word'])
    data=body+anchor(((native,owner),)if pairs is None else pairs)if database is None else database
    monkeypatch.setattr(archives,'world_database',lambda comps:data)
    members={'pl_hist_ls.dat':index(values)if ls is None else ls,
             'pl_hist_dt.cmt':b'\x03\x01tmc.\x03\x00'+wire()+wire(0,255,2024)if dt is None else dt}
    p=archives.archive(tmp_path/'career.fm',[],members)
    pin=snapshot_catalog.inspect_snapshot(p.name,directory=tmp_path,limit=1)['snapshot_id']
    return p,pin


def query(src,**kw):
    p,pin=src
    return career.get_starting_history(p.name,0,pin,directory=p.parent,**kw)


def test_native_owner_not_person_ordinal_and_duplicate_paging(tmp_path,monkeypatch):
    s=save(tmp_path,monkeypatch)
    r=query(s,years=[2024],limit=1)
    assert r['state']=='available'and r['total_indexed_entries']==3 and r['selected_row_count']==2
    assert r['rows'][0]['entry_index']==1 and r['rows'][0]['appearances']==0 and r['rows'][0]['goals']is None
    q=query(s,years=[2024],offset=r['next_offset'],limit=1)
    assert q['rows'][0]['entry_index']==2 and q['next_offset']is None
    assert q['rows'][0]['record_sha256']==r['rows'][0]['record_sha256']
    assert all(c['state']=='complete_frame_and_packed_bytes_rechecked'for c in r['components'].values())
    assert r['owner']['owner_key']==0 and r['owner']['native_id']!=0


@pytest.mark.parametrize('owner,values,state',[(0,(),'available_empty'),(-1,(0,),'no_history_index'),(1,(0,),'unavailable')])
def test_owner_states(tmp_path,monkeypatch,owner,values,state):
    r=query(save(tmp_path,monkeypatch,owner=owner,values=values))
    assert r['state']==state and r['rows']==[]
    if state=='available_empty': assert r['selected_row_count']==0


def test_map_miss_is_not_empty(tmp_path,monkeypatch):
    r=query(save(tmp_path,monkeypatch,pairs=((1,0),)))
    assert r['state']=='unavailable'and r['selected_row_count']is None


@pytest.mark.parametrize('pairs',[((9,0),(9,1)),((10,0),(9,1))])
def test_bad_map_order(pairs):
    with pytest.raises(ValueError,match='unsorted or duplicated'):
        career.locate_owner_map(anchor(pairs),competition_count=1,stage_name_count=1,native_id=9)


@pytest.mark.parametrize('section',[0,1,2])
def test_adjoining_positive_tables_stop(section):
    raw=bytearray(anchor());at=[0,14+5+4*33+9,14+5+4*33+9+14][section]
    raw[at]=1
    with pytest.raises(ValueError):career.locate_owner_map(raw,competition_count=1,stage_name_count=1,native_id=9)


def test_duplicate_anchors_refused():
    with pytest.raises(ValueError,match='Ambiguous'):
        career.locate_owner_map(anchor()+anchor(),competition_count=1,stage_name_count=1,native_id=9)


@pytest.mark.parametrize('kwargs',[{'person_index':True},{'years':[]},{'years':[True]},{'years':[32768]},{'offset':True},{'limit':201}])
def test_strict_inputs(kwargs):
    index=kwargs.pop('person_index',0)
    with pytest.raises(ValueError):career.get_starting_history('no.fm',index,'pin',**kwargs)


def test_late_failure_does_not_commit_progress(tmp_path,monkeypatch):
    s=save(tmp_path,monkeypatch,ls=index()+b'bad')
    with pytest.raises(ValueError):query(s)
    assert not population._PREFIXES and population._LAST_LAYOUT is None


def test_row_sentinels_and_truncations():
    r=career.decode_row(wire())
    assert r['appearances']is None and r['goals']==0 and r['on_loan']is True
    assert r['transfer_fee_raw']is None and r['fee_or_other_code_raw_i32']==-2
    assert r['team_reference']['state']=='unresolved_native_identity_pair'
    for n in range(40):
        with pytest.raises(ValueError):career.decode_row(wire()[:n])


def test_same_query_advances_checked_person_prefix(tmp_path,monkeypatch):
    first=prior.player()[:-9];second=bytearray(first);second[-12:-8]=struct.pack('<I',1)
    native=prior.history._signed(parse_record(first,0,0,limit=len(first))['identity']['native_id_word'])
    database=first+second+bytes(9)+anchor(((native,0),))
    src=save(tmp_path,monkeypatch,database=database)
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:prior.Layout(data,person_count=2))
    monkeypatch.setattr(prior.history,'MAX_ADVANCE',1)
    path,pin=src
    r=career.get_starting_history(path.name,1,pin,directory=tmp_path)
    assert r['state']=='stopped' and r['total_indexed_entries']is None
    assert r['PERSON_coverage']['retry_same_query_to_advance']
    r=career.get_starting_history(path.name,1,pin,directory=tmp_path)
    assert r['state']=='available'and r['person']['ordinal']==1


def test_outside_person_is_not_empty_history(tmp_path,monkeypatch):
    p,pin=save(tmp_path,monkeypatch)
    r=career.get_starting_history(p.name,1,pin,directory=tmp_path)
    assert r['state']=='unavailable'and r['selected_row_count']is None and r['owner']is None


def test_stale_pin(tmp_path,monkeypatch):
    p,pin=save(tmp_path,monkeypatch)
    with pytest.raises(ValueError,match='identity changed'):
        career.get_starting_history(p.name,0,'wrong',directory=tmp_path)
    assert not population._PREFIXES


def test_unsupported_class_and_map_absence_not_empty(tmp_path,monkeypatch):
    f=next(f for f in prior.FIXTURES if f['expected']['signed_tag']==16)
    raw=bytearray.fromhex(f['raw_hex']);raw[-12:-8]=bytes(4)
    r=query(save(tmp_path,monkeypatch,database=bytes(raw)+bytes(9)))
    assert r['state']=='unavailable'and r['owner']is None and r['selected_row_count']is None


def test_all_ones_identity_not_an_invented_name():
    raw=bytearray(wire());struct.pack_into('<II',raw,19,0xffffffff,0xffffffff)
    r=career.decode_row(raw)['competition_reference']
    assert r['state']=='stored_all_ones_identity_pair'and r['name']is None
    assert r['native_id_word']==r['secondary_word']==0xffffffff


def test_counts_only_cache_avoids_retraversal_after_complete_validation(tmp_path,monkeypatch):
    calls=[]
    def context(data):
        calls.append(len(data))
        return {'source_major':3754,'source_minor':9},[{}],[{}],0
    monkeypatch.setattr(career.fixture,'_canonical_context',context)
    src=save(tmp_path,monkeypatch)
    first=query(src);second=query(src)
    assert len(calls)==1 and first['rows']==second['rows'] and first['components']==second['components']
    assert len(career._CONTEXT_COUNTS)==1 and next(iter(career._CONTEXT_COUNTS.values()))==(1,1)


def test_failed_frame_does_not_cache_counts(tmp_path,monkeypatch):
    src=save(tmp_path,monkeypatch,ls=index()+b'bad')
    with pytest.raises(ValueError):query(src)
    assert not career._CONTEXT_COUNTS
