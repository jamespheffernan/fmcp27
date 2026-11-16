"""Current160 paired embedded scalar/vector wire; reader48ED3E0/writer48EC6D0.

No field labels, references or competition-state meanings are inferred. Legacy
versions fail rather than applying the current fixed geometry to older layouts.
"""
from .errors import UnsupportedLayout
import struct
FIXED_PREFIX_BYTES = 820  # u32version +572scalar +14*16+4loop +8+8scalar
VECTOR_STRIDES = (6, 6, 12, 12, 12, 12)

def parse(data,start,limit=None,*,max_items=4096):
 limit=len(data)if limit is None else limit
 if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid embedded codec bounds')
 if type(max_items)is not int or not 0<=max_items<=4096:raise ValueError('Invalid embedded work budget')
 at=start
 def take(n):
  nonlocal at
  if n<0 or n>limit-at:raise ValueError(f'Truncated48ED3E0 at {at}:need{n}')
  old=at;at+=n;return bytes(data[old:at])
 version=struct.unpack('<I',take(4))[0]
 if version!=160:raise UnsupportedLayout(f'Unsupported48ED3E0 version{version} at{start}')
 fixed=take(FIXED_PREFIX_BYTES-4)
 vectors=[];work=0
 for stride in VECTOR_STRIDES:
  count_at=at;count=struct.unpack('<i',take(4))[0]
  if count<0:raise ValueError(f'Negative48ED3E0 count at{count_at} reaches native reserve overflow')
  if count>max_items-work:raise ValueError(f'48ED3E0 item budget at{count_at}')
  work+=count;begin=at;raw=take(count*stride)
  vectors.append({'count_offset':count_at,'start':begin,'end':at,'count':count,'stride':stride,'raw_hex':raw.hex()})
 tail=take(20)
 return {'start':start,'end':at,'version':version,'fixed_prefix_bytes':FIXED_PREFIX_BYTES,'fixed_scalar_hex':fixed.hex(),'vectors':vectors,'raw_tail20_hex':tail.hex(),'native_reader':'0x48ed3e0','native_writer':'0x48ec6d0','semantic_fields_resolved':False,'references_resolved':False}
