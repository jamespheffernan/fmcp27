"""Prove competition context properties, enums and linked geography by read-only inspection."""
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
from fm_live_mcp import competitions, database, geography, players, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    geographic_rows = {}
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge.process
            tables = bridge._player_layout(process)
            base = tables[0] - players.RVA[0]
            plugin = Path(bridge.plugin_identity[0][0])
            read, _, _ = bridge._world_state(process, tables)
            for kind in ('nation', 'continent'):
                info = database.table(read, base, geography.FIELDS[kind][1])
                geographic_rows[kind] = [geography.record(read, base,
                    world.pointer(read, info['start'] + index * 8), kind) for index in range(info['count'])]
                assert len({r['native_id'] for r in geographic_rows[kind]}) == info['count']
            read.verify()
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva, size):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected) * 4).values())
            assert actual == expected, (hex(rva), actual, expected)
        comp = code(0xEFD3B8, 0x9000)
        cases = {'cnti': 0xF0230C, 'ccti': 0xEFE9AC, 'cpcm': 0xF013F8,
                 'crep': 0xEFF880, 'cext': 0xF02C08, 'dbty': 0xF02484,
                 'levl': 0xF01390, 'PLgn': 0xEFE354}
        for prop, target in cases.items():
            assert property_case(comp, prop, 0xEFD4B8, 'w21') == target
        for start, offset, null_target, finish in (
            (0xF0230C, 0x60, 0xF041CC, 0xF041D4),
            (0xEFE9AC, 0x58, 0xF042CC, 0xF042D4),
            (0xF013F8, 0x68, 0xF03CFC, 0xF03D04),
        ):
            check(start, [f'ldr x9, [x20, #{offset:#x}]', f'cbz x9, #{null_target:#x}',
                'ldp w8, w9, [x9, #0xc]', 'cmp w9, #0', 'csel w9, w8, w9, eq', f'b #{finish:#x}'])
            check(null_target, ['mov w8, #-1', 'mov w9, #-1'])
        check(0xEFF880, ['ldrsh w20, [x20, #0x188]', 'bl #0x4403cd4',
                         'add x0, x0, #0x28', 'str w20, [sp, #0x68]'])
        check(0xF02C08, ['ldrb w20, [x20, #0x1a9]', 'bl #0x4403cd4',
                         'add x0, x0, #0x18', 'ubfx w8, w20, #2, #1'])
        check(0xF02484, ['ldrsb w20, [x20, #0xf8]', 'cmn w20, #1', 'b.eq #0xf0362c'])
        check(0xF01390, ['ldrsb w8, [x20, #0x1aa]', 'cmp w8, #0x64',
                         'b.eq #0xf0362c', 'add w20, w8, #1'])
        check(0xEFE354, ['ldrb w20, [x20, #0xf9]', 'bl #0x4403cd4',
                         'add x0, x0, #0x28', 'str w20, [sp, #0x68]'])
        # Stored geography strings, distinct from the formatted Nnam path.
        nat = code(0x13B1D14, 0x165C)
        for prop, target, offset in (('Nsnm', 0x13B28A0, 0x20), ('N3ln', 0x13B240C, 0x28)):
            assert property_case(nat, prop, 0x13B1D40, 'w1') == target
            check(target, ['bl #0x4403cd4', f'ldr x8, [x20, #{offset:#x}]'])
        assert property_case(nat, 'Nnam', 0x13B1D40, 'w1') == 0x13B1F4C
        check(0x13B1FB0, ['mov x0, x21', 'mov w2, #0', 'mov w3, #0', 'mov w4, #0', 'bl #0x43cd17c'])
        cont = code(0xFE05C0, 0x11CC)
        for prop, target, offset in (('Cnam', 0xFE0C8C, 0x18), ('C3ln', 0xFE0C24, 0x20)):
            assert property_case(cont, prop, 0xFE0628, 'w21') == target
            check(target, ['bl #0x4403cd4', f'ldr x8, [x20, #{offset:#x}]'])
        archive = (plugin.parent.parent / 'Resources/shared/data/editor.fmf').read_bytes()
        fields, enum = None, None
        for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')), archive):
            try:
                root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
            except (zstandard.ZstdError, ET.ParseError):
                continue
            props = {r.find("flags[@id='field']").get('value'): r for r in root.iter('record')
                     if r.find("flags[@id='field']") is not None}
            if set(cases) <= props.keys():
                fields = props
            found = root.find(".//record[@id='cdbt']")
            if found is not None:
                enum = found
        assert fields is not None and enum is not None
        labels = {'cnti': 'Nation', 'ccti': 'Continent', 'cpcm': 'Parent Competition',
                  'crep': 'Reputation', 'cext': 'Is Extinct', 'dbty': 'Type',
                  'levl': 'Competition Level', 'PLgn': 'Player Gender'}
        for prop, label in labels.items():
            assert fields[prop].find("translation[@id='name']").get('value').split('[COMMENT')[0] == label
        assert fields['dbty'].find("flags[@id='enum_values']").get('value') == 'cdbt'
        enum_labels = {int(r.get('enum')): r.find("translation[@id='name']").get('value').split('[COMMENT')[0]
                       for r in enum.find("list[@id='enum_values']")}
        assert competitions.COMPETITION_TYPES == enum_labels
        genders = {int(r.get('enum_id')): r.find("translation[@id='name']").get('value').split('[COMMENT')[0]
                   for r in fields['PLgn'].find("list[@id='enum_values']")}
        assert competitions.GENDERS == genders
        hashes = {}
        for rva, size in ((0xEFD3B8, 0x9000), (0x13B1D14, 0x165C), (0xFE05C0, 0x11CC)):
            stream.seek(0x5ED4000 + rva)
            hashes[hex(rva)] = hashlib.sha256(stream.read(size)).hexdigest()
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'native_code_sha256': hashes,
               'competition_type_labels': enum_labels, 'gender_labels': genders,
               'geography': geographic_rows, 'foreground_ui_used': False,
               'scope': 'Native COMP properties, installed editor labels/enums, geography property getters and complete typed nation/continent membership. No native execution, current activity or UI comparison.'}
    (ROOT / 'evidence/competition-context-layout-verification.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(f'Verified eight competition context properties, {len(enum_labels)} type labels, '
          f'{len(geographic_rows["nation"])} nations and {len(geographic_rows["continent"])} continents.')


if __name__ == '__main__':
    verify()
