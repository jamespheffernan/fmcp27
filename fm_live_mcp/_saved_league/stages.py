"""Sequential conditional ACTUAL_COMP traversal; no fixed source offsets."""
from .errors import UnsupportedLayout
from . import prefix as P
CTX=dict(stream_bit1=True,global_3522=0,global_3523=1,global_2c98=1)
def parse(data,*,reference_context,child_readers=None):
 if reference_context!=CTX:raise UnsupportedLayout('Unproved reference context; explicit conditional profile required')
 prefix=P.decode_prefix(data);cursor=prefix['end'];parts=[]
 child_readers={} if child_readers is None else child_readers
 def take(n):
  nonlocal cursor
  if n<0 or cursor+n>len(data):raise ValueError('Truncated ACTUAL_COMP continuation')
  at=cursor;cursor+=n;return at,data[at:cursor]
 def item(name,n):
  at,raw=take(n);parts.append(dict(field=name,start=at,end=cursor,raw_hex=raw.hex()));return raw
 def count(name):
  n=int.from_bytes(item(name+'_count',4),'little')
  if n>4096:raise ValueError('Count budget exceeded')
  return n
 def stop(native,why):return dict(state='stopped',end=cursor,next_native_reader=hex(native),stop_reason=why,parts=parts,prefix=prefix,reference_context=reference_context,conditional_reference_profile=True,complete=False)
 def child(native,name):
  nonlocal cursor
  cb=child_readers.get(native)
  if cb is None:return False
  at=cursor;out=cb(data,cursor)
  if not isinstance(out,dict) or type(out.get('end')) is not int or not at<out['end']<=len(data):raise ValueError('Invalid child extent')
  cursor=out['end'];parts.append(dict(field=name,start=at,end=cursor,child=out,native=hex(native)));return True
 def compact(name):
  raw=item(name+'_short',2);v=int.from_bytes(raw,'little',signed=True)
  if v==-2:item(name+'_extended',4)
 if prefix['optional_398_marker']:return stop(0x3b7fd28,'Positive optional +398')
 for name,n in [('3b8',2),('3b6',2),('82a',1),('4c1',1),('829',1),('4c9',1),('4bc',1),('4b8',2)]:item(name,n)
 if item('optional_3f0',1)!=b'\0' and not child(0x3e009d0,'3f0_child'):return stop(0x3e009d0,'Positive optional +3F0')
 compact('410_COMP_reference');item('418_reference',4)
 n=count('648_raw_u32');item('648_values',n*4)
 n=count('3d8_reference');item('3d8_values',n*4)
 n=count('3c0_child')
 for i in range(n):
  if not child(0x3e00350,f'3c0_child_{i}'):return stop(0x3e00350,'Positive +3C0 collection')
 n=count('1b8_reference')
 item('1b8_values',n*4)
 n=count('580_child')
 for i in range(n):
  if not child(0x3bbf78c,f'580_child_{i}'):return stop(0x3bbf78c,'Positive +580 collection')
 n=count('598_child')
 for i in range(n):
  if not child(0x3f6e658,f'598_child_{i}'):return stop(0x3f6e658,'Positive +598 collection')
 n=count('450_TEAM_reference')
 for i in range(n):
  if cursor>=len(data):raise ValueError('Truncated +450 TEAM marker')
  if data[cursor]!=0:return stop(0x11019a0,'Positive +450 TEAM reference outside checked marker0 subset')
  item(f'450_TEAM_{i}',5)
 for name,n in [('4be',1),('4e8',2),('4ea',2),('4f8',2),('4fa',2),('4fc',2),('4fe',2),('3ac',4),('4ec',2),('4ee',2),('4f0',2),('4f2',2),('4f4',2),('4f6',2),('49',1),('48',1),('4a',1),('4b',1)]:item(name,n)
 item('98_header',6)
 prop=P.properties(data,cursor);parts.append(dict(field='98_property_map',start=cursor,end=prop['end'],property_map=prop));cursor=prop['end']
 groups=count('98_nested_groups')
 for group in range(groups):
  rows=count(f'98_group_{group}_rows')
  if rows:return stop(0x3f6fbfc,'Positive nested +98 group')
  item(f'98_group_{group}_tail',2)
 if item('optional_390',1)==b'\x01' and not child(0x3be2048,'390_child'):return stop(0x3be2048,'Positive optional +390')
 if item('optional_5b0',1)==b'\x01' and not child(0x3bdf670,'5b0_child'):return stop(0x3bdf670,'Positive optional +5B0')
 n=count('1d8_stage')
 if n>1024:raise ValueError('Stage vector exceeds bounded projection')
 entries=[]
 for i in range(n):
  kind=int.from_bytes(item(f'stage_{i}_kind',1),'little',signed=True)
  entry=dict(native_slot_index=i,kind_code=kind,body_start=cursor)
  if kind==7:
   entry.update(state='null_slot',end=cursor);entries.append(entry);continue
  reader={0:0x3c73aa0,1:0x3eef5c0,2:0x3de56e0,11:0x3c3dc74}.get(kind,0x3af3be4)
  if reader==0x3af3be4 or not child(reader,f'stage_{i}_body'):
   entry.update(state='body_unparsed',next_native_reader=hex(reader));entries.append(entry)
   result=stop(reader,'First unresolved stage body; original slot order retained')
   result.update(stage_count=n,stage_entries=entries)
   return result
  entry.update(state='body_parsed',end=cursor);entries.append(entry)
 result=stop(0x3aef6e8,'Stage vector complete; subsequent competition suffix unparsed')
 result.update(state='stage_vector_complete' if n else 'stage_vector_empty',stage_count=n,stage_entries=entries)
 return result
