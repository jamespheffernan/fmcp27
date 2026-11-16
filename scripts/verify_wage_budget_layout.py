"""Prove the stored Cwrb calculation against the pinned binary; never call it.

Run with uv run --no-project --with capstone --with zstandard python ...
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        result = bridge.get_club_finances(sid)
        plugin = Path(bridge.plugin_identity[0][0])
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva, size):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected)*4).values())
            assert actual == expected, (hex(rva), actual, expected)
        club = code(0xE476C4, 0xF12C)
        # The shared tracer stops at this unrelated stack-address instruction.
        assert property_case(club, 'Cwrb', 0xE476F8, 'w1') == 0xE49BAC
        check(0xE49BAC, ['sub x26, x29, #0x98', 'mov w8, #0x636c',
                        'movk w8, #0x4377, lsl #16', 'cmp w1, w8', 'b.ne #0xe4c280'])
        # Cwrb != Cwcl, so it uses the same GAME_CLUB fallback as Ctfc.
        check(0xE4C280, ['adrp x8, #0x56d3000', 'ldrb w8, [x8, #0x4e0]', 'tbz w8, #0, #0xe4c2d0',
            'adrp x19, #0x56d2000', 'ldr x0, [x19, #0xce8]', 'ldr x8, [x0]', 'ldr x8, [x8, #0x38]',
            'mov x21, x1', 'blr x8', 'mov x1, x21', 'tbnz w0, #0, #0xe4c2d0',
            'ldr x0, [x19, #0xce8]', 'ldr x8, [x0]', 'ldr x8, [x8, #0xb0]',
            'mov x1, x20', 'mov x2, x21', 'mov x3, x28', 'blr x8'])
        check(0x1FC7914, ['mov w0, #0', 'ret'])
        game = code(0x1FAF4D8, 0x14884)
        assert game[0x1FAF574] == 'str x26, [sp, #0x70]'
        game[0x1FAF574] = 'mov w22, w22'
        assert property_case(game, 'Cwrb', 0x1FAF568, 'w22') == 0x1FB1F34
        check(0x1FB1F34, ['ldr x0, [x26, #0x150]', 'cbz x0, #0x1fb9140',
            'ldr x8, [x0]', 'ldr x8, [x8, #0x40]', 'blr x8', 'cmp w0, #1',
            'b.ne #0x1fb9140', 'ldr x8, [x26, #0x150]', 'cbz x8, #0x1fb9140',
            'ldr w9, [x8, #0x808]', 'cmp w9, #1', 'b.lt #0x1fbea84',
            'ldr w8, [x8, #0x814]', 'sub w19, w9, w8', 'b #0x1fbea88'])
        check(0xEB8174, ['mov w0, #1', 'ret'])
        check(0xE648D4, ['mov w0, #0', 'ret'])
        check(0x1FB9140, ['bl #0x4403cd4', 'add x0, x0, #0x28', 'mov w8, #-1', 'str w8, [sp, #0x158]'])
        check(0x1FBEA84, ['mov w19, #0', 'bl #0x4403cd4', 'add x0, x0, #0x28', 'str w19, [sp, #0x158]'])
        # The regular getter can refresh spending. The bridge only reads stored data.
        check(0xE83F98, ['ldr w8, [x19, #0x814]', 'cmn w8, #0x3e9', 'b.gt #0xe83fb4',
            'mov x0, x19', 'mov x1, x21', 'mov w2, #0', 'bl #0xe830e4'])
        check(0xE83FB4, ['cmp w20, #0', 'mov w8, #0x810', 'mov w9, #0x814',
            'csel x8, x9, x8, ne', 'ldr w0, [x19, x8]'])
        # The updater adds per-player native wage calculations and finance-service
        # adjustments, proving why summing main contract wages is insufficient.
        check(0xE837AC, ['bl #0xcbfce8'])
        check(0xE837D8, ['ldr w8, [x19, #0x814]', 'add w8, w8, w27', 'str w8, [x19, #0x814]'])
        check(0xE83B18, ['adrp x8, #0x56d2000', 'ldr x0, [x8, #0xb10]',
            'ldr x8, [x0]', 'ldr x8, [x8, #0x50]', 'mov x1, x22', 'blr x8',
            'ldr d0, [x19, #0x810]', 'dup v1.2s, w0', 'add v0.2s, v0.2s, v1.2s', 'str d0, [x19, #0x810]'])
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'property': 'Cwrb', 'budget_offset': '0x808',
        'spending_offset': '0x814', 'managed_club': result,
        'scope': 'Native remaining weekly wage property, zero-budget and missing/base-finance branches, stored spending refresh boundary. No native execution, spending refresh or UI comparison.'}
    path = ROOT/'evidence/wage-budget-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified stored remaining wage-budget calculation. {path}')


if __name__ == '__main__': verify()
