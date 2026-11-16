"""Verify stored club cash fields against pinned native code and editor resources.

Run with uv run --no-project --with capstone --with zstandard python ...
No game functions are executed and no foreground UI is used.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import club_finance, players, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        result = bridge.get_club_finances(sid)
        plugin = Path(bridge.plugin_identity[0][0])
        assert result['finances']['state'] == 'stored'
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as f:
        def code(rva, length):
            f.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(f.read(length), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected)*4).values())
            assert actual == expected, (hex(rva), actual, expected)
        c = code(0xE476C4, 0xF12C)
        assert property_case(c, 'Ccba', 0xE476F8, 'w1') == 0xE4AECC
        assert property_case(c, 'Cwwb', 0xE476F8, 'w1') == 0xE4AECC
        check(0xE4AECC, ['ldr x0, [x20, #0x150]', 'cbz x0, #0xe4af0c',
            'ldr x8, [x0]', 'ldr x4, [x8, #0x18]'])
        c = code(0xE7DFB8, 0x1B0)
        assert property_case(c, 'Cwwb', 0xE7DFCC, 'w2') == 0xE7DFFC
        check(0xE7DFFC, ['ldr w20, [x0, #0x808]'])
        check(0xE7E0E0, ['b #0xe7d238'])
        c = code(0xE7D238, 0x658)
        assert property_case(c, 'Ccba', 0xE7D258, 'w2') == 0xE7D2A8
        check(0xE7D2A8, ['ldr x8, [x20]', 'ldr x8, [x8, #0x1b0]',
            'mov x0, x20', 'mov w2, #0', 'blr x8'])
        check(0xE84AD0, ['cbz w2, #0xe84bbc'])
        check(0xE84BBC, ['ldr w0, [x0, #0xc]'])
        check(0xE649F4, ['ldr w0, [x0, #0xc]', 'ret'])
        # Current transfer-budget property delegates to GAME_CLUB and applies rules.
        # The public tool exposes only the explicitly separate stored branch.
        assert property_case(code(0xE476C4, 0xF12C), 'Ctfc', 0xE476F8, 'w1') == 0xE4C280
        c = code(0x1FAF4D8, 0x14884)
        assert c[0x1FAF574] == 'str x26, [sp, #0x70]'
        c[0x1FAF574] = 'mov w22, w22'  # Stack spill does not affect comparison registers/flags.
        assert property_case(c, 'Ctfc', 0x1FAF568, 'w22') == 0x1FB1324
        check(0x1FB1364, ['adrp x8, #0x56d4000', 'ldrb w8, [x8, #0x951]',
            'cmp w8, #1', 'b.ne #0x1fb9cfc'])
        check(0x1FB9CFC, ['ldr x0, [x26, #0x150]'])
        check(0x1FBCDD0, ['cbz x0, #0x1fbe704', 'mov x1, x26', 'mov w2, #1',
            'mov w3, #0', 'mov w4, #0', 'bl #0xe86224'])
        check(0xE86224, ['cbz w3, #0xe86230', 'ldr w0, [x0, #0x7c4]', 'ret'])
        check(0xE862FC, ['ldr w20, [x22, #0x7c4]'])
        check(0xE863B8, ['sub w8, w20, #1', 'cmp w8, #0x1f3', 'csel w0, wzr, w20, lo'])
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    labels = {}
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try: root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
        except (ET.ParseError, zstandard.ZstdError): continue
        for row in root.iter('record'):
            values = {c.get('id'): c.get('value') for c in row if c.get('id')}
            prop = values.get('field')
            if prop in ('Ccba', 'Cwwb', 'Ctfc') and values.get('type') == 'cash':
                assert values.get('store_pence', 'false') == 'false'
                if prop == 'Cwwb': assert values['is_weekly_wage'] == 'true'
                labels[prop] = values['name'].split('[COMMENT')[0].strip()
    assert labels == {'Ccba': 'Balance', 'Cwwb': 'Wage Budget', 'Ctfc': 'Transfer Budget'}
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'labels': labels, 'native_finance_type': hex(world.TYPES['club_finance'][0]),
        'fields': club_finance.FIELDS, 'managed_club': result,
        'scope': 'Native stored balance, total weekly wage budget and pre-adjustment transfer budget. No UI comparison or spending-room claim.'}
    path = ROOT/'evidence/club-finance-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified three stored club cash fields and native availability distinction. {path}')


if __name__ == '__main__': verify()
