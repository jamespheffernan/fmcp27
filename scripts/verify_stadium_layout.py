"""Verify stored stadium fields without executing game getters or UI code."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import players, stadiums
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case

# Native property names and raw read cases; context-dependent cases are separate.
FIELDS = {
    'Snam': ('Name', 0x16CA7D4, ['bl #0x4403cd4','ldr x8, [x20, #0x40]']),
    'Scnm': ('Continental Name', 0x16C8D9C, ['bl #0x4403cd4','ldr x8, [x20, #0x48]']),
    'Scpy': ('Capacity', 0x16CA57C, ['ldr w20, [x20, #0x7c]']),
    'Sscy': ('Seating Capacity', 0x16CA0A0, ['ldr w20, [x20, #0x80]']),
    'Secy': ('Expansion Capacity', 0x16C96D4, ['ldr w20, [x20, #0x8c]']),
    'Sucy': ('Used Capacity', 0x16CA1BC, ['ldr w20, [x20, #0x84]','cmp w20, #1','b.lt #0x16ca734']),
    'Scas': ('Capacity For All-Seater Competitions', 0x16CA4BC, ['ldr w20, [x20, #0x88]','cmp w20, #0','b.le #0x16ca734']),
    'Slat': ('Latitude', 0x16CA520, ['ldr s8, [x20, #0x70]']),
    'Slon': ('Longitude', 0x16C8F50, ['ldr s8, [x20, #0x74]']),
    'SsfT': ('Pitch Type', 0x16CA220, ['ldrsb w20, [x20, #0xad]']),
    'Spty': ('Pitch Type', 0x16C9EF4, ['ldrb w8, [x20, #0xad]','cmp w8, #1','csinc w20, w8, wzr, hi']),
    'Sptc': ('Pitch Condition', 0x16C9304, ['ldrsh w20, [x20, #0xa8]']),
    'Sdtr': ('Pitch Deterioration Rate', 0x16CA460, ['ldrsb w20, [x20, #0xac]']),
    'Sprr': ('Pitch Recovery Rate', 0x16C9E98, ['ldrsb w20, [x20, #0xae]']),
    'Sdcy': ('Decay', 0x16C9BC0, ['ldrsb w20, [x20, #0xaa]']),
    'Sste': ('State', 0x16C99D8, ['ldrsb w20, [x20, #0xaf]']),
    'Senv': ('Environment', 0x16CA89C, ['ldrsb w20, [x20, #0xb0]']),
    'Soty': ('Owner Type', 0x16C9088, ['ldrsb w20, [x20, #0xb4]','cbz w20, #0x16ca734']),
    'Sunt': ('Used By National Team', 0x16C995C, ['ldrsb w20, [x20, #0xb1]']),
    'Su21': ('Used By National U21 Team', 0x16C8FEC, ['ldrsb w20, [x20, #0xb2]']),
    'Su19': ('Used By National U19 Team', 0x16CA044, ['ldrsb w20, [x20, #0xb3]']),
    'Sitg': ('Is Training Ground', 0x16CA96C, ['ldrb w20, [x20, #0xab]','bl #0x4403cd4','add x0, x0, #0x18','ubfx w8, w20, #2, #1']),
    'Sext': ('Extinct', 0x16C9274, ['ldrb w8, [x20, #0xab]','and w20, w8, #1']),
    'Sdah': ('Has Digital Ad Hoarding', 0x16CA774, ['ldrb w20, [x20, #0xab]','bl #0x4403cd4','add x0, x0, #0x18','ubfx w8, w20, #6, #1']),
    'Sush': ('Has Undersoil Heating', 0x16CA0FC, ['ldrb w20, [x20, #0xb6]','bl #0x4403cd4','add x0, x0, #0x18','ubfx w8, w20, #1, #1']),
    'Srrf': ('Retractable Roof', 0x16CA15C, ['ldrb w20, [x20, #0xb6]','bl #0x4403cd4','add x0, x0, #0x18','ubfx w8, w20, #6, #1']),
}


def verify():
    bridge=Bridge(); sid=bridge.attach()['session_id']
    try:
        with bridge.lock,bridge._read_scope(sid):
            bridge._player_layout(bridge._current(sid))
            plugin=Path(bridge.plugin_identity[0][0])
    finally:bridge.detach()
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    checks=[]
    with plugin.open('rb') as stream:
        def read(rva,size):
            stream.seek(0x5ED4000+rva);data=stream.read(size)
            assert len(data)==size
            return data
        def code(rva,size):
            return {i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(read(rva,size),rva)}
        def check(rva,expected):
            actual=list(code(rva,len(expected)*4).values())
            assert actual==expected,(hex(rva),actual,expected)
            checks.append({'rva':hex(rva),'sha256':hashlib.sha256(read(rva,len(expected)*4)).hexdigest()})
        def pointer(rva):return int.from_bytes(read(rva,8),'little') & 0xFFFFFFFF
        for vt,name in ((0x55BD7B0,'N2db7STADIUME'),(0x55A1B20,'N2db14DATABASE_TABLEINS_7STADIUMEEE')):
            assert int.from_bytes(read(vt-16,8),'little',signed=True)==0
            assert read(pointer(pointer(vt-8)+8),len(name)+1)==name.encode()+b'\0'
        assert pointer(0x55BD7B0+24)==0x16C8BC8
        getter=code(0x16C8BC8,0x302C)
        for prop,(label,case,instructions) in FIELDS.items():
            assert property_case(getter,prop,0x16C8C58,'w21')==case,(prop,hex(case))
            check(case,instructions)
        # Fixtures feed their +0x28 stored link to UI column 90 as a database reference.
        check(0x207D9C,['mov w8, #0x2020','movk w8, #0x3930, lsl #16','cmp w22, w8','b.eq #0x20a514'])
        check(0x20A514,['ldr x0, [x20, #0x28]','cbz x0, #0x20af8c','add x8, sp, #0x68','bl #0x11b3d1c'])
        # Existing stadium-reference conversion uses this canonical singleton.
        check(0x11B4FA8,['adrp x8, #0x56d2000','ldr x20, [x8, #0xd98]','mov x0, x1',
                         'mov w1, #0x6164','movk w1, #0x7374, lsl #16','bl #0x11b4874'])
        # Used/all-seater capacity <=0 returns the global empty variant, not total capacity.
        check(0x16CA734,['adrp x20, #0x56d6000','add x20, x20, #0x3c0','cmp x19, x20','b.eq #0x16c8c30'])
        # The raw/default dimensions are separate from context-selected international dimensions.
        for at,offset in ((0x16CA9FC,0x98),(0x16CAA64,0x9A)):
            check(at,[f'ldrsh w8, [x20, #{offset:#x}]','scvtf s0, w8','fmov s1, #10.00000000','fdiv s8, s0, s1'])
        for prop,at,offset in (('SlIM',0x16C9D44,0x9C),('SwIM',0x16C9420,0x9E)):
            assert property_case(getter,prop,0x16C8C58,'w21')==at
            check(at,[f'ldrsh w8, [x20, #{offset:#x}]','cmp w8, #1','b.lt #0x16ca734',
                      'and w8, w8, #0xffff','ucvtf s0, w8','fmov s1, #10.00000000','fdiv s8, s0, s1'])
        for prop,at,offset in (('Smnl',0x16CA6C0,0xA0),('Smnw',0x16C9B2C,0xA2),('Smxl',0x16CA5D8,0xA4),('Smxw',0x16C950C,0xA6)):
            assert property_case(getter,prop,0x16C8C58,'w21')==at
            check(at,[f'ldrsh w8, [x20, #{offset:#x}]','scvtf s0, w8','fmov s1, #10.00000000','fdiv s8, s0, s1',
                      'fmov s0, #-1.00000000','fcmp s8, s0','b.le #0x16ca734'])
        for prop,at,offset in (('Sbld',0x16C9CBC,0x30),('Srbd',0x16C9FDC,0x34),('Sprl',0x16C9750,0x2C)):
            assert property_case(getter,prop,0x16C8C58,'w21')==at
            check(at,['bl #0x42f038c',f'ldrh w8, [x20, #{offset:#x}]',f'ldrh w9, [x20, #{offset+2:#x}]',
                      'lsr w10, w8, #9','orr w9, w10, w9, lsl #17','bfi w9, w8, #8, #9'])
        check(0x16C94C4,['ldr x9, [x20, #0x60]','cbz x9, #0x16cae3c','ldp w8, w9, [x9, #0xc]'])
        check(0x16C98A4,['ldr x9, [x20, #0x90]','cbz x9, #0x16cac20','ldp w8, w9, [x9, #0xc]'])
        check(0x16C9DB8,['ldr x9, [x20, #0x68]','cbz x9, #0x16cae20','ldp w8, w9, [x9, #0xc]'])
        # Covered state also depends on a runtime setting when the roof retracts.
        check(0x16CA64C,['adrp x8, #0x56d4000','ldrb w8, [x8, #0x987]','ldrh w20, [x20, #0xb6]',
                         'cmp w8, #1','b.ne #0x16cabc4','tbz w20, #6, #0x16cabc4'])
        check(0x16CABC4,['bl #0x4403cd4','add x0, x0, #0x18','and w8, w20, #1'])
        # short_distance is type 34. Its formatting switch passes the float
        # unchanged to the metre/yard formatter; yards divide by 0.9144.
        assert read(0x505440E,15) == b'short_distance\0'
        check(0x68473C,['adrp x1, #0x5054000','add x1, x1, #0x40e','add x0, sp, #8',
                         'mov w2, #-1','bl #0x4388ef8'])
        check(0x684798,['add x0, x8, #0x110','add x1, sp, #8','bl #0x438906c'])
        check(0x6698C4,['and w8, w5, #0xff','sub w8, w8, #1','cmp w8, #0x22','b.hi #0x669f64'])
        check(0x6698E0,['adrp x9, #0x52f6000','add x9, x9, #0xa0e','adr x10, #0x6698f8',
                         'ldrh w11, [x9, x8, lsl #1]','add x10, x10, x11, lsl #2','br x10'])
        assert 0x6698F8+4*int.from_bytes(read(0x52F6A0E+33*2,2),'little') == 0x6699D0
        check(0x6699D0,['mov x0, x20','bl #0x4404b18','add x8, sp, #8','mov w0, #1',
                         'mov w1, #0','bl #0x68d994'])
        check(0x68D9B8,['fmov s8, s0'])
        check(0x68DA24,['cmp w23, #1','b.eq #0x68da70','cmp w23, #2','b.ne #0x68dba4'])
        check(0x68DA34,['mov w8, #0x161e','movk w8, #0x3f6a, lsl #16','fmov s0, w8','fdiv s0, s8, s0'])
        assert abs(struct.unpack('<f',struct.pack('<I',0x3F6A161E))[0]-0.9144)<1e-7
        check(0x68DA60,['mov w1, #0xec86','movk w1, #3, lsl #16','bl #0x43db8b8'])
        check(0x68DA70,['fmov s0, #0.50000000','fadd s0, s8, s0','fcvtzs w8, s0','strh w8, [sp, #0x28]'])
        check(0x68DA8C,['mov w1, #0xec85','movk w1, #3, lsl #16','bl #0x43db8b8'])
    archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    definitions={}
    distance_fields=set()
    national_usage={}
    usage_references=set()
    for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
        try:tree=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10000000))
        except (zstandard.ZstdError,ET.ParseError):continue
        for row in tree.iter('record'):
            if row.get('id')=='ubnt':
                national_usage={int(value.get('enum')):value.find("translation[@id='name']").get('value').split('[COMMENT')[0]
                                for value in row.findall("list[@id='enum_values']/record")}
            field=row.find("flags[@id='field']")
            if field is None:continue
            prop=field.get('value')
            enum_ref=row.find("flags[@id='enum_values']")
            if prop in ('Sunt','Su21','Su19') and enum_ref is not None and enum_ref.get('value')=='ubnt':
                usage_references.add(prop)
            kind=row.find("flags[@id='type']")
            if prop in ('Spln','Spwd','SlIM','SwIM','Smnl','Smnw','Smxl','Smxw') and kind is not None and kind.get('value')=='short_distance':
                distance_fields.add(prop)
            if prop not in FIELDS:continue
            names=[e.get('value','').split('[COMMENT')[0] for e in row if e.get('id')=='name']
            if FIELDS[prop][0] not in names:continue
            values={}
            for value in row.findall("list[@id='enum_values']/record"):
                name=value.find("translation[@id='name']")
                if name is not None:values[int(value.get('enum'))]=name.get('value').split('[COMMENT')[0]
            definitions[prop]={'label':FIELDS[prop][0],'enum_values':values}
    assert set(definitions)==set(FIELDS),set(FIELDS)-set(definitions)
    assert definitions['SsfT']['enum_values'][8]=='Grass/Synthetic Mix'
    assert definitions['Senv']['enum_values'][0]=='Not Set'
    assert len(distance_fields)==8
    assert usage_references=={'Sunt','Su21','Su19'}
    assert national_usage==stadiums.NATIONAL_USAGE
    for prop,labels in (('SsfT',stadiums.PITCH_TYPES),('Sdtr',stadiums.DETERIORATION),
                        ('Sste',stadiums.CONDITIONS),('Senv',stadiums.ENVIRONMENTS),('Soty',stadiums.OWNER_TYPES)):
        assert definitions[prop]['enum_values']==labels,(prop,definitions[prop])
    english=(plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
    assert 'KEY-257157: [%number#1]m[COMMENT - distance in metres]' in english
    assert 'KEY-257158: [%number#1]yds[COMMENT - distance in yards]' in english
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'plugin_sha256':players.SHA256,
             'checks':checks,'editor_definitions':definitions,'foreground_ui_used':False,'native_execution':False,
             'dimension_unit':'metres','distance_field_types':sorted(distance_fields),
             'national_usage_labels':national_usage,'national_usage_fields':sorted(usage_references),
             'scope':'Stored stadium fields, metric dimensions and fixture link; computed overrides, full city/owner decoding and live match suitability remain separate'}
    (ROOT/'evidence/stadium-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(f'Verified {len(checks)} native spans and {len(definitions)} editor field labels.')


if __name__=='__main__':verify()
