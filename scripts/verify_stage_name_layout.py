"""Verify stored fixture naming components against native getters and editor labels."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

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
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    checks = []
    with plugin.open('rb') as stream:
        def read(rva, size):
            stream.seek(0x5ED4000+rva)
            raw = stream.read(size)
            assert len(raw) == size
            return raw
        def check(rva, expected):
            raw = read(rva, len(expected)*4)
            actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw, rva)]
            assert actual == expected, (hex(rva), actual, expected)
            checks.append({'rva': hex(rva), 'sha256': hashlib.sha256(raw).hexdigest()})
        def pointer(rva):
            return struct.unpack('<Q', read(rva, 8))[0] & 0xFFFFFFFF
        for vtable, name in ((0x55A1C10, 'N2db14DATABASE_TABLEINS_10STAGE_NAMEEEE'),
                             (0x55BD9E8, 'N2db10STAGE_NAMEE'), (0x55AB970, 'N2db12FIXTURE_NAMEE')):
            assert struct.unpack('<q', read(vtable-16, 8))[0] == 0
            assert read(pointer(pointer(vtable-8)+8), len(name)+1) == name.encode()+b'\0'
        assert pointer(0x55BD9E8+24) == 0x16E2D4C
        # Native ID lookup uses the singleton table and record +0xC, not a table index.
        check(0x1320BD0, ['ldr w1, [x28, #4]', 'adrp x24, #0x56d2000', 'cmn w1, #1',
                          'b.eq #0x1320bf0', 'ldr x0, [x24, #0xda8]', 'bl #0x10b1700'])
        check(0x10B1744, ['ldr x0, [x8, w11, uxtw #3]', 'ldr w12, [x0, #0xc]', 'cmp w12, w1'])
        check(0x16E2D84, ['mov w8, #0x6e61', 'movk w8, #0x534e, lsl #16',
                          'cmp w1, w8', 'b.ne #0x16e2e84', 'bl #0x4403cd4', 'ldr x8, [x20, #0x18]'])
        check(0x16E2E0C, ['mov w8, #0x736e', 'movk w8, #0x534e, lsl #16',
                          'cmp w1, w8', 'b.ne #0x16e2e84', 'bl #0x4403cd4', 'ldr x8, [x20, #0x20]'])
        check(0x16E2DFC, ['mov w8, #0x706e', 'movk w8, #0x534e, lsl #16', 'cmp w1, w8', 'b.eq #0x16e2efc'])
        check(0x16E2EFC, ['bl #0x4403cd4', 'ldr x8, [x20, #0x28]'])
        # Formatter reads two competition fields and up to three stage-name slots.
        check(0x1263DD0, ['ldr x8, [x0, #0x18]', 'str x8, [sp, #0x10]',
                          'ldr x8, [x0, #0x40]', 'str x8, [x4]'])
        check(0x1263F2C, ['ldr x8, [x20, #0x20]', 'cbz x8, #0x1263f58'])
        check(0x1263F48, ['ldrsb x9, [x21]', 'add w10, w9, #1', 'strb w10, [x21]', 'str x8, [x22, x9, lsl #3]'])
        check(0x1263F58, ['ldr x8, [x20, #0x28]', 'cbz x8, #0x1263f70',
                          'ldrsb x9, [x21]', 'add w10, w9, #1', 'strb w10, [x21]', 'str x8, [x22, x9, lsl #3]'])
        check(0x1263F70, ['mov x28, x20', 'ldr x8, [x28, #0x30]!', 'cbz x8, #0x1264098'])
        check(0x1264084, ['ldr x1, [x28]', 'ldrsb x8, [x21]', 'add w9, w8, #1',
                          'strb w9, [x21]', 'str x1, [x22, x8, lsl #3]'])
        check(0x1263B58, ['mov x8, sp', 'mov w1, #0xbb60', 'movk w1, #6, lsl #16', 'bl #0x43db8b8'])
        check(0x1263B6C, ['mov x8, sp', 'mov w1, #0xbb5f', 'movk w1, #6, lsl #16', 'bl #0x43db8b8'])
        check(0x1263C88, ['mov x8, sp', 'mov w1, #0x78bd', 'movk w1, #3, lsl #16', 'bl #0x43db8b8'])
    resources = plugin.parent.parent/'Resources'
    language = (resources/'data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
    labels = {int(m[1]): m[2].split('[COMMENT')[0].strip() for m in re.finditer(r'^KEY-(\d+): (.*)', language, re.M)}
    assert labels[0x378BD] == '[%comp#1-long] [%stage_name#1-long] [%stage_name#2-long] [%stage_name#3-long]'
    assert labels[0x6BB5F] == '[%comp#1-short]/[%comp#2-short] [%stage_name#1-long] [%stage_name#2-long] [%stage_name#3-long]'
    assert labels[0x6BB60] == '[%comp#1-short]/[%comp#2-short] [%stage_name#1-long] [%stage_name#2-long]'
    archive = (resources/'shared/data/editor.fmf').read_bytes()
    fields = {}
    for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')), archive):
        try:
            tree = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10000000))
        except (zstandard.ZstdError, ET.ParseError):
            continue
        for row in tree.iter('record'):
            field, name = row.find("flags[@id='field']"), row.find("translation[@id='name']")
            if field is not None and name is not None and field.get('value') in ('SNna','SNsn','SNpn'):
                fields[field.get('value')] = name.get('value')
    assert fields == {'SNna':'Name', 'SNsn':'Short Name', 'SNpn':'Plural Name'}
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'checks': checks, 'editor_fields': fields,
               'scope': 'Stored name properties, fixture-name component slots and second competition; no localized formatter execution or display equivalence',
               'foreground_ui_used': False, 'native_execution': False}
    (ROOT/'evidence/stage-name-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified {len(checks)} native spans, three formatter labels and three editor labels.')


if __name__ == '__main__':
    verify()
