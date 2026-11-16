"""Native LEAGUE_TEAM_STATS prefix, conditional reader profile; not a full row."""
from .errors import UnsupportedLayout
import struct
CTX = dict(stream_bit1=True, global_3522=0, global_3523=1, global_2c98=1)
RAW_BYTE_OFFSETS = (0xf7,0xf8,0xf9,0xfa,0xfb,0xfc,0xee,0xf3,0xf4,0xf5,0xf6,0xef,0xf0,0xfd)

class UnsupportedRow(ValueError):
    def __init__(self, native, offset, reason):
        self.native,self.offset=native,offset
        super().__init__(f'{hex(native)} at {offset}: {reason}')

def parse_prefix(data,start,*,limit=None,reference_context,version=521):
    if type(reference_context)is not dict or reference_context!=CTX or any(type(reference_context[k])is not type(v)for k,v in CTX.items()):
        raise ValueError('Explicit conditional reference profile required')
    if type(version)is not int or version!=521:raise UnsupportedLayout('Unsupported component version')
    limit=len(data)if limit is None else limit
    if type(start)is not int or type(limit)is not int or not 0<=start<=limit<=len(data):raise ValueError('Invalid row bounds')
    at=start
    def take(n):
        nonlocal at
        if n>limit-at:raise ValueError('Truncated league row prefix')
        raw=bytes(data[at:at+n]);at+=n;return raw
    def number(fmt):return struct.unpack('<'+fmt,take(struct.calcsize('<'+fmt)))[0]
    def reference():
        p=at;marker=number('B')
        if marker==2:raise UnsupportedRow(0x11073a8,at,'Inline TEAM is unsupported')
        # Checked representation: retain native marker and signed word; no canonical claim.
        if marker not in(0,1):raise UnsupportedRow(0x11019a0,p,'Unverified marker representation')
        word=number('i');secondary=number('I')if marker==1 and word!=-1 else None
        return dict(start=p,end=at,marker=marker,stored_team_index=word,secondary_word=secondary,state='null'if word==-1 else 'stored_reference')
    team=reference();rawbytes={hex(o):number('B')for o in RAW_BYTE_OFFSETS};raw_d8=take(4).hex();blocks=[]
    for memory_offset in(0,0x18,0x30,0x48,0x60):
        p=at;ref=reference();played,rawf,wins,draws,losses,penalty_losses=struct.unpack('<6b',take(6));gf,ga,points=struct.unpack('<3h',take(6))
        difference=(gf-ga+32768)%65536-32768
        blocks.append(dict(start=p,end=at,memory_offset=hex(memory_offset),team_reference=ref,played=played,raw_f_u8=rawf&255,wins=wins,draws_or_penalty_wins=draws,losses=losses,penalty_losses=penalty_losses,goals_for=gf,goals_against=ga,goal_difference=difference,points=points))
    return dict(start=start,end=at,state='stopped',complete=False,next_native_reader='0x3f4f680',stop_reason='Optional paired statistics and remaining row body not yet consumed',team_reference=team,stored_position_u8=rawbytes['0xf7'],unmapped_bytes=rawbytes,raw_d8_hex=raw_d8,overall=blocks[0],home=blocks[1],away=blocks[2],unmapped_stat_blocks=blocks[3:],reference_context=dict(reference_context),source_runtime_profile_proved=False)

def parse(data,start,**kwargs):
    out=parse_prefix(data,start,**kwargs)
    raise UnsupportedRow(0x3f4f680,out['end'],'Prefix only; cannot publish as completed row')
