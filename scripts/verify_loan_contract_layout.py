"""Check loan field dispatch and native display/finance semantics without execution."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import loan_contracts as loans, players, world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    b = Bridge()
    sid = b.attach()['session_id']
    try:
        found = b.find_save_players(sid, 'Trevan Sanusi')
        ref = next(p['player_ref'] for p in found['players'] if p['name'] == 'Trevan Sanusi')
        assert b.get_loan_contract(sid, ref)['loan_contract']['state'] == 'decoded'
        plugin = Path(b.plugin_identity[0][0])
    finally:
        b.detach()
    cs = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva, length):
            stream.seek(0x5ED4000 + rva)
            return {i.address: f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(length), rva)}
        def check(rva, instructions):
            actual = list(code(rva, len(instructions)*4).values())
            assert actual == instructions, (hex(rva), actual, instructions)
        loan = code(0x1374874, 0xE08)
        base = code(0xFF5678, 0x5DA4)
        direct = {'Clmf': (0x1374D78, 0xCC), 'ClDf': (0x1374FF0, 0xD0),
                  'ClDw': (0x1374A1C, 0xD4), 'Clbb': (0x1374AA8, 0xC8)}
        for prop, (case, offset) in direct.items():
            assert property_case(loan, prop, 0x1374894, 'w1') == case
            check(case, [f'ldr w20, [x20, #{offset:#x}]', 'bl #0x4403cd4', 'add x0, x0, #0x28'])
        assert property_case(base, 'Cclc', 0xFF56A4, 'w1') == 0xFF6B18
        check(0xFF6B18, ['ldr x8, [x20]', 'ldr x8, [x8, #0x98]', 'mov x0, x20', 'blr x8',
            'cbz w0, #0xff8284', 'ldr x8, [x20]', 'ldr x8, [x8, #0x48]', 'mov x0, x20', 'blr x8'])
        check(0x13781B8, ['mov w0, #1', 'ret', 'mov w0, #1', 'ret'])
        check(0xD8C3C0, ['ldr w0, [x0, #0x20]', 'ret'])
        # The finance cost routine charges the loan's team and subtracts from the main team.
        check(0xCBFD68, ['ldr x8, [x23, #0x10]', 'cbz x8, #0xcbfd74',
            'ldr x8, [x8, #0x30]', 'cmp x8, x19', 'b.eq #0xcbfde0'])
        check(0xCBFE34, ['ldr x8, [x23]', 'ldr x8, [x8, #0x48]', 'mov x0, x23',
            'blr x8', 'mov x23, x0', 'cbnz w23, #0xcbfe80', 'str wzr, [x21]'])
        check(0xCBFE70, ['neg w23, w11'])
        check(0xCBFE98, ['cmp x9, x19', 'b.ne #0xcbffbc', 'ldr w9, [x24, #0x20]', 'add w23, w9, w23'])
        # Signed date / expiry use inherited base slots 29 / 30 on LOAN_CONTRACT.
        for prop, case, slot in [('Csda',0xFF68F8,29), ('Ceda',0xFF664C,30)]:
            assert property_case(base, prop, 0xFF56A4, 'w1') == case
            check(case, ['ldr x8, [x20]', f'ldr x8, [x8, #{slot*8:#x}]', 'mov x0, x20', 'blr x8'])
        check(0x1005C68, ['add x0, x0, #0x44', 'ret', 'ldr w0, [x0, #0x48]', 'ret'])
        # Auxiliary holder current slot is separate from future/other contract slots.
        check(0xD00008, ['ldr x8, [x0]', 'ldur x8, [x8, #-0x20]', 'add x8, x0, x8',
            'ldr x8, [x8, #0x80]', 'cbz x8, #0xd000ac', 'ldr x19, [x8]', 'cbz x19, #0xd000ac'])
        # The displayed future fee adds each positive amount once when its signed parameter is positive.
        assert property_case(loan, 'Clff', 0x1374894, 'w1') == 0x1374BB0
        check(0x1374C08, ['ldr w21, [x20, #0xc0]', 'tbnz w21, #0x1f, #0x1375444',
            'ldr x9, [x20, #0x68]', 'cbz x9, #0x1375250', 'ldp x8, x9, [x9]',
            'cmp x8, x9', 'b.eq #0x1375250', 'ldr w10, [x8]', 'cmp w10, #1',
            'b.lt #0x1374c40', 'ldrsb w11, [x8, #4]', 'cmp w11, #0',
            'csel w10, w10, wzr, gt', 'add w21, w10, w21', 'add x8, x8, #8', 'b #0x1374c1c'])
        for prop, case, offset in [('ClMm',0x1374B34,0xF7), ('ClMt',0x13750F8,0xF8)]:
            assert property_case(loan, prop, 0x1374894, 'w1') == case
            check(case, [f'ldrsb w20, [x20, #{offset:#x}]'])
        assert property_case(loan, 'ClFc', 0x1374894, 'w1') == 0x1374C68
        check(0x1374CA4, ['ldr w8, [x20, #0xc4]', 'tbnz w8, #0x1f, #0x13753d8'])
        check(0x181CB8, ['mov x0, x20', 'mov w1, #0x4d6d', 'movk w1, #0x436c, lsl #16',
            'bl #0x43f899c', 'bl #0x4404a08', 'strb w0, [sp, #0x7c]', 'cmp w0, #0x64', 'b.ne #0x183818'])
        check(0x183818, ['tbnz w0, #0x1f, #0x183e00', 'mov x0, x20', 'mov w1, #0x4d74',
            'movk w1, #0x436c, lsl #16', 'bl #0x43f899c', 'bl #0x4404a08', 'strb w0, [sp, #0x70]'])
        # Native labels associated with the display branches above.
        translations = {0x181CE0: (423897,'Mandatory Future Fee'),
            0x184098: (423896,'Optional Future Fee'),
            0x18383C: (425046,'After [%number#1] matches ([%number#2] played)'),
            0x183938: (374075,'Future Buy Back Fee'),
            0x1819B0: (423893,'[%wage#2] for duration of loan when playing, [%wage#5] when unused ([%number#1]% of minutes played this month)')}
        language = (plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
        labels = {int(m[1]): m[2].split('[COMMENT')[0].strip() for m in re.finditer(r'^KEY-(\d+): (.*)', language, re.M)}
        for rva, (identifier,label) in translations.items():
            check(rva, [f'mov w1, #{identifier & 65535:#x}', f'movk w1, #{identifier >> 16}, lsl #16', 'bl #0x43db8b8'])
            assert labels[identifier] == label
        # Playing/unused fee paths supply distinct native contract properties to the display.
        check(0x1841F8, ['mov x0, x20', 'mov w1, #0x6d66', 'movk w1, #0x436c, lsl #16',
            'bl #0x43f899c', 'bl #0x4404aa8', 'mov x26, x0', 'mov x0, x20',
            'mov w1, #0x4466', 'movk w1, #0x436c, lsl #16', 'bl #0x43f899c', 'bl #0x4404aa8'])
        # Offer fields become the two loan fees without arithmetic or unit conversion.
        check(0x2DF275C, ['mov x0, x22', 'bl #0x137276c'])
        check(0x13727C8, ['adrp x8, #0x55b5000', 'add x8, x8, #0x4e8', 'str x8, [x0]'])
        check(0x2DF2974, ['ldr w8, [x20, #0x58]', 'ldr w9, [x20, #0x104]', 'stp w8, w9, [x22, #0xcc]'])
        for rva, offset, prop in [(0x1A655F0,0x58,'lPMF'), (0x1A6562C,0x104,'lDMF')]:
            value = int.from_bytes(prop.encode(), 'big')
            check(rva, [f'ldr w24, [x19, #{offset:#x}]', 'bl #0x4403cd4', 'add x8, x0, #0x28',
                'str w24, [sp, #0x70]', 'str x8, [sp, #0x68]', 'add x2, sp, #0x68', 'mov x0, x20',
                f'mov w1, #{value & 65535:#x}', f'movk w1, #{value >> 16:#x}, lsl #16', 'bl #0x43f82a0'])
        offer_labels = code(0x62D4D0, 0x10D4)
        assert property_case(offer_labels, 'lPMF', 0x62D518, 'w8') == 0x62DCF8
        assert property_case(offer_labels, 'lDMF', 0x62D518, 'w8') == 0x62DEB4
        check(0x62DCF8, ['adrp x8, #0x56d4000', 'add x8, x8, #0x920', 'ldrb w9, [x8, #0x5d]',
            'cmp w9, #1', 'b.ne #0x62dd1c', 'ldrb w8, [x8, #0x30]', 'sub w8, w8, #1',
            'cmp w8, #3', 'b.hs #0x62e2dc'])
        for rva, identifier, label in [(0x62E2E4,693541,'Playing Monthly Fee[%person#1-hidden]'),
                (0x62DEBC,693543,'Unused Monthly Fee[%person#1-hidden]'),
                (0x62DD24,693542,'Monthly Fee[%person#1-hidden]')]:
            check(rva, [f'mov w1, #{identifier & 65535:#x}', f'movk w1, #{identifier >> 16:#x}, lsl #16', 'bl #0x43db8b8'])
            assert labels[identifier] == label
        # Clfl selects the whole nonzero override, then passes the uint64 to the
        # native loan-clause formatter. Verify labels and each independent test.
        assert property_case(loan, 'Clfl', 0x1374894, 'w1') == 0x1375178
        check(0x1375178, ['ldr x21, [x20, #0xb8]', 'cbnz x21, #0x1375184',
            'ldr x21, [x20, #0xb0]', 'bl #0x4403cd4', 'add x0, x0, #0x58',
            'stp x0, x21, [sp, #0x20]'])
        check(0x1822B0, ['mov x0, x20', 'mov w1, #0x666c', 'movk w1, #0x436c, lsl #16',
            'bl #0x43f899c', 'bl #0x4404b04', 'sub x8, x29, #0xb0', 'mov x1, #0', 'bl #0x186b10'])
        check(0x186B24, ['mov x22, x1', 'mov x20, x0'])
        clauses = [
            ('work_permit_loan',0x186B48,0x186B8C,0x186B54,0x601C1,'Work Permit Loan'),
            ('can_be_recalled',0x186B8C,0x186C2C,0x186B98,0xAFA6E,'Can be recalled[%person#1-hidden]'),
            ('loan_cannot_be_terminated',0x186C2C,0x186C70,0x186C38,0x66B75,'Loan cannot be terminated'),
            ('can_play_for_parent_club',0x186C70,0x186CB4,0x186C7C,0x6BBFD,'Can play for parent club'),
            ('can_play_for_parent_club_reserve_team',0x186CB4,0x186CF8,0x186CC0,0x5FFCC,"Can play for parent club's reserve team"),
            ('can_play_for_parent_club_in_cup_matches',0x186CF8,0x186D3C,0x186D04,0x7136A,'Can play for parent club in cup matches'),
            ('can_play_against_parent_club',0x186D3C,0x186D80,0x186D48,0x3B784,'Can play against own team'),
            ('can_play_in_cup_matches',0x186D80,0x186DC4,0x186D8C,0x3B783,'Can play in cup matches'),
            ('can_play_against_parent_club_b_team',0x186DC4,0x186E08,0x186DD0,0x66DCA,"Can play against parent club's B team"),
            ('trains_with_parent_club',0x186E08,0x186E4C,0x186E14,0x7C3B0,'Trains with parent club'),
            ('cannot_play_against_parent_club_in_cup_matches',0x186E4C,0x186EDC,0x186E5C,0xAF398,'Cannot play against parent club in cup matches[%person#1-hidden]'),
            ('cannot_play_in_continental_competitions',0x186EDC,0x186FE4,0x186EEC,0xAF39A,'Cannot play in continental competitions[%person#1-hidden]'),
            ('season_long_affiliate_loan_exempt_from_parent_salary_cap',0x186FE4,0x187028,0x186FF0,0x7CD70,'On season-long loan to affiliate, exempt from parent club salary cap'),
        ]
        assert {row[0] for row in clauses} == set(loans.CLAUSE_BITS)
        for name, branch, target, label_rva, identifier, label in clauses:
            bit = loans.CLAUSE_BITS[name]
            rendered_bit = str(bit) if bit < 10 else hex(bit)
            check(branch, [f'tbz {"w" if bit < 32 else "x"}20, #{rendered_bit}, #{target:#x}'])
            high = identifier >> 16
            check(label_rva, [f'mov w1, #{identifier & 65535:#x}',
                f'movk w1, #{str(high) if high < 10 else hex(high)}, lsl #16', 'bl #0x43db8b8'])
            assert labels[identifier] == label
        # The no-person branch uses equivalent labels for the two high bits.
        for rva, identifier, label in [(0x186F68,0xAF399,'Cannot play against parent club in cup matches'),
                (0x186FAC,0xAF39B,'Cannot play in continental competitions')]:
            check(rva, [f'mov w1, #{identifier & 65535:#x}', 'movk w1, #0xa, lsl #16', 'bl #0x43db8b8'])
            assert labels[identifier] == label
        # Persist the reviewed code fingerprints so future changes cannot silently reuse this evidence.
        spans = [(0x1374874,0xE08),(0xFF5678,0x5DA4),(0xCBFCE8,0x32C),(0x181900,0x2A88),(0x2DF25D0,0x620),(0x1A655F0,0x78),(0x62D4D0,0x10D4),(0x186B10,0x518)]
        hashes = {}
        for rva, size in spans:
            stream.seek(0x5ED4000+rva)
            hashes[hex(rva)] = hashlib.sha256(stream.read(size)).hexdigest()
    receipt = {'verified': True, 'observed_at': datetime.now(timezone.utc).isoformat(),
               'plugin_sha256': players.SHA256, 'native_code_sha256': hashes,
               'verified_clause_count': len(clauses),
               'scope': 'Loan object dispatch, owner path, date and cash getters, native fee sum, match counters, display trigger branches and thirteen displayed clause bits with whole-word override selection. No function execution or foreground UI.'}
    (ROOT/'evidence/loan-contract-layout-verification.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print('Verified native loan date, fee, wage, purchase, match-counter and thirteen clause paths.')


if __name__ == '__main__':
    verify()
