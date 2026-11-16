"""Bounded conditional tag2 LEAGUE_FATE_ACTION_RELEGATION child only."""
from .errors import UnsupportedLayout
import struct
CTX={'stream_bit1':True,'global_3522':0,'global_3523':1,'global_2c98':1}
def parse(data,start,*,limit=None,reference_context=CTX):
 if reference_context!=CTX:raise UnsupportedLayout('Unsupported explicit reference context')
 end_limit=len(data)if limit is None else limit
 if type(start)is not int or type(end_limit)is not int or not 0<=start<=end_limit<=len(data):raise ValueError('Invalid child bounds')
 at=start
 def take(n):
  nonlocal at
  if n>end_limit-at:raise ValueError('Truncated tag2 league action')
  old=at;at+=n;return bytes(data[old:at])
 short=struct.unpack('<h',take(2))[0];index=short
 if short==-2:
  index=struct.unpack('<i',take(4))[0]
  if index<0:raise ValueError('Native extended reference rejects negative index')
 if index< -1:raise ValueError('Native compact reference rejects negative index')
 marker=take(1)[0]
 if marker!=0:raise UnsupportedLayout('Unproved TEAM marker; only observed writer marker0 supported')
 team=struct.unpack('<i',take(4))[0];field18=take(1)[0];field19=take(1)[0]
 return {'start':start,'end':at,'complete_child_wire':True,'native_reader':'0x3e0bfbc','native_writer':'0x3e0bf08','factory_tag':2,'native_type':'sicomps::LEAGUE_FATE_ACTION_RELEGATION','reference_context':dict(reference_context),'runtime_globals_proved':False,'reference_08':{'short_word':short,'index_word':index,'namespace':'COMP reference transport; unresolved'},'reference_10':{'marker':marker,'index_word':team,'namespace':'TEAM_BASE reference transport; unresolved'},'raw_field18':field18,'raw_field19':field19,'semantic_outcome':None}
