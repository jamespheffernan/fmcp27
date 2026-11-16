"""Bounded actual injury transport and independent health-section failure states."""
from contextlib import contextmanager
from pathlib import Path
import json
import pytest
from fm_live_mcp import saved_player_health as health

# B44 positively exercised original v3 rows; no resource/evidence import at runtime.
RAMSEY = bytes.fromhex('032400002343ee072c004000030200ffffffff002102000001ffffffff000700ff')
SHAHAR = bytes.fromhex('03610001011e73ee071b0100000200c302000000cf0200000100760e02001e81ee0706000b00010100ffffffff00c302000001ffffffff000000ff')


def test_real_rows_and_exact_next_collection_boundary():
    raw = bytes([2]) + RAMSEY + SHAHAR + b'\xffNEXT'
    value = health.read_injury_vector(raw, 0, limit=len(raw))
    assert value['stored_record_count'] == 2
    assert value['source_end'] == 1 + len(RAMSEY) + len(SHAHAR)
    assert [r['injury_reference']['stored_index'] for r in value['records']] == [36, 97]
    assert [r['stored_injury_date']['value'] for r in value['records']] == ['2030-10-18', '2030-10-13']
    assert [r['raw_record_hex'] for r in value['records']] == [RAMSEY.hex(), SHAHAR.hex()]
    assert all(r['injury_reference']['identity'] is None for r in value['records'])


@pytest.mark.parametrize('row', [RAMSEY, SHAHAR])
def test_every_actual_truncation_is_not_absence(row):
    for end in range(1 + len(row)):
        with pytest.raises(ValueError):
            health.read_injury_vector(b'\x01' + row, 0, limit=end)


def test_empty_and_zero_bounds_are_distinct():
    assert health.read_injury_vector(b'\0next', 0, limit=1)['records'] == []
    for start, end in [(False,1),(0,True),(-1,1),(0,0),(0,6)]:
        with pytest.raises(ValueError):health.read_injury_vector(b'\0next',start,limit=end)


def test_unknown_version_or_presence_not_empty():
    for raw in [b'\x01\x04' + RAMSEY[1:], b'\x01' + RAMSEY[:3] + b'\x02' + RAMSEY[4:],
                b'\x01' + SHAHAR[:4] + b'\x02' + SHAHAR[5:]]:
        with pytest.raises(ValueError):health.read_injury_vector(raw,0,limit=len(raw))


def test_prefix_failure_preserves_fitness(monkeypatch):
    geometry={'record_start':0,'common_start':128,'identity':{'stored_index':1}}
    monkeypatch.setattr(health.saved_player_form_query,'_starts',lambda *_:([geometry],{},False))
    monkeypatch.setattr(health.saved_player_profile_query,'_name_context',lambda *_:{})
    monkeypatch.setattr(health.saved_player_fitness,'read_fitness',lambda *_a,**_k:{'state':'decoded','fields':{'condition':123}})
    monkeypatch.setattr(health.saved_form_player,'locate_f0',lambda *_:{'start':0,'end':50,'state':'stopped','stop_reason':'unsupported positive child'})
    result=health._person(bytes(128),None,{'person_index':1,'search_complete':True,'neighbour_corroboration':{'search_complete':True}})
    assert result['state']=='partial' and result['fitness']['fields']['condition']==123
    assert result['injuries']['stored_record_count'] is None and result['injuries']['records'] is None


@pytest.mark.parametrize('values', [None,[],[True],[-1],[2**31],list(range(33))])
def test_invalid_indices_before_source(values):
    with pytest.raises(ValueError):health.get_player_health('absent.fm',values,'pin')


@pytest.mark.parametrize('value', [None,0,1,'true'])
def test_strict_installed_opt_in(value):
    with pytest.raises(ValueError):health.get_player_health('absent.fm',[0],'pin',include_installed_names=value)


def test_duplicates_default_resource_off_and_missing_context(monkeypatch):
    @contextmanager
    def context(*args,**kwargs):
        assert args[1]==[1,2]
        yield {'data':b'','layout':type('Layout',(),{'person_count':3})(), 'ranked':[{'person_index':1},{'person_index':2}], 'snapshot_id':'pin','saved_metadata':{}}
    monkeypatch.setattr(health.saved_person_search,'checked_person_context',context)
    monkeypatch.setattr(health,'_person',lambda _d,_l,t:{'person_index':t['person_index'],'injuries':{'records':[]}})
    monkeypatch.setattr(health.saved_injury_labels,'load_english_injury_labels',lambda:pytest.fail('default opened installed resource'))
    value=health.get_player_health('test.fm',[1,2,1],'pin')
    assert [p['person_index'] for p in value['people']]==[1,2,1]
    assert 'installed_injury_labels' not in value
    monkeypatch.setattr(health.saved_injury_labels,'load_english_injury_labels',lambda:{'status':'unavailable','reason':'missing','metadata':{},'labels':{}})
    assert health.get_player_health('test.fm',[1,2],'pin',include_installed_names=True)['installed_injury_labels']['status']=='unavailable'


def test_canonical_failure_keeps_injury_rows(monkeypatch):
    rows=[{'injuries':health.read_injury_vector(b'\1'+RAMSEY,0,limit=1+len(RAMSEY))}]
    monkeypatch.setattr(health.saved_player_injury_history,'_definitions',lambda *_:(_ for _ in ()).throw(ValueError('unsupported definition table')))
    assert health._definitions(b'',rows)['state']=='unavailable'
    assert rows[0]['injuries']['stored_record_count']==1
    assert rows[0]['injuries']['records'][0]['injury_reference']['identity'] is None


@pytest.mark.parametrize('status', ['unavailable','unsupported'])
def test_missing_optional_resource_preserves_positive_raw_row(monkeypatch,status):
    vector=health.read_injury_vector(b'\1'+RAMSEY,0,limit=1+len(RAMSEY))
    row=vector['records'][0]
    row['injury_reference'].update(state='same_snapshot_canonical',identity={'native_id':38,'display_name':None})
    monkeypatch.setattr(health.saved_injury_labels,'load_english_injury_labels',lambda:{'status':status,'reason':'missing or changed resource','metadata':{},'labels':{}})
    result=health._labels([{'injuries':vector}])
    assert result['status']==status and row['raw_record_hex']==RAMSEY.hex()
    assert row['injury_reference']['identity']=={'native_id':38,'display_name':None}
    assert row['installed_injury_label']['state']=='resource_'+status
    assert row['installed_injury_label']['name'] is None


def test_incomplete_alternative_search_never_promotes_one_geometry(monkeypatch):
    monkeypatch.setattr(health.saved_player_form_query,'_starts',lambda *_:([{}],{},True))
    result=health._person(b'',None,{'person_index':1,'search_complete':True,'neighbour_corroboration':{'search_complete':True}})
    assert result['state']=='incomplete_candidates'
    assert result['fitness']['fields'] is None and result['injuries']['stored_record_count'] is None


def test_response_budget_counts_duplicate_projection(monkeypatch):
    @contextmanager
    def context(*args,**kwargs):
        yield {'data':b'','layout':type('Layout',(),{'person_count':3})(), 'ranked':[{'person_index':1}], 'snapshot_id':'pin','saved_metadata':{}}
    monkeypatch.setattr(health.saved_person_search,'checked_person_context',context)
    monkeypatch.setattr(health,'_person',lambda *_:{'injuries':{'records':[]},'large':'x'*(health.MAX_RESPONSE_BYTES//2)})
    with pytest.raises(ValueError,match='output budget'):
        health.get_player_health('test.fm',[1,1],'pin')
