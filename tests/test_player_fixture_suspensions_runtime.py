"""Complete original kind1 routine on explicitly synthetic owned contexts.

The immutable ARM64 function is the accepted build's full3CC6904 body. Every
executed instruction and data byte must be present; no result/callee stubs or
runtime data refill are permitted. Distinct groups deliberately avoid memchr.
These are parity controls, not current-career observations.
"""
import hashlib
import inspect
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs

from fm_live_mcp import player_fixture_suspensions as source
from test_player_fixture_suspensions import (
    native_memory, BASE, RECORD, PL_RT, MANAGER, TEAM, DEFAULT, OWNER, TABLE)

ORIGINAL_KIND1 = bytes.fromhex("ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191e80301aa090d41780a0540796b0440795f010b6b4901005400008052fd7b46a9f44f45a9f65744a9f85f43a9fa6742a9fc6f41a9ffc30191c0035fd6c3000054292100126a0040794a2100123f010a6b48feff54292cc0792903f837f30300aaf40305aaf50304aaf60301aaf70302aae00308aae10309aaf80303aa698c1894080740791f41406b88fcff540a7c105309034079292100120b2000121f010a6b20214b7ae20317aae10316aae40315aae50314aae00313aa08fbff5433144039751a1f12220300b4bf9a0071e1020054f40302aae00302aa63091197e80300aa00000052c8f907377f9e007181f9ff540000805288fa4e3909a101513f4d0071e3f8ff541f61007168010054290080522821c81a096084520930a0721f01096ae1f7ff5404000014681e00131f6100716d00005420008052b9ffff17e90300aa000080522828c079a8f6ff3729a940a94a0109cb4afd43d34a0500515f01086bebf5ff5400008052a2f5ffb434d968f874f5ffb4482081398801f8b749c441f9490100b429f940f929a944a94a0109cb1f0d8aeba2000054387968f8780000b4160080522e000014489c40f9480500b4083140f9080500b448f84e391f050071a8040054f60305aaf90304aaf80301aaf70302aaff0700f9a1ae009021000691e023009102008012fb081b9468d000f000e943f9080040f9084140f9e1230091220080520300805200013fd6e80740f9e10318aae40319aae50316aa480100b4001100d1080080120800e8b81f050071a1000054b8f41a94e50316aae40319aae10318aa180080d236008052e20317aa03000014180080d23600805237104039fffe03718000005448204139ff02086b8001005436010037081b40f9480000b408fd40f9891a40f9490000b429fd40f91f0109eb40090054fffe0371e1ebff5448f84e391f610071e8000054290080522921c81a0a4084520a20a0723f010a6a610000541fa10171e10a00547f1600714d0600547f1a0071200c00547f2a0071800d00547f3e0071a110005476e907371f610071e8000054290080522921c81a0a4084520a20a0723f010a6a61e8ff541fa1017120e8ff54489c40f9880000b4093140f9a9e7ffb5082d40f92a1440395f3d0071212e0054290040b93f050031c02d00540a0080d2a92df8376bd000906b9d46f94b2d00b46ad000b04a815339aa0000376ab146a98c010acb3f0d8cebe30000546a4540f94a2d40a96b010aebc02b00543f0d8beb822b0054490d098b2a0140f95a0100147f060071400800547f160071c10a005496e30737499c40f9891900b42a3140f9cb000014802644a94820c139e90300f9290100cbfa0301aae10308aafb0302aae20309aafc0304aaf90314aaf40305aa23a03894e50314aaf40319aae4031caae1031aaae2031baac0f4ffb4e80340f91f0008eb60f4ff5425e9ff3408ff41391f050071e1dfff5445ffff17891a40f9490000b429fd40f94ac441f94a0000b44afd40f9fffe037160f4ff543f010aeb21f4ff5449204139ff02096b00e7ff549dffff17f6dd0737f60305aaf70304aaf50301aaf30302aae00302aa11b6f797e009003628008052eb0313aaec0315aae90316aa5100001456dc0737499c40f9890a00b42a3140f953000014281440391f7d0071a00500541f05007121dbff54280040b91f050031c0daff54a8daff3769d00090299946f949daffb46ad000b04a8153392a1e00372aad46a96b010acb1f0d8beba21d0054f30302aa480d088bf2000014bf520071c1d8ff547f560071e10100541f610071e8000054290080522921c81a0a4084520a20a0723f010a6a610000541fa10171a1000054241500b488bc40391f050071a0dfff54841300b4282cc0794813f83788bc40391f050071e0deff5497000014210040b93f04003180d5ff54f30302aa68cf00b008c14e39680100b408f17dd369cf00b029e10e91200140f90a0c40b95f01016ba019005429210091082100f141ffff5468d00090009946f92ad64d97c5000014171200b4e90316aae8a240391f010071e8079f1aeb0313aaec0315aa881100346911003789f241393f050071a1daff54870000140a0080d20b0080d22c1440399f290071e80300542d008052ac21cc1a0d8c80529f010d6a400300542c0040b99f050031c00200540b0080d2ac02f8376dd00090ada146f94d0200b46bd000b06b815339ab000037abb946a9ce010bcb9f0d8eebe3000054ab4540f96b3540a9ad010bebc00000549f0d8deb820000546b0d0c8b6b0140f9020000140b0080d2f50305aa5f010beb411600541f610071e80000542a0080524a21c81a0b4084520b20a0725f010b6a411500541fa1017100150054f80314aaf70304aaf60302aa491300b4293140f9091300b4290d40b93f6d1671a11200541f150071e20316aaf40318aae1d2ff549a0000140a0080d20b0080d22c1440399f290071e80300542d008052ac21cc1a0d8c80529f010d6a400300542c0040b99f050031c00200540b0080d2ac02f8374dd000f0ada146f94d0200b46bd000906b815339ab000037abb946a9ce010bcb9f0d8eebe3000054ab4540f96b3540a9ad010bebc00000549f0d8deb820000546b0d0c8b6b0140f9020000140b0080d25f010beb4001005429c5ffb4293140f9e9c4ffb41f150071a1c4ff54280d40b91f6d167120cdff5421feff1709c4ffb4293140f90a1500515f0d0031a3feff5449ccffb5f3ffff17240100b42814403908191f12290040391f51007128019f5a89a040393f01286b21c2ff5448c441f9e8c1ffb408fd40f9a8c1ffb40899413968c1ff3551feff1708008052eb0313aaec0315aa699d40f9690000b42a3140f9020000140a0080d20d0080d28e154039df290071480a00542f008052ee21ce1a0f8c8052df010f6aa00900548c0140b99f050031c00200540d0080d20c09f8374ed000f0cea146f9ae0800b46bd000906b815339ab000037cbb546a9ad010bcb9f0d8debe3000054cb4540f96b3540a9ad010beb200700549f0d8debc20600546b0d0c8b6d0140f9340000140d0080d233000014294540f9292940a94a0109eb60bbff541f0d8aeb22bbff54f30302aa280d088b000140f9a0baffb4689e40f91f0100eb20c3ff54085840f91f0113ebc0c2ff5468e643f9a8b9ffb4089d40f91f0100eb41b9ff5410feff170a0080d21f010aebc1b8ff5448c441f908fd40f9089941391f791c7201c1ff54c0fdff17e00316aae6b4f797e20316aaf40318aac000003737c0ffb4e8a24039e20316aaf40318aaa8bfff34e00302aadcb4f79760b6ff3455b6073788f2413908b60737f6fdff170d0080d2eb0313aa5f010deb08059f1a48b50737890100b4283140f969f94e39a80100b4200080523f09007183b4ff543f150071600100543f39007100b4ff549efdff1768f94e391f15007161b3ff54e1fdff173f15007101b3ff54defdff17080d40b91f210c7181b2ff5494fdff17f30300aae80740f9e80000b4001100d1080080120800e8b81f05007141000054c9f21a94e00313aaf99b3894")
ORIGINAL_KIND1_SHA = '06a2bc52b7fbb0339a6b4a4d3c651f92c594827393960b84206daeeced4753e9'
ENTRY = 0x3CC6904
STACK, STOP = 0x400000000000, 0x400000100000
DATE_INPUT, OTHER_OWNER, OTHER_GROUP, COMP_ROOT = 0xF0000, 0xF1000, 0xF2000, 0xF3000
KNOWN_RUNTIME_KINDS = (0, 3, 21)


def cells_for(m, kind, selector):
    m['put'](PL_RT + 0x3BE, bytes([kind]))
    m['put'](RECORD + 4, bytes([selector]))
    m['q'](DEFAULT + 0x30, OTHER_OWNER)
    m['q'](OTHER_OWNER + 0x1F8, OTHER_GROUP)
    m['q'](PL_RT + 0x7C8, 0)
    m['q'](BASE + 0x56D2D30, COMP_ROOT)
    m['put'](BASE + 0x56D34E0, bytes([0]))
    m['put'](COMP_ROOT + 0x68, struct.pack('<QQ', TABLE, TABLE + 663 * 8))
    m['put'](DATE_INPUT, m['binding']['fixture_date_raw'])
    cells = dict(inspect.getclosurevars(m['read']).nonlocals['memory'])
    cells.update({BASE + ENTRY + i:byte for i,byte in enumerate(ORIGINAL_KIND1)})
    return cells


def original(cells):
    assert hashlib.sha256(ORIGINAL_KIND1).hexdigest() == ORIGINAL_KIND1_SHA
    assert next(d for at,n,d in source.NATIVE_GUARDS if at == ENTRY) == ORIGINAL_KIND1_SHA
    uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    known = set(cells)
    pages = {at & ~4095 for at in cells}
    pages.update(range(STACK, STACK + 0x10000, 4096)); pages.add(STOP)
    for page in pages:
        uc.mem_map(page, 4096)
    for page in {at & ~4095 for at in cells}:
        uc.mem_write(page, bytes(cells.get(at,0) for at in range(page,page+4096)))
    trace, reads, missing = [], [], []
    def instruction(machine,at,n,user):
        if at == STOP:
            machine.emu_stop(); return
        assert BASE + ENTRY <= at < BASE + ENTRY + len(ORIGINAL_KIND1), ('UNPROVED_NATIVE_CALLEE',hex(at))
        assert all(at+i in known for i in range(n)), 'MISSING_ORIGINAL_INSTRUCTION'
        trace.append(at - BASE)
    def load(machine,access,at,n,value,user):
        if not all(at+i in known for i in range(n)):
            missing.append(('MISSING_RECORDED_OPERAND',hex(at),n)); machine.emu_stop(); return
        if not STACK <= at < STACK + 0x10000:
            reads.append((at,n))
    def store(machine,access,at,n,value,user):
        assert STACK <= at and at+n <= STACK+0x10000, 'NONSTACK_WRITE'
        known.update(range(at,at+n))
    def invalid(machine,access,at,n,value,user):
        missing.append(('MISSING_RECORDED_OPERAND',hex(at),n)); machine.emu_stop(); return False
    uc.hook_add(UC_HOOK_CODE,instruction); uc.hook_add(UC_HOOK_MEM_READ,load)
    uc.hook_add(UC_HOOK_MEM_WRITE,store); uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    for i,value in enumerate((MANAGER, RECORD, PL_RT, DATE_INPUT, TEAM, 0)):
        uc.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
    uc.reg_write(regs.UC_ARM64_REG_SP, STACK+0xF000)
    uc.reg_write(regs.UC_ARM64_REG_LR,STOP)
    try:
        uc.emu_start(BASE+ENTRY,STOP,count=10000)
    except Exception:
        if missing:
            raise AssertionError(missing[0])
        raise
    assert not missing,missing
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==STOP, 'ORIGINAL_NOT_TERMINAL'
    result=uc.reg_read(regs.UC_ARM64_REG_X0)
    assert result in (0,1)
    return bool(result),trace,reads


@pytest.mark.parametrize('kind', KNOWN_RUNTIME_KINDS)
@pytest.mark.parametrize('selector', (0, 255))
def test_supported_runtime_kind1_matches_complete_original(native_memory,kind,selector):
    m=native_memory
    cells=cells_for(m,kind,selector)
    expected,trace,reads=original(cells)
    result,reason=source._kind1(m['read'],BASE,m['read'](RECORD,32),m['binding'])
    assert reason is None and result['native_competition_date_predicate'] is expected
    assert trace and reads


def test_original_refuses_missing_reached_native_operand(native_memory):
    cells=cells_for(native_memory,0,255)
    original(cells)
    del cells[RECORD+5]
    with pytest.raises(AssertionError,match='MISSING_RECORDED_OPERAND'):
        original(cells)


def context_world(m,monkeypatch,kind=21):
    from fm_live_mcp import fixtures
    from test_player_fixture_suspensions import PL, OWNER
    fixture,root,store,native,vt=0xF0000,0x110000,0x120000,0x130000,0x140000
    m['q'](fixture,BASE+fixtures.TYPES['fixture'][0])
    m['q'](BASE+fixtures.TYPES['fixture'][0]+0x108,BASE+0x3D030D8)
    m['put'](fixture+0x4C,struct.pack('<HH',330,2030))
    m['q'](BASE+0x56D57D0,root);m['q'](root+0x158,store);m['q'](store+0x70,MANAGER)
    m['q'](BASE+0x56D2D08,native);m['q'](native,vt);m['q'](vt+0x230,BASE+0x1F8AF7C)
    m['put'](PL_RT+0x3BE,bytes([kind]));m['put'](PL_RT+0x4C,struct.pack('<I',3145730))
    m['put'](PL_RT+0x4C0,bytes([0]));m['q'](PL_RT+0x510,0)
    m['put'](OWNER+0x23C,bytes([0]));m['put'](PL_RT+0x3B6,struct.pack('<h',-1))
    m['put'](BASE+0x56D3518,struct.pack('<i',-1))
    monkeypatch.setattr(source,'verify_native',lambda *_:None)
    monkeypatch.setattr(fixtures,'typed',lambda *_:None)
    monkeypatch.setattr(source.competition_stages,'typed',lambda *_:None)
    monkeypatch.setattr(source.competition_stages,'runtime_context',lambda *_:(
        dict(native_season_code=2030,shared_runtime=False),PL_RT,(PL_RT,0,PL,637,1301394,2030)))
    decoded=dict(kind='fixture',competition=dict(database_index=637,native_id=1301394,random_id=None),
                 competition_address=PL,teams=(TEAM,TEAM+8),season_code=2030)
    return fixture,decoded


def test_genuine_ucl_kind21_activation_shape_is_admitted(native_memory,monkeypatch):
    m=native_memory;fixture,decoded=context_world(m,monkeypatch)
    public,binding=source.context(m['read'],BASE,fixture,decoded,'2030-11-26')
    assert public['state']=='available' and public['native_runtime_kind']==21
    assert binding['unsupported_reason']is None and binding['discipline']==MANAGER
    assert public['full_outer_availability_evaluated']is False


@pytest.mark.parametrize('kind',(1,9,13,20,22,24,104,255))
def test_unproved_runtime_kinds_remain_unavailable(native_memory,monkeypatch,kind):
    m=native_memory;fixture,decoded=context_world(m,monkeypatch,kind)
    public,binding=source.context(m['read'],BASE,fixture,decoded,'2030-11-26')
    assert public['state']=='unavailable'and binding['unsupported_reason']=='unsupported_runtime_kind'


@pytest.mark.parametrize('fault',('bit6','bit17','byte4c0','pointer510','owner3','owner1','signed3b6'))
def test_ucl_runtime_activation_variants_stay_unknown(native_memory,monkeypatch,fault):
    from test_player_fixture_suspensions import OWNER
    m=native_memory;fixture,decoded=context_world(m,monkeypatch)
    if fault in('bit6','bit17'):
        m['put'](PL_RT+0x4C,struct.pack('<I',3145730|(1<<(6 if fault=='bit6'else 17))))
    if fault=='byte4c0':m['put'](PL_RT+0x4C0,bytes([3]))
    if fault=='pointer510':m['q'](PL_RT+0x510,0x900000)
    if fault in('owner3','owner1'):m['put'](OWNER+0x23C,bytes([3 if fault=='owner3'else 1]))
    if fault=='signed3b6':m['put'](PL_RT+0x3B6,struct.pack('<h',-3))
    public,binding=source.context(m['read'],BASE,fixture,decoded,'2030-11-26')
    assert public['state']=='unavailable'
    assert binding['unsupported_reason']=='unsupported_native_runtime_activation_branch'


@pytest.mark.parametrize('changed_field',('kind','flags'))
def test_late_ucl_runtime_operand_drift_rejects(native_memory,monkeypatch,changed_field):
    from fm_live_mcp import world
    m=native_memory;fixture,decoded=context_world(m,monkeypatch)
    snapshot=world.ReadSet(m['read'])
    public,_=source.context(snapshot,BASE,fixture,decoded,'2030-11-26')
    assert public['state']=='available'
    if changed_field=='kind':m['put'](PL_RT+0x3BE,bytes([22]))
    else:m['put'](PL_RT+0x4C,struct.pack('<I',3145730|64))
    with pytest.raises(ValueError,match='changed during read'):
        snapshot.verify()
