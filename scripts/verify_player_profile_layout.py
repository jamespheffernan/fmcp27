"""Check profile labels, property dispatch, getters, scaling and virtual cache delegates.

Run with uv run --no-project --with capstone --with zstandard python ...
Only reads installed resources/code and live vtables; never executes game functions.
"""
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp import player_profile as profile, players, world
from fm_live_mcp.bridge import Bridge


def property_case(code, prop, entry, register):
    regs = {register: int.from_bytes(prop.encode(), 'big')}
    pc, left, right = entry, 0, 0
    def value(s): return int(s[1:], 0) if s.startswith('#') else regs[s]
    def signed(n): return n - (1 << 32) if n & (1 << 31) else n
    for _ in range(160):
        op, _, tail = code[pc].partition(' ')
        args, nxt = tail.split(', '), pc + 4
        if op == 'mov':
            if args[0].startswith('x'): return pc
            regs[args[0]] = value(args[1]) & 0xFFFFFFFF
        elif op == 'movk':
            shift = int(args[2].split('#')[1])
            regs[args[0]] = (regs.get(args[0], 0) & ~(65535 << shift)) | (value(args[1]) << shift)
        elif op == 'cmp': left, right = value(args[0]), value(args[1])
        elif op == 'tst': left, right = value(args[0]) & value(args[1]), 0
        elif op in ('add', 'sub', 'lsl'):
            if args[0].startswith('x'): return pc
            a, b = value(args[1]), value(args[2])
            regs[args[0]] = (a + b if op == 'add' else a - b if op == 'sub' else a << (b & 31)) & 0xFFFFFFFF
        elif op.startswith('b.'):
            a, b = signed(left), signed(right)
            take = {'eq': left == right, 'ne': left != right, 'le': a <= b, 'lt': a < b,
                    'gt': a > b, 'ge': a >= b, 'hi': left > right, 'ls': left <= right,
                    'hs': left >= right, 'lo': left < right}[op[2:]]
            if take: nxt = value(args[0])
        elif op == 'b': nxt = value(args[0])
        else: return pc
        pc = nxt
    raise ValueError('Property comparison bound exceeded')


def verify():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        with bridge.lock, bridge._read_scope(sid):
            process = bridge.process
            base = bridge._player_layout(process)[0] - players.RVA[0]
            plugin = Path(bridge.plugin_identity[0][0])
            snapshot = world.ReadSet(lambda a, n: bridge._read_memory(process, a, n))
            for rva in (players.RVA[0], players.STAFF_RVA[0]):
                profile.verify_getters(snapshot, base, base + rva)
            profile.verify_getters(snapshot, base, base + world.TYPES['virtual_player'][0], profile.VIRTUAL_GETTERS)
            snapshot.verify()
    finally:
        bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as f:
        def disasm(rva, length):
            f.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(f.read(length), rva)}
        code = disasm(0x1503624, 0xD188) | disasm(0x1561580, 0x19F4)
        def check(rva, expected):
            actual = list(disasm(rva, 4*len(expected)).values())
            assert actual == expected, (hex(rva), actual, expected)
        check(0x1503698, ['ldr x8, [x20]', 'ldr x8, [x8, #0x388]', 'mov x0, x20', 'blr x8',
                         'mov x1, x21', 'mov x2, x19', 'bl #0x1561580'])
        check(0xD09E68, ['add x0, x0, #0x140', 'ret'])
        check(0xD09D58, ['ldrsh w0, [x0, #0x25c]', 'ret'])
        check(0xD28D64, ['ldrsh w0, [x0, #0x25e]', 'ret'])
        check(0xD1414C, ['ldrsb w9, [x0, #0x270]', 'add x8, x0, w1, sxtw', 'ldrsb w8, [x8, #0x148]',
                         'tbnz w9, #0x1f, #0xd14164', 'and w8, w8, #0xff', 'b #0xd1418c',
                         'mov w9, #0x6667', 'mov w10, #0xccce', 'madd w8, w8, w9, w10',
                         'asr w9, w8, #0x11', 'add w8, w9, w8, lsr #31', 'cmp w8, #1',
                         'csinc w8, w8, wzr, gt', 'mov w9, #0x14', 'cmp w8, #0x14',
                         'csel w8, w8, w9, lt', 'sxtb w0, w8', 'ret'])
        # Virtual getters obtain the existing/generated profile before using identical fields.
        # Production uses only the already materialized identity-checked cache.
        virtual_loads = {6: ('ldrsh', 0x25C), 7: ('ldrsh', 0x25E),
                         **{v[1]: ('ldrsb', v[0]) for v in profile.POSITIONS.values()}}
        for slot, (op, offset) in virtual_loads.items():
            rva = profile.VIRTUAL_GETTERS[slot]
            check(rva + 0x1C, ['bl #0x18a0ed0', f'{op} w0, [x0, #{offset:#x}]'])
        check(0x18A70CC, ['bl #0x18a0ed0', 'add x0, x0, #0x140'])
        check(0x18A6918, ['bl #0x18a0ed0', 'ldrsb w9, [x0, #0x270]', 'add x8, x0, w19, sxtw',
                          'ldrsb w8, [x8, #0x148]', 'tbnz w9, #0x1f, #0x18a6934',
                          'and w8, w8, #0xff', 'b #0x18a695c', 'mov w9, #0x6667',
                          'mov w10, #0xccce', 'madd w8, w8, w9, w10', 'asr w9, w8, #0x11',
                          'add w8, w9, w8, lsr #31', 'cmp w8, #1', 'csinc w8, w8, wzr, gt',
                          'mov w9, #0x14', 'cmp w8, #0x14', 'csel w8, w8, w9, lt', 'sxtb w0, w8'])
        fields, ranges = {}, None
        archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
        for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
            try: root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
            except (zstandard.ZstdError, ET.ParseError): continue
            if b'PCAB' not in ET.tostring(root): continue
            for row in root.iter('record'):
                values = {c.get('id'): c.get('value') for c in row if c.get('id')}
                if values.get('field') and values.get('name'):
                    fields[values['field']] = values['name'].split('[COMMENT')[0].strip()
                if values.get('field') == 'PPAR' and row.find("list[@id='enum_values']") is not None:
                    ranges = {int(e.get('enum')): tuple(map(int, e.find('string').get('value').split('-')))
                              for e in row.find("list[@id='enum_values']")}
        assert ranges == profile.POTENTIAL_RANGES
        results = []
        for prop, label, slot, case in [('PCAB', 'Current Ability', 6, 0x1509210), ('PPAB', 'Potential Ability', 7, 0x150AC90)]:
            assert fields[prop] == label and property_case(code, prop, 0x1503774, 'w21') == case
            check(case, ['ldr x8, [x20]', f'ldr x8, [x8, #{slot*8:#x}]', 'mov x0, x20', 'blr x8'])
            results.append({'property': prop, 'label': label, 'slot': slot})
        for name, (offset, slot, getter, prop, label, case) in profile.POSITIONS.items():
            assert fields[prop] == label and property_case(code, prop, 0x1503774, 'w21') == case, prop
            check(case, ['ldr x8, [x20]', f'ldr x8, [x8, #{slot*8:#x}]', 'mov x0, x20', 'blr x8'])
            check(getter, [f'ldrsb w0, [x0, #{offset:#x}]', 'ret'])
            results.append({'property': prop, 'label': label, 'offset': hex(offset), 'slot': slot})
        for mapping in (profile.GOALKEEPING, profile.HIDDEN, profile.FEET):
            for name, (offset, prop, label) in mapping.items():
                assert fields[prop] == label
                case = property_case(code, prop, 0x156159C, 'w1')
                assert code[case] == f'ldrsb w20, [x8, #{offset-0x140:#x}]', (prop, hex(case))
                results.append({'property': prop, 'label': label, 'offset': hex(offset), 'case': hex(case)})
    assert len(results) == 34
    evidence = {'verified': True, 'plugin_sha256': players.SHA256, 'fields': results,
                'layouts': ['regular', 'combined_player_staff', 'cached_virtual'],
                'potential_range_codes': len(ranges), 'scope': 'Stored native values; no scouting mask, stars, role recommendation or UI comparison.'}
    Path('evidence/player-profile-layout-verification.json').write_text(json.dumps(evidence, indent=2)+'\n')
    print(f'Verified {len(results)} profile fields, scaling branches, range codes and three native layouts.')


if __name__ == '__main__': verify()
