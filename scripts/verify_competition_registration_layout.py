"""Prove COMP registration-vector fields from native code and installed editor labels."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge=Bridge();sid=bridge.attach()['session_id']
    try:
        with bridge.lock,bridge._read_scope(sid):
            bridge._player_layout(bridge._current(sid))
            plugin=Path(bridge.plugin_identity[0][0])
    finally:bridge.detach()
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva,size):
            stream.seek(0x5ED4000+rva)
            return {i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size),rva)}
        def check(rva,expected):
            actual=list(code(rva,len(expected)*4).values())
            assert actual==expected,(hex(rva),actual,expected)
        comp=code(0xEFD3B8,0x9000)
        assert property_case(comp,'crgt',0xEFD4B8,'w21')==0xF02C68
        check(0xF02C98,['ldp x23, x22, [x20, #0x18]','sub x8, x22, x23','asr x21, x8, #3'])
        check(0xF02CBC,['ldr x8, [x20, #0x18]','ldr x22, [x8, x23, lsl #3]','cbz x22, #0xf02d00'])
        check(0xF02CD4,['add x1, sp, #0x48','mov x0, x22','bl #0xf12c30'])
        check(0xF12D18,['mov x2, sp','mov x0, x20','mov x1, x21','bl #0x3b90bd8'])
        props=code(0x3B90BD8,0x230)
        cases={'Ttea':0x3B90CFC,'nati':0x3B90D14,'year':0x3B90CA4,'info':0x3B90C20}
        for prop,target in cases.items():assert property_case(props,prop,0x3B90BF0,'w1')==target
        check(0x3B90CFC,['ldr x9, [x8]','cbz x9, #0x3b90d6c','ldp w8, w9, [x9, #0xc]',
                          'cmp w9, #0','csel w9, w8, w9, eq','b #0x3b90d74'])
        check(0x3B90CA4,['ldrh w20, [x8, #8]','cbz w20, #0x3b90cb8','mov w8, #0xffff',
                          'cmp w20, w8','b.ne #0x3b90d9c'])
        check(0x3B90C20,['ldrsb w20, [x8, #0xa]','tbnz w20, #0x1f, #0x3b90cb8'])
        check(0x3B90D14,['ldr x9, [x8]','cbz x9, #0x3b90d50','ldr x8, [x9, #0x30]',
                          'cbz x8, #0x3b90d50','ldrb w9, [x9, #0x2f]','cmp w9, #0',
                          'mov w9, #0x170','mov w10, #0xd8','csel x9, x10, x9, eq',
                          'ldr x9, [x8, x9]','cbz x9, #0x3b90d50'])
        hashes={}
        for rva,size in ((0xF02C68,0xE8),(0xF12C30,0x2D0),(0x3B90BD8,0x230)):
            stream.seek(0x5ED4000+rva);hashes[hex(rva)]=hashlib.sha256(stream.read(size)).hexdigest()
    archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes();editor=None
    for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
        try:root=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
        except (zstandard.ZstdError,ET.ParseError):continue
        for item in root.iter('record'):
            field=item.find("flags[@id='field']")
            if field is not None and field.get('value')=='crgt':editor=item;break
        if editor is not None:break
    assert editor is not None
    assert editor.find("translation[@id='name']").get('value')=='Registered Teams'
    hint=editor.find("translation[@id='hint']").get('value')
    assert 'a number to identify their registration by (Info)' in hint
    fields={r.find("flags[@id='field']").get('value'):r for r in editor.findall("record[@id='list_item']/list[@id='fields']/record")}
    assert set(fields)==set(cases)
    for prop,label in (('Ttea','Team'),('nati','Nation'),('year','Year'),('info','Info')):
        assert fields[prop].find("translation[@id='name']").get('value')==label
        assert fields[prop].find("boolean[@id='is_optional']").get('value')=='true'
    assert fields['nati'].find("boolean[@id='is_read_only']").get('value')=='true'
    for prop,minimum,maximum in (('year',1900,2100),('info',0,127)):
        assert int(fields[prop].find("integer[@id='min_value']").get('value'))==minimum
        assert int(fields[prop].find("integer[@id='max_value']").get('value'))==maximum
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),
        'plugin_sha256':players.SHA256,'native_code_sha256':hashes,'editor_label':'Registered Teams','info_meaning':'registration identifier',
        'year_sentinels':[0,65535],'info_unset_condition':'negative signed byte',
        'foreground_ui_used':False,'native_execution':False,
        'scope':'Stored registration vector, team/nation links, year and identifier properties; no current participation inference'}
    (ROOT/'evidence/competition-registration-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps(receipt,indent=2))


if __name__=='__main__':verify()
