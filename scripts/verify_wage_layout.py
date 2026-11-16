"""Verify native weekly cash units, currency basis and getter dispatch without game calls.

Run with uv run --no-project --with capstone --with zstandard python ...
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
from fm_live_mcp import database, players, world, wages
from fm_live_mcp.bridge import Bridge

bridge = Bridge()
sid = bridge.attach()['session_id']
try:
    with bridge.lock, bridge._read_scope(sid):
        process = bridge.process
        base = bridge._player_layout(process)[0] - players.RVA[0]
        plugin = Path(bridge.plugin_identity[0][0])
        snapshot = world.ReadSet(lambda a, n: bridge._read_memory(process, a, n))
        assert wages.base_currency(snapshot, base) == 'GBP'
        info = database.table(snapshot, base, 'currencies')
        for kind in ('full_contract', 'basic_contract'):
            assert players.u64(snapshot(base + world.TYPES[kind][0] + 9*8, 8)) == base + 0xD8C3C0
        assert players.u64(snapshot(base + 0x5692CC0 + 11*8, 8)) == base + 0x42CC2C4
        # Base enum slot's live formatter rate is unity as well as the database rate.
        assert struct.unpack('<d', snapshot(base + 0x56C0868, 8))[0] == 1.0
        snapshot.verify()
finally:
    bridge.detach()

expected = {
    0xD8C3C0: ['ldr w0, [x0, #0x20]', 'ret'],
    0xD8BC88: ['ldr x9, [x8]', 'ldr x9, [x9, #0x48]', 'mov x0, x8', 'blr x9', 'mov x20, x0'],
    0x1498964: ['mov x0, x20', 'mov w1, #0x7761', 'movk w1, #0x4377, lsl #16', 'b #0x1498a20'],
    # Currency enum maps directly to the installed database identity table.
    0x1010AC0: ['cmp w0, #0x41', 'b.hi #0x1010ad8', 'adrp x8, #0x538e000',
                 'add x8, x8, #0xf50', 'ldr w0, [x8, w0, sxtw #2]', 'ret'],
    # Integer cash constructor keeps the input as whole units; cents start at zero.
    0x42CA68C: ['mov x19, x3', 'mov x20, x2', 'mov x21, x1', 'mov x22, x0',
                 'str wzr, [x0, #8]', 'adrp x8, #0x5692000', 'add x8, x8, #0xcc0',
                 'str x8, [x0]', 'stp xzr, xzr, [x0, #0x10]', 'strb wzr, [x0, #0x20]',
                 'mov w8, #0xff', 'sturh w8, [x0, #0x21]', 'bl #0x42ca3f8', 'str x21, [x22, #0x10]'],
    # The cash rate getter returns the selected currency rate. Base has rate 1.
    0x42CC2D4: ['sxtb w0, w1', 'bl #0x42cc770', 'cbz x0, #0x42cc314',
                 'ldr d0, [x0]', 'fcvt s0, d0', 'ldp x29, x30, [sp], #0x10', 'ret'],
    # Input conversion divides selected-currency amount by rate to store base units.
    0x42CB2E0: ['ldr x8, [x19]', 'ldr x8, [x8, #0x58]', 'sxtb w1, w1',
                 'mov x0, x19', 'blr x8', 'fcvt d0, s0', 'fdiv d1, d8, d0'],
    # Output conversion multiplies base whole units + cents by selected-currency rate.
    0x42D0C34: ['ldp d0, d1, [sp, #0x18]', 'scvtf d0, d0', 'mov x8, #0x4059000000000000',
                 'fmov d2, x8', 'fdiv d1, d1, d2', 'fadd d8, d1, d0', 'ldr x8, [sp, #8]',
                 'ldr x8, [x8, #0x58]', 'sxtb w1, w19', 'add x0, sp, #8', 'blr x8',
                 'fcvt d0, s0', 'fmul d0, d8, d0'],
}
cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
with plugin.open('rb') as stream:
    for rva, instructions in expected.items():
        stream.seek(0x5ED4000 + rva)
        actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(len(instructions)*4), rva)]
        assert actual == instructions, (hex(rva), actual)

archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
fields = []
for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
    try:
        raw = zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000)
        root = ET.fromstring(raw)
    except (zstandard.ZstdError, ET.ParseError):
        continue
    for row in root.iter('record'):
        values = {c.get('id'): c.get('value') for c in row if c.get('id')}
        if values.get('field') == 'Pcwg' and values.get('type') == 'cash':
            assert values.get('is_weekly_wage') == 'true'
            fields.append({k: values[k] for k in ('field', 'type', 'is_weekly_wage')})
assert fields
receipt = {'verified': True, 'plugin_sha256': players.SHA256, 'currency_count': info['count'],
           'currency': 'GBP', 'currency_record_id': 86, 'native_currency_enum': 0,
           'unit': 'whole_currency_unit', 'period': 'week', 'editor_fields': fields,
           'instruction_blocks': [hex(rva) for rva in expected],
           'scope': 'Native stored base amount. Does not reproduce UI currency/period rounding, bonuses or payroll.'}
Path('evidence/wage-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt))
