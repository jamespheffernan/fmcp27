"""Check installed editor labels and native getter mappings using background reads.

Run: uv run --with capstone --with zstandard python scripts/verify_staff_attribute_layout.py
This traverses disassembled branches locally. It never executes game functions.
"""
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
from fm_live_mcp import players, staff_attributes
from fm_live_mcp.bridge import Bridge


def property_case(code, prop):
    """Follow only the bounded integer comparison tree for a four-byte property ID."""
    registers = {'w21': int.from_bytes(prop.encode(), 'big')}
    pc, left, right = 0xC9A170, 0, 0
    def value(s):
        return int(s[1:], 0) if s.startswith('#') else registers[s]
    def signed(n):
        return n - (1 << 32) if n & (1 << 31) else n
    for _ in range(150):
        op, _, operands = code[pc].partition(' ')
        args, next_pc = operands.split(', '), pc + 4
        if op == 'mov':
            if args[0].startswith('x'): return pc
            registers[args[0]] = value(args[1])
        elif op == 'movk':
            shift = int(args[2].split('#')[1])
            registers[args[0]] = (registers.get(args[0], 0) & ~(65535 << shift)) | (value(args[1]) << shift)
        elif op == 'cmp': left, right = value(args[0]), value(args[1])
        elif op in ('add', 'sub'):
            if args[0].startswith('x'): return pc
            a, b = value(args[1]), value(args[2])
            registers[args[0]] = (a + b if op == 'add' else a - b) & 0xFFFFFFFF
        elif op.startswith('b.'):
            a, b = signed(left), signed(right)
            take = {'eq': left == right, 'ne': left != right, 'le': a <= b, 'lt': a < b,
                    'gt': a > b, 'ge': a >= b, 'hi': left > right, 'ls': left <= right,
                    'hs': left >= right, 'lo': left < right}[op[2:]]
            if take: next_pc = value(args[0])
        elif op == 'b': next_pc = value(args[0])
        else: return pc
        pc = next_pc
    raise ValueError('Property comparison tree exceeded bound')


def verify():
    bridge = Bridge()
    bridge.attach()
    try:
        with bridge._read_scope(bridge.session):
            process = bridge.process
            base = bridge._player_layout(process)[0] - players.RVA[0]
            def read(rva, size):
                return b''.join(bridge._read_memory(process, base + rva + start, min(16000, size - start))
                                for start in range(0, size, 16000))
            plugin = Path(bridge.plugin_identity[0][0])
            archive = plugin.parent.parent / 'Resources/shared/data/editor.fmf'
            data = archive.read_bytes()
            fields = {}
            for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), data):
                raw = zstandard.ZstdDecompressor().decompress(data[match.start():], max_output_size=10_000_000)
                if b'Ncha' not in raw or b'Npja' not in raw: continue
                try: root = ET.fromstring(raw)
                except ET.ParseError: continue
                for row in root.iter('record'):
                    values = {child.get('id'): child.get('value') for child in row if child.get('id')}
                    if values.get('type') == 'attribute' and values.get('field', '').startswith('N'):
                        fields[values['field']] = values['name'].split('[COMMENT')[0].strip()
            disassembler = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
            code = {}
            for rva, size in ((0xC9A0A8, 0x6108), (0xC8B220, 0x6A0)):
                code.update({i.address: f'{i.mnemonic} {i.op_str}' for i in disassembler.disasm(read(rva, size), rva)})
            jumps = struct.unpack('<45H', read(0x5387760, 90))
            scale = ['mov w9, #0x6667', 'mov w10, #0xccce', 'madd w8, w8, w9, w10',
                     'asr w9, w8, #0x11', 'add w8, w9, w8, lsr #31', 'cmp w8, #1',
                     'csinc w8, w8, wzr, gt', 'mov w9, #0x14', 'cmp w8, #0x14']
            assert [code[0xC8B504 + n * 4] for n in range(9)] == scale
            assert code[0xC8B528] == 'csel w0, w8, w9, lt'
            for value in range(101):
                assert max(1, min(20, (value * 26215 + 52430) >> 17)) == max(1, min(20, (value + 2) // 5))
            rows = []
            groups = {'attributes': staff_attributes.ATTRIBUTES, 'tendencies': staff_attributes.TENDENCIES,
                      'board_attributes': staff_attributes.BOARD}
            for group, mapping in groups.items():
                for name, (offset, fifths, prop) in mapping.items():
                    assert fields[prop].casefold().replace(' ', '_') == name, (prop, fields[prop], name)
                    entry = property_case(code, prop)
                    target = entry
                    if code[entry] == 'mov x0, x20':
                        index = int(code[entry + 4].split('#')[1], 0)
                        assert code[entry + 8] == 'mov w2, #1'
                        assert code[entry + 12] == 'bl #0xc8b220'
                        target = 0xC8B41C + jumps[index] * 4
                        assert code[target] == (f'ldrsb w8, [x19, #{offset:#x}]' if fifths else f'ldrb w0, [x19, #{offset:#x}]')
                        if target + 8 == 0xC8B504:
                            assert fifths and code[target + 4] == 'cbz w20, #0xc8b538'
                        else:
                            assert code[target + 4] == ('cbnz w20, #0xc8b504' if fifths else 'b #0xc8b41c')
                    else:
                        register = 'w8' if fifths else 'w20'
                        assert code[entry] == f'ldrsb {register}, [x20, #{offset:#x}]'
                        if fifths:
                            assert [code[entry + 4 + n * 4] for n in range(9)] == scale
                            assert code[entry + 40] == 'csel w20, w8, w9, lt'
                    rows.append({'group': group, 'name': name, 'editor_property': prop, 'editor_label': fields[prop],
                                 'property_case_rva': hex(entry), 'value_getter_rva': hex(target),
                                 'nonplayer_offset': hex(offset), 'fifths': fifths})
            entry = property_case(code, 'Npad')
            assert fields['Npad'] == 'Adaptability'
            assert [code[entry + n * 4] for n in range(4)] == ['mov x0, x20', 'mov w1, #0xb', 'mov w2, #1', 'bl #0xc8b220']
            target = 0xC8B41C + jumps[11] * 4
            assert [code[target + n * 4] for n in range(5)] == [
                'ldr x8, [x19]', 'ldur x8, [x8, #-0x18]', 'add x8, x19, x8', 'ldrb w0, [x8, #0x40]', 'b #0xc8b41c']
            rows.append({'group': 'attributes', 'name': 'adaptability', 'editor_property': 'Npad',
                         'property_case_rva': hex(entry), 'value_getter_rva': hex(target), 'person_data_offset': '0x40'})
            assert len(rows) == len(fields) == 39
            evidence = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
                        'plugin_sha256': players.SHA256, 'editor_sha256': hashlib.sha256(data).hexdigest(),
                        'fields': rows, 'scope': 'Static native getter mapping and installed editor labels. Stored values only; role/UI suppression is not applied. No game function execution or foreground UI comparison.'}
            output = ROOT / 'evidence/staff-attribute-layout-verification.json'
            output.write_text(json.dumps(evidence, indent=2) + '\n')
            print(f'Verified {len(rows)} editor labels, native property cases, offsets and scaling. {output}')
    finally:
        bridge.detach()


if __name__ == '__main__': verify()
