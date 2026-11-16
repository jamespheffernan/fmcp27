"""Bounded current521 league settings; unsupported positives stop explicitly."""
from .errors import UnsupportedLayout
import struct
from .. import saved_properties
from . import settings_tag2, settings210
CTX={'stream_bit1':True,'global_3522':0,'global_3523':1,'global_2c98':1}
FIRST=[(132, 2), (134, 1), (135, 1), (136, 1), (137, 1), (120, 8), (324, 1), (326, 1), (327, 1), (202, 1), (212, 1), (158, 2), (206, 2), (208, 1), (204, 2), (193, 1), (195, 1), (192, 1), (194, 1), (211, 1), (143, 1), (138, 1), (210, 1), (128, 4), (209, 1), (479, 1), (142, 1), (140, 1), (373, 1), (374, 1), (328, 4), (332, 4), (336, 4), (340, 4), (344, 4), (388, 1), (348, 4), (352, 4), (360, 4), (368, 4), (356, 4), (139, 1), (141, 1), (201, 1)]
SECOND=[(144, 1), (145, 1), (146, 1), (147, 1), (148, 1), (149, 1), (150, 1), (151, 1), (152, 1), (153, 1), (154, 1), (155, 1), (156, 1), (157, 1), (375, 1), (320, 4), (325, 1), (364, 4), (372, 1), (376, 1), (377, 1), (378, 1), (379, 1), (380, 1), (381, 1), (382, 1), (383, 1), (384, 1), (385, 1), (386, 1), (387, 1)]
class UnsupportedSettings(ValueError):
 def __init__(self,partial):
  self.partial=partial;self.offset=partial['end'];self.native=partial['next_native_reader']
  super().__init__(f"Unparsed LEAGUE_SETTINGS {self.native} at {self.offset}")
class R:
 def __init__(self,data,start,limit):
  self.data=data;self.offset=start;self.limit=limit
  if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid LEAGUE_SETTINGS bounds')
 def take(self,n):
  if type(n)is not int or n<0 or n>self.limit-self.offset:raise ValueError('Truncated LEAGUE_SETTINGS')
  at=self.offset;self.offset+=n;return bytes(self.data[at:self.offset])
 def skip(self,n):self.take(n)
 def u8(self):return self.take(1)[0]
 def u32(self):return int.from_bytes(self.take(4),'little')
 def i16(self):return int.from_bytes(self.take(2),'little',signed=True)
 def i32(self):return int.from_bytes(self.take(4),'little',signed=True)
def _rule(r,max_items):
 start=r.offset;first=r.take(4);count=r.u8()
 if count>=128:raise ValueError('Signed rule allocation count unsupported')
 fixed=r.take(3+4+2)
 if count>max_items:raise ValueError('Rule child implementation budget')
 children=r.take(count*10)
 present=r.u8()
 if present not in(0,1):raise UnsupportedLayout('Unsupported writer rule text marker')
 text=None
 if present:
  n=r.u32()
  if n>8192:raise ValueError('Rule text implementation budget')
  text=r.take(n).hex()
 tail=r.take(4+1+1) #version>=520:date4,+21,+24
 return dict(start=start,end=r.offset,raw10_count=count,text_presence=present,text_raw_hex=text,raw_fixed_hex=(first+fixed).hex(),child_hex=children.hex(),tail_hex=tail.hex(),native_reader='0x3E020C4')
def _d8(r,max_items):
 start=r.offset;fixed=r.take(21);count=r.i32()
 if count<0:raise ValueError('Negative +D8 allocation count unsupported')
 if count>max_items:raise ValueError('+D8 map implementation budget')
 rows=r.take(count*5);tail=r.take(2)
 return dict(start=start,end=r.offset,native_reader='0x3F52294',raw_fixed_hex=fixed.hex(),count=count,raw_rows_hex=rows.hex(),tail_hex=tail.hex())
def _tag2_reader(data,start,**context):
 return settings_tag2.parse(data,start,**context)
def _child210(data,start,**context):
 return settings210.parse(data,start,**context)
def _compact(r):
 value=r.i16()
 if value==-2:
  value=r.i32()
  if value<0:raise UnsupportedLayout('Unsupported escaped negative compact index')
 elif value<-2:raise UnsupportedLayout('Unsupported compact index')
 return value
def parse_prefix(data,start,*,limit=None,file_version=521,reference_context=CTX,max_items=4096,tag2_reader=None):
 if file_version!=521 or type(file_version)is not int:raise UnsupportedLayout('Unsupported settings file version')
 if reference_context!=CTX:raise ValueError('Explicit conditional settings reference profile required')
 if type(max_items)is not int or not 0<=max_items<=4096:raise ValueError('Invalid settings work budget')
 r=R(data,start,len(data)if limit is None else limit);parts=[]
 def scalar(field,n):
  at=r.offset;raw=r.take(n);parts.append(dict(native_field=hex(field),start=at,end=r.offset,raw_hex=raw.hex()));return raw
 def vector(field,stride,native):
  at=r.offset;n=r.u32()
  if n>max_items:raise ValueError('Settings vector implementation budget')
  raw=r.take(n*stride);parts.append(dict(native_field=hex(field),native_reader=native,start=at,end=r.offset,count=n,stride=stride,raw_hex=raw.hex()));return n
 def stop(native,reason):return dict(state='stopped',start=start,end=r.offset,complete=False,complete_settings=False,next_native_reader=native,stop_reason=reason,parts=parts,conditional_reference_context=reference_context,pending_bytes=0)
 at=r.offset;short=r.i16();index=r.i32()if short==-2 else short
 if short<-2 or short==-2 and index<0:raise ValueError('Invalid compact settings stage-name index')
 parts.append(dict(native_field='0x70',start=at,end=r.offset,short_word=short,index_word=index,reference_namespace='contextroot+90 STAGE_NAME',native_reader='0x111A144'))
 for field,n in FIRST:scalar(field,n)
 at=r.offset;saved_properties.skip_property_map(r);parts.append(dict(native_field='0x248',start=at,end=r.offset,native_reader='0x43FD1E0'))
 for field in(0x138,0x13c,0x2e8):scalar(field,4)
 scalar(0x1d0,15) #3CE5FC4 exactly15 scalarbytes, reorders native0..14 only.
 for field,n in SECOND:scalar(field,n)
 vector(0x58,1,'0x3F1DF94');vector(0x1e0,4,'0x11C3C40')
 for field in(0x188,0x1a0):
  at=r.offset;n=r.u32()
  if n>max_items:raise ValueError('Settings rule collection implementation budget')
  rows=[_rule(r,max_items)for _ in range(n)]
  parts.append(dict(native_field=hex(field),start=at,end=r.offset,count=n,rows=rows,native_reader='0x3E020C4'))
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +1F8 implementation budget')
 parts.append(dict(native_field='0x1f8',start=at,end=r.offset,count=n,native_reader='0x3E25728'))
 if n:return stop('0x3E25728','Positive +1F8 row child not yet consumed')
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +D8 implementation budget')
 rows=[_d8(r,max_items)for _ in range(n)]
 parts.append(dict(native_field='0xd8',start=at,end=r.offset,count=n,rows=rows,native_reader='0x3F52294'))
 at=r.offset;saved_properties.skip_property_vector(r);parts.append(dict(native_field='0xf0',start=at,end=r.offset,native_reader='0x43FD35C'))
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +108 implementation budget')
 parts.append(dict(native_field='0x108',start=at,end=r.offset,count=n,native_reader='0x3E13BB0'))
 if n:return stop('0x3E13BB0','Positive +108 row not yet consumed')
 at=r.offset;presence=r.u8();parts.append(dict(native_field='round_arrays_presence',start=at,end=r.offset,presence=presence))
 if presence not in(0,1):raise UnsupportedLayout('Unsupported writer round-array marker')
 if presence:
  rounds=next(int.from_bytes(bytes.fromhex(x['raw_hex']),'little')for x in parts if x.get('native_field')=='0x87')
  scalar(0x1b8,rounds*3)
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +2B0 implementation budget')
 parts.append(dict(native_field='0x2b0',start=at,end=r.offset,count=n,native_reader='0x3FC49AC factory →vslot18'))
 if tag2_reader is None:tag2_reader=_tag2_reader
 for i in range(n):
  tag_at=r.offset;tag=r.u8()
  if tag!=2 or tag2_reader is None:
   r.offset=tag_at
   return stop('0x3FC49AC','Positive +2B0 typed child needs explicit tag2 reader')
  child=tag2_reader(data,r.offset,limit=r.limit,reference_context=reference_context)
  end=child.get('end')
  if type(end)is not int or not r.offset<=end<=r.limit:raise ValueError('Invalid tag2 child endpoint')
  if child.get('state')=='stopped' or child.get('complete_child_wire')is not True:raise ValueError('Partial tag2 endpoint rejected')
  r.offset=end;parts.append(dict(native_field='0x2b0_child',index=i,tag=tag,start=tag_at,end=end,child=child))
 at=r.offset;presence=r.u8();parts.append(dict(native_field='0x2a8_presence',start=at,end=r.offset,presence=presence))
 if presence not in(0,1):raise UnsupportedLayout('Unsupported writer +2A8 marker')
 if presence:
  child_start=r.offset;fixed=r.take(22);n=r.u32()
  if n>max_items:raise ValueError('Settings +2A8 vector budget')
  values=r.take(n);parts.append(dict(native_field='0x2a8',start=child_start,end=r.offset,count=n,raw_fixed_hex=fixed.hex(),values_hex=values.hex(),native_reader='0x3F139D0',native_writer='0x3F1364C'))
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +2C8 implementation budget')
 raw=r.take(n*14);tail=r.take(1)
 parts.append(dict(native_field='0x2c8',start=at,end=r.offset,count=n,raw_hex=raw.hex(),tail_hex=tail.hex(),native_reader='0x3B7AD54/0x3B7AAB4'))
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Settings +210 implementation budget')
 parts.append(dict(native_field='0x210',start=at,end=r.offset,count=n,native_reader='0x3E02F64'))
 for i in range(n):
  child=_child210(data,r.offset,limit=r.limit,reference_context=reference_context,version=file_version)
  end=child.get('end')
  if type(end)is not int or not r.offset<=end<=r.limit or child.get('complete_child_wire')is not True:raise ValueError('Invalid +210 child endpoint')
  r.offset=end;parts.append(dict(native_field='0x210_child',index=i,end=end,child=child))
 for field in(0xd5,0xc8,0xcb):scalar(field,1)
 at=r.offset;presence=r.u8();parts.append(dict(native_field='0x228_presence',start=at,end=r.offset,presence=presence))
 if presence not in(0,1):raise UnsupportedLayout('Unsupported writer +228 marker')
 if presence:return stop('0x3E22E90','Positive +228 child not yet consumed')
 base_start=r.offset;first_comp=_compact(r);stage_name=_compact(r);raw38=r.take(4);raw3c=r.take(1);second_comp=_compact(r);raw3def=r.take(3)
 at=r.offset;n=r.u32()
 if n>max_items:raise ValueError('Shared settings base +8 item budget')
 parts.append(dict(native_field='settings_base',start=base_start,end=r.offset,first_comp_index=first_comp,stage_name_index=stage_name,second_comp_index=second_comp,raw_38_hex=raw38.hex(),raw_3c_hex=raw3c.hex(),raw_3def_hex=raw3def.hex(),child_count=n,native_reader='0x3FB91B0/0x3FB9308'))
 if n:return stop('0x3F6E658','Positive shared settings-base +8 row unparsed')
 return dict(state='complete',start=start,end=r.offset,complete=True,complete_settings=True,parts=parts,conditional_reference_context=reference_context,pending_bytes=0,native_reader='0x3EF0568',native_writer='0x3EEE244')
def parse(data,start,*,limit=None,**context):
 result=parse_prefix(data,start,limit=limit,**context)
 if not result.get('complete_settings'):raise UnsupportedSettings(result)
 return result
