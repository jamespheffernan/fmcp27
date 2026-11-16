"""Verify currency fields, historical-rate layout and native GBP conversion direction."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from fm_live_mcp import players, world, database, wages
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case

b=Bridge();sid=b.attach()['session_id'];runtime=[]
try:
    with b.lock,b._read_scope(sid):
        process=b._current(sid);layout=b._player_layout(process);base=layout[0]-players.RVA[0]
        plugin=Path(b.plugin_identity[0][0]);read,save,_=b._world_state(process,layout)
        assert wages.base_currency(read,base)=='GBP'
        info=database.table(read,base,'currencies');stored={}
        for index in range(info['count']):
            a=world.pointer(read,info['start']+index*8);world.typed(read,base,a,'currency')
            i,nid,dup=struct.unpack('<III',read(a+8,12));assert i==index and nid and nid not in stored
            stored[nid]=struct.unpack('<f',read(a+0x38,4))[0]
        mapping=struct.unpack('<66i',read(base+0x538ef50,264))
        assert len(set(mapping))==66 and mapping[0]==86
        assert read(base+0x56c10a8,1)[0]&1 and read(base+0x56c0864,1)[0]&1
        for i,nid in enumerate(mapping):
            value=struct.unpack('<d',read(base+0x56c0868+i*32,8))[0]
            if nid in stored:assert value==stored[nid],(nid,value,stored[nid])
            runtime.append({'native_index':i,'native_id':nid,'rate':value,'database_record_present':nid in stored})
        read.verify();b._current(sid)
finally:b.detach()

cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
expected={
    0x10104F0:['bl #0x4403cd4','ldr x8, [x20, #0x18]'],
    0x101063C:['ldr s8, [x20, #0x38]','bl #0x4403cd4','add x0, x0, #0x68','str s8, [sp, #0x18]'],
    # Four SI string fields in the serializer; only the first has a verified semantic label.
    0x10100A0:['ldr x0, [x1]','add x1, x19, #0x18','bl #0x43836a4'],
    0x10100CC:['ldr x0, [x25]','add x1, x19, #0x20','bl #0x43836a4'],
    0x10100DC:['ldr x0, [x25]','add x1, x19, #0x28','bl #0x43836a4'],
    0x10100EC:['ldr x0, [x25]','add x1, x19, #0x30','bl #0x43836a4'],
    0x1010120:['add x1, x19, #0x40','mov x0, x25','bl #0x1010ea8'],
    # History serialization: vector stride 8, uint16 year and float32 rate at +4.
    0x1010384:['ldp x9, x8, [x1]','sub x8, x8, x9','lsr x8, x8, #3'],
    0x1010418:['mov x0, x22','mov x1, x21','mov w2, #2','blr x8'],
    0x1010430:['ldr x22, [x19]','add x21, x21, #4'],
    0x1010440:['mov x0, x22','mov x1, x21','mov w2, #4','blr x8'],
    0x1010BCC:['ldp x13, x14, [x0, #0x40]'],
    0x1010BFC:['add x13, x13, #8','cmp x13, x14','b.eq #0x1010c58'],
    0x1010C08:['ldrh w15, [x13]','cmp w15, w10','b.eq #0x1010c48'],
    0x1010C48:['ldr s0, [x13, #4]'],
    # Loading and editing copy float32 record rates to double formatter rates.
    0x10101A8:['ldr w0, [x0, #0xc]','bl #0x10106f4','cmn w0, #1','b.eq #0x10101cc',
               'bl #0x42cc770','cbz x0, #0x10101cc','ldr s0, [x19, #0x38]','fcvt d0, s0','str d0, [x0]'],
    0x1010A78:['str s0, [x19, #0x38]','ldr w0, [x19, #0xc]','bl #0x10106f4','cmn w0, #1',
               'b.eq #0x1010aa0','bl #0x42cc770','cbz x0, #0x1010aa0','ldr s0, [x19, #0x38]','fcvt d0, s0','str d0, [x0]'],
    0x42CC7C4:['sxtw x8, w19','add x8, x20, x8, lsl #5','add x0, x8, #8'],
    # Base cash input divides by selected rate; output multiplies base units by rate.
    0x42CB2E0:['ldr x8, [x19]','ldr x8, [x8, #0x58]','sxtb w1, w1','mov x0, x19','blr x8','fcvt d0, s0','fdiv d1, d8, d0'],
    0x42D0C34:['ldp d0, d1, [sp, #0x18]','scvtf d0, d0','mov x8, #0x4059000000000000',
               'fmov d2, x8','fdiv d1, d1, d2','fadd d8, d1, d0','ldr x8, [sp, #8]',
               'ldr x8, [x8, #0x58]','sxtb w1, w19','add x0, sp, #8','blr x8','fcvt d0, s0','fmul d0, d8, d0'],
}
with plugin.open('rb') as f:
    assert hashlib.file_digest(f,'sha256').hexdigest()==players.SHA256
    def raw(a,n):f.seek(0x5ed4000+a);return f.read(n)
    def ptr(a):return int.from_bytes(raw(a,8),'little')&0xffffffff
    for vt,name in (world.TYPES['currency'],database.TABLES['currencies'][1:]):
        assert raw(vt-16,8)==bytes(8) and raw(ptr(ptr(vt-8)+8),len(name)+1)==name+b'\0'
    assert ptr(world.TYPES['currency'][0]+24)==0x1010480
    code={i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw(0x1010480,0x274),0x1010480)}
    assert property_case(code,'Cnam',0x101049C,'w1')==0x10104F0
    assert property_case(code,'Cexr',0x101049C,'w1')==0x101063C
    for at,instructions in expected.items():
        actual=[f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw(at,len(instructions)*4),at)]
        assert actual==instructions,(hex(at),actual)
archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes();definition=None
for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
    try:root=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
    except(zstandard.ZstdError,ET.ParseError):continue
    for row in root.iter('record'):
        field=row.find("flags[@id='field']")
        if field is not None and field.get('value')=='Cexr':definition=row
assert definition is not None
assert definition.find("flags[@id='type']").get('value')=='real'
hint=definition.find("translation[@id='hint']").get('value').split('[COMMENT')[0]
assert hint=='Compared to the value of the Pound Sterling'
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'plugin_sha256':players.SHA256,
         'instruction_spans':[{ 'rva':hex(k),'instructions':v} for k,v in expected.items()],
         'editor_rate_hint':hint,'runtime_slots':runtime,'historical_stride':8,'historical_year_type':'uint16',
         'historical_rate_type':'float32','foreground_ui_used':False,'native_execution':False,
         'scope':'Stored rates relative to GBP, serializer fields/history, native conversion direction and observed runtime correspondence. No display rounding or historical interpolation implementation.'}
(ROOT/'evidence/currency-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Verified',len(expected),'native instruction spans, editor GBP basis and',len(runtime),'runtime slots.')
