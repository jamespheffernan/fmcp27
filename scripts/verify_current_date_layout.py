"""Verify the native simulation-date anchor through fixture-relative date labels.

Reads installed ARM64 code/resources and live bytes; never executes game functions.
"""
from datetime import date, timedelta, datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge

# Fixture-relative date display and TEAM next-fixture lookup both use this anchor.
EXPECTED = {
    0x2014f4: [
        'mov x1, x0',
        'mov x19, x8',
        'stur wzr, [x29, #-0x14]',
        'adrp x0, #0x56b1000',
        'add x0, x0, #0xdb8',
        'sub x2, x29, #0x12',
        'sub x3, x29, #0x14',
        'bl #0x42eccbc',
    ],
    0x201524: [
        'ldursh w8, [x29, #-0x14]',
        'tbnz w8, #0x1f, #0x201554',
        'and w8, w8, #0xffff',
        'cmp w8, #1',
        'b.eq #0x20158c',
        'cbnz w8, #0x2015d8',
        'add x8, sp, #8',
        'mov x0, x20',
        'mov w1, #0xbd2',
        'movk w1, #5, lsl #16',
        'bl #0x43db8b8',
    ],
    0x201554: [
        'add x8, sp, #8',
        'mov x0, x20',
        'mov w1, #0xd0e5',
        'movk w1, #0xa, lsl #16',
        'bl #0x43db8b8',
    ],
    0x20158c: [
        'add x8, sp, #8',
        'mov x0, x20',
        'mov w1, #0xca45',
        'movk w1, #3, lsl #16',
        'bl #0x43db8b8',
    ],
    0x2015d8: [
        'add x8, sp, #8',
        'mov x0, x20',
        'mov w1, #0x8711',
        'movk w1, #8, lsl #16',
        'bl #0x43db8b8',
    ],
    0x201600: [
        'add x8, sp, #8',
        'sub x0, x29, #0x14',
        'bl #0x43cff9c',
        'add x0, sp, #0x28',
        'add x2, sp, #8',
        'mov w1, #1',
        'mov w3, #0',
        'bl #0x43d1f9c',
    ],
    0x42eccbc: [
        'ldrh w8, [x0]',
        'tst w8, #0x1ff',
        'b.eq #0x42eccf4',
        'ldrh w8, [x1]',
        'tst w8, #0x1ff',
        'b.eq #0x42eccf4',
        'ldr w9, [x0]',
        'lsr w8, w9, #0x10',
        'ldr w10, [x1]',
        'lsr w11, w10, #0x10',
        'cmp w8, w11',
        'b.ls #0x42ecd04',
        'and w12, w10, #0x1ff',
    ],
    0x17748d4: [
        'adrp x19, #0x56b1000',
        'add x19, x19, #0xdb8',
        'mov x0, x19',
        'bl #0x42e9b44',
        'str w0, [sp, #0x1c]',
    ],
    0x17748fc: [
        'add x0, x22, #8',
        'add x2, sp, #0x1c',
        'strb wzr, [sp]',
        'mov x1, x19',
        'mov x3, x20',
        'mov x4, #0',
        'mov x5, #0',
        'mov w6, #1',
        'mov w7, #1',
        'bl #0x3d1cfd0',
    ],
}


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge._current(sid)
            tables = bridge._player_layout(process)
            base = tables[0]-players.RVA[0]
            snapshot, save, _ = bridge._world_state(process, tables)
            raw = snapshot(base+0x56B1DB8, 4)
            value = struct.unpack('<I', raw)[0]
            observed = (date(value >> 16, 1, 1)+timedelta(days=(value & 511)-1)).isoformat()
            assert save['current_date'] == observed
            snapshot.verify()
            bridge._current(sid)
            plugin = Path(bridge.plugin_identity[0][0])
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    checks = []
    with plugin.open('rb') as stream:
        for rva, expected in EXPECTED.items():
            stream.seek(0x5ED4000+rva)
            code = stream.read(len(expected)*4)
            actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(code, rva)]
            assert actual == expected, (hex(rva), actual, expected)
            checks.append({'rva': hex(rva), 'sha256': hashlib.sha256(code).hexdigest()})
        # Preserve the complete calendar-difference function's bytes as evidence.
        stream.seek(0x5ED4000+0x42ECCBC)
        difference_hash = hashlib.sha256(stream.read(0x1130)).hexdigest()
    language = (plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
    labels = {0x50BD2: 'Today', 0x3CA45: 'Tomorrow', 0xAD0E5: 'Match has been played',
              0x88711: 'In [%number#1] days'}
    for key, text in labels.items():
        assert f'KEY-{key}: {text}[' in language
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'checks': checks, 'labels': labels,
               'difference_function_sha256': difference_hash,
               'current_date': observed, 'raw_date_hex': raw.hex(),
               'last_saved_date': save['last_saved_date'], 'save_count': save['save_count'],
               'scope': 'Native simulation calendar date used by fixture-relative labels and next-fixture search. No current clock time, timezone or match-completion inference.',
               'foreground_ui_used': False, 'native_execution': False}
    (ROOT/'evidence/current-date-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    verify()
