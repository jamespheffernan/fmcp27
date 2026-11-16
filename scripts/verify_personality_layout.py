"""Verify personality labels, property dispatch and all live native getter layouts.

Run with uv run --no-project --with capstone --with zstandard python ...
Reads installed code/resources and memory; never executes native game functions.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import personality, players, staff, virtual, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            base = bridge._player_layout(bridge.process)[0] - players.RVA[0]
            plugin = Path(bridge.plugin_identity[0][0])
            snapshot = world.ReadSet(lambda a, n: bridge._read_memory(bridge.process, a, n))
            layouts = {'player': players.RVA[2], **{kind: fields[1] for kind, fields in staff.LAYOUTS.items()}}
            for table in layouts.values(): personality.verify_getters(snapshot, base, base + table)
            personality.verify_getters(snapshot, base, base + virtual.PERSON_RVA, virtual=True)
            # Cached virtual pressure delegates through the regular PERSON_DATA base.
            assert struct.unpack('<q', snapshot(base + players.RVA[0] - 32, 8))[0] == 0x278
            assert players.u64(snapshot(base + 0x5589A90 + 75*8, 8)) == base + 0xCF61D4
            snapshot.verify()
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    rows = []
    with plugin.open('rb') as stream:
        def code(rva, length):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(length), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected)*4).values())
            assert actual == expected, (hex(rva), actual, expected)
        getter = code(0x148F9B8, 0xA000)
        for name, (offset, slot, rva, prop) in personality.FIELDS.items():
            entry = property_case(getter, prop, 0x148FCC4, 'w21')
            check(entry, ['ldr x8, [x20]', f'ldr x8, [x8, #{slot*8:#x}]', 'mov x0, x20', 'blr x8'])
            check(rva, ['ldr x8, [x0]', f'sub x8, x8, #{slot*8+16:#x}', 'ldr x8, [x8]',
                        'add x8, x0, x8', f'ldrsb w0, [x8, #{offset:#x}]', 'ret'])
            vrva = personality.VIRTUAL_GETTERS[slot]
            if name == 'controversy':
                check(vrva, ['mov w0, #0', 'ret'])
            else:
                check(vrva + 0x10, ['ldr x8, [x0]', f'sub x8, x8, #{slot*8+16:#x}', 'ldr x20, [x8]',
                                    'bl #0x1dcee4', 'add x1, x19, x20', 'mov w2, #1', 'bl #0x18a0ed0'])
                tail = ['ldr x8, [x0]', 'ldur x8, [x8, #-0x20]']
                if name == 'pressure':
                    tail += ['ldr x9, [x0, x8]', 'ldr x1, [x9, #0x258]', 'add x0, x0, x8',
                             'ldp x29, x30, [sp, #0x10]', 'ldp x20, x19, [sp], #0x20', 'br x1']
                    check(0xCF61D4, ['ldrsb w0, [x0, #0x43]', 'ret'])
                else: tail += ['add x8, x0, x8', f'ldrsb w0, [x8, #{offset:#x}]']
                check(vrva + 0x2C, tail)
            rows.append({'name': name, 'property': prop, 'person_slot': slot, 'property_case': hex(entry),
                         'getter': hex(rva), 'person_data_offset': hex(offset), 'virtual_getter': hex(vrva),
                         'virtual_source': 'constant_zero' if name == 'controversy' else 'existing_cached_profile'})
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    labels = {}
    wanted = {v[3]: name for name, v in personality.FIELDS.items()}
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try:
            raw = zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000)
            root = ET.fromstring(raw)
        except (ET.ParseError, zstandard.ZstdError): continue
        for row in root.iter('record'):
            values = {c.get('id'): c.get('value') for c in row if c.get('id')}
            prop = values.get('field')
            if prop in wanted and values.get('type') == 'integer':
                assert values['min_value'] == '0' and values['max_value'] == '20'
                assert values['name'].casefold() == wanted[prop]
                labels[prop] = values['name']
    assert set(labels) == set(wanted)
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'labels': labels, 'person_layouts': layouts,
               'fields': rows, 'scope': 'Native signed direct 0–20 values, virtual cache delegates and fixed controversy zero; no UI comparison.'}
    path = ROOT/'evidence/personality-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified {len(rows)} personality fields across four regular layouts and virtual delegates. {path}')


if __name__ == '__main__': verify()
