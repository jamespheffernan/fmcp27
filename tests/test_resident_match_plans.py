import struct
import pytest
from fm_live_mcp import resident_match_plans as source


@pytest.fixture
def native(monkeypatch):
    memory={}
    def put(address,value):memory[(address,8)]=struct.pack('<Q',value)
    engine=0x10000
    for i in range(2):
        side=0x20000+i*0x10000;team=0xa0000+i*0x10000;player=0x60000+i*0x10000;manager=0x80000+i*0x10000
        put(engine+0x15370+i*8,side);put(side+0xb8,team);memory[(team+8,4)]=struct.pack('<I',i+10)
        memory[(side+0x140,208)]=struct.pack('<26Q',player,*([0]*25))
        put(player+0x280,engine);put(player+0x288,side);put(player+0x298,manager)
        put(manager+0x280,engine);put(manager+0x288,side)
    def read(a,n):return memory[(a,n)]
    monkeypatch.setattr(source,'verify_native',lambda *a:None)
    monkeypatch.setattr(source.prepared_tactics_source,'_typed',lambda *a:None)
    monkeypatch.setattr(source.teams,'by_index',lambda r,b,i:({'database_index':i,'native_id':i+100},{'address':0xa0000+(i-10)*0x10000}))
    monkeypatch.setattr(source.prepared_tactics_fields,'decode',lambda *a:{'name':'Stored','phases':{'in_possession':{'positions':[{'position_index':0}]},'out_of_possession':{'positions':[{'position_index':0}]}}})
    monkeypatch.setattr(source.prepared_tactic_instructions,'decode',lambda *a:{'mentality':{'name':'Balanced'},'team_instructions':{'selected_options':[{'name':'Trap Outside'}]}})
    monkeypatch.setattr(source.prepared_tactic_roles,'decode',lambda *a:{'compiled_english_name':'Stored role'})
    return read,memory,put


def test_current_plans_are_content_pinned_and_do_not_claim_kickoff_or_fixture(native):
    read,_,_=native
    result=source.inspect(read,0,0x10000,[10,11])
    assert [s['team']['native_id']for s in result['sides']]==[110,111]
    assert not result['actual_kickoff_plan_verified'] and not result['display_clock_alignment_verified']
    assert result['fixture_binding_state']=='requires_independent_exact_fixture_binding'
    assert result['sides'][0]['checked_match_player_reverse_links']==1
    assert result['content_sha256']==source.inspect(read,0,0x10000,[10,11])['content_sha256']


def test_mismatched_ordered_fixture_team_rejected(native):
    with pytest.raises(ValueError,match='TEAM differs'):
        source.inspect(native[0],0,0x10000,[11,10])

@pytest.mark.parametrize('pointer,value',[(0x60000+0x280,0x99990),(0x60000+0x288,0x30000),(0x80000+0x280,0x99990),(0x80000+0x288,0x30000)])
def test_independent_reverse_link_mismatch_rejected(native,pointer,value):
    read,_,put=native;put(pointer,value)
    with pytest.raises(ValueError,match='reverse links'):
        source.inspect(read,0,0x10000)


def test_no_manager_is_unknown_source_not_a_zero_or_inactive_player_claim(native):
    read,_,put=native;put(0x60000+0x298,0)
    with pytest.raises(ValueError,match='missing or ambiguous'):
        source.inspect(read,0,0x10000)


def test_source_instruction_change_rejected():
    with pytest.raises(ValueError,match='native source changed'):
        source.verify_native(lambda a,n:bytes(n),0)

def test_unbound_extra_player_slot_is_counted_without_inventing_participation(native):
    read,memory,put=native
    memory[(0x20000+0x140,208)]=struct.pack('<26Q',0x60000,0x65000,*([0]*24))
    put(0x65000+0x298,0)
    row=source.inspect(read,0,0x10000)['sides'][0]
    assert row['checked_match_player_reverse_links']==1 and row['player_slots_without_manager']==1


def test_optional_raw_instruction_capture_retains_unclassified_bits(native):
    read,memory,_=native
    flags=(1<<0)|(1<<64)|(1<<87)
    for manager in (0x80000,0x90000):
        memory[(manager+0x1800+0xe0,11)]=flags.to_bytes(11,'little')
    plans=source.inspect(read,0,0x10000,[10,11],include_raw_instructions=True)
    for side in plans['sides']:
        instructions=side['plan']['team_instructions']
        assert instructions['raw_selection_flags_hex']==flags.to_bytes(11,'little').hex()
        assert instructions['unclassified_selected_bits']==[0,87]
    assert 'raw_selection_flags_hex' not in source.inspect(read,0,0x10000)['sides'][0]['plan']['team_instructions']
