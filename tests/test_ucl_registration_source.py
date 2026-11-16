"""Synthetic native UCL rule-selection controls, never career observations."""
import hashlib
import struct

import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
from unicorn import UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_INVALID
import unicorn.arm64_const as regs

from fm_live_mcp import ucl_registration_source as source,world

ORIGINAL = bytes.fromhex("ff0302d1f85f04a9f65705a9f44f06a9fd7b07a9fdc30191f40303aaf60302aaf50301aaf30300aae2df003917c441f9970e00b4682641391ffd0371e0120054df0600316100005476264139f6df003978fa4e3908a701511f490071042b577a041b487a2101005421de00f021002b91a2de009042c03c91e00313aa030080d256234194203000b56832413928021836689e40f9480100b4083140f91f0100f1021b4e7a280080520821d81a690088520801090a0499407ac1000054b50000b4e00315aa46840a94f50300aa002e00b5150080d2d62d3837c81e4093e9fa40f9292946a94a0109cb4afd43935f0108ebe92c0054357968f8552800b5f7df00f0f61246f9ff1f00f941bf0090216c3291e0e3009102008012f38c2394e8430091e1e30091e00316aa60db2494e81f40f9e80000b4001100d1080080120800e8b81f05007141000054b7782394e8e30091e0df0091aba82494e0430091e2e30091210080520300805208b12494e01f40f9200100b408200091090080120801e9b81f05007181000054080040f9080540f900013fd6769e40f9f71246f9ff0300f9e82b40b91f050031e0000054e80640f9183d40f968ce1697080840f91f0308eb0016005483e1009063c03d91e043009101008052020080129eb42494e80640f90841483908140034e8e30091e04300910bb82494e81f40f9281400b5a100001468fa4e391f610071290080522921c81a0a4084520a20a07229010a0a2499407a610000541fa1017101230054699e40f9280d40b98ab989524a00a0721f010a6b4a768c524ae7ae7204114a7a210600540900805288e1009008e943f9082945a94b0108eb202100546a2253396bfd43937f0500f16b859f9a0c0140f98d994139bf01096b60050054082100916b0500f141ffff54fd000014e8fa40f9092946a94a0109ebe0ecff540b0080d2080080524afd43935f010beb290200542b796bf8eb0100b46c0941b96b9e40f96d0d40b96be643f99f010d6b400500540b0100b46d9d40f96d0000b4ad0d40b9020000140d0080129f010d6b000b0054080500110b1d40925f0128eb68fdff544dffff17205940f9c00100b4978c199788e1009008e943f94003003609008052ccffff175f01007108078052090880522811889a976968f897e7ffb5d000001428e143391fa500712a0080524821c89a0a9891d2ea63b1f22a40c0f208010a8a049940fa01f7ff5488e1009008e943f90600001468260139cb0600b52effff17699e40f9a92800b4293140f9692800b46a2253395f0100710a2280520b2380526a118a9a2b696af88b2700b46ab940f94c0d40b9690180529f090c71a0f4ff549fd1197160f4ff549fe5197120f4ff5469e542393f010071092280520b2380526911899a496969f8e90200b46be100d06b8153397f050071e10100542bb940f96b9540f98b0100b42ce542399f0100710c0780520d088052ac118c9a60696cf8a00000b40bfc40f96b0d40f97f010aeba022005429dd4a7929051d123f410071c12200546901805282ffff176826013968250139f8feff17e80f40f9a80000b4091100d1ff0300f92a00805229012ab8e80300f9e8230091e1030091e00316aa5c1f0894e80340f9e80000b4001100d1080080120800e8b81f05007141000054de772394e80740f9280a00b4090140b92909003488e1009000e943f9080040f9084140f9e1230091220080520300805200013fd6c007003488e10090081151396807003688e1009008a11091080940f9c80000b4090140f9890000b40971403969ff07373200001488e100900801d1391f050071cc05005497e10090f7a21091e80317aa080940f9280100b4090140f9e90000b409714039a90400360961c0393f0500710dffff5421000014000e815286952294f60300aa41bf0090214c069143bf0090632033918269855204008052250080520c962294e1230091e00316aa699f2394d70e00f9e81e40b9c91640b92801082ac81600b968006836e00316aa50962294e00316aa0e91229400011036214c00b021101791a00080529824419440244194a100805211244194e80740f9e80000b4001100d1080080120800e8b81f050071410000548c772394e0430091afae2494881e00121ffd037100050054f50400b4a99644393f01086bc004005469c641f9490300b429f940f9292946a94b0109ebc00200540a0080d26bfd43937f0500f16b859f9a35796af8ac9644399f01086b210100546c9e40f96c0000b48c0d40b9020000140c008012ad0a41b9bf010c6b00020054150080d24a0500917f010aeb21feff5402000014150080d2e00315aafd7b47a9f44f46a9f65745a9f85f44a9ff030291c0035fd635ffffb4a89644391f210071c1feff54a8b2443988fe0737749e40f9d40100b4883240f9880100b468fa4e3909a501513f19007183fdff541f390071c8000054290080522821c81a692088521f01096aa1fcff54ff1f00f921bf00f021683391e0e3009102008012758b2394e8430091e1e30091e00314aab71e0894e81f40f9e80000b4001100d1080080120800e8b81f0500714100005439772394e80b40f928faffb4090140b92909003468e100f000e943f9080040f9084140f9e1430091220080520300805200013fd6c007003468e100f0081151396807003668e100f008a11091080940f9c80000b4090140f9890000b40971403969ff07373200001468e100f00801d1391f050071cc05005473e100f073a21091e80313aa080940f9280100b4090140f9e90000b409714039a90400360961c0393f0500710dffff5421000014000e8152e1942294f40300aa21bf00f0214c069123bf00f063203391c26b8552040080522500805267952294e1430091e00314aac49e2394930e00f9681e40b9891640b92801082a881600b968006836e00314aaab952294e00314aa6990229400011036214c009021101791a0008052f32341949b234194a10080526c234194e80b40f9e8f0ffb4001100d1080080120800e8b81f05007141f0ff54e776239480ffff1701008052f70308aa27741e94e80317aa80dd0736490180526dfeff17f30300aae00314aa099522940a0000140800001407000014f30300aae00316aa03952294090000140700001406000014f30300aae80b40f9280400b52a0000141c000014f30300aae80740f9a80000b523000014f30300aae80340f9080400b4001100d1080080120800e8b81f05007161030054c176239419000014f30300aae01f40f9c00200b408200091090080120801e9b81f05007121020054080040f9080540f900013fd60d0000140b000014f30300aae81f40f9680100b4001100d1080080120800e8b81f050071c1000054aa76239404000014f30300aae0430091cbad2494e00313aad61f4194")
BASE,RT,OWNER,BANK,TABLE,RULE,COMP,REQ,TI,NAME = (0x10000000+i*0x100000 for i in range(10))
STACK,STOP=0x400000000000,0x400000100000
ENTRY=0x3AA5A14


def memory(selector=19):
    cells={}
    def put(at,raw):cells.update({at+i:b for i,b in enumerate(raw)})
    def q(at,n):put(at,struct.pack('<Q',n))
    def read(at,n):
        try:return bytes(cells[at+i]for i in range(n))
        except KeyError as exc:raise ValueError('Missing synthetic byte')from exc
    put(BASE+ENTRY,ORIGINAL);put(RT,bytes(0x400));put(RULE,bytes(0x130))
    q(RT,BASE+0x566C2B8);put(BASE+0x566C2B8-16,struct.pack('<qQ',0,TI))
    q(TI+8,NAME);put(NAME,b'N7sicomps11ACTUAL_COMPE\0')
    put(RT+0x3BE,b'\x15');q(RT+0x138,COMP);put(COMP+12,struct.pack('<i',1301394))
    q(RT+0x388,OWNER);q(OWNER+0x1F0,BANK)
    put(BANK+0x60,struct.pack('<QQQ',TABLE,TABLE+8,TABLE+8));q(TABLE,RULE)
    put(RULE+0x125,bytes([selector]));put(RULE+0x12C,b'\x01')
    put(RULE+0x108,struct.pack('<i',1301394));q(RULE+0x70,REQ)
    put(REQ+0x18,b'\x02\x03\x17')
    return cells,read,put,q


def original(cells,index=-1):
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);known=set(cells)
    pages={a&~4095 for a in cells}|set(range(STACK,STACK+0x10000,4096))|{STOP}
    for page in pages:uc.mem_map(page,4096)
    for page in {a&~4095 for a in cells}:
        uc.mem_write(page,bytes(cells.get(a,0)for a in range(page,page+4096)))
    trace,reads,missing=[],[],[]
    def instruction(machine,at,n,user):
        if at==STOP:machine.emu_stop();return
        assert BASE+ENTRY<=at and at+n<=BASE+ENTRY+len(ORIGINAL),'Unproved native callee'
        assert all(at+i in known for i in range(n)),'Missing original instruction'
        trace.append(at-BASE)
    def load(machine,access,at,n,value,user):
        if not all(at+i in known for i in range(n)):
            missing.append((at,n));machine.emu_stop();return
        if not STACK<=at<STACK+0x10000:reads.append((at,n))
    def store(machine,access,at,n,value,user):
        assert STACK<=at and at+n<=STACK+0x10000,'Nonstack write'
        known.update(range(at,at+n))
    def invalid(machine,access,at,n,value,user):
        missing.append((at,n));machine.emu_stop();return False
    uc.hook_add(UC_HOOK_CODE,instruction);uc.hook_add(UC_HOOK_MEM_READ,load)
    uc.hook_add(UC_HOOK_MEM_WRITE,store);uc.hook_add(UC_HOOK_MEM_INVALID,invalid)
    for i,arg in enumerate((RT,0,index&0xFFFFFFFF,0xFFFFFFFF)):
        uc.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),arg)
    uc.reg_write(regs.UC_ARM64_REG_SP,STACK+0xF000);uc.reg_write(regs.UC_ARM64_REG_LR,STOP)
    try:uc.emu_start(BASE+ENTRY,STOP,count=2000)
    except Exception:
        if missing:raise AssertionError('Missing recorded operand')
        raise
    assert not missing,'Missing recorded operand'
    assert uc.reg_read(regs.UC_ARM64_REG_PC)==STOP,'Original did not terminate'
    return uc.reg_read(regs.UC_ARM64_REG_X0),trace,reads


@pytest.mark.parametrize('selector',(4,8,9,19,255))
@pytest.mark.parametrize('index',(-1,0))
def test_rule_operands_match_complete_original(selector,index):
    cells,read,_,_=memory(selector)
    assert hashlib.sha256(ORIGINAL).hexdigest()==source.NATIVE_GUARDS[0][2]
    pointer,trace,reads=original(cells,index)
    result,binding=source.rule_context(read,BASE,RT,index)
    assert pointer==binding['rule_address']==RULE
    assert result['native_selector']==(selector if selector<128 else selector-256)
    assert result['requirement_codes']==[3,23]
    assert result['registration_verdict']is None and result['age_exempt']is None
    assert result['fixture_phase_evaluated']is False
    assert result['full_eligibility_evaluated']is False
    assert trace and reads


@pytest.mark.parametrize('fault',('type','kind','owner','override','initialization','absent_rule','postfilter'))
def test_unproved_context_remains_unknown(fault):
    cells,read,put,q=memory(8 if fault=='postfilter'else 19)
    if fault=='type':q(RT,BASE+0x5671128)
    if fault=='kind':put(RT+0x3BE,b'\x03')
    if fault=='owner':put(COMP+12,struct.pack('<i',11))
    if fault=='override':put(RT+0x4C,b'\x08')
    if fault=='initialization':put(RT+0x49,b'\xff')
    if fault=='absent_rule':q(TABLE,0)
    if fault=='postfilter':put(RULE+0x12C,b'\0')
    if fault=='type':
        with pytest.raises(ValueError,match='type'):source.rule_context(read,BASE,RT)
    else:
        result,binding=source.rule_context(read,BASE,RT)
        assert result['state']=='unavailable'and binding is None
        assert result['registration_verdict']is None and result['age_exempt']is None


def test_late_selector_drift_is_rejected():
    _,read,put,_=memory();snapshot=world.ReadSet(read)
    assert source.rule_context(snapshot,BASE,RT)[0]['state']=='available'
    put(RULE+0x125,b'\x08')
    with pytest.raises(ValueError,match='changed during read'):snapshot.verify()


def test_each_reached_original_operand_is_required():
    cells,_,_,_=memory();_,_,reads=original(cells)
    for at,n in set(reads):
        altered=dict(cells);del altered[at]
        with pytest.raises(AssertionError,match='Missing recorded operand'):original(altered)


@pytest.mark.parametrize('index',(True,-2,128,255,'0'))
def test_invalid_rule_index_rejects(index):
    _,read,_,_=memory()
    with pytest.raises(ValueError,match='rule index'):source.rule_context(read,BASE,RT,index)


def test_missing_operand_is_not_a_negative_registration_fact():
    cells,read,_,_=memory();del cells[RULE+0x125]
    with pytest.raises(ValueError,match='Missing synthetic byte'):source.rule_context(read,BASE,RT)


def test_native_code_drift_rejects(monkeypatch):
    _,read,put,_=memory();monkeypatch.setattr(source,'NATIVE_GUARDS',source.NATIVE_GUARDS[:1])
    source.verify_native(read,BASE);put(BASE+ENTRY,b'\0')
    with pytest.raises(ValueError,match='layout changed'):source.verify_native(read,BASE)


def phase_memory():
    from fm_live_mcp import competition_stages, fixtures
    cells,read,put,q=memory(0)
    fixture,stage,settings,slots=0x70000000,0x71000000,0x72000000,0x73000000
    def typed(address,expected,info):
        rva,name=expected;q(address,BASE+rva)
        put(BASE+rva-16,struct.pack('<qQ',0,info));q(info+8,info+16);put(info+16,name+b'\0')
    typed(fixture,fixtures.TYPES['fixture'],0x74000000)
    typed(stage,competition_stages.STAGE_TYPES['league'],0x75000000)
    typed(settings,competition_stages.SETTINGS,0x76000000)
    put(fixture+0x38,b'\0\xff');put(fixture+0x54,b'\xff');put(fixture+0x4C,struct.pack('<HH',330,2030))
    put(BASE+world.CURRENT_DATE,struct.pack('<HH',330,2030))
    put(RT+0x1D8,struct.pack('<QQQ',slots,slots+8,slots+8));q(slots,stage)
    q(stage+0x70,COMP);q(stage+0xF0,settings);put(settings+0x175,b'\xff')
    table=BASE+competition_stages.STAGE_TYPES['league'][0]
    for slot,fn in((0x2F8,0x3F22F98),(0x2D8,0x3B8C0A0),(0x2C8,0x3F22F90),(0x3E0,0x3F23068)):
        q(table+slot,BASE+fn)
    put(REQ+0x18,b'\x02\x0e\x1a');put(RULE+0xF2,b'\x01')
    decoded=dict(kind='fixture',competition=dict(native_id=1301394,database_index=637,random_id=None),
                 competition_address=COMP,season_code=2030,teams=(0x77000000,0x78000000))
    return cells,read,put,q,fixture,stage,settings,slots,decoded


def test_typed_league_phase_matches_proven_fixture_route():
    _,read,_,_,fixture,_,_,_,_=phase_memory()
    assert source._phase_index(read,BASE,RT,fixture,COMP)==(-1,'fixture_league_settings')


def test_direct_fixture_rule_uses_its_own_index():
    _,read,put,_,fixture,_,_,_,_=phase_memory();put(fixture+0x54,b'\x03')
    assert source._phase_index(read,BASE,RT,fixture,COMP)==(3,'fixture_direct_rule')


@pytest.mark.parametrize('fault',('owner','dispatch','null_stage','other_stage','invalid_index'))
def test_invalid_phase_sources_do_not_become_registration(fault):
    from fm_live_mcp import competition_stages
    _,read,put,q,fixture,stage,settings,slots,_=phase_memory()
    if fault=='owner':q(stage+0x70,COMP+8)
    if fault=='dispatch':q(BASE+competition_stages.STAGE_TYPES['league'][0]+0x3E0,BASE+0x3B8C0A0)
    if fault=='null_stage':q(slots,0)
    if fault=='other_stage':q(stage,BASE+competition_stages.STAGE_TYPES['cup'][0])
    if fault=='invalid_index':put(settings+0x175,b'\x80')
    if fault in('owner','dispatch'):
        with pytest.raises(ValueError,match='changed'):source._phase_index(read,BASE,RT,fixture,COMP)
    else:assert source._phase_index(read,BASE,RT,fixture,COMP)[0]is None


def setup_context(monkeypatch):
    result=phase_memory();decoded=result[-1]
    monkeypatch.setattr(source,'verify_native',lambda *_:None)
    monkeypatch.setattr(source.player_registration_source,'verify_native',lambda *_:None)
    monkeypatch.setattr(source.competition_stages,'runtime_context',lambda *_:(
        dict(native_season_code=2030,shared_runtime=False),RT,None))
    monkeypatch.setattr(source.player_registration_source,'current_league_context',lambda *_:(
        dict(source_state='available',reason='native_current_pl_registration_context'),
        dict(base=BASE,team_address=decoded['teams'][0],club_address=COMP+0x100,selector=8)))
    return result


def test_ucl_fixture_context_never_uses_pl_selector(monkeypatch):
    _,read,_,_,fixture,_,_,_,decoded=setup_context(monkeypatch)
    public,binding=source.fixture_context(read,BASE,dict(team_address=decoded['teams'][0]),
                                         fixture,decoded,'2030-11-26')
    assert public['state']=='available'and public['native_selector']==binding['selector']==0
    assert public['fixture_phase_evaluated']is True
    assert public['requirement_codes']==[14,26]
    assert public['registration_verdict']is None and public['age_exempt']is None
    assert public['full_eligibility_evaluated']is False


@pytest.mark.parametrize('fault',('season','competition','past','team','requirement','prerequisite'))
def test_other_fixture_contexts_stay_unavailable(monkeypatch,fault):
    _,read,put,_,fixture,_,_,_,decoded=setup_context(monkeypatch)
    coach=dict(team_address=decoded['teams'][0])
    if fault=='season':decoded['season_code']=2029
    if fault=='competition':decoded['competition']['native_id']=11
    if fault=='past':put(fixture+0x4C,struct.pack('<HH',329,2030))
    if fault=='team':coach['team_address']+=8
    if fault=='requirement':put(REQ+0x19,b'\x03')
    if fault=='prerequisite':
        monkeypatch.setattr(source.player_registration_source,'current_league_context',lambda *_:(dict(reason='unsupported_context'),None))
    public,binding=source.fixture_context(read,BASE,coach,fixture,decoded,'2030-11-26')
    assert public['state']=='unavailable'and binding is None
    assert public['full_eligibility_evaluated']is False


def test_late_fixture_phase_drift_rejects():
    _,read,put,_,fixture,_,settings,_,_=phase_memory();snapshot=world.ReadSet(read)
    source._phase_index(snapshot,BASE,RT,fixture,COMP);put(settings+0x175,b'\0')
    with pytest.raises(ValueError,match='changed during read'):snapshot.verify()


def test_unknown_contract_getter_cannot_inherit_positive_marker(monkeypatch):
    _,read,_,q=memory();primary,contract,table=0x80000000,0x81000000,0x82000000
    q(primary+0x2F0,contract);q(contract,table)
    monkeypatch.setattr(source.player_registration_source,'current_predicate',lambda *_:
        dict(source_state='available',native_predicate_result=True,reason='marker'))
    result=source.registered(read,primary,'actual',dict(base=BASE))
    assert result['source_state']=='unavailable'and result['native_predicate_result']is None


def age_memory(monkeypatch,birth='2010-10-13',days=731):
    from datetime import date
    from fm_live_mcp import players,teams
    cells,read,put,q=memory()
    primary,team,club,holder,vector,entry=(0x90000000+i*0x10000 for i in range(6))
    nation,nation_runtime,season,bank,context,template,previous,settings,info=(0x91000000+i*0x10000 for i in range(9))
    q(primary,BASE+players.RVA[0]);q(primary+0x388,BASE+players.RVA[2])
    table=BASE+players.RVA[2]
    put(table-0x1C8,struct.pack('<q',-0x110));put(table-0x580,struct.pack('<q',-0x110))
    for slot,fn in((0x138,0x148F4C0),(0x1B8,0xCA4640),(0x570,0xCC83D4)):
        q(table+slot,BASE+fn)
    put(primary+0x388+0x18,bytes(8));q(primary+0x128,team);put(team+0x2F,b'\0');q(team+0x30,club)
    put(team+8,struct.pack('<I',42));put(club+0x163,b'\x10')
    born=date.fromisoformat(birth)
    put(primary+0x2D0,struct.pack('<HH',born.timetuple().tm_yday,born.year))
    put(BASE+world.CURRENT_DATE,struct.pack('<HH',330,2030))
    q(primary+0x2C0,holder);put(holder+0x30,struct.pack('<QQQ',vector,vector+8,vector+8));q(vector,entry)
    put(entry,struct.pack('<QhBBI',team,days,0,0,0))
    q(club+0xD8,nation);q(nation,BASE+world.TYPES['nation'][0])
    put(BASE+world.TYPES['nation'][0]-16,struct.pack('<qQ',0,info));q(info+8,info+16)
    put(info+16,world.TYPES['nation'][1]+b'\0')
    put(BASE+0x56D34E0,b'\x01');q(nation+0x128,nation_runtime);q(nation_runtime+0x38,season)
    q(season+0x1F0,bank);q(bank+0x78,context);q(context+0x1B8,template)
    q(template+0x1F8,previous+0x100);q(template+0x1F0,previous)
    put(previous+4,struct.pack('<H',2025));put(template+0x234,struct.pack('<H',2030));put(template+0x240,b'\0')
    q(BASE+0x56A49F8,settings);put(settings+0x80B,b'\0')
    put(context+0x1DE,struct.pack('<h',1));put(context+0x1F1,b'\x07\0')
    monkeypatch.setattr(teams,'by_index',lambda *_:(None,dict(address=team,owner_address=club)))
    binding=dict(base=BASE,club_address=club,team_address=team,current_date='2030-11-26',selector=0,
                 ucl_competition_native_id=1301394,ucl_requirement_codes=(14,26))
    return dict(cells=cells,read=read,put=put,q=q,primary=primary,team=team,club=club,holder=holder,
                vector=vector,entry=entry,nation=nation,context=context,template=template,binding=binding)


def test_ucl_requirement14_needs_age_cutoff_and_club_history(monkeypatch):
    m=age_memory(monkeypatch)
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['current_age']==20 and result['age_at_cutoff']==19
    assert result['cutoff_date']=='2030-06-30'
    assert result['native_club_history_days']==731 and result['native_requirement14']is True
    assert result['registration_exempt']is True
    assert result['requirement26_evaluated']is False and result['full_eligibility_evaluated']is False


@pytest.mark.parametrize('days,expected',((730,False),(731,True)))
def test_native_club_days_threshold_is_strict(monkeypatch,days,expected):
    m=age_memory(monkeypatch,days=days)
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['native_requirement14']is expected
    assert result['registration_exempt']is (True if expected else None)


def test_requirement14_failure_cannot_exclude_other_requirement26(monkeypatch):
    m=age_memory(monkeypatch,birth='2008-10-13')
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['current_age']==22 and result['age_at_cutoff']==21
    assert result['native_requirement14']is False and result['registration_exempt']is None
    assert result['requirement26_evaluated']is False


@pytest.mark.parametrize('fault',('calendar','cache_init','day29','month0','template_transition','indexed_history','affiliation'))
def test_unproved_requirement14_branches_remain_unknown(monkeypatch,fault):
    m=age_memory(monkeypatch)
    if fault=='calendar':m['put'](m['primary']+0x388+0x18,struct.pack('<Q',1<<12))
    if fault=='cache_init':m['put'](m['context']+0x1DE,b'\xff\xff')
    if fault=='day29':m['put'](m['context']+0x1DE,struct.pack('<h',29))
    if fault=='month0':m['put'](m['context']+0x1F1,b'\0')
    if fault=='template_transition':m['put'](m['template']+0x234,struct.pack('<H',2024))
    if fault=='indexed_history':m['put'](m['entry']+11,b'\x01')
    if fault=='affiliation':
        m['put'](m['club']+0x163,b'\0')
        m['put'](m['club']+0x118,struct.pack('<QQQ',m['vector'],m['vector']+8,m['vector']+8))
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['state']=='unavailable'and result['native_requirement14']is None
    assert result['registration_exempt']is None


def test_club_history_combines_sum_and_flagged_max_like_native(monkeypatch):
    m=age_memory(monkeypatch,days=400)
    entries=[m['entry']+i*16 for i in range(3)]
    for i,(days,flags)in enumerate(((400,0),(400,0),(900,2))):
        m['q'](m['vector']+i*8,entries[i]);m['put'](entries[i],struct.pack('<QhBBI',m['team'],days,0,flags,0))
    m['put'](m['holder']+0x30,struct.pack('<QQQ',m['vector'],m['vector']+24,m['vector']+24))
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['native_club_history_days']==900


def test_late_club_history_drift_rejects(monkeypatch):
    m=age_memory(monkeypatch);snapshot=world.ReadSet(m['read'])
    assert source.requirement14(snapshot,m['primary'],'actual',m['binding'])['native_requirement14']is True
    m['put'](m['entry']+8,struct.pack('<h',0))
    with pytest.raises(ValueError,match='changed during read'):snapshot.verify()


def test_pl_binding_cannot_be_reused_as_ucl_exemption(monkeypatch):
    m=age_memory(monkeypatch);m['binding']['selector']=8
    result=source.requirement14(m['read'],m['primary'],'actual',m['binding'])
    assert result['state']=='unavailable'and result['native_requirement14']is None


def test_future_fixture_keeps_current_read_date_distinct(monkeypatch):
    _,read,put,_,fixture,_,_,_,decoded=setup_context(monkeypatch)
    put(fixture+0x4C,struct.pack('<HH',344,2030))
    context,_=source.fixture_context(read,BASE,dict(team_address=decoded['teams'][0]),fixture,decoded,'2030-11-26')
    assert context['current_read_date']=='2030-11-26'
    assert context['fixture_date']=='2030-12-10'
    assert context['full_eligibility_evaluated']is False


def test_pl_registered_predicate_cannot_be_relabelled_ucl():
    result=source.registered(lambda *_:pytest.fail('wrong competition must not read players'),
        0x90000000,'actual',dict(selector=8,ucl_competition_native_id=11))
    assert result['source_state']=='unavailable'and result['native_predicate_result']is None
