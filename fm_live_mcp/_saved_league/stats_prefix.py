"""Bounded conditional prefix; never claims full F90A50 for selector FF."""
from .errors import UnsupportedLayout
import struct
CTX=dict(stream_bit1=True,global_3522=0,global_3523=1,global_2c98=1)
class Stop(ValueError):
    def __init__(self, offset):
        self.native, self.offset = 0x11073a8, offset
        super().__init__('Nested native11073A8 reference at ' + str(offset))
class Cursor:
    def __init__(self,data,start,limit):
        if type(start)is not int or start<0:raise ValueError('Invalid start')
        if limit is None:limit=len(data)
        if type(limit)is not int or not start<=limit<=len(data):raise ValueError('Invalid limit')
        self.data=data;self.p=start;self.limit=limit
    def take(self,n):
        if self.p+n>self.limit:raise ValueError('Truncated stats child')
        start=self.p;self.p+=n;return self.data[start:self.p]
    def value(self,fmt):return struct.unpack(fmt,self.take(struct.calcsize(fmt)))[0]
    def object_ref(self):
        start=self.p;marker=self.value('<B')
        if marker==2:raise Stop(start)
        index=self.value('<i');secondary=None
        if index != -1 and marker==1:secondary=self.value('<I')
        return dict(start=start,end=self.p,marker=marker,index=index,secondary_word=secondary,meaning='unresolved polymorphic object reference')
def check(context):
    if context!=CTX:raise UnsupportedLayout('Unsupported explicit reference context')
def _scalar(c):
    start=c.p;out=dict(start=start,native_08=c.value('<B'),native_22=c.value('<H'),native_24=c.value('<B'))
    # Under explicit 3523=1/C98=1 native1104FB0 transports a raw32 word.
    out['person_reference_word']=c.value('<I');out['native_20']=c.value('<H');out['object_reference']=c.object_ref();out['end']=c.p
    return out
def parse_scalar_child(data,start,*,reference_context,limit=None):
    check(reference_context);c=Cursor(data,start,limit);out=_scalar(c)
    out.update(state='conditional_child_complete',native_reader='0xFA27EC');return out
def parse(data,start,*,version=5,reference_context,object_profile,limit=None):
    check(reference_context)
    if version!=5:raise UnsupportedLayout('Unsupported enclosing stored stats version')
    if object_profile not in ('base','extended'):raise ValueError('Explicit factory object profile required')
    c=Cursor(data,start,limit);selector=c.value('<B')
    if selector!=255:raise UnsupportedLayout('Only checked full selector FF supported')
    parts=[]
    def record(offset,tail_words):
        begin=c.p;flag=c.value('<B');ref=c.object_ref();words=[c.value('<H')for _ in range(tail_words)]
        parts.append(dict(native_offset=offset,start=begin,end=c.p,raw_flag=flag,object_reference=ref,raw_u16_words=words))
    record('0x10',1);record('0x50',2)
    if object_profile=='extended':record('virtual_E0_extended_0x5E0',2)
    record('0x70',2)
    child=_scalar(c);parts.append(dict(native_offset='0x370',native_reader='0xFA27EC',child=child,start=child['start'],end=c.p))
    if object_profile=='base':
        begin=c.p;flag=c.value('<B');word=c.value('<I');parts.append(dict(native_offset='0x90',start=begin,end=c.p,raw_flag=flag,raw_word=word))
        return dict(start=start,end=c.p,state='stopped',next_native_reader='0x3F94FC0',native_field='0x98',parts=parts,selector=selector,enclosing_version=version,object_profile=object_profile,required_factory_global=dict(address='0x56D497A',predicate='not_equals1'),reference_context=reference_context,source_runtime_profile_proved=False,full_child_complete=False,stop_reason='base-profile current-writer nested version not yet supported; no runtime profile elimination')
    def group(offset):
        begin=c.p;flag=c.value('<B');word=c.value('<I')
        child_start=c.p;child_version=c.value('<B')
        if child_version!=1:raise UnsupportedLayout('Unsupported3F94FC0 version')
        raw18=c.value('<I');reference_word=c.value('<I');raw22=c.value('<B')
        ref08=c.object_ref();ref10=c.object_ref();raw20=c.value('<B');raw21=c.value('<B');raw1c=c.value('<I')
        child=dict(start=child_start,end=c.p,native_reader='0x3F94FC0',version=child_version,raw18=raw18,reference_word=reference_word,raw22=raw22,object08=ref08,object10=ref10,raw20=raw20,raw21=raw21,raw1c=raw1c)
        parts.append(dict(native_offset=offset,start=begin,end=c.p,raw_flag=flag,raw_word=word,child=child))
    group('0x90');group('0xD0')
    begin=c.p;flag=c.value('<B');ref=c.object_ref();raw120=c.value('<I');raw124=c.value('<H')
    parts.append(dict(native_offset='0x110',start=begin,end=c.p,raw_flag=flag,object_reference=ref,raw120=raw120,raw124=raw124))
    next_reader='0xF9AE54' if object_profile=='extended' else '0xF9BAC8'
    return dict(start=start,end=c.p,state='stopped',next_native_reader=next_reader,native_field='virtual118_extended_0x6E8'if object_profile=='extended'else'0x128',parts=parts,selector=selector,enclosing_version=version,object_profile=object_profile,required_factory_global=dict(address='0x56D497A',predicate='equals1'if object_profile=='extended'else'not_equals1'),reference_context=reference_context,source_runtime_profile_proved=False,full_child_complete=False)
