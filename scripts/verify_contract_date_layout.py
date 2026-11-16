"""Verify installed date labels, property dispatch, getters and live vtables.

Run with uv run --no-project --with capstone --with zstandard python ...
Only reads installed code/resources and game memory; never calls game functions.
"""
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp import players, staff, world
from fm_live_mcp.bridge import Bridge

bridge = Bridge()
bridge.attach()
try:
    process = bridge.process
    base = bridge._player_layout(process)[0] - players.RVA[0]
    plugin = Path(bridge.plugin_identity[0][0])
    checked = []
    for kind, rva in [('player', players.RVA[2])] + [(k, v[1]) for k, v in staff.LAYOUTS.items()]:
        for slot, getter, adjustment in ((73, 0xCA4764, 0x258), (121, 0xCB3724, 0x3D8)):
            assert players.u64(bridge._read_memory(process, base + rva + slot*8, 8)) == base + getter
            assert struct.unpack('<q', bridge._read_memory(process, base + rva - adjustment, 8))[0] == -0x110
        checked.append(kind)
    for slot, getter in ((29, 0x1005C68), (30, 0x12920F8)):
        assert players.u64(bridge._read_memory(process, base + world.TYPES['full_contract'][0] + slot*8, 8)) == base + getter
finally:
    bridge.detach()

cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
# Getter and property case bodies, established by bounded switch traversal in research.
expected = {
    0xCA4764: ['ldr x8, [x0]', 'sub x8, x8, #0x258', 'ldr x8, [x8]', 'add x8, x0, x8', 'add x0, x8, #0xec', 'ret'],
    0xCB3724: ['ldr x8, [x0]', 'sub x8, x8, #0x3d8', 'ldr x8, [x8]', 'add x8, x0, x8', 'ldr x0, [x8, #0x78]', 'ret'],
    0x1005C68: ['add x0, x0, #0x44', 'ret'],
    0x12920F8: ['ldrb w8, [x0, #0x2b]', 'tbnz w8, #3, #0x1292108', 'ldr w0, [x0, #0x48]', 'ret'],
    0x1292108: ['adrp x8, #0x56b1000', 'add x8, x8, #0xdb8', 'ldr w8, [x8]',
                 'lsr w9, w8, #0x10', 'add w9, w9, #1', 'mov w10, #0x5c29',
                 'mul w10, w9, w10', 'and w10, w10, #0xffff', 'mov w11, #3',
                 'mov w12, #0xf', 'cmp w10, #0xa3e', 'csel w10, w12, w11, lo',
                 'tst w9, w10', 'mov w10, #0x16d', 'cinc w10, w10, eq',
                 'and w11, w8, #0x1ff', 'sub w11, w11, #1', 'and w12, w8, #0xfe00',
                 'orr w12, w10, w12', 'cmp w10, w11', 'csel w0, w12, w8, eq',
                 'bfi w0, w9, #0x10, #0x10', 'ret'],
    0x1495988: ['ldr x8, [x20]', 'ldr x8, [x8, #0x248]', 'mov x0, x20', 'blr x8'],
    0x149719C: ['mov x0, x20', 'mov w1, #0x6461', 'b #0x1497418'],
    0x1497418: ['movk w1, #0x4373, lsl #16', 'b #0x1498a20'],
    0x1495640: ['mov x0, x20', 'mov w1, #0x6461', 'movk w1, #0x4365, lsl #16', 'b #0x1498a20'],
    0xFF664C: ['ldr x8, [x20]', 'ldr x8, [x8, #0xf0]', 'mov x0, x20', 'blr x8'],
    0xFF68F8: ['ldr x8, [x20]', 'ldr x8, [x8, #0xe8]', 'mov x0, x20', 'blr x8', 'ldr w20, [x0]'],
}
with plugin.open('rb') as stream:
    for rva, instructions in expected.items():
        stream.seek(0x5ED4000 + rva)
        actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(len(instructions)*4), rva)]
        assert actual == instructions, (hex(rva), actual)

wanted = {'Pcjd': 'Date Joined', 'Pcsd': 'Date Last Contract Signed', 'Pcex': 'Contract Expires'}
archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
found = {}
for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
    try:
        raw = zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000)
        root = ET.fromstring(raw)
    except (zstandard.ZstdError, ET.ParseError):
        continue
    for row in root.iter('record'):
        values = {c.get('id'): c.get('value') for c in row if c.get('id')}
        field = values.get('field')
        if field in wanted and 'name' in values:
            found[field] = values['name'].split('[COMMENT')[0].strip()
assert found == wanted, found
receipt = {'verified': True, 'plugin_sha256': players.SHA256, 'person_layouts': checked,
           'labels': found, 'instruction_blocks': [hex(rva) for rva in expected],
           'dynamic_expiry': 'complete native calculation checked; live dynamic record not observed'}
Path('evidence/contract-date-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
