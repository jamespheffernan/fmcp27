"""Prove stored loan competition references, achievements and names without execution."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import loan_contracts, players
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    b=Bridge();sid=b.attach()['session_id']
    try:
        found=b.find_save_players(sid,'Vítězslav Jaroš')
        ref=next(p['player_ref'] for p in found['players'] if p['name']=='Vítězslav Jaroš')
        condition=b.get_loan_contract(sid,ref)['loan_contract']['purchase']['competition_condition']
        assert condition['achievement']=='qualify_for_competition'
        assert condition['competition']['name']=='Italian Serie A'
        assert condition['target_competition']['name']=='UEFA Europa League'
        plugin=Path(b.plugin_identity[0][0])
    finally:b.detach()
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    with plugin.open('rb') as stream:
        def code(rva,size):
            stream.seek(0x5ED4000+rva)
            return {i.address:f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(size),rva)}
        def check(rva,expected):
            actual=list(code(rva,len(expected)*4).values())
            assert actual==expected,(hex(rva),actual,expected)
        comp=code(0xEFD3B8,0x9000)
        for prop,case,offset in [('cnam',0xF02D50,0x40),('csnm',0xEFECB8,0x48),('c3ln',0xF00E44,0x50)]:
            assert property_case(comp,prop,0xEFD4B8,'w21')==case
            check(case,['bl #0x4403cd4',f'ldr x8, [x20, #{offset:#x}]'])
        # Resolve stored indices with the same mode/primary/canonical vector paths.
        check(0x1374CA4,['ldr w8, [x20, #0xc4]','tbnz w8, #0x1f, #0x13753d8',
            'adrp x9, #0x56d2000','ldr x9, [x9, #0xd30]','cbz x9, #0x137538c',
            'adrp x10, #0x56d3000','ldrb w10, [x10, #0x4e0]','tbnz w10, #0, #0x1375368',
            'ldp x10, x11, [x9, #0x68]','sub x11, x11, x10','cmp x8, x11, asr #3',
            'b.hs #0x1375368','add x8, x10, x8, lsl #3','b #0x1375384'])
        check(0x1375368,['ldr x9, [x9, #0x88]','ldp x9, x10, [x9]','subs x10, x10, x9',
            'b.eq #0x137538c','cmp x8, x10, asr #3','b.hs #0x137538c',
            'add x8, x9, x8, lsl #3','ldr x0, [x8]'])
        loan=code(0x1374874,0xE08)
        assert property_case(loan,'ClFs',0x1374894,'w1')==0x137504C
        check(0x1375058,['add x0, x20, #0x90','add x2, sp, #0x40','mov w1, #0','bl #0x13756e0'])
        # Serializer and display deserializer preserve the same 13-byte layout.
        for write_at,read_at,offset,size in [(0x1375768,0x13209EC,4,4),
                (0x137578C,0x1320A10,8,4),(0x13757B0,0x1320A34,12,1)]:
            offset_text=str(offset) if offset<10 else hex(offset)
            expected=[f'add x1, x20, #{offset_text}','mov x0, x21',f'mov w2, #{size}','blr x8']
            check(write_at,expected);check(read_at,expected)
        check(0x13757D4,['mov x1, x20','mov w2, #4','blr x8'])
        check(0x1320A58,['mov x0, x21','mov x1, x20','mov w2, #4','blr x8'])
        check(0x183E58,['mov w1, #0x4673','movk w1, #0x436c, lsl #16','bl #0x43f899c',
            'stur wzr, [x29, #-0xb0]','add x1, sp, #0x50','sub x2, x29, #0xb0','bl #0x1689b0'])
        check(0x1689E0,['add x1, sp, #8','mov x0, x19','bl #0x13209a0'])
        check(0x183E80,['add x0, sp, #0x50','mov x1, x24','mov w2, #-1','mov w3, #-1',
            'mov w4, #0','mov w5, #0','bl #0x1320b58'])
        # Target competition is at +0; the two stage name fields are IDs searched
        # by record +0xC, not indices. No stage-name composition is claimed.
        check(0x1320C30,['ldr w8, [x28]','tbnz w8, #0x1f, #0x1320c90','adrp x9, #0x56d2000',
            'ldr x9, [x9, #0xd30]'])
        check(0x1320BD0,['ldr w1, [x28, #4]','adrp x24, #0x56d2000','cmn w1, #1',
            'b.eq #0x1320bf0','ldr x0, [x24, #0xda8]','bl #0x10b1700'])
        check(0x10B1744,['ldr x0, [x8, w11, uxtw #3]','ldr w12, [x0, #0xc]','cmp w12, w1'])
        check(0x1320C90,['ldrb w8, [x28, #0xc]','cmp w8, #9','b.gt #0x1320cf8',
            'cbz w8, #0x1320d58','cmp w8, #3','b.eq #0x1320e84','cmp w8, #6','b.ne #0x1320de8'])
        check(0x1320CF8,['cmp w8, #0xa','b.eq #0x1320da0','cmp w8, #0xe','b.eq #0x1320d58',
            'cmp w8, #0x14','b.ne #0x1320de8'])
        cases=[(0,'win_competition',0x1320D58,0x1320FD0,0x1321330,0x5B8CB,'Winning the [%comp#1-short]'),
            (14,'win_competition',0x1320D58,0x1320FD0,0x1321330,0x5B8CB,'Winning the [%comp#1-short]'),
            (3,'promotion',0x1320E84,0x1321150,0x13214F8,0x5B837,'Promotion from the [%comp#1-short]'),
            (6,'avoid_relegation',0x1320CB0,0x13210F0,0x13214B0,0x5B7AE,'Avoiding relegation from the [%comp#1-short]'),
            (10,'qualify_for_competition',0x1320DA0,0x1321060,0x13213C0,0x5B83B,'Qualifying for the [%comp#2-short]'),
            (20,'avoid_fine',0x1320D10,0x1321120,0x13214D4,0x839DF,'Avoiding receiving a fine in the [%comp#1-short]')]
        language=(plugin.parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text()
        labels={int(m[1]):m[2].split('[COMMENT')[0].strip() for m in re.finditer(r'^KEY-(\d+): (.*)',language,re.M)}
        for kind,name,case,generic,plain,identifier,label in cases:
            assert loan_contracts.COMPETITION_ACHIEVEMENTS[kind]==name
            assert code(case+20,4)[case+20]==f'b.ne #{generic:#x}'
            check(generic,['ldrsh w8, [sp, #0x4e]','cmn w8, #1',f'b.eq #{plain:#x}'])
            check(plain+8,[f'mov w1, #{identifier & 65535:#x}',f'movk w1, #{identifier >> 16}, lsl #16','bl #0x43db8b8'])
            assert labels[identifier]==label
        assert set(loan_contracts.COMPETITION_ACHIEVEMENTS)=={r[0] for r in cases}
        archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
        editor=None
        for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
            try:tree=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10_000_000))
            except (zstandard.ZstdError,ET.ParseError):continue
            props={r.find("flags[@id='field']").get('value'):r for r in tree.iter('record') if r.find("flags[@id='field']") is not None}
            if all(p in props for p in ('cnam','csnm','c3ln')):
                editor=props;break
        assert editor is not None
        for prop,label in [('cnam','Name'),('csnm','Short Name'),('c3ln','Three Letter Name')]:
            assert editor[prop].find("translation[@id='name']").get('value')==label
        spans=[(0xEFD3B8,0x9000),(0x1374874,0x1400),(0x13209A0,0x14A0),(0x183E00,0xA0)]
        hashes={}
        for rva,size in spans:
            stream.seek(0x5ED4000+rva);hashes[hex(rva)]=hashlib.sha256(stream.read(size)).hexdigest()
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),'plugin_sha256':players.SHA256,
        'native_code_sha256':hashes,'achievement_codes':loan_contracts.COMPETITION_ACHIEVEMENTS,
        'scope':'Native competition lookup, stored name properties/editor labels, condition serialization and six achievement-code display paths. Stage composition and trigger activation remain unverified. No native execution or UI.'}
    (ROOT/'evidence/loan-competition-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Verified competition references, stored names and six loan achievement codes.')


if __name__=='__main__':verify()
