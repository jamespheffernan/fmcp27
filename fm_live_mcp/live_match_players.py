"""Bounded complete-side current-session player projection; B80/B89 semantics."""
import hashlib
from . import saved_match_statistics_wire as wire
from . import live_match_participation
from .match_player_position import read_position
import struct

def _signed(value,bits):
 value&=(1<<bits)-1
 return value-(1<<bits)if value&(1<<(bits-1))else value

def _trunc_div(value,denominator):
 return value//denominator if value>=0 else -((-value)//denominator)

def _usage(child,end_clock):
 if not isinstance(child,bytes)or len(child)<1:raise ValueError('Complete proved child required')
 if type(end_clock)is not int or not 0<=end_clock<65536:raise ValueError('Invalid clock')
 mode=child[0];rw=4 if mode>=2 else 8;delta=rw-4
 if len(child)<140+delta:raise ValueError('Truncated native usage fields')
 def byte(at):return child[at+delta]
 person=int.from_bytes(child[1:1+rw],'little');flags=byte(76)
 source={'source_person_word':person,'flags5c':flags,'on_minute':byte(71),'off_minute':byte(67),'injury_minute':byte(72),'sent_off_minute':byte(74),'native_rating_hundredths':struct.unpack_from('<h',child,136+delta)[0],'native8c':byte(21),'end_clock':end_clock}
 #153F5AC..5FC: setting x21null prevents allocation of form statistics.
 suppressed=bool(flags&32)and source['on_minute']==0
 on,off,inj,sent=(source[k]for k in('on_minute','off_minute','injury_minute','sent_off_minute'))
 terminal=off or inj or sent or end_clock
 null_person=person in(0xffffffff,0xffffffffffffffff)
 raw=0 if null_person else terminal-on if flags&32 else terminal
 if flags&32 and not(off or inj or sent or on):raw=0
 duration=max(_signed(raw,8),0)
 if suppressed:return {'form_statistics_state':'suppressed_by_native_predicate','native_form_status':12,'native_duration_minutes':duration,'minutes':None,'form_rating_tenths':None,'match_rating':None,'source':source,'appearance_state':'unused_substitute'}
 rating=0;rating_gate='duration_below2'
 if duration>=2:
  hundredths=source['native_rating_hundredths']+5
  threshold=_trunc_div(_signed(end_clock,16),6)
  qualifies=(duration>=threshold or hundredths>=700 or byte(20)!=0 or byte(56)!=0 or byte(21)!=0)
  if qualifies:
   rating=max(_trunc_div(hundredths,10),1)&255;rating_gate='qualified'
  else:rating_gate='insufficient_duration_and_no_threshold_exception'
 return {'form_statistics_state':'projected','native_form_status':0,'native_duration_minutes':duration,'minutes':duration,'form_rating_tenths':rating,'match_rating':rating/10,'rating_gate':rating_gate,'source':source,'appearance_state':None}

WIDTHS=(2,5,5,8,4,4,4,4,12,2,1,15,5,4,6,3,3,3,2,2,1,1,8,5,8,5,8,1,4,4,16,4,12,9,6,4,4,2,2,2,2,2,2,4,1)
def project_frame(raw,key):
 if not isinstance(raw,bytes) or not 1<=len(raw)<=1048576:raise ValueError('frame budget')
 prefix=wire.fixture_prefix(raw);fixture=wire.continue_fixture(raw,prefix['end'],wire.parse_person,wire.fixture_extra)
 if fixture['fields']['scalar_u32'][0]!=key:raise ValueError('fixture key mismatch')
 stats=wire.stats_prefix(raw,fixture['end']);at=stats['end'];teams=[x['index_word'] for x in prefix['fixture_fields8_10_team_references']];rows=[];counts=[]
 for side_index,team in enumerate(teams):
  side=wire.side(raw,at,version=60,parse_child=wire.player,parse_collection=wire.collection);at=side['end']
  if side['fields']['0x5c_raw_reference']!=team:raise ValueError('team binding mismatch')
  counts.append(side['child_count'])
  for slot,c in enumerate(side['children']):
   child=raw[c['start']:c['end']];rw=4 if c['reference']['tag']>=2 else 8;delta=rw-4;person=int.from_bytes(bytes.fromhex(c['reference']['raw']),'little')
   pos=1+rw;segments=[]
   for ordinal,width in enumerate(WIDTHS):
    segments.append({'field_id':f'wire_segment_{ordinal:02d}','row_offset':pos,'width':width,'raw_hex':child[pos:pos+width].hex(),'unsigned_little_endian':int.from_bytes(child[pos:pos+width],'little')});pos+=width
   projected=_usage(child,stats['fields']['ac'])
   projected.update(read_position(child,rw))
   rows.append({'fixture_key':key,'side_index':side_index,'team_index_word':team,'stored_player_slot':slot,'person_index_word':person,'person_reference_tag':c['reference']['tag'],'canonical_person_id':None,'person_name':None,'start':c['start'],'end':c['end'],'row_sha256':hashlib.sha256(child).hexdigest(),'goals':child[20+delta],'assists':child[56+delta],**projected,'raw_segments':segments,'raw_variable_suffix_hex':child[pos:].hex(),'raw_child_hex':child.hex(),'group_count':c['group_count'],'nested_count':c['nested_count'],'unknown_semantics':['shots','passes','crosses','tackles','interceptions','saves','distance'],'completion_state':'unresolved'})
 if len(rows)>512:raise ValueError('player budget')
 return {'fixture_key':key,'raw_frame_sha256':hashlib.sha256(raw).hexdigest(),'end_clock':stats['fields']['ac'],'rows':rows,'coverage':{'stored_rows_per_side':counts,'complete_side_sections':True,'parsed_until':at,'frame_bytes':len(raw),'unparsed_tail_bytes':len(raw)-at,'whole_payload_wire_parsed':False,'identity_scope':'file-local PERSON/TEAM index words; join canonical identity separately','historical_runtime_factory_overrides_proved':False}}

def decode_retained_players(raw, key):
    return live_match_participation.enrich(project_frame(raw,key)["rows"])
