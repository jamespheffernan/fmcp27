"""Trace installed editor labels to native main-contract entry fields, read-only.

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
from fm_live_mcp import contract_terms as terms, players
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case
from verify_contract_bonus_layout import verify as verify_bonus_layout


def person_contract_property(code, prop):
    """Follow only integer comparisons and property construction; no native calls."""
    regs = {'w21': int.from_bytes(prop.encode(), 'big')}
    pc, left, right = 0x148FCC4, 0, 0
    def val(s): return int(s[1:], 0) if s.startswith('#') else regs[s]
    def signed(n): return n - (1 << 32) if n & (1 << 31) else n
    for _ in range(220):
        if pc == 0x1498A20:
            return regs['w1'].to_bytes(4, 'big').decode()
        op, _, tail = code[pc].partition(' ')
        args, nxt = tail.split(', '), pc + 4
        if op == 'mov':
            if args[0].startswith('x'):
                assert args == ['x0', 'x20']
            else: regs[args[0]] = val(args[1]) & 0xFFFFFFFF
        elif op == 'movk':
            shift = int(args[2].split('#')[1])
            regs[args[0]] = (regs.get(args[0], 0) & ~(65535 << shift)) | val(args[1]) << shift
        elif op == 'cmp': left, right = val(args[0]), val(args[1])
        elif op == 'tst': left, right = val(args[0]) & val(args[1]), 0
        elif op in ('add', 'sub', 'lsl', 'orr'):
            a, b = val(args[1]), val(args[2])
            regs[args[0]] = (a + b if op == 'add' else a - b if op == 'sub' else a << (b & 31) if op == 'lsl' else a | b) & 0xFFFFFFFF
        elif op.startswith('b.'):
            a, b = signed(left), signed(right)
            take = {'eq': left == right, 'ne': left != right, 'le': a <= b, 'lt': a < b,
                    'gt': a > b, 'ge': a >= b, 'hi': left > right, 'ls': left <= right,
                    'hs': left >= right, 'lo': left < right}[op[2:]]
            if take: nxt = val(args[0])
        elif op == 'b': nxt = val(args[0])
        else: raise AssertionError((prop, hex(pc), code[pc]))
        pc = nxt
    raise AssertionError('Person property trace bound exceeded')


def verify():
    verify_bonus_layout()  # Shared ownership, main pointer, cash getter and traversal.
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    try:
        roster = bridge.get_managed_squad(sid)
        assert bridge.get_contract_terms(sid, player_ref=roster['players'][0]['player_ref'])['contract_terms']['state'] == 'decoded'
        plugin = Path(bridge.plugin_identity[0][0])
    finally: bridge.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva, size):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size), rva)}
        def check(rva, expected):
            actual = list(code(rva, len(expected) * 4).values())
            assert actual == expected, (hex(rva), actual, expected)
        person, full, base = code(0x148F9B8, 0x10AE0), code(0x128670C, 0x27C0), code(0xFF5678, 0x5DA4)
        cases = []
        for kind, field, slot, prop, editor, label in terms.FIELDS:
            if editor is not None: assert person_contract_property(person, editor) == prop, editor
            assert property_case(full, prop, 0x1286734, 'w1') == 0x1286F0C
            pc = property_case(base, prop, 0xFF56A4, 'w1')
            start, observed_slot, observed_kind = pc, None, None
            for _ in range(20):
                inst = base[pc]
                if inst.startswith('ldr x3, [x8, #') or inst.startswith('ldr x8, [x8, #'):
                    observed_slot = int(inst.split('#')[1].split(']')[0], 0) // 8
                elif inst.startswith('mov w1, #'): observed_kind = int(inst.split('#')[1], 0)
                elif inst == 'blr x8':
                    assert slot == 46
                    check(pc + 4, ['cmp x0, #0', 'cset w20, ne'])
                    break
                elif inst == 'mov x2, x19':
                    assert slot in (52, 54, 56)
                    break
                elif inst.startswith('b #'):
                    pc = int(inst.split('#')[1], 0)
                    continue
                else: assert inst in ('ldr x8, [x20]', 'mov x0, x20'), (prop, hex(pc), inst)
                pc += 4
            else: raise AssertionError('Contract case trace bound exceeded')
            assert (observed_kind, observed_slot) == (kind, slot), (prop, observed_kind, observed_slot)
            if slot == 54: assert terms.PARAMETER_MASK & 1 << kind
            if slot == 56: assert kind in (0, 16, 17, 18, 27, 31)
            cases.append({'kind': kind, 'field': field, 'editor': editor, 'contract_property': prop, 'case': hex(start), 'slot': slot})
        # Presence getter and parameter getter use the same entry selection as cash.
        check(0x1288E8C, ['ldp x8, x9, [x0, #0x68]', 'cmp x8, x9', 'b.eq #0x1288f20',
            'mov x0, #0', 'and w10, w1, #0xff', 'mov w11, #1', 'mov x12, #0xef38',
            'movk x12, #0x2778, lsl #16', 'movk x12, #0x300, lsl #32'])
        check(0x1288EF4, ['ldrh w14, [x0, #4]', 'sxth w13, w13', 'cmp w13, w14, sxth',
            'b.ge #0x1288f08', 'mov x0, x8', 'add x8, x8, #8', 'cmp x8, x9',
            'b.ne #0x1288eb0', 'b #0x1288f24', 'mov w14, #0xffff', 'b #0x1288ef8', 'mov x0, #0', 'ret'])
        check(0x12893FC, ['ldp x9, x10, [x21, #0x68]', 'cmp x9, x10', 'b.eq #0x1289508',
            'mov x8, #0', 'and w12, w20, #0xff', 'mov w13, #1', 'mov x11, #0xef38',
            'movk x11, #0x2778, lsl #16', 'movk x11, #0x300, lsl #32'])
        check(0x1289464, ['ldrh w15, [x8, #4]', 'sxth w14, w14', 'cmp w14, w15, sxth',
            'b.ge #0x1289478', 'mov x8, x9', 'add x9, x9, #8', 'cmp x9, x10',
            'b.ne #0x1289420', 'b #0x1289490', 'mov w15, #0xffff', 'b #0x1289468'])
        check(0x1289490, ['cbz x8, #0x1289508', 'ldrb w9, [x8, #6]', 'cmp w9, #0x29',
            'mov w10, #1', 'lsl x9, x10, x9', 'and x9, x9, x11', 'ccmp x9, #0, #4, ls',
            'b.eq #0x1289520', 'ldrsh w20, [x8, #4]', 'bl #0x4403cd4',
            'add x0, x0, #0x28', 'str w20, [sp, #8]'])
        # Date getter: signed parameter, mode suppression and signed-date offset.
        check(0x128989C, ['cbz x8, #0x1289954', 'mov w21, #1', 'movk w21, #0x76c, lsl #16',
            'ldrsh w1, [x8, #4]', 'tbnz w1, #0x1f, #0x12898f4', 'adrp x9, #0x56d4000',
            'ldrb w9, [x9, #0x950]', 'sub w9, w9, #1', 'cmp w9, #3', 'b.lo #0x12898f4',
            'ldrb w8, [x8, #6]', 'cmp w8, #0x1f', 'b.hi #0x128996c', 'mov w9, #1',
            'lsl w9, w9, w8', 'mov w10, #1', 'movk w10, #0x8807, lsl #16',
            'tst w9, w10', 'b.eq #0x128996c', 'add x0, x20, #0x44', 'bl #0x42e9b44', 'mov x21, x0'])
        assert all((1 << kind) & 0x88070001 for kind in (0, 16, 17, 18, 27, 31))
        check(0x42E9B44, ['tbnz w1, #0x1f, #0x42e9bc8', 'ldrh w8, [x0]',
            'and w9, w8, #0x1ff', 'add w9, w1, w9', 'ldrh w14, [x0, #2]',
            'sub w10, w9, #1', 'mov w11, #0x5c29', 'mov w12, #3', 'mov w13, #0xf',
            'b #0x42e9b74', 'add w10, w14, w10', 'add w14, w9, #1',
            'and w9, w14, #0xffff', 'mul w14, w14, w11', 'and w14, w14, #0xffff',
            'cmp w14, #0xa3e', 'csel w15, w13, w12, lo', 'sxth w14, w10', 'tst w15, w9',
            'b.eq #0x42e9ba4', 'cmp w14, #0x16d', 'b.lt #0x42e9bb4',
            'mov w14, #0xfe93', 'b #0x42e9b6c', 'cmp w14, #0x16e', 'b.lt #0x42e9bb4',
            'mov w14, #0xfe92', 'b #0x42e9b6c', 'add w10, w10, #1',
            'and w0, w8, #0xfe00', 'bfxil w0, w10, #0, #9', 'bfi w0, w9, #0x10, #0x10', 'ret'])
        # Additional kinds have native string-table labels but no editor PERSON field.
        check(0x1000818, ['cmp w9, #0x39', 'b.hi #0x1000be8', 'mov w8, w9',
            'adrp x9, #0x538e000', 'add x9, x9, #0x30a', 'adr x10, #0x100083c',
            'ldrb w11, [x9, x8]', 'add x10, x10, x11, lsl #2', 'br x10'])
        stream.seek(0x5ED4000 + 0x538E30A)
        jumps = stream.read(58)
        for kind, translation in terms.NATIVE_LABELS.items():
            check(0x100083C + jumps[kind] * 4, ['mov x8, sp',
                f'mov w1, #{translation & 65535:#x}', f'movk w1, #{translation >> 16}, lsl #16',
                'bl #0x43db8b8'])
    labels = {}
    archive = (plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
    fields = {f[4] for f in terms.FIELDS if f[4] is not None}
    for match in re.finditer(re.escape(b'\x28\xb5\x2f\xfd'), archive):
        try: root = ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():], max_output_size=10_000_000))
        except (zstandard.ZstdError, ET.ParseError): continue
        for row in root.iter('record'):
            d = {c.get('id'): c.get('value') for c in row if c.get('id')}
            if d.get('field') in fields: labels[d['field']] = d
    language = (plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
    native_labels = {int(m[1]): m[2].split('[COMMENT')[0].strip() for line in language.splitlines()
                     if (m := re.match(r'KEY-(\d+): (.*)', line))}
    for kind, field, slot, prop, editor, label in terms.FIELDS:
        if editor is None:
            assert native_labels[terms.NATIVE_LABELS[kind]] == label
            continue
        d = labels[editor]
        assert d['name'].split('[COMMENT')[0].strip() == label, (editor, d['name'], label)
        assert d['type'] == {46: 'boolean', 52: 'cash', 54: 'integer', 56: 'date'}[slot]
        if slot == 52: assert d.get('store_pence', 'false') == 'false'
        if field == 'weekly_wage_gbp': assert d['is_weekly_wage'] == 'true'
    assert set(terms.KINDS) == {f[0] for f in terms.FIELDS}
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'kinds': len(terms.KINDS), 'fields': cases,
               'scope': 'Stored entry types, cash/parameter/presence fields, native selection and signed-date expiry calculation. No trigger activation or UI visibility.'}
    path = ROOT/'evidence/contract-term-layout-verification.json'
    path.write_text(json.dumps(receipt, indent=2)+'\n')
    print(f'Verified {len(terms.KINDS)} entry kinds and {len(cases)} fields. {path}')


if __name__ == '__main__': verify()
