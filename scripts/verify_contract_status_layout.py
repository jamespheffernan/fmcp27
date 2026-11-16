"""Verify current-contract status semantics from installed resources and native code.

Run with uv run --no-project --with capstone --with zstandard python ...
Reads code/data only; never calls game functions or interacts with the UI.
"""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp import contract_status, players, world
from fm_live_mcp.bridge import Bridge

bridge = Bridge()
sid = bridge.attach()['session_id']
try:
    with bridge.lock, bridge._read_scope(sid):
        process = bridge.process
        base = bridge._player_layout(process)[0] - players.RVA[0]
        plugin = Path(bridge.plugin_identity[0][0])
        snapshot = world.ReadSet(lambda a, n: bridge._read_memory(process, a, n))
        assert players.u64(snapshot(base + world.TYPES['full_contract'][0] + 27*8, 8)) == base + 0x127BE34
        assert players.u64(snapshot(base + world.TYPES['basic_contract'][0] + 3*8, 8)) == base + 0xD8BAB4
        snapshot.verify()
finally:
    bridge.detach()

expected = {
    0x1492F84: ['mov w8, #0x7374', 'movk w8, #0x5063, lsl #16', 'cmp w21, w8', 'b.eq #0x1497410'],
    0x1497410: ['mov x0, x20', 'mov w1, #0x7473', 'movk w1, #0x4373, lsl #16', 'b #0x1498a20'],
    0x14A0798: ['mov w8, #0x7473', 'movk w8, #0x4373, lsl #16', 'cmp w20, w8', 'b.eq #0x14a07f0'],
    0x14A0B28: ['ldr x8, [x21]', 'ldr x8, [x8, #0x18]', 'mov x0, x21', 'mov x1, x20', 'mov x2, x19', 'blr x8'],
    0xFF6D98: ['mov w8, #0x7473', 'movk w8, #0x4373, lsl #16', 'cmp w1, w8', 'b.ne #0xff770c',
               'ldr x8, [x20]', 'ldr x8, [x8, #0xd8]', 'mov x0, x20', 'blr x8'],
    0x127BE34: ['ldrsb w0, [x0, #0xc3]', 'ret'],
    0xD8BDA4: ['mov w9, #0x7473', 'movk w9, #0x4373, lsl #16', 'cmp w1, w9', 'b.eq #0xd8bf28'],
    0xD8BF28: ['bl #0x4403cd4', 'add x0, x0, #0x28', 'mov w8, #-1', 'str w8, [sp, #0x10]'],
}
cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
with plugin.open('rb') as stream:
    for rva, instructions in expected.items():
        stream.seek(0x5ED4000 + rva)
        actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(len(instructions)*4), rva)]
        assert actual == instructions, (hex(rva), actual)

archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
found = []
for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
    try:
        root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
    except (zstandard.ZstdError, ET.ParseError):
        continue
    for row in root.iter('record'):
        values = {c.get('id'): c.get('value') for c in row if c.get('id')}
        if values.get('field') != 'Pcst' or values.get('type') != 'enum':
            continue
        assert values['name'] == 'Contract Status'
        enums = row.find("list[@id='enum_values']")
        labels = {int(e.get('enum')): e.find("translation[@id='name']").get('value').split('[COMMENT')[0].strip() for e in enums}
        assert labels == contract_status.LABELS
        found.append(labels)
assert found
receipt = {'verified': True, 'plugin_sha256': players.SHA256, 'labels': found[0],
           'instruction_blocks': [hex(rva) for rva in expected],
           'scope': 'Native current-contract Pcst/Csts status; Pces specialized contract type is distinct.'}
Path('evidence/contract-status-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
