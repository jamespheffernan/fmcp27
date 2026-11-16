"""Verify native language/region fields, reverse city links and installed editor definitions."""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib,re,xml.etree.ElementTree as ET
import zstandard
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'scripts'))
from fm_live_mcp import players,languages,geography,world,database
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case
bridge=Bridge();sid=bridge.attach()['session_id']
try:
    with bridge.lock,bridge._read_scope(sid):
        bridge._player_layout(bridge._current(sid))
        plugin=Path(bridge.plugin_identity[0][0])
finally:bridge.detach()
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);spans=[]
with plugin.open('rb') as f:
    assert hashlib.file_digest(f,'sha256').hexdigest()==players.SHA256
    def read(rva,size):f.seek(0x5ed4000+rva);return f.read(size)
    def pointer(rva):return int.from_bytes(read(rva,8),'little')&0xFFFFFFFF
    for kind,table_kind in (('language','languages'),('local_region','local_regions')):
        for vt,name in (world.TYPES[kind],(database.TABLES[table_kind][1],database.TABLES[table_kind][2])):
            assert int.from_bytes(read(vt-16,8),'little',signed=True)==0
            assert read(pointer(pointer(vt-8)+8),len(name)+1)==name+b'\0'
        assert pointer(world.TYPES[kind][0]+24)==geography.FIELDS[kind][0]
    def span(at,expected,label):
        raw=read(at,4*len(expected));actual=[f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw,at)]
        assert actual==expected,(label,actual,expected)
        spans.append({'label':label,'rva':hex(at),'instructions':expected,'sha256':hashlib.sha256(raw).hexdigest()})
    for kind,getter,size,start,fields in (
        ('language',0x1369c14,0x5b8,0x1369c30,{
            'Lnam':(0x1369f44,['bl #0x4403cd4','ldr x8, [x20, #0x18]']),
            'Lnat':(0x1369ec8,['ldr x9, [x20, #0x28]']),
            'Lfam':(0x1369fac,['ldrsh w20, [x20, #0x34]']),
            'Lgro':(0x136a064,['ldrsh w20, [x20, #0x36]']),
            'Lsub':(0x136a008,['ldrsh w20, [x20, #0x38]']),
            'Linf':(0x1369c80,['ldrsb w20, [x20, #0x3b]']),
            'Ldff':(0x1369e4c,['ldrsb w20, [x20, #0x3c]']),
            'DELE':(0x1369ee0,['ldrsh w8, [x20, #0x34]','cmn w8, #1','cset w20, eq'])}),
        ('local_region',0x137a600,0x774,0x137a620,{
            'Lnam':(0x137a6ec,['bl #0x4403cd4','ldr x8, [x20, #0x18]']),
            'Lnat':(0x137a820,['ldr x9, [x20, #0x48]']),
            'Lwea':(0x137a774,['ldr x9, [x20, #0x50]']),
            'Lpop':(0x137a660,['ldr w20, [x20, #0x58]']),
            'Lcit':(0x137a78c,['mov x0, sp','mov x1, x20','bl #0x137d530']),
            'Lrll':(0x137a838,['stp xzr, xzr, [sp, #0x48]','str xzr, [sp, #0x58]'])})):
        code={i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(read(getter,size),getter)}
        for prop,(case,instructions) in fields.items():
            assert property_case(code,prop,start,'w1')==case,(kind,prop)
            span(case,instructions,f'{kind}.{prop}')
    span(0x137a868,['ldp x23, x22, [x20, #0x30]','sub x8, x22, x23','asr x21, x8, #4'],'region.language_vector_stride')
    span(0x137a8a8,['add x0, x23, x22','add x1, sp, #0x18','bl #0x137c4a8'],'region.language_entry_conversion')
    span(0x137c5cc,['mov w25, #0x6770','movk w25, #0x4c6c, lsl #16','mov w26, #0x676c','movk w26, #0x4c6c, lsl #16'],'region.entry_property_ids')
    span(0x137c60c,['cmp w21, w25','b.eq #0x137c634','cmp w21, w26','b.ne #0x137c6b4','ldr x9, [x20]'],'region.entry_language_pointer')
    span(0x137c634,['ldrsb w27, [x20, #8]'],'region.entry_percentage')
    span(0x137d57c,['adrp x8, #0x56d2000','ldr x8, [x8, #0xd20]','ldr x8, [x8, #0x88]','ldp x21, x22, [x8]'],'region.reverse_city_table')
    span(0x137d59c,['ldr x8, [x21]','str x8, [sp, #8]','ldr x8, [x8, #0x38]','cmp x8, x20','b.ne #0x137d590'],'region.reverse_city_membership')
archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes();defs=[];enums={}
fields={'Lfam','Lgro','Lsub','Ldff','Linf','Lrll','Lpop'}
for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
    try:root=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
    except(zstandard.ZstdError,ET.ParseError):continue
    for row in root.iter('record'):
        field=row.find("flags[@id='field']")
        if field is None or field.get('value') not in fields:continue
        prop=field.get('value');defs.append({'field':prop,'xml':ET.tostring(row,encoding='unicode')})
        if prop in ('Lfam','Lgro','Lsub'):
            enums[prop]={int(e.get('enum')):next(n for n in e if n.get('id')=='name').get('value').split('[COMMENT')[0]
                         for e in row.findall("list[@id='enum_values']/record")}
assert enums=={'Lfam':languages.FAMILIES,'Lgro':languages.GROUPS,'Lsub':languages.SUBGROUPS}
assert {k:len(v) for k,v in enums.items()}=={'Lfam':109,'Lgro':22,'Lsub':24}
for prop in ('Linf','Ldff','Lpop'):
    row=ET.fromstring(next(r['xml'] for r in defs if r['field']==prop))
    assert row.find("integer[@id='min_value']").get('value')=='0'
    assert row.find("integer[@id='max_value']").get('value')==('1000000000' if prop=='Lpop' else '20')
row=ET.fromstring(next(r['xml'] for r in defs if r['field']=='Lrll'))
entries=row.findall("record[@id='list_item']/list[@id='fields']/record")
assert [r.find("flags[@id='field']").get('value') for r in entries]==['Llgl','Llgp']
assert entries[0].find("flags[@id='database_table_type']").get('value')=='language'
assert entries[1].find("integer[@id='max_value']").get('value')=='100'
receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'plugin_sha256':players.SHA256,
    'native_spans':spans,'language_enums':enums,'foreground_ui_used':False,'native_execution':False,
    'limitations':'Local-region deletion and population freshness are not established; percentages must not be normalized; unknown classification codes remain unmapped.'}
(ROOT/'evidence/language-region-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
print('Verified',len(spans),'native spans, language enums, rating/population bounds and nested language-entry definitions.')
