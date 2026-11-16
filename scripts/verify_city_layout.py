"""Verify city fields and geographic identities without executing native getters."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))
from verify_player_profile_layout import property_case
from fm_live_mcp import cities,database,geography,players,world
from fm_live_mcp.bridge import Bridge

EXPECTED_SHA = players.SHA256
FIELDS = {
    'Cnam': ('Name', 0xDD54F4, ['mov x20, x0', 'bl #0x4403cd4', 'ldr x8, [x20, #0x18]']),
    'Cnti': ('Nation', 0xDD5864, ['ldr x9, [x0, #0x20]', 'cbz x9, #0xdd58e8', 'ldp w8, w9, [x9, #0xc]']),
    'Clat': ('Latitude', 0xDD5720, ['ldr s8, [x0, #0x48]']),
    'Clon': ('Longitude', 0xDD5808, ['ldr s8, [x0, #0x4c]']),
    'Calt': ('Altitude', 0xDD56C4, ['ldrsh w20, [x0, #0x50]']),
    'Cinh': ('Inhabitants Range', 0xDD57AC, ['ldrsb w20, [x0, #0x52]']),
    'Catt': ('Attraction', 0xDD5668, ['ldrsb w20, [x0, #0x54]']),
    'Clgi': ('Language', 0xDD55A0, ['ldr x9, [x0, #0x30]', 'cbz x9, #0xdd58cc', 'ldp w8, w9, [x9, #0xc]']),
    'Clri': ('Local Region', 0xDD577C, ['ldr x9, [x0, #0x38]', 'cbz x9, #0xdd5894', 'ldp w8, w9, [x9, #0xc]']),
    'Cwea': ('Weather', 0xDD5794, ['ldr x9, [x0, #0x28]', 'cbz x9, #0xdd58b0', 'ldp w8, w9, [x9, #0xc]']),
}


def verify():
    bridge=Bridge();sid=bridge.attach()['session_id']
    try:
        with bridge.lock,bridge._read_scope(sid):
            bridge._player_layout(bridge._current(sid))
            plugin=Path(bridge.plugin_identity[0][0])
    finally:bridge.detach()
    with plugin.open('rb') as source:
        assert hashlib.file_digest(source, 'sha256').hexdigest() == EXPECTED_SHA
        def read(rva, size):
            source.seek(0x5ED4000 + rva)
            data = source.read(size)
            assert len(data) == size
            return data
        def pointer(rva):
            return int.from_bytes(read(rva, 8), 'little') & 0xFFFFFFFF
        types=[world.TYPES[k] for k in ('city','language','local_region','weather')]
        types += [(database.TABLES[k][1],database.TABLES[k][2]) for k in ('cities','languages','local_regions','weather')]
        for vt, name in types:
            assert int.from_bytes(read(vt - 16, 8), 'little', signed=True) == 0
            assert read(pointer(pointer(vt - 8) + 8), len(name) + 1) == name + b'\0'
        assert pointer(world.TYPES['city'][0] + 24) == cities.PROPERTY_GETTER == 0xDD548C
        cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
        code = {i.address: f'{i.mnemonic} {i.op_str}'.strip()
                for i in cs.disasm(read(0xDD548C, 0x4CC), 0xDD548C)}
        spans = []
        for prop, (label, case, instructions) in FIELDS.items():
            assert property_case(code, prop, 0xDD54A4, 'w1') == case, prop
            assert [code[case + n * 4] for n in range(len(instructions))] == instructions, prop
            spans.append({'property': prop, 'rva': hex(case),
                          'sha256': hashlib.sha256(read(case, len(instructions) * 4)).hexdigest()})
        assert property_case(code,'DELE',0xDD54A4,'w1')==0xDD55E8
        assert [code[0xDD55E8+n*4] for n in range(2)]==['ldrb w8, [x0, #0x55]','and w20, w8, #1']
        spans.append({'property':'DELE','rva':'0xdd55e8','sha256':hashlib.sha256(read(0xDD55E8,8)).hexdigest()})
        for kind,getter,size,dispatch,prop,case,instructions in (
            ('language',0x1369C14,0x5B8,0x1369C30,'Lnam',0x1369F44,['bl #0x4403cd4','ldr x8, [x20, #0x18]']),
            ('local_region',0x137A600,0x774,0x137A620,'Lnam',0x137A6EC,['bl #0x4403cd4','ldr x8, [x20, #0x18]']),
            ('weather',0x18B2768,0xCE8,0x18B2778,'wnam',0x18B2E4C,['mov x19, x2','mov x20, x0','bl #0x4403cd4','ldr x8, [x20, #0x18]'])):
            assert pointer(world.TYPES[kind][0]+24)==geography.FIELDS[kind][0]==getter
            linked={i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(read(getter,size),getter)}
            assert property_case(linked,prop,dispatch,'w1')==case
            assert [linked[case+n*4] for n in range(len(instructions))]==instructions
            spans.append({'kind':kind,'property':prop,'rva':hex(case),'sha256':hashlib.sha256(read(case,len(instructions)*4)).hexdigest()})
    archive = (plugin.parent.parent / 'Resources/shared/data/editor.fmf').read_bytes()
    definitions = {}
    for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')), archive):
        try:
            tree = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10000000))
        except (zstandard.ZstdError, ET.ParseError):
            continue
        for row in tree.iter('record'):
            field = row.find("flags[@id='field']")
            if field is None or field.get('value') not in FIELDS:
                continue
            prop = field.get('value')
            names = [e.get('value', '').split('[COMMENT')[0] for e in row if e.get('id') == 'name']
            if FIELDS[prop][0] not in names:
                continue
            kind = row.find("flags[@id='type']")
            if kind is None:
                continue
            enum = {int(value.get('enum')): value.find("translation[@id='name']").get('value').split('[COMMENT')[0]
                    for value in row.findall("list[@id='enum_values']/record")}
            definition = {'label': FIELDS[prop][0], 'type': kind.get('value'), 'enum_values': enum}
            for bound in ('min_value', 'max_value'):
                value = next((e.get('value') for e in row if e.get('id') == bound), None)
                if value is not None:
                    definition[bound] = value
            if prop not in definitions or enum:
                definitions[prop] = definition
    assert set(definitions) == set(FIELDS), set(FIELDS) - set(definitions)
    assert definitions['Calt']['type'] == 'integer'
    assert definitions['Calt']['min_value'] == '-1000' and definitions['Calt']['max_value'] == '8000'
    population = definitions['Cinh']['enum_values']
    assert set(population) == set(range(16))
    assert population[0] == 'Not Set' and population[15] == '20000001 +'
    assert population==cities.POPULATION_RANGES
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': EXPECTED_SHA, 'native_spans': spans, 'editor_definitions': definitions,
               'altitude_unit': None, 'foreground_ui_used': False, 'native_execution': False,
               'scope': 'City stored fields, DELE flag, population categories and linked geographic identities/names. Altitude unit and broader linked-record fields remain unverified.'}
    (ROOT / 'evidence/city-layout-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Verified {len(spans)} city field spans and {len(definitions)} editor definitions; altitude unit remains unverified.')


if __name__ == '__main__':
    verify()
