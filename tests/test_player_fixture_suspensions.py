"""Native kind1 positive/negative controls, distinct from overall clearance."""
import struct

import pytest

from fm_live_mcp import database, player_fixture_suspensions as suspension, players, teams

# Genuine Diouf source captured13Nov2030. TEAM/runtime addresses are separate
# controlled inputs, never substituted into these stored32 source bytes.
DIOUF = bytes.fromhex('96020000ff01000000000000000000002e7fee078800ffff020000ff01000000')
BASE, PRIMARY, TEAM, SECONDARY, RECORD = 0x10000000, 0x10000, 0x20000, 0x30000, 0x40000
CUP, PL, CUP_RT, PL_RT, MANAGER, BAN_RULE, DEFAULT, OWNER, BANK, GROUP, TABLE = (
    0x50000, 0x51000, 0x60000, 0x61000, 0x70000, 0x80000, 0x90000,
    0xA0000, 0xB0000, 0xC0000, 0xD0000)


@pytest.fixture
def native_memory(monkeypatch):
    memory = {}
    next_address = 0x100000
    def put(address, raw):
        for index, byte in enumerate(raw):
            memory[address+index] = byte
    def read(address, size):
        return bytes(memory.get(address+index, 0) for index in range(size))
    def q(address, value):
        put(address, struct.pack('<Q', value))
    def vector(address, values, width=8):
        nonlocal next_address
        if not values:
            put(address, bytes(24))
            return
        start = next_address
        next_address += max(0x100, width*len(values))
        raw = bytes(values) if width == 1 else struct.pack(f'<{len(values)}Q', *values)
        put(start, raw)
        put(address, struct.pack('<QQQ', start, start+len(raw), start+len(raw)))
    q(PRIMARY, BASE+players.RVA[0]); q(PRIMARY+0x128, TEAM);q(PRIMARY+0xF0, SECONDARY)
    put(TEAM+8, struct.pack('<I', 545));vector(SECONDARY+0x18, [RECORD]);put(RECORD, DIOUF)
    vector(MANAGER+8, [0]*136+[BAN_RULE])
    q(BAN_RULE+0x30, OWNER);q(OWNER+0x1F8, GROUP);q(OWNER+0x1F0, BANK)
    q(DEFAULT+0x30, OWNER);vector(BAN_RULE+0x40, [])
    q(CUP+0xB0, CUP_RT);q(PL+0xB0, PL_RT)
    for runtime, comp, kind in ((CUP_RT,CUP,3),(PL_RT,PL,0)):
        q(runtime+0x138,comp);q(runtime+0x388,OWNER)
        put(runtime+0x48,b'\0');put(runtime+0x3BE,bytes((kind,)))
    vector(BANK+0x48, [DEFAULT]);q(TABLE+662*8,CUP)
    monkeypatch.setattr(teams, 'by_index', lambda *_: ({}, dict(address=TEAM)))
    monkeypatch.setattr(database, 'table', lambda *_: dict(start=TABLE))
    scope = dict(native_id=1301427, database_index=662, random_id=None, name='Carabao Cup')
    monkeypatch.setattr(suspension.competitions, 'by_index', lambda *_: dict(scope))
    binding = dict(base=BASE,fixture_teams=(TEAM,TEAM+8),unplayed=True,runtime=PL_RT,
        discipline=MANAGER,fixture_date_raw=struct.pack('<HH',327,2030),unsupported_reason=None)
    return dict(read=read,put=put,q=q,vector=vector,binding=binding,scope=scope)


def project(m):
    return suspension.project(m['read'],BASE,PRIMARY,'actual',m['binding'])


def test_genuine_diouf_record_is_pl_negative_and_cup_positive(native_memory):
    m=native_memory
    negative=project(m)
    assert negative['state']=='checked' and negative['native_suspended']is False
    context=negative['record_context']
    assert context['native_scope_competition']['native_id']==1301427
    assert context['native_carryover_phase_list']==[]
    assert not any(context[k] for k in ('direct_scope_matches','scope_runtime_matches','fallback_scope_matches'))
    m['binding']['runtime']=CUP_RT
    m['binding']['fixture_date_raw']=struct.pack('<HH',352,2030)
    positive=project(m)
    assert positive['native_suspended']is True
    assert positive['record_context']['direct_scope_matches']is True
    assert positive['overall_fixture_eligibility']=='not_evaluated'


def test_phase_carryover_can_apply_across_competitions(native_memory):
    m=native_memory;m['vector'](BAN_RULE+0x40,[0],1)
    result=project(m)
    assert result['native_suspended']is True
    assert result['record_context']['trace'][-1]=='native_shared_group_phase_carryover'


def test_fallback_competition_relation_is_not_lost(native_memory):
    m=native_memory;m['q'](PL_RT+0x7C8,CUP_RT)
    result=project(m)
    assert result['native_suspended']is True
    assert result['record_context']['fallback_scope_matches']is True


def test_explicit_phase_mismatch_is_negative_without_comp_name_inference(native_memory):
    m=native_memory;m['put'](RECORD+4,b'\x01')
    result=project(m)
    assert result['native_suspended']is False
    assert result['record_context']['trace'][-1]=='native_explicit_phase_mismatch'


def test_supported_predicate_does_not_invent_match_balance_gate(native_memory):
    m=native_memory;m['binding']['runtime']=CUP_RT
    for total, served in ((1,0),(1,1),(0,0)):
        m['put'](RECORD+0x1C,bytes((total,served)))
        result=project(m)
        assert result['native_suspended']is True
        assert result['record_context']['match_balance_gate']=='not_read_on_supported_native_path'


def test_before_start_is_native_negative(native_memory):
    m=native_memory;m['binding']['runtime']=CUP_RT
    m['binding']['fixture_date_raw']=struct.pack('<HH',301,2030)
    assert project(m)['native_suspended']is False


@pytest.mark.parametrize('fault,reason',[("kind",'unsupported_personal_ban_kind'),
    ('duration','unsupported_finite_duration_or_cleanup_branch'),
    ('multiple','unsupported_multiple_or_null_personal_records'),
    ('phase','unsupported_default_phase_rule_fallback'),
    ('exemption','unsupported_special_competition_exemption_gate')])
def test_unsupported_sources_stay_unknown(native_memory,fault,reason):
    m=native_memory;m['binding']['runtime']=CUP_RT
    if fault=='kind':m['put'](RECORD+5,b'\x14')
    if fault=='duration':m['put'](RECORD+0x16,b'\x02\0')
    if fault=='multiple':m['vector'](SECONDARY+0x18,[RECORD,RECORD])
    if fault=='phase':m['put'](CUP_RT+0x48,b'\xff')
    if fault=='exemption':m['scope']['native_id']=0x24DCC
    result=project(m)
    assert result['native_suspended']is None and result['reason']==reason


def test_empty_negative_only_in_proved_unplayed_fixture_branch(native_memory):
    m=native_memory;m['vector'](SECONDARY+0x18,[])
    assert project(m)['reason']=='native_checked_empty_personal_ban_list'
    m['binding'].update(unplayed=False,unsupported_reason='unsupported_score_bearing_fixture_branch')
    assert project(m)['native_suspended']is None


def test_absent_secondary_native_false_keeps_missing_source_distinct(native_memory):
    m=native_memory;m['q'](PRIMARY+0xF0,0)
    result=project(m)
    assert result['native_suspended']is False and result['personal_record_count']is None
    assert result['reason']=='native_absent_personal_secondary'


def test_outside_current_team_stays_unknown_even_for_empty_source(native_memory):
    m=native_memory;m['vector'](SECONDARY+0x18,[]);m['binding']['fixture_teams']=(TEAM+8,TEAM+16)
    assert project(m)['reason']=='player_current_team_not_fixture_participant'


def test_malformed_rule_phase_vector_rejects(native_memory):
    m=native_memory;m['put'](BAN_RULE+0x40,struct.pack('<QQQ',0xE0000,0xD0000,0xF0000))
    with pytest.raises(ValueError,match='phase vector'):project(m)


def test_native_guard_drift_is_rejected():
    with pytest.raises(ValueError,match='native source changed'):
        suspension.verify_native(lambda at,size:bytes(size),BASE)


def test_context_accepts_real_four_aligned_native_method_pointer(native_memory,monkeypatch):
    from fm_live_mcp import fixtures
    m=native_memory;fixture,root,store,native,vt=0xF0000,0x110000,0x120000,0x130000,0x140000
    m['q'](fixture,BASE+fixtures.TYPES['fixture'][0]);m['q'](BASE+fixtures.TYPES['fixture'][0]+0x108,BASE+0x3D030D8)
    m['put'](fixture+0x4C,struct.pack('<HH',327,2030))
    m['q'](BASE+0x56D57D0,root);m['q'](root+0x158,store);m['q'](store+0x70,MANAGER)
    m['q'](BASE+0x56D2D08,native);m['q'](native,vt);m['q'](vt+0x230,BASE+0x1F8AF7C)
    monkeypatch.setattr(suspension,'verify_native',lambda *_:None)
    monkeypatch.setattr(fixtures,'typed',lambda *_:None)
    monkeypatch.setattr(suspension.competition_stages,'typed',lambda *_:None)
    monkeypatch.setattr(suspension.competition_stages,'runtime_context',lambda *_:(
        dict(native_season_code=2030,shared_runtime=False),PL_RT,(PL_RT,0,PL,7,11,2030)))
    decoded=dict(kind='fixture',competition=dict(database_index=7,native_id=11,random_id=None),
        competition_address=PL,teams=(TEAM,TEAM+8),season_code=2030)
    public,binding=suspension.context(m['read'],BASE,fixture,decoded,'2030-11-13')
    assert public['state']=='available' and binding['discipline']==MANAGER
    assert public['fixture_date']=='2030-11-23'
    m['q'](vt+0x230,BASE+0x1F8AF80)
    with pytest.raises(ValueError,match='manager method changed'):
        suspension.context(m['read'],BASE,fixture,decoded,'2030-11-13')
