"""Verify native On Loan property dispatch and affiliation/trial branches; no execution."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import xml.etree.ElementTree as ET

from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
import zstandard

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import players,world
from fm_live_mcp.bridge import Bridge
from verify_player_profile_layout import property_case


def verify():
    b=Bridge();sid=b.attach()['session_id'];observed=[]
    try:
        for name in ('Trevan Sanusi','Fabian Bredlow','Mladen Beljan','Stefan Kahlisch'):
            rows=b.find_save_players(sid,name)['players'];row=next(p for p in rows if p['name']==name)
            result=b.get_player(sid,row['player_ref'],include_clubs=True)['player']
            observed.append({'name':name,'clubs':result['clubs']})
            with b.lock,b._read_scope(sid):
                tables=b._player_layout(b.process);base=tables[0]-players.RVA[0]
                snap,_,_=b._world_state(b.process,tables)
                address=b.player_refs[row['player_ref']]['address']
                primary=world.pointer(snap,address);person_offset=players.person_offset(snap,address,tables)
                assert players.u64(snap(primary+93*8,8))==base+0xCFFFFC
                assert struct.unpack('<q',snap(primary-0x20,8))[0]==person_offset-0x110
                snap.verify()
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
        c=code(0x1503624,0xD188)
        assert property_case(c,'Pion',0x1503774,'w21')==0x1509664
        check(0x1509664,['ldr x8, [x20]','ldr x8, [x8, #0x2e8]','mov x0, x20','blr x8',
            'mov x20, x0','bl #0x4403cd4','add x0, x0, #0x18','sturb w20, [x29, #-0xd0]'])
        check(0xD00008,['ldr x8, [x0]','ldur x8, [x8, #-0x20]','add x8, x0, x8',
            'ldr x8, [x8, #0x80]','cbz x8, #0xd000ac','ldr x19, [x8]',
            'cbz x19, #0xd000ac','ldr x8, [x19]','ldr x8, [x8, #0x90]',
            'mov x0, x19','blr x8','cmp w0, #1','b.ne #0xd000ac',
            'ldr x8, [x19]','ldr x8, [x8, #0x98]','mov x0, x19','blr x8',
            'cbz w0, #0xd00060','ldr x8, [x19, #0x10]','cbz x8, #0xd00060',
            'ldrb w9, [x8, #0x2f]','cbz w9, #0xd00068','mov w0, #1','b #0xd000b0',
            'ldr x8, [x8, #0x30]','cbz x8, #0xd00060','ldp x9, x10, [x8, #0x118]',
            'cmp x9, x10','b.eq #0xd00060','mov w0, #1','ldr x11, [x9]',
            'ldr x12, [x11, #8]','cmp x12, x8','b.ne #0xd0009c',
            'ldrb w11, [x11, #0x30]','cmp w11, #0x12','b.eq #0xd000ac',
            'add x9, x9, #8','cmp x9, x10','b.ne #0xd00080','b #0xd000b0','mov w0, #0'])
        check(0x13781B8,['mov w0, #1','ret','mov w0, #1','ret'])
        check(0x1006B44,['mov w0, #2','ret'])
        archive=(plugin.parent.parent/'Resources/shared/data/editor.fmf').read_bytes()
        label=None
        for match in re.finditer(re.escape(bytes.fromhex('28b52ffd')),archive):
            try:tree=ET.fromstring(zstandard.ZstdDecompressor().decompress(archive[match.start():],max_output_size=10_000_000))
            except (zstandard.ZstdError,ET.ParseError):continue
            for record in tree.iter('record'):
                field=record.find("flags[@id='field']")
                if field is not None and field.get('value')=='Pion':
                    label=record.find("translation[@id='name']").get('value')
        assert label and label.split('[COMMENT')[0]=='On Loan'
        hashes={}
        for rva,size in [(0xCFFFFC,0xC0),(0x1503624,0xD188),(0x13781B8,16),(0x1006B44,8)]:
            stream.seek(0x5ED4000+rva);hashes[hex(rva)]=hashlib.sha256(stream.read(size)).hexdigest()
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),
        'plugin_sha256':players.SHA256,'native_code_sha256':hashes,'samples':observed,
        'scope':'Pion editor label/property dispatch to slot 93; full native holder, contract-kind, team-mode and affiliation branches. Live regular/combined dispatch and trial/suppressed examples. No native execution or foreground UI.'}
    (ROOT/'evidence/player-club-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print('Verified native On Loan property, regular/combined dispatch, trial and affiliation branches.')


if __name__=='__main__':verify()
