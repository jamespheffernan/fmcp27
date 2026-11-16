"""Check native league-table layout evidence without executing game code."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            bridge._player_layout(bridge._current(sid))
            plugin = Path(bridge.plugin_identity[0][0])
    finally:
        bridge.detach()
    language = (plugin.parent.parent / 'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
    labels = {int(m[1]): m[2] for m in re.finditer(r'^KEY-(\d+): (.*)', language, re.M)}
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    checks = []
    with plugin.open('rb') as stream:
        def read(rva, size):
            stream.seek(0x5ED4000 + rva)
            return stream.read(size)

        def code(rva, size):
            return [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(read(rva, size), rva)]

        def check(rva, expected):
            actual = code(rva, len(expected)*4)
            assert actual == expected, (hex(rva), actual, expected)
            checks.append({'rva': hex(rva), 'sha256': hashlib.sha256(read(rva, len(expected)*4)).hexdigest()})

        # COMP runtime stages, nullable slots, and nested league groups.
        check(0xEFD7E0, ['ldr x21, [x20, #0xb0]', 'cbz x21, #0xf041e8',
                         'ldp x9, x8, [x21, #0x1d8]'])
        check(0xEFD7F8, ['ldr x20, [x9, x22, lsl #3]', 'cbz x20, #0xefd834'])
        check(0x3DECBD4, ['ldp x9, x8, [x0, #0xd0]', 'sub x8, x8, x9',
                          'asr x0, x8, #3', 'ret'])
        check(0x3DD80BC, ['ldp x8, x9, [x19, #0xd0]', 'cmp x8, x9',
                          'b.eq #0x3dd810c', 'ldr x0, [x8]', 'ldr x8, [x0, #0xf0]'])
        check(0x3F23000, ['ldr x8, [x0, #0xc0]', 'ldr x0, [x8, x1, lsl #3]', 'ret'])
        check(0x3F23028, ['ldp x8, x9, [x0, #0xc0]', 'cmp x9, x8',
                          'b.eq #0x3f23060', 'ldr x0, [x8]', 'ldr x10, [x0, #0x88]'])

        # The same native sort enum selects an English label and a scalar getter.
        label_offsets = struct.unpack('<48H', read(0x53EEAC8, 96))
        getter_offsets = read(0x53EED12, 48)
        comparator_offsets = read(0x53EEB83, 48)
        check(0x3EF4DFC, ['mov w8, w23', 'adrp x9, #0x53ee000',
                          'add x9, x9, #0xac8', 'adr x10, #0x3ef4e18',
                          'ldrh w11, [x9, x8, lsl #1]', 'add x10, x10, x11, lsl #2', 'br x10'])
        check(0x3F4A274, ['mov w8, w1', 'adrp x9, #0x53ee000',
                          'add x9, x9, #0xd12', 'adr x10, #0x3f4a290',
                          'ldrb w11, [x9, x8]', 'add x10, x10, x11, lsl #2', 'br x10'])
        check(0x3F12CA4, ['mov w10, w2', 'adrp x11, #0x53ee000',
                          'add x11, x11, #0xb83', 'adr x12, #0x3f12cc0',
                          'ldrb w13, [x11, x10]', 'add x12, x12, x13, lsl #2', 'br x12'])
        fields = {
            0: ('Goal Difference', 0x3F4A298, ['ldrh w8, [x0, #8]', 'ldrh w9, [x0, #0xa]', 'sub w19, w8, w9', 'b #0x3f4a66c']),
            1: ('Goals Scored', 0x3F4A290, ['ldrh w19, [x0, #8]', 'b #0x3f4a66c']),
            2: ('Games Won', 0x3F4A2A8, ['ldrsb w19, [x0, #0x10]', 'b #0x3f4a66c']),
            23: ('Points', 0x3F4A3BC, ['ldrh w19, [x0, #0xc]', 'b #0x3f4a66c']),
            25: ('Goals Against', 0x3F4A578, ['ldrh w19, [x0, #0xa]', 'b #0x3f4a66c']),
            26: ('Games Lost', 0x3F4A350, ['ldrsb w19, [x0, #0x12]', 'b #0x3f4a66c']),
        }
        for enum, (label, getter, expected) in fields.items():
            pc = 0x3EF4E18 + label_offsets[enum]*4
            instructions = list(cs.disasm(read(pc, 24), pc))
            assert instructions[2].mnemonic == 'mov' and instructions[2].op_str.startswith('w1, #')
            assert instructions[3].mnemonic == 'movk' and instructions[3].op_str.endswith('lsl #16')
            low = int(instructions[2].op_str.split('#')[1], 0)
            high = int(instructions[3].op_str.split('#')[1].split(',')[0], 0)
            assert labels[low | high << 16].split('[')[0] == label
            assert 0x3F4A290 + getter_offsets[enum]*4 == getter
            check(getter, expected)
        check(0x3F4A66C, ['sxth w0, w19'])

        # Home and away comparator branches prove the 24-byte block stride.
        assert 0x3F12CC0 + comparator_offsets[5]*4 == 0x3F12DA8
        assert 0x3F12CC0 + comparator_offsets[32]*4 == 0x3F12DB4
        check(0x3F12DA8, ['ldrsh w9, [x1, #0x38]', 'ldrsh w8, [x8, #0x38]', 'b #0x3f12e74'])
        check(0x3F12DB4, ['ldrsh w9, [x1, #0x20]', 'ldrsh w8, [x8, #0x20]', 'b #0x3f12e74'])
        check(0x3F12F84, ['ldrsh w9, [x1, #0x24]', 'ldrsh w10, [x8, #0x24]', 'subs w0, w9, w10'])
        check(0x3F12F30, ['ldrsh w9, [x1, #0x3c]', 'ldrsh w10, [x8, #0x3c]', 'subs w0, w9, w10'])

        # Average Points uses +E as its games denominator; carried totals copy E, not F.
        assert labels[0x3C89E] == 'Average Points'
        assert 0x3EF4E18 + label_offsets[15]*4 == 0x3EF51C8
        check(0x3F0E70C, ['cmp w0, #0xf', 'b.ne #0x3f0e780', 'mov w8, #0x18',
                          'smaddl x9, w22, w8, x20', 'ldrsb w8, [x9, #0xe]'])
        check(0x3F0E730, ['ldrsh w9, [x9, #0xc]', 'scvtf s1, w9',
                          'and w8, w8, #0xff', 'ucvtf s2, w8', 'fdiv s1, s1, s2'])
        check(0x3F0FE2C, ['ldrb w10, [x9, #0xe]', 'add x8, x27, x8, lsl #3',
                          'strb w10, [x8, #0xe]', 'ldrb w10, [x9, #0x10]',
                          'strb w10, [x8, #0x10]', 'ldurh w10, [x9, #0x11]',
                          'sturh w10, [x8, #0x11]', 'ldr w9, [x9, #8]', 'str w9, [x8, #8]'])

        # Native sorting defaults to C0, records its view, and writes zero-based order at F7.
        check(0x3F0C4C0, [
            'ldr x8, [x29, #0x10]', 'add x9, x0, #0xc0', 'cmp x8, #0',
            'csel x25, x9, x8, eq', 'ldr x19, [x25]', 'ldrsb x8, [x0, #0x100]',
            'add x23, x19, x8, lsl #3'])
        check(0x3F0C5B8, ['strb w28, [x26, #0x101]'])
        check(0x3F0CA58, ['adrp x9, #0x3f0e000', 'add x9, x9, #0x68c'])
        check(0x3F0E68C, ['stp x29, x30, [sp, #-0x10]!', 'mov x29, sp',
                          'bl #0x3f0e6a4', 'lsr w0, w0, #0x1f'])
        check(0x3F0CED8, ['ldr x8, [sp, #0x48]', 'ldr x8, [x8]',
                          'ldr x21, [x8, x28, lsl #3]', 'ldr w8, [sp, #0x3c]',
                          'cbz w8, #0x3f0cf0c', 'strb w28, [x21, #0xf7]'])

    receipt = {
        'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'checks': checks,
        'scope': 'Native stage/group vectors, six scalar statistics, home/away blocks, played denominator, and native sorting storage. Draw/penalty categories still need a public contract. This does not prove freshness or completeness of every table.',
        'foreground_ui_used': False, 'native_execution': False,
    }
    (ROOT / 'evidence/league-stage-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    verify()
