"""Bounded extended competition-stat transport; conditional factory profile."""
from .errors import UnsupportedLayout
import struct
from . import stats_prefix as prefix, stats_f9 as f9
CTX=prefix.CTX
class UnsupportedStats(ValueError):
 def __init__(self,native,offset,reason,partial=None):
  self.native,self.offset,self.reason,self.partial=native,offset,reason,partial
  super().__init__(f'Unsupported extended stats child {hex(native)} at {offset}: {reason}')

class Cursor(prefix.Cursor):
 def object_ref(self):
  begin=self.p
  if begin>=self.limit:raise ValueError('Truncated object reference')
  marker=self.data[begin]
  if marker==2:raise UnsupportedStats(0x11073a8,begin,'Inline object reference requires separate child')
  if marker not in(0,1):raise UnsupportedStats(0x11019a0,begin,'Object marker outside checked subset')
  out=super().object_ref()
  if out['index'] < -1:raise ValueError('Invalid signed original object index')
  return out

def parse_prefix(data,start,*,limit=None,version=5,reference_context,object_profile='extended'):
 if type(reference_context)is not dict or reference_context!=CTX or any(type(reference_context.get(k))is not type(v)for k,v in CTX.items()):raise ValueError('Explicit conditional reference context required')
 if object_profile!='extended':raise UnsupportedLayout('Only explicit extended hypothesis in this codec')
 first=prefix.parse(data,start,limit=limit,version=version,reference_context=reference_context,object_profile='extended')
 c=Cursor(data,first['end'],limit);parts=[dict(native_reader='frozen_prefix',value=first,start=start,end=c.p)]
 result=dict(start=start,end=c.p,state='stopped',complete=False,full_child_complete=False,object_profile='extended',required_factory_global={'address':'0x56D497A','predicate':'equals1'},source_runtime_profile_proved=False,reference_context=reference_context,parts=parts)
 def stop(native,reason):result.update(end=c.p,next_native_reader=hex(native),stop_reason=reason);return result
 def group():
  begin=c.p;v=c.value('<B')
  if v!=1:raise UnsupportedStats(0x3f94fc0,begin,'Unsupported nested version')
  raw_a=c.take(9);a=c.object_ref();b=c.object_ref();raw_b=c.take(6)
  return dict(start=begin,end=c.p,version=v,raw9_hex=raw_a.hex(),references=[a,b],raw6_hex=raw_b.hex())
 def comp():
  begin=c.p;n=c.value('<h');extended=c.value('<i')if n==-2 else None
  if n < -2 or (extended is not None and extended<0):raise ValueError('Invalid compact COMP reference')
  return dict(start=begin,end=c.p,short=n,extended=extended)
 def keep(name,fn):
  begin=c.p;value=fn();parts.append(dict(native_reader=name,start=begin,end=c.p,value=value))
 def f9bac8():return dict(flag=c.value('<B'),group=group())
 def f9cf78():return dict(flag=c.value('<B'),raw13_hex=bytes(c.take(13)).hex(),ref=c.object_ref())
 def f9dbec():return dict(flag=c.value('<B'),raw2b=c.value('<B'),person_word=c.value('<I'),comp=comp(),raw28=c.value('<H'),raw2a=c.value('<B'),ref=c.object_ref())
 def fa0248():return dict(flag=c.value('<B'),raw40=c.value('<B'),person_word=c.value('<I'),group=group())
 def f9e9dc():return dict(flag=c.value('<B'),raw22=c.value('<B'),person_word=c.value('<I'),raw20=c.value('<H'),ref=c.object_ref(),raw23=c.value('<B'))
 for offset in ('virtual118/+6e8','virtual120/+708'):
  value=f9.parse(data,c.p,limit=c.limit,reference_context=reference_context)
  if value['object_reference']['marker'] not in(0,1):raise UnsupportedStats(0x11019a0,c.p,'Reference marker outside checked subset')
  if value['object_reference']['stored_index_i32'] < -1:raise ValueError('Invalid signed original object index')
  parts.append(dict(native_reader='0xf9ae54',native_offset=offset,start=c.p,end=value['end'],value=value));c.p=value['end']
 for off in ('128','160'):keep('F9BAC8/+'+off,f9bac8)
 for off in ('198','1b8','1d8','1f8','218','238'):keep('F9CF78/+'+off,f9cf78)
 keep('F9DBEC/+258',f9dbec);keep('FA0248/+288',fa0248);keep('F9E9DC/+2d0',f9e9dc)
 def fa101c():return dict(flag=c.value('<B'),raw20=c.value('<I'),person_word=c.value('<I'),raw26=c.value('<B'),raw24=c.value('<H'),ref=c.object_ref())
 def fa4578():return dict(flag=c.value('<B'),raw38=c.value('<I'),person_word=c.value('<I'),group=group())
 def faaf98():return dict(flag=c.value('<B'),person_word=c.value('<I'),raw40=c.value('<H'),group=group())
 def fac2e0():return dict(flag=c.value('<B'),ref=c.object_ref(),raw18=c.value('<H'),raw1a=c.value('<H'))
 def facf04():return dict(flag=c.value('<B'),ref=c.object_ref(),raw18=c.value('<H'),raw1a=c.value('<B'))
 keep('FA101C/+2f8',fa101c);keep('FA1B94/+320',f9e9dc)
 keep('FA27EC/+348',lambda:prefix._scalar(c))
 for off in ('398','3e0','428','470'):keep('FA4578/+'+off,fa4578)
 keep('FAAF98/+4b8',faaf98);keep('F9F648/virtualA0',f9e9dc)
 keep('FAC2E0/+28',fac2e0)
 for off in ('A8','B0','B8','C0','C8','D0','D8'):keep('FAC2E0/virtual'+off,fac2e0)
 for off in ('E8','F0','F8','100','108','110'):keep('FACF04/virtual'+off,facf04)
 result.update(end=c.p,state='complete',next_native_reader=None,stop_reason=None,complete=True,full_child_complete=True)
 return result

def parse(data,start,**kwargs):
 out=parse_prefix(data,start,**kwargs)
 if out.get('complete'):return out
 raise UnsupportedStats(int(out['next_native_reader'],16),out['end'],out['stop_reason'],out)
