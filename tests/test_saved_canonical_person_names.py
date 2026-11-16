"""Typed records, query/index boundaries and independent portable source controls."""
from contextlib import contextmanager
from dataclasses import dataclass, replace
from hashlib import sha256
import json
from pathlib import Path
import struct
import pytest
from fm_live_mcp import saved_canonical_person_names as query, saved_population as population
from fm_live_mcp.person_wire import parse_record


def retired(index,first=0,second=0,alias=None,native=0,secondary=99):
    selector=0 if alias is None else 1
    flags=0 if alias is None else 1<<29
    return bytes([16,selector])+(struct.pack('<I',first)if selector==0 else b'')+struct.pack('<IQIII',second if alias is None else alias,flags,index,native,secondary)


def literal(index,first=b'',second=b'Fotaq Strakosha'):
    return b'\5'+struct.pack('<I',len(first))+first+struct.pack('<I',len(second))+second+bytes(8)+struct.pack('<III',index,24,25)


@dataclass
class Layout:
    _data: object
    person_count: int
    names: dict
    person_offset=0
    person_records_offset=5
    provenance={'scope':'typed synthetic source fixture'}
    @property
    def name_counts(self):return {k:len(v) for k,v in self.names.items()}
    def lookup_raw(self,ns,index):return self.names[ns][index]


@pytest.fixture
def checked(monkeypatch):
    state={'records':[retired(0),retired(1,first=1,second=1),retired(2,alias=0)],
           'names':{'first':[b'Claudio',b'Kylian'], 'second':[b'Silva','Mbappé'.encode()], 'common':[b'Rodri']},
           'changed':False,'source_calls':0}
    def data():return struct.pack('<IB',len(state['records']),1)+b''.join(state['records'])+state.get('footer',bytes(9))
    def locate(source):return Layout(source,len(state['records']),state['names'])
    @contextmanager
    def source(filename,pin,directory,*,locate):
        if pin!='pin':raise ValueError('Snapshot identity changed')
        state['source_calls']+=1
        source=data();yield source,locate(source),'pin',{}
        if state['changed']:raise ValueError('Snapshot changed during request')
    monkeypatch.setattr(population.saved_name_vectors,'locate',locate)
    monkeypatch.setattr(population,'checked_name_source',source)
    monkeypatch.setattr(population,'_LAST_LAYOUT',None)
    population._PREFIXES.clear();query._INDEXES.clear()
    yield state
    population._PREFIXES.clear();query._INDEXES.clear()


def find(**kwargs):return query.find_people('save.fm','pin',_seconds=100,**kwargs)


def test_typed_names_unicode_aliases_and_independent_identity_words(checked):
    result=find(first_name=' cláudio ',surname='SÍLVA')
    assert [p['person_index']for p in result['matches']]==[0]
    row=result['matches'][0]
    assert row['native_identity']=={'database_index':0,'native_id':0,'secondary_id':99}
    assert row['name_fields'][0]['text']=='Claudio'
    assert row['source_record_kind']=='RETIRED_PERSON_NAME_POINTERS'
    assert row['state']=='available' and result['state']=='complete_declared_table'
    assert result['all_declared_slots_decoded'] and not result['whole_population_complete']
    assert find(surname='MBAPPE')['matches'][0]['person_index']==1
    assert find(common_name='rodri')['matches'][0]['person_index']==2
    assert find(first_name='Claudio',surname='Mbappe')['counts']['matched']==0
    assert find(surname='Sil',match_mode='prefix')['match_count']==1
    assert find(surname='lva',match_mode='substring')['match_count']==1
    assert find(surname='il',match_mode='prefix')['match_count']==0


def test_cursor_pages_preserve_original_order_without_prefix_redecoding(checked,monkeypatch):
    checked['records']=[retired(i)for i in range(4)]
    calls=[];original=population._read_record
    def read(data,at,index,**kw):calls.append(index);return original(data,at,index,**kw)
    monkeypatch.setattr(population,'_read_record',read)
    first=find(any_name='silva',limit=1)
    second=find(any_name='silva',cursor=first['next_cursor'],limit=2)
    third=find(any_name='silva',cursor=second['next_cursor'],limit=2)
    assert [p['person_index']for p in first['matches']+second['matches']+third['matches']]==[0,1,2,3]
    assert calls==[0,1,2,3]
    assert third['cumulative_counts']=={'matched':4,'predicate_excluded':0,'name_unavailable':0,'unsupported':0}
    assert third['next_cursor']is None
    calls.clear();cached=find(any_name='not present')
    assert calls==[] and cached['index']['cache_hits']==4
    assert cached['cumulative_decoded_slot_count']==4
    cached=find(any_name='silva',limit=1)
    assert calls==[0] and cached['index']['matched_records_reparsed']==1


def test_empty_partial_pages_and_known_failure_before_unknown(checked):
    checked['records']=[literal(0),retired(1),retired(2,first=999)]
    first=find(first_name='Claudio',surname='Silva',scan_limit=1)
    assert first['matches']==[] and first['next_cursor'] and first['counts']['name_unavailable']==1
    second=find(first_name='Claudio',surname='Silva',cursor=first['next_cursor'],scan_limit=1)
    assert second['matches'][0]['person_index']==1
    third=find(first_name='Claudio',surname='Silva',cursor=second['next_cursor'])
    # Retained-pointer native bounds are a proved null guard, not out_of_range.
    assert third['cumulative_counts']['predicate_excluded']==1
    fields=(('first','out_of_range',None,'indexed_name'),('second','decoded','wrong','indexed_name'))
    assert query._evaluate(fields,{'first':'claudio','second':'silva'},'exact')=='predicate_excluded'


def test_literal_names_and_unclassified_namespaces_are_not_guessed(checked):
    checked['records']=[literal(0)]
    out=find(any_name='Fotaq Strakosha')
    assert out['matches'][0]['search_name_fields'][0]['text']==''
    assert out['matches'][0]['search_name_fields'][1]['text']=='Fotaq Strakosha'
    assert find(surname='Strakosha')['counts']['name_unavailable']==1
    assert find(first_name='Fotaq')['counts']['name_unavailable']==1
    assert find(any_name='Fotaq',match_mode='prefix')['match_count']==1
    assert find(any_name='Fotaq  Strakosha')['match_count']==0


def test_unmapped_bytes_and_unprojected_virtual_are_explicit(checked):
    fixtures=json.loads(Path(__file__).with_name('person_wire_fixtures.json').read_text())
    raw=bytearray.fromhex(next(f['raw_hex']for f in fixtures if f['expected']['signed_tag']==7))
    struct.pack_into('<I',raw,len(raw)-12,1)
    checked['records']=[literal(0,second=b'\xff'),bytes(raw)]
    out=find(any_name='anything')
    assert out['counts']['name_unavailable']==2
    assert out['field_counts']['unsupported_encoding']==1 and out['field_counts']['unprojected_name']==1
    assert out['all_declared_slots_decoded'] and not out['all_projected_name_fields_decodable']
    assert out['kind_counts']=={'5':1,'7':1}


def test_source_final_failure_does_not_publish_index_or_prefix(checked):
    checked['changed']=True
    with pytest.raises(ValueError,match='changed'):find(surname='Silva')
    assert not query._INDEXES and not population._PREFIXES
    checked['changed']=False
    first=find(surname='Silva',scan_limit=1)
    before=next(iter(query._INDEXES.values()));assert len(before.entries)==1
    checked['changed']=True
    with pytest.raises(ValueError):find(surname='Silva',cursor=first['next_cursor'])
    assert len(before.entries)==1 and len(next(iter(population._PREFIXES.values())))==1


def test_shared_prefix_eviction_rebuilds_contiguous_ends_without_body_reparse(checked,monkeypatch):
    find(any_name='not present')
    population._PREFIXES.clear()
    original=population._read_record;calls=[]
    def read(*args,**kw):calls.append(args[2]);return original(*args,**kw)
    monkeypatch.setattr(population,'_read_record',read)
    out=find(any_name='not present')
    assert out['index']['cache_hits']==3 and not calls
    assert len(next(iter(population._PREFIXES.values())))==3


def test_cursor_tamper_query_drift_source_change_and_eviction_reject(checked):
    page=find(any_name='Silva',scan_limit=1)
    for cursor in ('garbage',page['next_cursor'][:-2]+'xx'):
        with pytest.raises(ValueError):find(any_name='Silva',cursor=cursor)
    with pytest.raises(ValueError,match='selectors'):find(any_name='Rodri',cursor=page['next_cursor'])
    checked['records'][0]=retired(0,native=88)
    with pytest.raises(ValueError,match='source'):find(any_name='Silva',cursor=page['next_cursor'])
    checked['records'][0]=retired(0)
    query._INDEXES.clear()
    with pytest.raises(ValueError,match='expired'):find(any_name='Silva',cursor=page['next_cursor'])


def test_cached_geometry_identity_and_matching_text_rechecked(checked):
    find(any_name='not present')
    cache=next(iter(query._INDEXES.values()));old=cache.entries[0]
    cache.entries[0]=replace(old,native=900)
    with pytest.raises(ValueError,match='identity'):find(any_name='Silva')
    cache.entries[0]=replace(old,fields=(('second','decoded','invented','retained_pointer'),))
    with pytest.raises(ValueError,match='fields'):find(any_name='invented')


def test_unsupported_frontier_and_bad_footer_cannot_become_empty(checked):
    checked['records']=[retired(0),b'\x7f']
    out=find(any_name='not present')
    assert out['state']=='stopped' and out['source_frontier']['ordinal']==1
    assert out['next_cursor']is None and out['counts']['unsupported']==1
    assert out['attempted_slot_count']==2 and out['decoded_slot_count']==1
    checked['records']=[retired(0)];checked['footer']=b'\0'*8
    with pytest.raises(ValueError,match='footer'):find(any_name='anything')


@pytest.mark.parametrize('kwargs',[{}, {'first_name':True},{'any_name':' '},{'surname':'x','match_mode':'bad'},
 {'surname':'x','limit':True},{'surname':'x','limit':51},{'surname':'x','scan_limit':0},{'surname':'x','scan_limit':True}])
def test_invalid_queries_reject_before_source(checked,kwargs):
    with pytest.raises(ValueError):find(**kwargs)
    assert checked['source_calls']==0


def test_memory_response_and_population_lock_budgets_reject_without_publication(checked,monkeypatch):
    monkeypatch.setattr(query,'_MAX_INDEX_BYTES',1)
    with pytest.raises(ValueError,match='memory budget'):find(surname='Silva')
    assert not query._INDEXES and not population._PREFIXES
    monkeypatch.setattr(query,'_MAX_INDEX_BYTES',128*1024**2)
    monkeypatch.setattr(query,'_MAX_RESPONSE_BYTES',1)
    with pytest.raises(ValueError,match='response'):find(surname='Silva')
    assert not query._INDEXES and not population._PREFIXES
    assert population._LOCK.acquire(blocking=False)
    try:
        with pytest.raises(ValueError,match='progress'):find(surname='Silva')
    finally:population._LOCK.release()


def test_independent_original_Claudio_and_literal_byte_controls():
    controls=json.loads((Path(__file__).parent/'fixtures'/'canonical_person_name_controls.json').read_text())
    first,literal_control,_=controls
    expected=first['source_metadata'];raw=bytes.fromhex(first['raw_hex'])
    assert sha256(raw).hexdigest()==expected['record_sha256']
    row=parse_record(raw,0,expected['person_index'],limit=len(raw))
    class OriginalLayout:
        name_counts={'first':200421,'second':406241,'common':1}
        def lookup_raw(self,ns,index):return {('first',200420):b'Claudio',('second',406240):b'Silva'}[ns,index]
    projected=population._project(raw,OriginalLayout(),row)
    fields=query._fields(projected)
    assert query._evaluate(fields,{'first':'claudio','second':'silva'},'exact')=='matched'
    assert query._evaluate(fields,{'first':'claudio','second':'wrong'},'exact')=='predicate_excluded'
    assert row['identity']['native_id_word']==row['identity']['secondary_word']==2002084196
    raw=bytes.fromhex(literal_control['raw_hex']);expected=literal_control['source_metadata']
    assert sha256(raw).hexdigest()==expected['raw_record_sha256']
    row=parse_record(raw,0,71529,limit=len(raw));projected=population._project(raw,OriginalLayout(),row)
    fields=query._fields(projected)
    assert query._evaluate(fields,{'any':'fotaq strakosha'},'exact')=='matched'
    assert query._evaluate(fields,{'second':'strakosha'},'substring')=='name_unavailable'


def test_inline_payload_is_not_silently_an_effective_indexed_name():
    projected={'signed_tag':1,'name_fields':[{'namespace':'first','state':'stored_inline_reference',
        'stored_index':10,'inline_record':{'name':{'text':'Inline','valid_utf8':True}}}]}
    fields=query._fields(projected)
    assert query._evaluate(fields,{'first':'inline'},'exact')=='name_unavailable'
    assert query._evaluate(fields,{'any':'inline'},'exact')=='name_unavailable'
    assert fields[0][1]=='inline_effective_unresolved'


def test_independent_original_retained_pointer_name_control():
    control=json.loads((Path(__file__).parent/'fixtures'/'canonical_person_name_controls.json').read_text())[2]
    expected=control['source_metadata'];raw=bytes.fromhex(control['raw_hex'])
    assert sha256(raw).hexdigest()==expected['raw_record_sha256']
    row=parse_record(raw,0,1,limit=len(raw))
    class OriginalLayout:
        name_counts={'first':23067,'second':27102,'common':0}
        def lookup_raw(self,ns,index):return {('first',23066):b'Axel',('second',27101):b'Smeets'}[ns,index]
    projected=population._project(raw,OriginalLayout(),row)
    assert row['identity']['native_id_word']==row['identity']['secondary_word']==14
    assert [f['text']for f in projected['name_fields']]==['Axel','Smeets']
    assert all(f['source']=='retained_pointer'for f in query._details(projected))
    assert query._evaluate(query._fields(projected),{'first':'axel','second':'smeets'},'exact')=='matched'


def test_elapsed_budget_always_advances_one_slot_and_page_limits_are_independent(checked):
    first=query.find_people('save.fm','pin',any_name='not present',_seconds=0)
    assert first['next_original_ordinal']==1 and first['stop_reason']=='elapsed_work_budget'
    second=find(any_name='not present',cursor=first['next_cursor'],limit=1)
    assert second['state']=='complete_declared_table' and second['cumulative_decoded_slot_count']==3


def test_source_bound_name_index_eviction_is_an_explicit_cursor_expiry(checked,monkeypatch):
    monkeypatch.setattr(query,'_MAX_CACHES',1)
    first=find(any_name='Silva',scan_limit=1)
    checked['records'][0]=retired(0,native=77)
    find(any_name='not present')
    checked['records'][0]=retired(0)
    with pytest.raises(ValueError,match='expired'):find(any_name='Silva',cursor=first['next_cursor'])
