"""Prove independent PERSON identity fields using installed native code, read-only."""
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
        with bridge._read_scope(sid):
            bridge._player_layout(bridge.process)
            plugin = Path(bridge.plugin_identity[0][0])
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as source:
        def code(rva, size):
            source.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(source.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, 4*len(expected)).values())
            assert actual == expected, (hex(rva), actual)
        record = code(0x11B23E8, 0x1000)
        person = code(0x148F9B8, 0xA000)
        assert property_case(record, 'duni', 0x11B2404, 'w1') == 0x11B28C4
        assert property_case(record, 'rdui', 0x11B2404, 'w1') == 0x11B2AB0
        # PERSON delegates these properties to RECORD with the same person pointer.
        for prop in ('duni', 'rdui'):
            assert property_case(person, prop, 0x148FCC4, 'w21') == 0x1497C8C
        check(0x1497C8C, ['mov x0, x20', 'mov x1, x21', 'mov x2, x19'])
        check(0x1497CB4, ['b #0x11b23e8'])
        check(0x150CAA4, ['b #0x148f9b8'])
        check(0x11B28C4, ['ldr w20, [x20, #0xc]'])
        # Equal fields suppress rdui; unequal fields, including zero, are returned.
        check(0x11B2AEC, ['ldp w8, w20, [x20, #0xc]', 'cmp w8, w20', 'b.eq #0x11b30e8',
                          'bl #0x4403cd4', 'add x0, x0, #0x28', 'str w20, [sp, #0x20]'])
    result = {'verified': True, 'plugin_sha256': players.SHA256,
              'primary_property': 'duni', 'primary_person_offset': 12,
              'secondary_property': 'rdui', 'secondary_person_offset': 16,
              'equal_required': False, 'secondary_zero_allowed': True,
              'scope': 'Static native property delegation and independent fields; no native execution or UI automation.'}
    (ROOT/'evidence/person-identity-layout-verification.json').write_text(json.dumps(result, indent=2)+'\n')
    print('Verified independent person identity fields; equality is not a validity condition.')


if __name__ == '__main__':
    verify()
