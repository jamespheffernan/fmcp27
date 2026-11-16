"""Verify resident fixture traversal and named score fields without executing game code."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

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
            stream.seek(0x5ED4000 + rva)
            data = stream.read(size)
            assert len(data) == size
            return data

        def check(rva, expected):
            raw = read(rva, len(expected)*4)
            actual = [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(raw, rva)]
            assert actual == expected, (hex(rva), actual, expected)
            checks.append({'rva': hex(rva), 'sha256': hashlib.sha256(raw).hexdigest()})

        def pointer(rva):
            # Offline chained fixups; these verified targets lie within this image.
            return struct.unpack('<Q', read(rva, 8))[0] & 0xFFFFFFFF

        def vtable(rva, name, slots):
            assert struct.unpack('<q', read(rva-16, 8))[0] == 0
            typeinfo = pointer(rva-8)
            assert read(pointer(typeinfo+8), len(name)+1) == name.encode()+b'\0'
            for slot, target in slots.items():
                assert pointer(rva+slot*8) == target

        vtable(0x55DD068, '23GAME_RULE_GROUP_MANAGER', {})
        vtable(0x55DC600, '17GAME_COMP_MANAGER', {})
        vtable(0x5672C88, 'N7sicomps7FIXTUREE', {6: 0x3D03084})
        vtable(0x5672E00, 'N7sicomps14FIXTURE_RESULTE', {6: 0x3CFBAA8, 7: 0x3CFB8F8})
        vtable(0x55A16E8, 'N2db14DATABASE_TABLEINS_12FIXTURE_NAMEEEE', {})
        vtable(0x55AB970, 'N2db12FIXTURE_NAMEE', {})
        vtable(0x55FA3E0, '26GAME_MATCH_DATABASE_HELPER', {0x1D0//8: 0x2E88B4C})
        # The native game database helper resolves the stored fixture-name COMP link.
        check(0x2E88B98, ['ldr x0, [x1, #0x18]', 'ldp x29, x30, [sp], #0x10', 'ret'])
        check(0x3CF658C, ['ldr x1, [x8, #0x20]', 'cbz x1, #0x3cf65b8'])
        check(0x3CF659C, ['ldr x8, [x0]', 'ldr x8, [x8, #0x1d0]', 'blr x8',
                          'cbz x0, #0x3cf65b0', 'ldr x0, [x0, #0xb0]'])

        # TEAM next-match lookup reaches the central embedded manager, not a team cache vector.
        check(0x17748C8, ['adrp x8, #0x56d5000', 'ldr x8, [x8, #0x7d0]',
                          'ldr x22, [x8, #0x158]'])
        check(0x17748FC, ['add x0, x22, #8', 'add x2, sp, #0x1c', 'strb wzr, [sp]',
                          'mov x1, x19', 'mov x3, x20', 'mov x4, #0', 'mov x5, #0',
                          'mov w6, #1', 'mov w7, #1', 'bl #0x3d1cfd0'])
        check(0x3D1F148, ['ldrh w8, [x20, #0x40]', 'cmp w8, w21',
                          'b.ne #0x3d1f15c', 'mov x19, x20', 'b #0x3d1f3f8'])
        check(0x3D1F15C, ['ldr x9, [x20]', 'ldp x9, x10, [x9]', 'subs x10, x10, x9'])
        check(0x3D1F178, ['ldr x19, [x9]', 'ldrh w11, [x19, #0x40]',
                          'cmp w11, w21', 'b.eq #0x3d1f3f8'])
        check(0x3D1F19C, ['ldrb w8, [x20, #0x43]', 'tbz w8, #0, #0x3d1f284',
                          'ldr x8, [x20, #8]', 'ldp x8, x9, [x8]'])
        check(0x3D1F1C0, ['ldr x19, [x8]', 'ldrh w10, [x19, #0x40]',
                          'cmp w10, w21', 'b.eq #0x3d1f3f8'])

        # Date year is the upper halfword; ordinal day is the low nine bits minus one.
        check(0x3D1F594, ['mov x20, x1', 'ldrh w1, [x1, #2]'])
        check(0x3D1F5D4, ['ldrh w8, [x0, #0x40]', 'cmp w1, w8', 'b.ne #0x3d1f624',
                          'ldrh w8, [x20]', 'and w8, w8, #0x1ff', 'sub w8, w8, #1',
                          'mov x1, x2', 'mov x2, x8', 'mov w3, #0'])
        check(0x3D1F608, ['b #0x3d2246c'])
        check(0x3D22488, ['ldr x8, [x0, #0x10]', 'ldr x20, [x8, w1, uxtw #3]',
                          'ldrb w8, [x20, #0xb70]', 'tbnz w8, #0, #0x3d224d8'])
        # An unset flag takes a mutating materialization call. Our readers must skip it.
        check(0x3D224B0, ['ldr x9, [x8]', 'ldr x9, [x9, #0x2c0]', 'add x2, sp, #8',
                          'mov x0, x8', 'mov x1, x20', 'mov x21, x3', 'blr x9',
                          'mov x3, x21', 'mov w8, #1', 'strb w8, [x20, #0xb70]'])
        check(0x3D224D8, ['cmp w19, #0x16d', 'b.hi #0x3d2258c',
                          'ldr x21, [x20, w19, sxtw #3]'])

        check(0x3CF6CD0, ['add x8, x0, x1, lsl #3', 'ldr x0, [x8, #8]', 'ret'])
        check(0x20784C, ['ldr x0, [x19, #0x30]', 'mov x1, #0', 'bl #0x3cf6cd0'])
        check(0x20786C, ['mov w0, #0x6d54', 'movk w0, #0x6668, lsl #16', 'bl #0x201174'])
        check(0x207890, ['ldr x0, [x19, #0x30]', 'mov w1, #1', 'bl #0x3cf6cd0'])
        check(0x2078CC, ['mov w0, #0x7754', 'movk w0, #0x6661, lsl #16', 'bl #0x201174'])
        check(0x209164, ['mov w8, #0x7465', 'movk w8, #0x6664, lsl #16',
                          'cmp w22, w8', 'b.ne #0x20af90', 'bl #0x42f038c',
                          'add x1, sp, #0x68', 'add x2, x20, #0x4c', 'bl #0x42f05b8'])

        # fdte -> UI fxdt -> localized Kick Off date parameter; preserve its time bits.
        check(0x201288, [
            'mov w1, #0x7465',
            'movk w1, #0x6664, lsl #16',
            'bl #0x77f180',
            'mov x1, x0',
            'add x0, sp, #0xc',
            'bl #0x42eaaf4',
        ])
        check(0x42eaaf4, [
            'lsr w8, w1, #0x11',
            'strh w8, [x0, #2]',
            'lsl w8, w1, #9',
            'bfxil w8, w1, #8, #9',
            'strh w8, [x0]',
            'ret',
        ])
        check(0x1f5960, [
            'add x0, x20, #0x18',
            'bl #0x201250',
            'stur w0, [x29, #-0x98]',
            'bl #0x42f038c',
            'sub x1, x29, #0x78',
            'sub x2, x29, #0x98',
            'bl #0x42f05b8',
            'sub x0, x29, #0x58',
            'sub x2, x29, #0x78',
            'mov w1, #0x6474',
            'movk w1, #0x6678, lsl #16',
            'bl #0x43f72e4',
        ])
        check(0x13169c, [
            'mov w1, #0x6474',
            'movk w1, #0x6678, lsl #16',
            'bl #0x43f899c',
            'mov x23, x0',
            'bl #0x42f038c',
            'mov x1, x23',
            'bl #0x42f0600',
            'stur w0, [x29, #-0x7c]',
        ])
        check(0x1319a0, [
            'mov x0, x28',
            'mov w1, #0xb24d',
            'movk w1, #3, lsl #16',
            'bl #0x43db8b8',
        ])
        check(0x1319c4, [
            'sub x8, x29, #0xa0',
            'sub x0, x29, #0x7c',
            'bl #0x42d6dd8',
            'sub x0, x29, #0x78',
            'sub x2, x29, #0xa0',
            'mov w1, #2',
            'mov w3, #0',
            'bl #0x43d1f9c',
        ])
        check(0x131f18, [
            'sub x8, x29, #0xa0',
            'mov x0, x28',
            'mov w1, #0xb24e',
            'movk w1, #3, lsl #16',
            'bl #0x43db8b8',
            'sub x0, x29, #0x78',
            'sub x1, x29, #0xa0',
            'bl #0x43d1ce0',
            'sub x0, x29, #0xa0',
            'bl #0x43d1cdc',
            'sub x8, x29, #0xa0',
            'sub x0, x29, #0x7c',
            'bl #0x42d6dd8',
            'sub x0, x29, #0x78',
            'sub x2, x29, #0xa0',
            'mov w1, #1',
            'mov w3, #0',
            'bl #0x43d1f9c',
            'b #0x131728',
        ])
        check(0x42f05b8, [
            'ldrh w8, [x2]',
            'ldrh w9, [x2, #2]',
            'lsr w10, w8, #9',
            'orr w9, w10, w9, lsl #17',
            'bfi w9, w8, #8, #9',
            'str w9, [x1, #8]',
            'str x0, [x1]',
            'ret',
        ])
        check(0x42f0668, [
            'ldr w8, [x1, #8]',
            'lsr w9, w8, #0x11',
            'ubfiz w10, w8, #9, #7',
            'bfxil w10, w8, #8, #9',
            'orr w0, w10, w9, lsl #16',
            'ret',
        ])
        check(0x42ef200, [
            'ldrh w9, [x0, #2]',
            'ldrh w11, [x0]',
            'and w14, w11, #0x1ff',
            'cmp w9, #0x76c',
            'ccmp w14, #1, #0, eq',
            'b.eq #0x42ef26c',
        ])
        check(0x42ef45c, [
            'lsr w11, w11, #9',
            'cbz w11, #0x42ef510',
            'cmp w11, #0x7f',
            'b.ne #0x42ef480',
            'mov w13, #0x5aa0',
            'movk w13, #0x32, lsl #16',
            'mov w11, #0xd680',
            'movk w11, #0x3a5, lsl #16',
            'b #0x42ef514',
            'sub w11, w11, #1',
            'ubfx w13, w11, #0xd, #2',
            'add w13, w11, w13',
            'sxtb w14, w13',
            'ubfx w14, w14, #2, #8',
            'mov w15, #0x64',
            'mul w14, w14, w15',
            'and w13, w13, #0xfc',
            'sub w13, w11, w13',
            'lsl w16, w13, #4',
            'sub w13, w16, w13',
            'add w13, w14, w13, sxtb',
            'add w13, w13, #0x258',
            'ubfx w13, w13, #2, #0xe',
            'mov w14, #0x147b',
            'mul w13, w13, w14',
            'lsr w13, w13, #0x11',
            'ubfx w16, w11, #2, #6',
            'and w11, w11, #3',
            'neg w17, w11',
            'madd w16, w16, w15, w17',
            'add w11, w16, w11, lsl #4',
            'add w11, w11, #0x258',
            'mul w14, w11, w14',
            'lsr w14, w14, #0x13',
            'msub w11, w14, w15, w11',
            'and x14, x11, #0xffff',
            'mov w11, #0xee80',
            'movk w11, #0x36, lsl #16',
            'umull x11, w13, w11',
            'mov w13, #0xea60',
            'umull x13, w14, w13',
            'b #0x42ef514',
        ])
        check(0x42ef058, [
            'sxth w11, w11',
            'cmp w11, #0x258',
            'b.lt #0x42ef09c',
            'cmp w11, #0x6db',
            'b.ne #0x42ef0d4',
            'mov w11, #0x7f',
            'and w13, w10, #0xff',
        ])
        check(0x42ef09c, [
            'mov w11, #0',
        ])
        check(0x42ef0d4, [
            'ubfx w12, w11, #2, #0xe',
            'mov w13, #0x147b',
            'mul w12, w12, w13',
            'lsr w12, w12, #0x11',
            'mov w13, #0x64',
            'msub w11, w12, w13, w11',
            'and w11, w11, #0xff',
            'mov w13, #0x89',
            'mul w11, w11, w13',
            'lsl w12, w12, #2',
            'add w11, w12, w11, lsr #11',
            'sub w11, w11, #0x17',
            'and w13, w10, #0xff',
        ])
        language = (plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
        for key, label in ((242253, '[%fixture_name#1-long-nocomp] - Kick Off [%date#2-time]'),
                           (242254, 'Kick Off [%date#1-time]')):
            assert f'KEY-{key}: {label}' in language

        # Current runtime stage lookup is guarded by the stored fixture/runtime season code.
        check(0x2090b8, [
            'mov x0, x20',
            'bl #0x3cf657c',
            'mov x21, x0',
            'cbz x0, #0x20af8c',
            'mov x0, x20',
            'bl #0x3cf657c',
            'ldrh w8, [x0, #0x3b0]',
            'ldrh w9, [x20, #0x30]',
            'cmp w8, w9',
            'b.ne #0x20af8c',
            'ldrsb w1, [x20, #0x38]',
            'mov x0, x21',
            'mov w2, #-1',
            'mov w3, #0',
            'mov w4, #1',
            'bl #0x3a83b1c',
            'mov x21, x0',
        ])
        check(0x3a83b34, [
            'cbz w3, #0x3a83b4c',
        ])
        check(0x3a83b4c, [
            'tbnz w1, #0x1f, #0x3a83d04',
            'sxtw x21, w1',
            'ldp x8, x9, [x0, #0x1d8]',
            'sub x9, x9, x8',
            'cmp x21, x9, asr #3',
            'b.hs #0x3a83d04',
            'tbnz w19, #0x1f, #0x3a83cd8',
        ])
        check(0x3a83cd8, [
            'ldr x9, [x0, #0x1d8]',
            'cbz w4, #0x3a83d10',
            'ldr x8, [x9, x21, lsl #3]',
            'cbz x8, #0x3a83d10',
            'mov x19, x0',
            'ldr x9, [x8]',
            'ldr x9, [x9, #0x2f8]',
            'mov x0, x8',
            'blr x9',
            'cmp w0, #6',
            'b.ne #0x3a83d0c',
            'mov x0, #0',
            'b #0x3a83d14',
            'ldr x9, [x19, #0x1d8]',
            'ldr x0, [x9, x21, lsl #3]',
        ])
        vtable(0x56759f8, 'N7sicomps12LEAGUE_STAGEE', {0x2F8//8: 0x3f22f98})
        check(0x3f22f98, ['mov w0, #1', 'ret'])
        vtable(0x5673fe0, 'N7sicomps11GROUP_STAGEE', {0x2F8//8: 0x3decbc0})
        check(0x3decbc0, ['mov w0, #2', 'ret'])
        vtable(0x5671128, 'N7sicomps9CUP_STAGEE', {0x2F8//8: 0x3c9c284})
        check(0x3c9c284, ['mov w0, #0', 'ret'])
        vtable(0x567a6a0, 'N7sicomps11EMPTY_STAGEE', {0x2F8//8: 0x3fc44c8})
        check(0x3fc44c8, ['mov w0, #6', 'ret'])
        vtable(0x5670d60, 'N7sicomps15CUP_GROUP_STAGEE', {0x2F8//8: 0x3c4013c})
        check(0x3c4013c, ['mov w0, #0xb', 'ret'])

        # The const and mutable score-block getters agree on five bytes per side.
        for rva in (0x3CFBAA8, 0x3CFB8F8):
            check(rva, ['add x8, x1, x1, lsl #2', 'add x8, x0, x8',
                        'add x0, x8, #0x64', 'ret'])
        check(0x3D03084, ['mov x0, #0', 'ret'])
        # BASIC_SCORELINE is the +10 subobject; formatter offsets are relative to it.
        vtable(0x55BD188, 'N2db9SCORELINE15BASIC_SCORELINEE', {})
        check(0x16280E8, ['adrp x9, #0x55bd000', 'add x9, x9, #0x188',
                          'stp x9, x8, [x0, #0x10]'])
        formatters = (
            (0x55BCA08, '45SCORELINE_CURRENT_OPPOSITION_NORMAL_FORMATTERE', 0x162DA20,
             0x162DAA4, 0x162DAEC, 0x22, 0x23),
            (0x55BCA68, '48SCORELINE_CURRENT_OPPOSITION_EXTRATIME_FORMATTERE', 0x162DD14,
             0x162DD98, 0x162DDE0, 0x24, 0x25),
            (0x55BCAC8, '43SCORELINE_CURRENT_OPPOSITION_PENS_FORMATTERE', 0x162E008,
             0x162E08C, 0x162E0D4, 0x26, 0x27),
            (0x55BCB28, '42SCORELINE_CURRENT_OPPOSITION_AGG_FORMATTERE', 0x162E2FC,
             0x162E380, 0x162E3C8, 0x28, 0x29),
        )
        for vt, suffix, method, first, second, a, b in formatters:
            vtable(vt, 'N2db20scoreline_formatters'+suffix, {6: method})
            check(first, [f'add x0, x20, #{hex(a)}', 'bl #0x43cfe14'])
            check(second, [f'add x0, x20, #{hex(b)}', 'bl #0x43cfe14'])

        # The fixture-to-scoreline constructor copies normal, extra-time and penalty values.
        check(0x162A2D0, ['cbz x0, #0x162a2dc', 'ldrb w8, [x0]',
                          'b #0x162a2e0', 'mov w8, #0xff', 'strb w8, [x19, #0x32]'])
        check(0x162A320, ['cbz x0, #0x162a338', 'ldrb w8, [x0, #1]',
                          'cmp w8, #0xff', 'b.ne #0x162a33c', 'ldrb w8, [x0]',
                          'b #0x162a33c', 'mov w8, #0xff', 'strb w8, [x19, #0x34]'])
        check(0x162A388, ['cbz x0, #0x162a3ac', 'ldrb w8, [x0, #3]',
                          'cmp w8, #0xff', 'b.ne #0x162a3b0', 'ldrb w8, [x0, #1]',
                          'cmp w8, #0xff', 'b.ne #0x162a3b0', 'ldrb w8, [x0]',
                          'b #0x162a3b0', 'mov w8, #0xff', 'strb w8, [x19, #0x38]'])
        check(0x162A3F4, ['add x8, x21, #0x64', 'orr x9, x23, x23, lsl #2',
                          'add x9, x8, x9', 'ldrb w9, [x9, #2]', 'strb w9, [x19, #0x36]',
                          'orr x9, x24, x24, lsl #2', 'add x8, x8, x9',
                          'ldrb w8, [x8, #2]', 'strb w8, [x19, #0x37]'])
        check(0x162A268, ['cbz x0, #0x162a280', 'ldrb w8, [x0, #1]',
                          'cmp w8, #0xff', 'b.ne #0x162a284', 'ldrb w8, [x0]',
                          'b #0x162a284', 'mov w8, #0xff', 'strb w8, [x19, #0x30]'])

    receipt = {
        'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
        'plugin_sha256': players.SHA256, 'checks': checks,
        'scope': ('Resident year/group/day traversal, materialization boundary, home/away teams, '
                  'fixture date/kickoff clock, guarded top-level runtime-stage links and normal/extra-time/penalty/aggregate score bytes. '
                  'No complete-save coverage, current-date, kickoff timezone, completion-status, '
                  'half-time-score or fifth score-byte claim.'),
        'foreground_ui_used': False, 'native_execution': False,
    }
    (ROOT/'evidence/fixture-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    verify()
