"""Verify the current-budget normal-career path without invoking game code."""
from datetime import datetime, timezone
import json
from pathlib import Path
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
        result = bridge.get_club_finances(sid)
        plugin = Path(bridge.plugin_identity[0][0])
        assert result['finances']['current_transfer_budget']['state'] == 'decoded'
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as f:
        def check(rva, expected):
            f.seek(0x5ED4000 + rva)
            actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(f.read(len(expected)*4), rva)]
            assert actual == expected, (hex(rva), actual, expected)
        check(0xE4C280, ['adrp x8, #0x56d3000', 'ldrb w8, [x8, #0x4e0]', 'tbz w8, #0, #0xe4c2d0',
            'adrp x19, #0x56d2000', 'ldr x0, [x19, #0xce8]', 'ldr x8, [x0]', 'ldr x8, [x8, #0x38]',
            'mov x21, x1', 'blr x8', 'mov x1, x21', 'tbnz w0, #0, #0xe4c2d0',
            'ldr x0, [x19, #0xce8]', 'ldr x8, [x0]', 'ldr x8, [x8, #0xb0]',
            'mov x1, x20', 'mov x2, x21', 'mov x3, x28', 'blr x8'])
        check(0x1FC7914, ['mov w0, #0', 'ret'])
        check(0x1FB1364, ['adrp x8, #0x56d4000', 'ldrb w8, [x8, #0x951]',
            'cmp w8, #1', 'b.ne #0x1fb9cfc'])
        check(0x1FB9CFC, ['ldr x0, [x26, #0x150]', 'cbz x0, #0x1fbc820',
            'ldr x8, [x0]', 'ldr x8, [x8, #0x40]', 'blr x8', 'cmp w0, #1',
            'b.ne #0x1fbc81c', 'ldr x0, [x26, #0x150]', 'b #0x1fbc820'])
        check(0xEB8174, ['mov w0, #1', 'ret'])
        check(0xE648D4, ['mov w0, #0', 'ret'])
        check(0x1FBC81C, ['mov x0, #0', 'ldrb w8, [x26, #0x161]', 'tbnz w8, #6, #0x1fbc838',
            'ldr w8, [x26, #0xc]', 'sub w8, w8, #0xd70, lsl #12', 'cmp w8, #0xdd0',
            'b.ne #0x1fbcdd0', 'bl #0x4403cd4', 'add x0, x0, #0x28', 'mov w8, #-1'])
        check(0x1FBCDD0, ['cbz x0, #0x1fbe704', 'mov x1, x26', 'mov w2, #1',
            'mov w3, #0', 'mov w4, #0', 'bl #0xe86224'])
        check(0xE86260, ['adrp x8, #0x56d2000', 'ldr x0, [x8, #0xb10]', 'ldr x8, [x0]',
            'ldr x8, [x8, #0x48]', 'blr x8', 'tbnz w0, #0, #0xe862f4', 'cbz w20, #0xe862fc'])
        check(0xE862F4, ['mov w0, #0', 'b #0xe863c4', 'ldr w20, [x22, #0x7c4]',
            'adrp x8, #0x56d4000', 'ldrb w8, [x8, #0x999]', 'cmp w8, #1',
            'ccmp w21, #0, #4, eq', 'b.eq #0xe863b8'])
        check(0xE863B8, ['sub w8, w20, #1', 'cmp w8, #0x1f3', 'csel w0, wzr, w20, lo'])
        check(0x1FFD5FC, ['mov x19, x1', 'bl #0x2dccf6c', 'tbz w0, #0, #0x1ffd610',
            'mov w0, #1', 'b #0x1ffd674', 'ldrb w8, [x19, #0x163]', 'tbnz w8, #4, #0x1ffd670',
            'ldp x8, x9, [x19, #0x118]', 'cmp x8, x9', 'b.eq #0x1ffd670', 'mov w10, #1',
            'mov w11, #0x1f0', 'movk w11, #0x10, lsl #16', 'ldr x12, [x8]',
            'ldr x13, [x12, #8]', 'cmp x13, x19', 'b.ne #0x1ffd658',
            'ldrb w13, [x12, #0x30]', 'cmp w13, #0x14', 'lsl w13, w10, w13',
            'and w13, w13, w11', 'ccmp w13, #0, #4, ls', 'b.ne #0x1ffd668',
            'add x8, x8, #8', 'cmp x8, x9', 'b.ne #0x1ffd630', 'b #0x1ffd670',
            'ldr x8, [x12]', 'cbnz x8, #0x1ffd608', 'mov w0, #0'])
        check(0x2DCCF6C, ['adrp x8, #0x56d4000', 'ldrb w8, [x8, #0x972]',
            'tbz w8, #0, #0x2dccf80', 'mov w0, #0', 'ret', 'adrp x8, #0x56d4000',
            'ldrb w8, [x8, #0x987]', 'cmp w8, #1', 'b.ne #0x2dcd02c'])
        check(0x2DCD02C, ['mov w0, #1', 'ret'])
    path = ROOT/'evidence/transfer-budget-layout-verification.json'
    path.write_text(json.dumps({'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'managed_club': result,
        'scope': 'Native current-budget routing, unavailable sentinel, global/club relationship gates and small-budget normalization. Alternative mode/date/manager branches remain unavailable.'}, indent=2)+'\n')
    print(f'Verified current transfer-budget branches. {path}')


if __name__ == '__main__': verify()
