"""One +210 LEAGUE_SETTINGS row under explicit conditional source521 context."""
from .errors import UnsupportedLayout
import struct
CTX={'stream_bit1':True,'global_3522':0,'global_3523':1,'global_2c98':1}
def parse(data,start,*,limit=None,reference_context=CTX,version=521):
 if reference_context!=CTX or type(version)is not int or version!=521:raise UnsupportedLayout('Unsupported source/context')
 bound=len(data)if limit is None else limit
 if type(start)is not int or type(bound)is not int or not 0<=start<=bound<=len(data):raise ValueError('Invalid child bounds')
 at=start
 def take(n):
  nonlocal at
  if n>bound-at:raise ValueError('Truncated +210 settings row')
  old=at;at+=n;return bytes(data[old:at])
 raw=take(8);field10=take(1)[0];short=struct.unpack('<h',take(2))[0];index=short
 if short==-2:
  index=struct.unpack('<i',take(4))[0]
  if index<0:raise ValueError('Negative escaped reference rejected natively')
 if index< -1:raise ValueError('Negative compact reference rejected natively')
 return {'start':start,'end':at,'complete_child_wire':True,'native_reader':'0x3e02f64','native_writer':'0x3e02df8','field08_u32':struct.unpack_from('<I',raw)[0],'field0c_u32':struct.unpack_from('<I',raw,4)[0],'writer_four_u16':list(struct.unpack('<4H',raw)),'raw08_0f_hex':raw.hex(),'raw_field10':field10,'reference00':{'short_word':short,'index_word':index,'namespace':'COMP transport, unresolved'},'reference_context':dict(reference_context),'runtime_globals_proved':False,'semantic_labels':None}
