"""Native range codes against the complete original helper in owned RAM."""
from _knowledge_stream_fixture import native_stream_transport
import struct

import pytest

from fm_live_mcp import knowledge_scouting_range_source as source
from fm_live_mcp import knowledge_transfer_predicate as transfer
from test_knowledge_context_score_source import Memory
from test_knowledge_search_preliminary_source import restore_metadata
from _knowledge_state_native import execute


@pytest.fixture
def memory():
    m=Memory();m.range_context=m.personal+0xbd8
    m.other_competition=m.typed('competition',0x1b0)
    m.identity(m.other_competition,1,7001,7002)
    m.database('competitions',[m.competition,m.other_competition])
    m.other_nation=m.typed('nation',0x220);m.identity(m.other_nation,1,8001,8002)
    m.database('nations',[m.nation,m.other_nation])
    m.put(m.competition+0x1aa,b'\0');m.put(m.other_competition+0x1aa,b'\0')
    restore_metadata(m)
    return m


def actual(m,definition=None,nation=None):
    reader=transfer._Reader(m.read,m.base)
    return source.admitted(reader,m.club,m.range_context,
        m.competition if definition is None else definition,m.nation if nation is None else nation)


def native(m,definition=None,nation=None):
    value,_,reads,writes,code=execute(m,0xe1e354,[m.club,m.range_context,
        m.competition if definition is None else definition,m.nation if nation is None else nation],extra=source.NATIVE_GUARDS)
    assert 0xe1e354 in code
    assert all(0x200000000<=at<at+n<=0x200010000 for _,at,n in writes)
    return bool(value),reads,code


def test_all_codes_match_original_without_guessing_english_names(memory):
    m=memory
    for raw in range(256):
        m.put(m.personal+0xda4,bytes([raw]))
        assert actual(m) is native(m)[0]


@pytest.mark.parametrize('mode',[0,1,2,3,4,255])
def test_override_gate_matches_native_and_uses_same_callers_modes(memory,mode):
    m=memory;m.put(m.base+0x56d4951,bytes([mode]));m.put(m.base+0x56d496e,b'\1')
    assert actual(m) is native(m)[0] is True
    m.put(m.base+0x56d496e,b'\2')
    assert actual(m) is native(m)[0] is True


@pytest.mark.parametrize('code',[2,3])
def test_competition_identity_and_nested_key_comparisons(memory,code):
    m=memory;m.put(m.personal+0xda4,bytes([code]));definition=m.other_competition
    assert actual(m,definition) is native(m,definition)[0] is False
    left,right=m.allocate(0x7d0),m.allocate(0x7d0);key=m.allocate(8)
    m.q(definition+0xb0,left);m.q(m.competition+0xb0,right)
    m.q(left+0x7c8,key);m.q(right+0x7c8,key)
    assert actual(m,definition) is native(m,definition)[0] is True
    m.q(right+0x7c8,0)
    assert actual(m,definition) is native(m,definition)[0] is False


@pytest.mark.parametrize('code',[2,3,4,5,6,7])
@pytest.mark.parametrize('which',['empty','null_team','null_owner','null_competition','null_home','null_target','null_definition'])
def test_native_null_and_empty_comparisons(memory,code,which):
    m=memory;m.put(m.personal+0xda4,bytes([code]));definition=m.competition;nation=m.nation
    if which=='empty':m.vec(m.club+0x18,[])
    if which=='null_team':m.vec(m.club+0x18,[0])
    if which=='null_owner':m.q(m.team+0x30,0)
    if which=='null_competition':m.q(m.team+0x50,0)
    if which=='null_home':m.q(m.club+0xd8,0)
    if which=='null_target':nation=0
    if which=='null_definition':definition=0
    assert actual(m,definition,nation) is native(m,definition,nation)[0]


@pytest.mark.parametrize('code,offset',[(5,0x100),(6,0xf8)])
def test_shared_nation_property_allows_both_null_but_not_one_null(memory,code,offset):
    m=memory;m.put(m.personal+0xda4,bytes([code]))
    assert actual(m,nation=m.other_nation) is native(m,nation=m.other_nation)[0] is True
    key=m.allocate(8);m.q(m.nation+offset,key)
    assert actual(m,nation=m.other_nation) is native(m,nation=m.other_nation)[0] is False
    m.q(m.other_nation+offset,key)
    assert actual(m,nation=m.other_nation) is native(m,nation=m.other_nation)[0] is True


@pytest.mark.parametrize('left,right',[(-128,-127),(-127,-128),(-128,127),(127,-128),(126,127),(127,126),(0,0),(0,1),(0,-1),(-2,0),(2,0)])
def test_code3_signed_adjacency_has_no_byte_wraparound(memory,left,right):
    m=memory;m.put(m.personal+0xda4,b'\3')
    m.put(m.other_competition+0x1aa,struct.pack('<b',left));m.put(m.competition+0x1aa,struct.pack('<b',right))
    assert actual(m,m.other_competition) is native(m,m.other_competition)[0] is (left in (right-1,right+1))


def test_code3_requires_home_identity_before_competition_and_adjacency(memory):
    m=memory;m.put(m.personal+0xda4,b'\3')
    assert actual(m,nation=m.other_nation) is native(m,nation=m.other_nation)[0] is False


@pytest.mark.parametrize('fault',['code','club_type','definition_type','nation_type','team_owner','pointer','bounds'])
def test_unproved_sources_do_not_become_false_predicate_answers(memory,fault):
    m=memory;m.put(m.personal+0xda4,b'\2')
    if fault=='code':m.put(m.base+0xe1e354,b'\0')
    if fault=='club_type':m.q(m.club,0)
    if fault=='definition_type':m.q(m.competition,0)
    if fault=='nation_type':m.q(m.nation,0)
    if fault=='team_owner':m.q(m.team+0x30,m.other)
    if fault=='pointer':m.q(m.team+0x50,2)
    if fault=='bounds':m.q(m.club+0x20,0)
    with pytest.raises(ValueError):actual(m)


def _override_context(m):
    m.put(m.base+0x56d4951,b'\0');m.put(m.base+0x56d496e,b'\1')
    m.q(m.team+0x58,m.competition)


def test_entire_override_and_reached_policy_return_execute_without_lower_stubs(memory):
    m=memory;_override_context(m)
    for code in (0,2,3,4,5,6,7,255):
        m.put(m.personal+0xda4,bytes([code]))
        expected,reads,instructions=native(m,nation=m.other_nation)
        assert actual(m,nation=m.other_nation) is expected is True
        assert {0x1fa72c4,0x169552c,0x1695564,0x16956fc}<=set(instructions)
        assert 0x1fa7394 not in instructions


def test_every_mode_and_flag_byte_distinguishes_override_from_stored_false(memory):
    m=memory;_override_context(m);m.put(m.personal+0xda4,b'\0')
    for mode in range(256):
        m.put(m.base+0x56d4951,bytes([mode]))
        assert actual(m) is native(m)[0] is (mode not in (1,2))
    m.put(m.base+0x56d4951,b'\0')
    for flag in range(256):
        m.put(m.base+0x56d496e,bytes([flag]))
        assert actual(m) is native(m)[0] is bool(flag&1)


@pytest.mark.parametrize('edge',['flag','special_uid','empty','null_team','null_home','no_next','no_current','no_competition','null_projection','alternate_projection'])
def test_override_early_codes_and_selection_match_complete_original(memory,edge):
    m=memory;_override_context(m);m.put(m.personal+0xda4,b'\7');expected=False
    if edge=='flag':m.put(m.club+0x161,b'\x40')
    if edge=='special_uid':m.identity(m.club,0,0xd70dd0,0xd70dd0)
    if edge=='empty':m.vec(m.club+0x18,[])
    if edge=='null_team':m.vec(m.club+0x18,[0])
    if edge=='null_home':m.q(m.club+0xd8,0)
    if edge=='no_next':m.q(m.team+0x58,0);expected=True
    if edge=='no_current':m.q(m.team+0x50,0);expected=True
    if edge=='no_competition':m.q(m.team+0x50,0);m.q(m.team+0x58,0)
    if edge=='null_projection':m.q(m.nation+0x110,0)
    if edge=='alternate_projection':
        m.put(m.club+0xb9,b'\2');m.q(m.nation+0x118,m.container);m.q(m.nation+0x110,0);expected=True
    assert actual(m,nation=m.other_nation) is native(m,nation=m.other_nation)[0] is expected


@pytest.mark.parametrize('fault',['service','route','range_source','policy_source','projection_type','chosen_competition_type'])
def test_override_source_and_types_remain_checked(memory,fault):
    m=memory;_override_context(m)
    if fault=='service':m.q(m.game_club,0)
    if fault=='route':m.q(m.base+0x55df850+0x168,m.base+0x1fa72c8)
    if fault=='range_source':m.put(m.base+0x1fa72c4,b'\0')
    if fault=='policy_source':m.put(m.base+0x169552c,b'\0')
    if fault=='projection_type':m.q(m.container,0)
    if fault=='chosen_competition_type':m.q(m.team+0x58,m.nation)
    with pytest.raises(ValueError):actual(m)


def test_override_selects_existing_next_competition_without_reading_unused_current(memory):
    m=memory;_override_context(m);m.q(m.team+0x58,m.other_competition);m.q(m.team+0x50,2)
    assert actual(m) is native(m)[0] is True
