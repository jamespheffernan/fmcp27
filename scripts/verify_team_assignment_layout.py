"""Verify native property dispatch and direct assignment branches without executing them."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp.bridge import Bridge
from fm_live_mcp import database, players, teams
from verify_player_profile_layout import property_case


def verify():
    b=Bridge();sid=b.attach()['session_id']
    try:
        with b.lock,b._read_scope(sid):
            process=b._current(sid);tables=b._player_layout(process);base=tables[0]-players.RVA[0]
            plugin=Path(b.plugin_identity[0][0]);read,save,_=b._world_state(process,tables)
            info=teams.lookup(read,base)
            containers=database.table(read,base,'national_team_containers')
            samples=[teams.by_index(read,base,index,info=info)[0] for index in (0,253,545,29381,63742)]
            read.verify()
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
        cases={prop:property_case(comp,prop,0xEFD4B8,'w21') for prop in
               ('ctms','CTMS','cntm','CNTM','otms','OTMS','nsod','NSOD')}
        # Uppercase toggles parent aggregation; the exposed tool uses lowercase only.
        for prop,start,flags in (('ctms',0xEFFBB0,(0,0)),('cntm',0xEFEA8C,(1,0)),
                                 ('otms',0xF00EF4,(0,1)),('nsod',0xF00F4C,(1,1))):
            assert cases[prop] <= start and start-cases[prop] <= 12,(prop,cases[prop],start)
            check(start,['cset w5, eq','add x0, sp, #0x60','mov x1, x20',
                         f'mov w2, #{flags[0]}',f'mov w3, #{flags[1]}','mov w4, #0','bl #0xf1ae9c'])
        check(0xF1AEE4,['adrp x8, #0x56d2000','ldr x8, [x8, #0xdb0]',
                        'ldr x8, [x8, #0x88]','ldp x8, x9, [x8]','subs x8, x9, x8'])
        check(0xF1AF34,['asr x25, x8, #3','cbz w24, #0xf1b01c','mov x22, #0','tbz w23, #0, #0xf1b0e4'])
        check(0xF1AF74,['ldrb w10, [x26, #0x730]','and x8, x22, #0x7fffffff',
                        'ldr x9, [x26]','cmp w10, #1','b.ne #0xf1afa0',
                        'ldr x9, [x9, #0x88]','ldp x9, x10, [x9]',
                        'sub x10, x10, x9','cmp x8, x10, asr #3','b.hs #0xf1af64','b #0xf1afb0'])
        check(0xF1AFA0,['ldp x9, x10, [x9, #0x68]','sub x10, x10, x9',
                        'cmp x8, x10, asr #3','b.hs #0xf1af64'])
        for start,offset,fallback,load,target in ((0xF1AF44,0x70,0x68,0xF1AFC0,0xF1AF58),
                                                (0xF1B0E4,0x58,0x50,0xF1B160,0xF1B0F8)):
            check(start,[f'mov w23, #{offset:#x}',f'mov w24, #{fallback:#x}'])
            check(load,[f'ldr x9, [x8, #{offset:#x}]','cmp x9, #0','csel x9, x24, x23, eq',
                        'ldr x8, [x8, x9]','cmp x8, x20',f'b.eq #{target:#x}'])
        check(0xF1B2C0,['cbz x8, #0xf1b268','ldr x8, [x8, #0x68]','cmp x8, x20',
                        'b.ne #0xf1b268','add x1, sp, #8','mov x0, x19','bl #0x14cb38'])
        check(0xF1B410,['ldr x9, [x8, #0x30]','cbz x9, #0xf1b3b4','ldr x8, [x8, #0x50]',
                        'cmp x8, x20','b.ne #0xf1b3b4'])
        team_base=code(0x179D450,0x1500)
        assert property_case(team_base,'Ttyp',0x179D46C,'w1')==0x179D558
        assert property_case(team_base,'Ttea',0x179D46C,'w1')==0x179DF8C
        record=code(0x11B23E8,0x1000)
        assert property_case(record,'duni',0x11B2404,'w1')==0x11B28C4
        assert property_case(record,'rdui',0x11B2404,'w1')==0x11B2AB0
        check(0x179D558,['ldrsb w20, [x20, #0x28]'])
        check(0x179DF8C,['ldr w20, [x20, #8]'])
        check(0x11B28C4,['ldr w20, [x20, #0xc]'])
        check(0x11B2AEC,['ldp w8, w20, [x20, #0xc]','cmp w8, w20','b.eq #0x11b30e8'])
        check(0x13EC54C,['ldr x0, [x0, #0x170]','mov w3, #0','bl #0x13b1d1c'])
    receipt={'verified':True,'observed_at':datetime.now(timezone.utc).isoformat(),
             'plugin_sha256':hashlib.file_digest(plugin.open('rb'),'sha256').hexdigest(),
             'property_cases':{k:hex(v) for k,v in cases.items()},'samples':samples,
             'national_team_containers':containers['count'],'team_count':info['count'],'lookup_count':info['lookup_count'],'foreground_ui_used':False,
             'native_function_execution':False,'scope':'Direct lowercase assignment branches; no parent aggregation'}
    (ROOT/'evidence/team-assignment-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='samples'},indent=2))


if __name__=='__main__':verify()
