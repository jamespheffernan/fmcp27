"""Verify WEATHER dispatch, signed fields, null sentinel and editor category definitions."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib, json, re, sys, xml.etree.ElementTree as ET
import zstandard
from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT/'scripts'))
from fm_live_mcp import players, world, database, geography, weather
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case
b=Bridge(); sid=b.attach()['session_id']
try:
    with b.lock,b._read_scope(sid):
        p=b._current(sid); layout=b._player_layout(p); base=layout[0]-players.RVA[0]
        plugin=Path(b.plugin_identity[0][0]); snapshot,save,_=b._world_state(p,layout)
        descriptor=world.pointer(snapshot,base+0x56d63c0)
        vt=world.pointer(snapshot,descriptor)
        assert vt==base+0x569ca88
        info=world.pointer(snapshot,vt-8); name=players.u64(snapshot(info+8,8))
        null_type=b'N6sicore17NULL_TYPED_TRAITSE'
        assert snapshot(name,len(null_type)+1)==null_type+b'\0'
        snapshot.verify(); b._current(sid)
finally:b.detach()
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
with plugin.open('rb') as f:
    assert hashlib.file_digest(f,'sha256').hexdigest()==players.SHA256
    def read(rva,size):f.seek(0x5ed4000+rva);return f.read(size)
    def pointer(rva):return int.from_bytes(read(rva,8),'little')&0xFFFFFFFF
    for vt,name in (world.TYPES['weather'],database.TABLES['weather'][1:]):
        assert int.from_bytes(read(vt-16,8),'little',signed=True)==0
        assert read(pointer(pointer(vt-8)+8),len(name)+1)==name+b'\0'
    assert pointer(world.TYPES['weather'][0]+24)==geography.FIELDS['weather'][0]
    raw=read(0x18b2768,0x18b3f2c-0x18b2768)
    code={i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw,0x18b2768)}
    runtime_raw=read(0x18b6b08,16)
    runtime=[f'{i.mnemonic} {i.op_str}' for i in cs.disasm(runtime_raw,0x18b6b08)]
assert runtime==['ldrb w9, [x1, #0x16]','mov w17, #0xa','cmp w9, #0x64','csel w9, w17, w9, eq'],runtime

def route(prop):
    regs={'x0':0,'w1':int.from_bytes(prop.encode(),'big')};pc=0x18b2778;left=right=0;trace=[]
    def value(s):return int(s[1:],0) if s.startswith('#') else regs[s]
    def signed(v):return v-2**32 if v&2**31 else v
    for _ in range(200):
        if pc==0x18b3428:return regs['x0'],regs['w1'].to_bytes(4,'big').decode('ascii'),trace
        text=code[pc];trace.append((hex(pc),text));op,_,tail=text.partition(' ');args=tail.split(', ');nxt=pc+4
        if op=='mov':regs[args[0]]=value(args[1])
        elif op=='movk':
            shift=int(args[2].split('#')[1]);regs[args[0]]=(regs.get(args[0],0)&~(65535<<shift))|(value(args[1])<<shift)
        elif op in ('add','sub','orr','and','lsl'):
            a,b=value(args[1]),value(args[2]);v={'add':lambda:a+b,'sub':lambda:a-b,'orr':lambda:a|b,'and':lambda:a&b,'lsl':lambda:a<<(b&31)}[op]()
            regs[args[0]]=v&((1<<32)-1 if args[0].startswith('w') else (1<<64)-1)
        elif op=='cmp':left,right=value(args[0]),value(args[1])
        elif op=='tst':left,right=value(args[0])&value(args[1]),0
        elif op=='b':nxt=value(args[0])
        elif op.startswith('b.'):
            a,b=signed(left),signed(right)
            take={'eq':left==right,'ne':left!=right,'le':a<=b,'lt':a<b,'gt':a>b,'ge':a>=b,'hi':left>right,'ls':left<=right,'hs':left>=right,'lo':left<right}[op[2:]]
            if take:nxt=value(args[0])
        else:raise ValueError((prop,hex(pc),text))
        pc=nxt
    raise ValueError('Dispatch trace bound exceeded')

archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes(); definitions={}
for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
    try:root=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
    except(zstandard.ZstdError,ET.ParseError):continue
    for row in root.iter('record'):
        field=row.find("flags[@id='field']")
        if field is not None and re.fullmatch(r'w[0-3](sd|dn|w[0-4]|p[0-4]|t[ev0-7])',field.get('value','')):
            definitions[field.get('value')]=row
assert len(definitions)==88
mapped=[]
for period in range(4):
    specs=[('sd',0,'ldrsh',None,365),('dn',22,'ldrsb',None,50)]
    for kind,prefix,offset,suffixes in (('wind','w',2,'01234'),('precipitation','p',7,'01234'),('temperature','t',12,'ev01234567')):
        specs.extend((prefix+suffix,offset+i,'ldrsb',weather.CATEGORIES[kind][i],100) for i,suffix in enumerate(suffixes))
    for suffix,offset,load,label,maximum in specs:
        prop=f'w{period}{suffix}';at,child,trace=route(prop)
        assert at==0x20+period*24
        case=property_case(code,child,0x18b346c,'w1')
        match=re.fullmatch(r'(ldrsb|ldrsh) w\d+, \[x8(?:, #(0x[0-9a-f]+|\d+))?\]',code[case])
        assert match and match[1]==load and (int(match[2],0) if match[2] else 0)==offset,(prop,code[case])
        definition=definitions[prop]
        assert definition.find("integer[@id='min_value']").get('value')=='0'
        assert definition.find("integer[@id='max_value']").get('value')==str(maximum)
        if label is not None:
            actual=next(e.get('value') for e in definition if e.get('id')=='name').split('[COMMENT')[0]
            assert actual==label,(prop,actual,label)
        mapped.append({'property':prop,'period_offset':at,'field_offset':offset,'load':load,'child':child,'case':hex(case)})
expected=['ldrsb w20, [x8, #0x16]','cmp w20, #0x64','b.ne #0x18b3e14',
          'adrp x20, #0x56d6000','add x20, x20, #0x3c0']
assert [code[0x18b3d10+i*4] for i in range(len(expected))]==expected
assert [code[0x18b3d40+i*4] for i in range(6)]==['ldr x0, [x20]','ldr x8, [x0]','ldr x8, [x8, #0x20]','mov x1, x20','mov x2, x19','blr x8']
assert [code[0x18b3e14+i*4] for i in range(4)]==['bl #0x4403cd4','add x0, x0, #0x28','str w20, [sp, #8]','str x0, [sp]']
assert [code[0x18b3428+i*4] for i in range(4)]==['ldp x29, x30, [sp, #0x20]','ldp x20, x19, [sp, #0x10]','add sp, sp, #0x30','b #0x18b3450']
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'plugin_sha256':players.SHA256,
         'mapped_fields':mapped,'getter_sha256':hashlib.sha256(raw).hexdigest(),
         'variance_sentinel':100,'sentinel_type':null_type.decode(),'runtime_default_native':10,
         'runtime_default_instructions':runtime,'foreground_ui_used':False,'native_execution':False,
         'limitations':weather.SCOPE}
(ROOT/'evidence/weather-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Verified',len(mapped),'weather fields, editor labels/bounds, native null sentinel and runtime default.')
