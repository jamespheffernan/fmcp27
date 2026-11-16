"""Bounded GAME_COMP_STATS suffix research; raw counters/words have no labels."""
from .errors import UnsupportedLayout
import struct
CTX={'stream_bit1':True,'global_3522':0,'global_3523':1,'global_2c98':1}
class UnsupportedSuffix(ValueError):
 def __init__(self,native,offset,reason,partial=None):
  self.native,self.offset,self.reason,self.partial=native,offset,reason,partial
  super().__init__(f'Unsupported GAME_COMP_STATS suffix child {hex(native)} at {offset}: {reason}')
def parse_prefix(data,start,*,limit=None,version=173,reference_context,child_readers=None):
 if reference_context!=CTX or any(type(reference_context.get(k))is not type(v)for k,v in CTX.items()):raise ValueError('Explicit conditional reference context required')
 limit=len(data)if limit is None else limit
 if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid suffix bounds')
 if version!=173:raise UnsupportedLayout('Only current COMP_STATS version173 supported')
 at=start;parts=[]
 child_readers={} if child_readers is None else child_readers
 def take(n):
  nonlocal at
  if n<0 or n>limit-at:raise ValueError('Truncated GAME_COMP_STATS suffix')
  pos=at;at+=n;return bytes(data[pos:at])
 def u32():return int.from_bytes(take(4),'little')
 def group(name,cap):
  begin=at;n=u32()
  if n>cap:raise ValueError('Native fixed-capacity table exceeds bound')
  rows=[]
  for i in range(n):
   pos=at;raw=take(13);rows.append(dict(row_index=i,start=pos,end=at,ignored_marker=raw[0],raw12_hex=raw[1:].hex()))
  parts.append(dict(native_field=name,start=begin,end=at,count=n,rows=rows))
 marker=take(1)[0]
 for name,cap in [('810+0',10),('810+78',10),('810+f0',10),('810+168',10),('810+1e0',11),('810+264',15),('810+318',15),('810+3cc',15),('810+480',13),('810+51c',15),('810+5d0',15),('810+684',15),('810+738',13),('810+87c',13),('810+7d4',14)]:group(name,cap)
 end_171aa60=at
 marker_1128=take(1)[0];group('1128',24);end_171b550=at
 result=dict(start=start,end=at,state='stopped',next_native_reader='0xf2f2d4',stop_reason='',parts=parts,marker_810=marker,marker_1128=marker_1128,end_171aa60=end_171aa60,end_171b550=end_171b550,version=version,reference_context=reference_context,complete=False)
 def stop(native,reason):
  result.update(end=at,state='stopped',next_native_reader=hex(native),stop_reason=reason);return result
 def child(native,**kwargs):
  nonlocal at
  cb=child_readers.get(native)
  if cb is None:return False
  begin=at;value=cb(data,at,limit=limit,reference_context=reference_context,**kwargs)
  if not isinstance(value,dict) or type(value.get('end'))is not int or not at<value['end']<=limit:raise ValueError('Invalid suffix child cursor')
  if value.get('state')=='stopped' or value.get('complete')is False:
   raise UnsupportedSuffix(int(value.get('next_native_reader',hex(native)),16),value['end'],'Nested callback is partial',value)
  at=value['end'];parts.append(dict(native_child=hex(native),start=begin,end=at,value=value));return True
 def vector_count(name):
  pos=at;n=u32()
  if n>4096:raise ValueError('Vector exceeds offline work budget')
  result['count_'+name]=n;result['count_'+name+'_offset']=pos;return n
 n=vector_count('1278')
 for i in range(n):
  result['row_1278_ordinal']=i
  if not child(0xf2f2d4,version=version):return stop(0xf2f2d4,'Positive +1278 row')
 n=vector_count('12a8');begin=at;raw=take(n*14);parts.append(dict(native_field='12a8',start=begin,end=at,count=n,raw14_rows_hex=raw.hex()))
 n=vector_count('1290');begin=at;raw=take(n*8);parts.append(dict(native_field='1290',start=begin,end=at,count=n,raw_pairs_hex=raw.hex()))
 stats_version=int.from_bytes(take(2),'little');result['stats_version']=stats_version
 for native_offset in ('1248','1250'):
  result['next_stats_native_offset']=native_offset
  if not child(0xf90a50,version=stats_version):return stop(0xf90a50,'Stats object +'+native_offset)
 begin=at;raw=take(4);parts.append(dict(native_field='125c',start=begin,end=at,raw_hex=raw.hex()))
 n=vector_count('1260')
 if n:return stop(0x11019a0,'Positive +1260 TEAM-bearing inline row')
 begin=at;raw=take(11);parts.append(dict(native_fields='1308/1258/1317/130a/130c',start=begin,end=at,raw_hex=raw.hex()))
 n=vector_count('12c0');begin=at;raw=take(n*17);parts.append(dict(native_field='12c0',start=begin,end=at,count=n,raw17_rows_hex=raw.hex()))
 n=vector_count('12d8')
 for i in range(n):
  begin=at;person=take(4)
  if at>=limit:raise ValueError('Truncated TEAM marker')
  if data[at]!=0:return stop(0x11019a0,'Positive +12D8 TEAM outside checked marker0 subset')
  team=take(5);raw=take(27);parts.append(dict(native_field='12d8',ordinal=i,start=begin,end=at,person_reference_hex=person.hex(),team_reference_hex=team.hex(),raw27_hex=raw.hex()))
 n=vector_count('12f0')
 for i in range(n):
  result['row_12f0_ordinal']=i
  if not child(0xf2f2d4,version=version):return stop(0xf2f2d4,'Positive +12F0 row')
 result.update(end=at,state='complete',next_native_reader=None,stop_reason=None,complete=True)
 return result

def parse(data,start,**kwargs):
 out=parse_prefix(data,start,**kwargs)
 if out['complete']:return out
 raise UnsupportedSuffix(int(out['next_native_reader'],16),out['end'],out['stop_reason'],out)
