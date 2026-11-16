"""Current173 GAME_TEAM_COMP_STATS F36F0C wire, bounded and raw-only.

Source reference switches are explicit. The ring's runtime56C1628 admission
limit is not inferred from saved counts; native loader acceptance is unproved.
"""
import struct
CTX={'stream_bit1':True,'global_3522':0,'global_3523':1,'global_2c98':1}
TAIL=((0x150,8),(0x172,10),(0x17e,18),(0x194,49),(0x1dd,3),(0x1c8,12),
      (0x170,2),(0x1d4,6),(0x190,4),(0x118,4),(0x158,8),(0x11c,4),
      (0x160,16),(0x120,4),(0x17c,2),(0x124,20))
class UnsupportedRowExtension(ValueError):
 def __init__(self,native,offset,reason,partial=None):
  self.native,self.offset,self.partial=native,offset,partial
  super().__init__(f'Unsupported GAME_TEAM_COMP_STATS {hex(native)} at {offset}: {reason}')

def parse(data,start,*,limit=None,version=173,reference_context,
          native_collection_limit=None,require_native_ring_guard=False):
 if type(version)is not int or version!=173:
  raise UnsupportedRowExtension(0xf36f0c,start,'Only current paired-writer parent version173 is supported')
 if reference_context!=CTX or any(type(reference_context.get(k))is not type(v)for k,v in CTX.items()):raise ValueError('Explicit conditional row reference context required')
 limit=len(data)if limit is None else limit
 if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid bounded row input')
 if native_collection_limit is not None and(type(native_collection_limit)is not int or native_collection_limit<=0):raise ValueError('Invalid independently supplied native collection limit')
 if type(require_native_ring_guard)is not bool:raise ValueError('Explicit ring guard policy must be boolean')
 at=start;chunks=[];rings=[];components=[]
 def take(n,label):
  nonlocal at
  if n>limit-at:raise ValueError(f'Truncated GAME_TEAM_COMP_STATS {label} at {at}: need{n}')
  begin=at;at+=n;raw=bytes(data[begin:at]);return raw
 def number(fmt,label):return struct.unpack('<'+fmt,take(struct.calcsize('<'+fmt),label))[0]
 def raw(n,label):
  begin=at;value=take(n,label);entry={'native_offset':label,'start':begin,'end':at,'raw_hex':value.hex()};chunks.append(entry);return entry
 def team(label):
  begin=at;marker=number('B',label)
  if marker!=0:raise UnsupportedRowExtension(0x11073a8 if marker==2 else 0x11019a0,begin,'Only paired-writer TEAM mode0 marker0 is supported')
  index=number('i',label)
  if index< -1:raise UnsupportedRowExtension(0x11019a0,begin,'Negative TEAM index outside supported null/original subset')
  return {'start':begin,'end':at,'marker':marker,'original_index':index,'resolved':False}
 first,second=team('base+18'),team('base+20')
 comp_begin=at;short=number('h','baseCOMP+28');comp=number('i','baseCOMPescape')if short==-2 else short
 if comp<0 and(short==-2 or comp!=-1):raise UnsupportedRowExtension(0x1101bfc,comp_begin,'Invalid compact COMP original index')
 competition={'start':comp_begin,'end':at,'short_marker':short,'original_index':comp,'resolved':False}
 for native,n in(('base+30..35',6),('base+08..17',16),('base+39,36,38,37',4)):
  raw(n,native)
 base_end=at
 for native,n in(('0x1c5',3),('0x140',16),('0x108',16),('0x1da',1),('0x3c',96)):raw(n,native)
 for native in(0xf0,0xf7,0xfe):
  begin=at;count=number('I','F6388C count')
  if count>5:raise UnsupportedRowExtension(0xf6388c,begin,'Native ring reader rejects unsigned counts above5',{'rings':rings,'count':count})
  guard_checked=native_collection_limit is not None or count==0
  if count and native_collection_limit is not None and count>=native_collection_limit:raise UnsupportedRowExtension(0xf6388c,begin,'Count fails independently supplied56C1628 limit')
  if count and require_native_ring_guard and native_collection_limit is None:raise UnsupportedRowExtension(0xf6388c,begin,'Positive ring requires independently checked56C1628 limit in native-guard mode')
  values=take(count,'F6388C serialized byte entries')
  rings.append({'native_offset':hex(native),'start':begin,'end':at,'count':count,'serialized_bytes_hex':values.hex(),'native_collection_guard_checked':guard_checked,'native_collection_limit':native_collection_limit})
 for native in(0x9c,0xa8,0xb4,0xc0,0xcc,0xd8,0xe4):
  begin=at;discarded=number('B','1276270 ignored version');payload=take(12,'1276270 raw12')
  components.append({'native_offset':hex(native),'start':begin,'end':at,'ignored_version_byte':discarded,'raw12_hex':payload.hex()})
 for native,n in TAIL:raw(n,hex(native))
 return {'start':start,'end':at,'version':version,'base_end':base_end,
         'base':{'team18':first,'team20':second,'competition28':competition},
         'chunks':chunks,'rings':rings,'components':components,
         'native_reader':'0xf36f0c','native_writer':'0xf357f8','complete_row_wire':True,
         'reference_context':reference_context,'reference_profile_is_conditional':True,
         'native_collection_guard_complete':all(r['native_collection_guard_checked']for r in rings),
         'native_loader_acceptance_proved':False,'raw_wire_only':True,'semantic_stats_decoded':False,'pending_bytes':0}
