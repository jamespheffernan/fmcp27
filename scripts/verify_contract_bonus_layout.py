"""Verify six bonus labels and native cash selection; never execute game code.

Run with uv run --no-project --with capstone --with zstandard python ...
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
from fm_live_mcp import contract_bonuses as bonuses, players, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        roster = bridge.get_managed_squad(sid)
        player = bridge.get_player(sid, roster['players'][0]['player_ref'], include_contract_bonuses=True)
        assert player['player']['contract_bonuses']['state'] == 'decoded'
        plugin = Path(bridge.plugin_identity[0][0])
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva, size):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected) * 4).values())
            assert actual == expected, (hex(rva), actual, expected)
        person = code(0x148F9B8, 0xB000)
        full = code(0x128670C, 0x27C0)
        base = code(0xFF5678, 0x5DA4)
        cases = {'Cabo': 0xFF7548, 'Cgbo': 0xFF7FA4, 'Csbo': 0xFF7738,
                 'Ccsb': 0xFF6050, 'Cusb': 0xFF7F28, 'Cicb': 0xFF801C}
        person_cases = {'Pcap': 0x1494F58, 'Pcgb': 0x14948A8, 'PcAb': 0x1498A1C,
                        'Pccb': 0x14947B4, 'Pusb': 0x1491D9C, 'Picb': 0x149062C}
        for name, (kind, prop, editor, label) in bonuses.BONUSES.items():
            assert not (1 << kind) & 0x3002778EF38  # all six select the first match
            assert property_case(person, editor, 0x148FCC4, 'w21') == person_cases[editor]
            assert property_case(full, prop, 0x1286734, 'w1') == 0x1286F0C
            assert property_case(base, prop, 0xFF56A4, 'w1') == cases[prop]
            check(cases[prop], ['ldr x8, [x20]', 'ldr x3, [x8, #0x1a0]',
                               'mov x0, x20', f'mov w1, #{kind:#x}', 'b #0xff8200'])
            if editor not in ('Pcap', 'PcAb'):
                value = int.from_bytes(prop.encode(), 'big')
                check(person_cases[editor], ['mov x0, x20', f'mov w1, #{value & 65535:#x}',
                    f'movk w1, #{value >> 16:#x}, lsl #16', 'b #0x1498a20'])
        check(0x1494F50, ['mov w8, #0x626c', 'movk w8, #0x4361, lsl #16',
                         'orr w1, w8, #3', 'b #0x1498a1c'])
        check(0x1495FF0, ['mov w8, #0x6461', 'movk w8, #0x4373, lsl #16',
                         'sub w1, w8, #0x1f2', 'b #0x1498a1c'])
        assert (0x4361626C | 3).to_bytes(4, 'big') == b'Cabo'
        assert (0x43736461 - 0x1F2).to_bytes(4, 'big') == b'Csbo'
        check(0x1498A40, ['b #0x14a04b0'])
        check(0x14A04D8, ['ldr x8, [x0]', 'ldr x8, [x8, #0x3c8]', 'blr x8'])
        check(0xCB3724, ['ldr x8, [x0]', 'sub x8, x8, #0x3d8', 'ldr x8, [x8]',
                         'add x8, x0, x8', 'ldr x0, [x8, #0x78]', 'ret'])
        check(0x14A0B28, ['ldr x8, [x21]', 'ldr x8, [x8, #0x18]',
            'mov x0, x21', 'mov x1, x20', 'mov x2, x19', 'blr x8'])
        check(0x1286F30, ['b #0xff5678'])
        check(0xFF8224, ['br x3'])
        # Native getter initializes an empty result, then walks 8-byte inline entries.
        check(0x1288F48, ['adrp x22, #0x56d6000', 'add x22, x22, #0x3c0',
            'cmp x2, x22', 'b.eq #0x1288f84'])
        check(0x1288F84, ['ldp x8, x9, [x21, #0x68]', 'cmp x8, x9',
            'b.eq #0x1289074', 'mov x10, #0', 'and w11, w20, #0xff',
            'mov w12, #1', 'mov x13, #0xef38', 'movk x13, #0x2778, lsl #16',
            'movk x13, #0x300, lsl #32', 'ldrb w14, [x8, #6]', 'cmp w14, w11',
            'b.ne #0x1289000', 'cbz x10, #0x1288ffc', 'mov w14, #0xffff',
            'cmp w11, #0x29', 'b.hi #0x1288fd4', 'lsl x15, x12, x11',
            'tst x15, x13', 'b.eq #0x1288fd4', 'ldrh w14, [x8, #4]',
            'ldrb w15, [x10, #6]', 'cmp w15, #0x29', 'lsl x15, x12, x15',
            'and x15, x15, x13', 'ccmp x15, #0, #4, ls', 'b.eq #0x1289010',
            'ldrh w15, [x10, #4]', 'sxth w14, w14', 'cmp w14, w15, sxth',
            'b.ge #0x1289000', 'mov x10, x8', 'add x8, x8, #8', 'cmp x8, x9',
            'b.ne #0x1288fa8', 'b #0x1289018', 'mov w15, #0xffff', 'b #0x1288ff0',
            'cbz x10, #0x1289074', 'ldr w20, [x10]', 'bl #0x4403cd4',
            'add x0, x0, #0x28', 'str w20, [sp, #8]'])
    labels = {}
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try: root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
        except (zstandard.ZstdError, ET.ParseError): continue
        for record in root.iter('record'):
            values = {c.get('id'): c.get('value') for c in record if c.get('id')}
            if values.get('field') in {v[2] for v in bonuses.BONUSES.values()}:
                assert values['type'] == 'cash' and values.get('store_pence', 'false') == 'false'
                labels[values['field']] = values['name'].split('[COMMENT')[0].strip()
    for _, _, prop, label in bonuses.BONUSES.values(): assert labels[prop] == label
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'labels': labels,
               'native_kinds': {name: value[0] for name, value in bonuses.BONUSES.items()},
               'scope': 'Six stored current-contract cash entries, first-match selection and labels. No UI visibility, payment eligibility or other clause decoding.'}
    path = ROOT/'evidence/contract-bonus-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified six contract cash bonuses. {path}')


if __name__ == '__main__': verify()
