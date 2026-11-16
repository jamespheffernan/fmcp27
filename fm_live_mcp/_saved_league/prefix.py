"""Bounded ACTUAL_COMP fixed prefix only; 0x209 is the proved writer profile.
No calendar range, active/completed state, stage/fixture or final-table claim.
"""
from .errors import UnsupportedLayout
import struct
WIDTHS=[('82b',1),('4ba',1),('4bb',1),('4c',4),('4bd',1),('d4',1),('d5',1),('d6',1),('d7',1),('3b0',2),('3b2',2),('3a0',4),('3a8',4),('4c8',1),('rule_group_1f8_64',2),('3bf',1),('3a4',4),('3b4',2),('3bc',1),('3bd',1),('3be',1),('4bf',1),('4c0',1),('4c2',2)]
def parse(data):
 if not isinstance(data,bytes):raise ValueError('Expected bytes')
 if len(data)<8:raise ValueError('Truncated stream header')
 if data[:6]!=bytes.fromhex('03017461642e'):raise UnsupportedLayout('Unsupported stream marker/endian/type')
 version=int.from_bytes(data[6:8],'little')
 if version!=0x209:raise UnsupportedLayout('Unsupported ACTUAL_COMP writer version')
 cursor=8;raw={};offsets={}
 for field,width in WIDTHS:
  if cursor+width>len(data):raise ValueError('Truncated ACTUAL_COMP fixed field '+field)
  offsets[field]=cursor;raw[field]=data[cursor:cursor+width].hex();cursor+=width
 if cursor+4>len(data):raise ValueError('Truncated property count')
 count=int.from_bytes(data[cursor:cursor+4],'little')
 if count>4096:raise ValueError('Property count exceeds work budget')
 return dict(stream_version=version,native_season_code=int.from_bytes(bytes.fromhex(raw['3b0']),'little'),unmapped_fixed_fields=raw,offsets=offsets,property_map_start=cursor,property_count=count,end=cursor+4,complete=False,next_native_reader='0x43FD1E0',scope='Fixed prefix; native_season_code is a stored discriminator, not a decoded season date range')

# Same supported scalar extent set as shipped saved_properties. Values remain raw.
SCALARS={1:4,2:4,3:1,5:8,15:8,17:1,18:2,19:1,20:2,21:4,24:8,25:4,27:8,32:4}
def properties(data,start):
 cursor=start;nodes=0
 def take(n):
  nonlocal cursor
  if n<0 or cursor+n>len(data) or cursor+n-start>4*1024*1024:raise ValueError('Truncated or over-budget properties')
  value=data[cursor:cursor+n];cursor+=n;return value
 def count():
  v=int.from_bytes(take(4),'little')
  if v>4096:raise ValueError('Property count exceeds budget')
  return v
 def mapping(depth):
  n=count();out=[]
  for _ in range(n):
   key=take(4);out.append(dict(key_hex=key.hex(),key_fourcc=key[::-1].decode('ascii',errors='replace'),value=variant(depth)))
  return out
 def variant(depth):
  nonlocal nodes
  nodes+=1
  if depth>16 or nodes>4096:raise ValueError('Property nesting/node budget')
  at=cursor;version,kind=take(2);out=dict(start=at,version=version,kind=kind)
  if kind in SCALARS:out['raw_hex']=take(SCALARS[kind]).hex()
  elif kind in (0,6,7):out['raw_hex']=''
  elif kind==10:out['map']=mapping(depth+1)
  elif kind==11:out['vector']=[variant(depth+1) for _ in range(count())]
  elif kind==26:
   n=count()
   if n>8192:raise ValueError('Text exceeds budget')
   out['text']=take(n).decode('utf-8')
  else:raise UnsupportedLayout(f'Unsupported property variant{kind} at{at}')
  out['end']=cursor;return out
 out=mapping(0)
 return dict(end=cursor,rows=out,nodes=nodes)

def decode_prefix(data):
 result=parse(data);prop=properties(data,result['property_map_start']);result['properties']=prop
 at=prop['end']
 if at>=len(data):raise ValueError('Missing optional398 marker')
 result['optional_398_marker']=data[at];result['end']=at+1
 result['next_native_reader']='0x3B7FD28' if data[at] else 'fixed +3B8/+3B6 then later optional +3F0'
 return result
