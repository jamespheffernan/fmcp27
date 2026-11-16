"""Verify stored health fields, injury-vector semantics and typed injury names.

Run with uv run --no-project --with capstone --with zstandard python ...
Only inspects code/resources and live data; no native refresh or game function calls.
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
from fm_live_mcp import database, player_health, players, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            base = bridge._player_layout(bridge.process)[0] - players.RVA[0]
            plugin = Path(bridge.plugin_identity[0][0])
            snapshot = world.ReadSet(lambda a, n: bridge._read_memory(bridge.process, a, n))
            for rva in (players.RVA[0], players.STAFF_RVA[0]):
                player_health.verify_getters(snapshot, base, base + rva)
            player_health.verify_getters(snapshot, base, base + world.TYPES['virtual_player'][0], virtual=True)
            info = database.table(snapshot, base, 'injuries')
            definitions = []
            for index in range(info['count']):
                address = world.pointer(snapshot, info['start'] + index*8)
                world.typed(snapshot, base, address, 'injury')
                raw = snapshot(address, 0x28)
                assert int.from_bytes(raw[8:12], 'little') == index and raw[12:16] == raw[16:20]
                assert players.u64(snapshot(base + world.TYPES['injury'][0] + 3*8, 8)) == base + 0x1329D64
                definitions.append(world.string(snapshot, players.u64(raw, 0x18)))
            snapshot.verify()
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as f:
        def code(rva, size):
            f.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(f.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected)*4).values())
            assert actual == expected, (hex(rva), actual, expected)
        c = code(0x1503624, 0xD188)
        for prop, slot, case, getter, offset in [('Pcon',138,0x1509140,0xD3012C,0x254),
            ('Pfit',139,0x150A570,0xD19E70,0x250), ('Pjad',141,0x1505030,0xD3016C,0x252)]:
            assert property_case(c, prop, 0x1503774, 'w21') == case
            dispatch = 0x150B23C if prop == 'Pcon' else case
            check(dispatch, ['ldr x8, [x20]', f'ldr x8, [x8, #{slot*8:#x}]', 'mov x0, x20', 'mov w1, #1', 'blr x8'])
            check(getter+0x10, [f'cbz w1, #{getter+0x30:#x}', 'adrp x8, #0x56d2000', 'ldr x0, [x8, #0xd08]',
                'ldr x8, [x0]', 'ldr x8, [x8, #0x278]', 'mov x1, x19', 'mov w2, #1', 'blr x8', f'ldrsh w0, [x19, #{offset:#x}]'])
        # Condition's property can suppress the stored value for an injured player.
        check(0x1509140, ['ldr x8, [x20]', 'ldr x8, [x8, #0xa8]', 'mov x0, x20', 'blr x8',
            'cbz w0, #0x150b23c', 'ldr x8, [x20]', 'ldr x8, [x8, #0xb8]', 'mov x0, x20', 'blr x8',
            'cmp w0, #0', 'b.le #0x150b23c', 'mov w20, #-1', 'b #0x150b254'])
        check(0xD09BB0, ['ldr x8, [x0, #0xf0]', 'cbz x8, #0xd09bc8', 'ldp x9, x8, [x8]',
            'cmp x9, x8', 'cset w0, ne', 'ret', 'mov w0, #0', 'ret'])
        check(0xD2CAD0, ['ldr x0, [x8, x22, lsl #3]', 'cbz x0, #0xd2caec', 'mov x1, x20', 'bl #0x154d334'])
        check(0xD09C4C, ['ldrsh w9, [x22, #0x28]', 'tbnz w9, #0x1f, #0xd09cb4',
            'ldrh w8, [x22, #0x22]', 'ldrh w10, [x22, #0x20]', 'and w10, w10, #0x1ff'])
        # Native injury-info property builder publishes definition +8 as injr and date +20 as iida.
        check(0x154C6D8, ['ldr x0, [x21, #8]', 'add x1, sp, #0x20', 'bl #0x101e81c',
            'add x2, sp, #0x20', 'mov x0, x19', 'mov w1, #0x6a72', 'movk w1, #0x696e, lsl #16', 'bl #0x43f82a0'])
        check(0x154C708, ['ldrh w8, [x21, #0x20]', 'ldrh w9, [x21, #0x22]', 'lsr w10, w8, #9',
            'orr w9, w10, w9, lsl #17', 'bfi w9, w8, #8, #9', 'str w9, [sp, #0x18]'])
        check(0x154C734, ['mov w1, #0x6461', 'movk w1, #0x6969, lsl #16', 'bl #0x43f82a0'])
        c = code(0x1329D64, 0xD20)
        for prop, case, offset in [('Inam',0x132A6A0,0x18), ('Isnm',0x132A768,0x20)]:
            assert property_case(c, prop, 0x1329D7C, 'w1') == case
            check(case, ['mov x20, x0', 'bl #0x4403cd4', f'ldr x8, [x20, #{offset:#x}]'])
        check(0xD5BEA8, ['mov w0, #0', 'ret'])
        check(0xD5C1A4, ['mov w0, #0', 'ret'])
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    labels = {}
    wanted = {'Pcon': 'Overall Physical Condition', 'Pfit': 'Match Sharpness', 'Pjad': 'Fatigue', 'Inam': 'Name', 'Isnm': 'Sentence Name'}
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try: root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
        except (ET.ParseError, zstandard.ZstdError): continue
        for row in root.iter('record'):
            values = {c.get('id'): c.get('value') for c in row if c.get('id')}
            prop = values.get('field')
            if prop in wanted and values.get('name'):
                label = values['name'].split('[COMMENT')[0].strip()
                assert label == wanted[prop]
                labels[prop] = label
                if prop == 'Pjad': assert 'higher the value the more fatigued' in values['hint']
    assert labels == wanted
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(), 'plugin_sha256': players.SHA256,
        'labels': labels, 'injury_definition_count': len(definitions), 'injury_names': definitions,
        'scope': 'Stored fitness branch without refresh; live injury vector/definition/name/start-date mappings; virtual zero defaults. No UI comparison or eligibility inference.'}
    path = ROOT/'evidence/player-health-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified stored health getters, injury links and {len(definitions)} typed injury definitions. {path}')


if __name__ == '__main__': verify()
