"""Verify live weekly contribution fields from native code and installed labels.

Run with uv run --no-project --with capstone --with zstandard python ...
No game functions are executed.
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
from fm_live_mcp import players
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        result = bridge.get_wage_contributions(sid, all_clubs=True)
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
        # The game's finance service adds only the +8 club's amounts to weekly
        # wage spending. This establishes payer direction and weekly units.
        check(0x1FFE24C, ['adrp x8, #0x56a4000', 'ldr x9, [x8, #0x9f8]',
            'ldp x8, x9, [x9, #0xf0]', 'cmp x8, x9', 'b.eq #0x1ffe28c', 'mov w0, #0',
            'ldr x10, [x8]', 'ldr x11, [x10, #8]', 'cmp x11, x1', 'b.ne #0x1ffe27c',
            'ldr w10, [x10, #0x14]', 'add w0, w10, w0', 'add x8, x8, #8',
            'cmp x8, x9', 'b.ne #0x1ffe264', 'ret', 'mov w0, #0', 'ret'])
        check(0xE83B18, ['adrp x8, #0x56d2000', 'ldr x0, [x8, #0xb10]', 'ldr x8, [x0]',
            'ldr x8, [x8, #0x50]', 'mov x1, x22', 'blr x8', 'ldr d0, [x19, #0x810]',
            'dup v1.2s, w0', 'add v0.2s, v0.2s, v1.2s', 'str d0, [x19, #0x810]'])
        # Native construction: two clubs, person database index, cash and packed date.
        check(0x2DBADD4, ['mov x21, x5', 'mov x20, x4', 'mov x22, x3',
            'mov x23, x2', 'mov x24, x1', 'mov x19, x0', 'mov w0, #0x20', 'bl #0x4aee72c'])
        check(0x2DBAE08, ['ldr w9, [x24, #8]', 'str w9, [x0, #0x10]',
            'ldrb w9, [x23, #0x2f]', 'cbnz w9, #0x2dbae1c', 'ldr x8, [x23, #0x30]',
            'str x8, [x0]', 'ldrb w8, [x22, #0x2f]', 'cbz w8, #0x2dbae30',
            'mov x8, #0', 'b #0x2dbae34', 'ldr x8, [x22, #0x30]', 'str x8, [x0, #8]',
            'ldr w8, [x21]', 'stp w20, w8, [x0, #0x14]'])
        check(0x2DBAE40, ['str x0, [sp, #8]', 'ldp x8, x9, [x19, #0xf8]',
            'cmp x8, x9', 'b.hs #0x2dbae5c', 'str x0, [x8], #8', 'str x8, [x19, #0xf8]',
            'b #0x2dbae7c', 'add x0, x19, #0xf0'])
        c = code(0x3A58878, 0x270)
        assert property_case(c, 'wage', 0x3A58894, 'w1') == 0x3A589B4
        assert property_case(c, 'wend', 0x3A58894, 'w1') == 0x3A58920
        assert property_case(c, 'club', 0x3A58894, 'w1') == 0x3A5899C
        assert property_case(c, 'play', 0x3A58894, 'w1') == 0x3A588C4
        check(0x3A589B4, ['ldr w20, [x20, #0x14]', 'bl #0x4403cd4',
                        'add x0, x0, #0x28', 'str w20, [sp, #8]'])
        check(0x3A58930, ['ldrh w8, [x20, #0x18]', 'ldrh w9, [x20, #0x1a]',
            'lsr w10, w8, #9', 'orr w9, w10, w9, lsl #17', 'bfi w9, w8, #8, #9'])
        check(0x3A5899C, ['ldr x9, [x20]', 'cbz x9, #0x3a58a10', 'ldp w8, w9, [x9, #0xc]'])
        check(0x3A588C4, ['mov x0, #0', 'ldr w8, [x20, #0x10]', 'tbnz w8, #0x1f, #0x3a58a5c',
            'adrp x9, #0x56d2000', 'ldr x9, [x9, #0xd80]'])
        check(0x3A58A34, ['ldr x9, [x9, #0x88]', 'ldp x9, x10, [x9]',
            'subs x10, x10, x9', 'b.eq #0x3a58a58', 'cmp x8, x10, asr #3',
            'b.hs #0x3a58a58', 'add x8, x9, x8, lsl #3', 'ldr x0, [x8]'])
        check(0x2E101B0, ['ldp x21, x22, [x20, #0xf0]', 'cmp x21, x22', 'b.eq #0x2e101d4',
            'ldr x0, [x21]', 'mov x1, x19', 'bl #0x3a58324'])
        # The serializer writes cash and the same packed date through native date IO.
        check(0x3A58450, ['add x1, x20, #0x14', 'mov x0, x21', 'mov w2, #4', 'blr x8'])
        check(0x3A58494, ['add x0, x20, #0x18', 'mov x1, x19', 'bl #0x42e9ce8'])
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    labels = {}
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try: tree = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
        except (zstandard.ZstdError, ET.ParseError): continue
        for row in tree.iter('record'):
            values = {c.get('id'): c.get('value') for c in row if c.get('id')}
            if values.get('field') != 'Cwcl': continue
            assert values['name'] == 'Wage Contributions'
            for child in row.iter('record'):
                d = {c.get('id'): c.get('value') for c in child if c.get('id')}
                if d.get('field') in ('wage', 'wend', 'play', 'club'):
                    labels[d['field']] = d['name']
                    if d['field'] == 'wage':
                        assert d['type'] == 'cash' and d.get('store_pence', 'false') == 'false'
    assert labels == {'play': 'Player', 'club': 'Club', 'wage': 'Wage', 'wend': 'Contributions Paid Till'}
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'labels': labels, 'live_record_count': result['count'],
        'scope': 'Live contribution vector, native creation/persistence, person-table index, club pointers, weekly cash and paid-until property. No native execution or UI comparison.'}
    path = ROOT/'evidence/wage-contribution-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified live weekly wage-contribution layout. {path}')


if __name__ == '__main__': verify()
