import json
from pathlib import Path
import struct
from contextlib import contextmanager
from dataclasses import dataclass
import pytest
from fm_live_mcp import saved_population as pop,saved_scouting_query as scout
from fm_live_mcp.person_wire import parse_record

FIX=json.loads(Path(__file__).with_name('person_wire_fixtures.json').read_bytes())

def test_typed_projection_both_player_classes_matches_source():
 for tag in (2,3):
  f=next(x for x in FIX if x['expected']['signed_tag']==tag);b=bytes.fromhex(f['raw_hex']);r=parse_record(b,0,f['original_ordinal'],limit=len(b),_include_scouting=True)
  assert r['_scouting']['raw69']==b[31:100]
  assert r['_scouting']['current']==struct.unpack_from('<h',b,7)[0]
  assert r['_scouting']['scale_byte']==b[r['_scouting']['scale_offset']]
  assert '_scouting' not in parse_record(b,0,f['original_ordinal'],limit=len(b))

def test_known_failure_wins_over_other_missing_field():
 f=next(x for x in FIX if x['expected']['signed_tag']==2);b=bytes.fromhex(f['raw_hex']);r=parse_record(b,0,f['original_ordinal'],limit=len(b),_include_scouting=True)
 r['_scouting']['raw69']=bytes([255])*69
 r['_scouting']['current']=100
 state,_,_=scout._evaluate(r,{'positions.striker':{'min':1},'ability.current':{'min':200}},None,23,None)
 assert state=='predicate_excluded'

@pytest.fixture
def source(monkeypatch):
 @dataclass
 class Layout:
  _data:object=None
  person_count:int=4
  person_offset:int=0
  person_records_offset:int=0
  provenance:str='test'
 layout=Layout();data=b'abcd'
 control={'data':data,'layout':layout}
 @contextmanager
 def checked(filename,pin,directory,locate):
  if pin!='pin':raise ValueError('Snapshot identity changed')
  data=control['data']
  yield data,locate(data),'pin',{'status':'verified','saved_simulation_date':'2030-10-19'}
 monkeypatch.setattr(pop,'checked_name_source',checked);monkeypatch.setattr(pop.saved_name_vectors,'locate',lambda data:layout);monkeypatch.setattr(pop,'_LAST_LAYOUT',None);pop._PREFIXES.clear()
 def read(data,at,index,**kwargs):
  if index==3:return {'state':'unsupported','signed_tag':9,'reason':'unsupported child'}
  return {'state':'decoded','end':index+1,'signed_tag':1 if index==0 else 2,'ordinal':index}
 monkeypatch.setattr(pop,'_read_record',read)
 monkeypatch.setattr(scout,'_evaluate',lambda row,*a:('matched',{'ability.current':100},{'state':'available','age':20}))
 monkeypatch.setattr(pop,'_project',lambda data,layout,row:{'ordinal':row['ordinal'],'name_fields':[]})
 yield control
 pop._PREFIXES.clear()

def call(**kwargs):return scout.find_players('x.fm','pin',criteria={'ability.current':{'min':10}},**kwargs)

def test_empty_page_continues_then_matches_then_stops(source):
 a=call(scan_limit=1);assert a['matches']==[] and a['next_cursor'] and a['counts']['class_excluded']==1
 b=call(cursor=a['next_cursor'],limit=1);assert [x['database_index']for x in b['matches']]==[1]
 c=call(cursor=b['next_cursor']);assert [x['database_index']for x in c['matches']]==[2]
 assert c['next_cursor'] is None and c['source_frontier']['ordinal']==3
 assert c['cumulative_counts']=={'matched':2,'predicate_excluded':0,'rating_missing':0,'age_missing':0,'class_excluded':1,'unsupported':1}
 assert c['last_scanned_ordinal']==3 and c['scanned_slot_count']==2
 assert c['decoded_slot_count']==1 and c['attempted_slot_count']==2
 assert c['cumulative_decoded_slot_count']==3 and c['cumulative_attempted_slot_count']==4

def test_cursor_changed_criteria_and_restart_reject(source,monkeypatch):
 a=call(scan_limit=1)
 with pytest.raises(ValueError,match='criteria changed'):scout.find_players('x.fm','pin',criteria={'ability.current':{'min':11}},cursor=a['next_cursor'])
 monkeypatch.setattr(scout,'_SECRET',b'new server')
 with pytest.raises(ValueError,match='stale'):call(cursor=a['next_cursor'])

@pytest.mark.parametrize('kw',[{'criteria':{}},{'criteria':{'bad':{'min':1}}},{'criteria':{'ability.current':{'min':True}}},{'criteria':{'ability.current':{'min':2,'max':1}}},{'min_age':True},{'scan_limit':True},{'limit':51},{'cursor':'bad'}])
def test_invalid(kw):
 params={'criteria':{'ability.current':{'min':1}}};params.update(kw)
 with pytest.raises(ValueError):scout.find_players('x.fm','pin',**params)

def test_birth_calendar():
 import datetime
 assert scout._birth(struct.pack('<HH',60,2000),datetime.date(2023,2,28))['age']==22
 assert scout._birth(struct.pack('<HH',366,2001),datetime.date(2030,1,1))['state']=='invalid_date_of_birth'
 assert scout._birth(struct.pack('<HH',1,2040),datetime.date(2030,1,1))['state']=='future_date_of_birth'

@pytest.mark.parametrize('field,raw', [('current',-1),('current',201),('potential',-10),('potential',-95),('potential',-99),('potential',201),('potential',None)])
def test_nonfixed_ability_is_missing_even_if_bounds_overlap(field,raw):
 row={'_scouting':{'raw69':bytes(69),'scale_byte':0,'current':100,'potential':150,'birth_raw':struct.pack('<HH',1,2000)}}
 row['_scouting'][field]=raw
 state,values,_=scout._evaluate(row,{f'ability.{field}':{'min':-32768,'max':32767}},None,None,None)
 assert state=='rating_missing' and values[f'ability.{field}'] is None

@pytest.mark.parametrize('value',[0,200])
def test_fixed_ability_endpoints_are_inclusive(value):
 row={'_scouting':{'raw69':bytes(69),'scale_byte':0,'current':value,'potential':value,'birth_raw':struct.pack('<HH',1,2000)}}
 state,values,_=scout._evaluate(row,{'ability.current':{'min':value,'max':value},'ability.potential':{'min':value,'max':value}},None,None,None)
 assert state=='matched' and set(values.values())=={value}

def test_known_position_failure_wins_over_negative_potential():
 row={'_scouting':{'raw69':bytes(69),'scale_byte':0,'current':100,'potential':-10,'birth_raw':struct.pack('<HH',1,2000)}}
 state,_,_=scout._evaluate(row,{'positions.striker':{'min':20},'ability.potential':{'min':180}},None,None,None)
 assert state=='predicate_excluded'

def test_complete_table_requires_footer(source):
 source['layout'].person_count=3
 source['data']=b'abc'+bytes(9)
 result=call()
 assert result['all_declared_slots_decoded'] and result['declared_table_audit_complete']
 assert result['state']=='complete_declared_table' and result['footer']['state']=='source_footer_read'
 assert result['footer']['start']==3 and result['footer']['end']==12
 assert result['cumulative_decoded_slot_count']==3 and result['native_loader_globals_proved'] is False

@pytest.mark.parametrize('footer',[b'',bytes(8),struct.pack('<I',2_000_001)+bytes(5),struct.pack('<I',1)+bytes(5)])
def test_malformed_footer_does_not_commit_new_progress(source,footer):
 source['layout'].person_count=3
 source['data']=b'abc'+footer
 before=dict(pop._PREFIXES);layout_before=pop._LAST_LAYOUT
 with pytest.raises(ValueError,match='footer'):call()
 assert dict(pop._PREFIXES)==before and pop._LAST_LAYOUT is layout_before

def test_malformed_footer_preserves_existing_checked_prefix(source):
 source['layout'].person_count=3
 source['data']=b'abc'+bytes(8)
 first=call(scan_limit=1)
 before={key:list(value)for key,value in pop._PREFIXES.items()};layout_before=pop._LAST_LAYOUT
 with pytest.raises(ValueError,match='footer'):call(cursor=first['next_cursor'])
 assert {key:list(value)for key,value in pop._PREFIXES.items()}==before
 assert pop._LAST_LAYOUT is layout_before


def test_empty_declared_table_still_reads_footer(source):
 source['layout'].person_count=0
 source['data']=bytes(9)
 result=call()
 assert result['footer']['state']=='source_footer_read'
 assert result['all_declared_slots_decoded'] and result['declared_table_audit_complete']
 assert result['decoded_slot_count']==0 and result['last_scanned_ordinal'] is None
 assert result['stop_reason']=='declared_table_end'

def test_match_limit_at_table_end_is_audited_completion(source):
 source['layout'].person_count=3
 source['data']=b'abc'+bytes(9)
 result=call(limit=2)
 assert result['match_count']==2 and result['declared_table_audit_complete']
 assert result['stop_reason']=='declared_table_end' and result['next_cursor'] is None
