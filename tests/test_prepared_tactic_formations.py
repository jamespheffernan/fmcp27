"""Full-u32 recognition and checked native runtime-resource composition."""
import struct

import pytest

from fm_live_mcp import prepared_tactic_formations as formations, world
from prepared_tactics_fixture import prepared_tactics_memory
from test_database import database_memory
from test_players import memory
from test_teams import team_memory
from test_world import world_memory
from prepared_tactic_formation_fixture import add_formation_context, IDENTIFIERS


IP = [1,4,0x200010,0x100010,8,0x200080,0x100080,0x800,0x2000,0x1000,0x4000]
OOP = IP[:7] + [0x100,0x200,0x2000,0x4000]
CODES = [-15,-13,-12,-10,-9,-7,-5,2,4,6,9]
# Independent native inverse-table oracle, not production converter output.
CANONICAL = [1,0,4,0x200010,0x10,0x100010,8,0x20,0x200080,0x80,
             0x100080,0x40,0x100,0x200400,0x400,0x100400,0x200,
             0x800,0x202000,0x2000,0x102000,0x1000,0x8000,0x204000,
             0x4000,0x104000,0x10000]


@pytest.fixture
def formation_memory(prepared_tactics_memory):
    return add_formation_context(prepared_tactics_memory)


def load(m, read=None):
    return formations.load(read or m['read'], m['base'])


@pytest.mark.parametrize('masks,identifier', [(IP,29),(OOP,33),(list(reversed(IP)),29)])
def test_independent_native_phase_shapes_and_order_invariance(formation_memory,masks,identifier):
    m = formation_memory
    read = world.ReadSet(m['read'])
    result = formations.identify(load(m,read),masks)
    read.verify()
    assert result == {'native_id':identifier,'state':'recognized',
                      'name':'4-2-3-1 DM AM Wide' if identifier==29 else '4-4-1-1 2DM'}


@pytest.mark.parametrize('mask,code', [(mask, -16 if code == -14 else code)
                                      for code,mask in zip(range(-15,12),CANONICAL)])
def test_all_native_canonical_converter_entries(mask,code):
    assert formations._compact_position(mask) == code


@pytest.mark.parametrize('mask,code', [(2,-15),(3,-15),(0x80000000,-15),(0xFFFFFFFF,-15),
                                      (0x100000,-15),(0x400000,-15),
                                      (0x100010|8,-10),(4|0x200000,-13)])
def test_full_u32_alias_and_branch_precedence(mask,code):
    assert formations._compact_position(mask) == code


def test_unknown_mask_can_match_native_id_without_inventing_position_name(formation_memory):
    context = load(formation_memory)
    assert formations.identify(context,[2]+IP[1:]) == {
        'native_id':29,'state':'recognized','name':'4-2-3-1 DM AM Wide'}


@pytest.mark.parametrize('flags', [None,b''])
def test_null_and_allocated_empty_policy_use_native_static_exclusions(formation_memory,flags):
    m = formation_memory
    m['formation_set_policy'](flags)
    assert formations.STATIC_EXCLUDED == frozenset((1,13,17,37,43,44,45,48,49))
    assert formations.identify(load(m),IP)['native_id'] == 29
    assert formations.identify(load(m),OOP)['native_id'] == 33
    # An absent ID1 falls back to3, but empty native policy excludes1.
    m['formation_set_template'](3,CODES)
    assert formations.identify(load(m),IP)['native_id'] == 3


def test_short_nonempty_policy_excludes_out_of_bounds_candidates(formation_memory):
    m = formation_memory
    m['formation_set_policy'](bytes(29)+b'\x80')
    context = load(m)
    assert formations.identify(context,IP)['native_id'] == 29
    assert formations.identify(context,OOP) == {
        'native_id':0,'state':'no_eligible_template_match','name':None}


@pytest.mark.parametrize('flags', [b'\x01',bytes(70)])
def test_nonempty_policy_without_eligible_candidates_is_valid_no_match(formation_memory,flags):
    m = formation_memory
    m['formation_set_policy'](flags)
    assert formations.identify(load(m),IP)['state'] == 'no_eligible_template_match'


def test_candidate_absent_from_metadata_uses_native_template3_fallback(formation_memory):
    m = formation_memory
    assert 1 not in IDENTIFIERS
    m['formation_set_template'](3,CODES)
    m['formation_set_policy'](b'\x00\x01')
    assert formations.identify(load(m),IP)['native_id'] == 1


def test_first_eligible_match_wins_without_template_or_shape_dedup(formation_memory):
    m = formation_memory
    m['formation_set_template'](3,CODES)
    m['formation_set_template'](4,CODES)
    m['formation_set_policy'](b'\0\0\0\1\1')
    assert formations.identify(load(m),IP)['native_id'] == 3
    m['formation_set_policy'](b'\0\0\0\0\1')
    assert formations.identify(load(m),IP)['native_id'] == 4


@pytest.mark.parametrize('code', [c for c in range(-15,12) if c != -14])
def test_alternative_runtime_layouts_cover_every_canonical_position(formation_memory,code):
    m = formation_memory
    m['formation_set_template'](3,[code]*11)
    m['formation_set_policy'](b'\0\0\0\1')
    mask = CANONICAL[code+15]
    assert formations.identify(load(m),[mask]*11)['native_id'] == 3


def test_packed_high_bits_are_not_interpreted_as_roles_or_names(formation_memory):
    m = formation_memory
    index = IDENTIFIERS.index(29)
    address = m['formation_templates']+index*24
    words = struct.unpack('<11H',m['read'](address,22))
    m['put'](address,struct.pack('<11H',*(word|0xFFC0 for word in words)))
    assert formations.identify(load(m),IP)['native_id'] == 29


def test_metadata_order_rebinds_exact_runtime_records(formation_memory):
    m = formation_memory
    first,second = IDENTIFIERS.index(29),IDENTIFIERS.index(33)
    m['put'](m['formation_metadata']+first*24,b'\x21')
    m['put'](m['formation_metadata']+second*24,b'\x1d')
    assert formations.identify(load(m),IP)['native_id'] == 33
    assert formations.identify(load(m),OOP)['native_id'] == 29


@pytest.mark.parametrize('guard,raw', [('metadata',0),('runtime',0),('metadata',2),('runtime',254)])
def test_known_uninitialized_guard_does_not_read_or_initialize_storage(formation_memory,guard,raw):
    m = formation_memory
    rva = formations.METADATA_GUARD_RVA if guard=='metadata' else formations.TEMPLATE_GUARD_RVA
    m['put'](m['base']+rva,bytes([raw]))
    forbidden = {m['base']+formations.POLICY_RVA,m['base']+formations.TEMPLATE_VECTOR_RVA,
                 m['formation_metadata'],m['formation_templates']}
    def read(address,size):
        assert address not in forbidden
        return m['read'](address,size)
    assert load(m,read) is None
    assert formations.identify(None,IP) == {
        'native_id':None,'state':'unavailable_uninitialized_templates','name':None}


@pytest.mark.parametrize('masks', [[],IP[:-1],IP+[1],[True]+IP[1:],[-1]+IP[1:],
                                   [1<<32]+IP[1:],['1']+IP[1:],None])
def test_mask_shape_and_u32_validation_even_with_uninitialized_context(masks):
    with pytest.raises(ValueError):
        formations.identify(None,masks)


@pytest.mark.parametrize('code', [-32,-16,-14,12,31])
def test_unsupported_initialized_template_encoding_rejects_whole_context(formation_memory,code):
    m = formation_memory
    m['formation_set_template'](29,[code]+CODES[1:])
    with pytest.raises(ValueError,match='template position encoding'):
        load(m)


@pytest.mark.parametrize('change', ['duplicate','no_fallback3','zero','above69'])
def test_unsupported_metadata_representation_rejects(formation_memory,change):
    m = formation_memory
    index = IDENTIFIERS.index(3) if change=='no_fallback3' else 0
    value = {'duplicate':IDENTIFIERS[1],'no_fallback3':1,'zero':0,'above69':70}[change]
    m['put'](m['formation_metadata']+index*24,bytes([value]))
    with pytest.raises(ValueError,match='metadata identifiers'):
        load(m)


@pytest.mark.parametrize('kind', ['null','unaligned','short','long','capacity_below_end','capacity_stride','capacity_budget'])
def test_malformed_initialized_template_vector_rejects(formation_memory,kind):
    m = formation_memory
    start = m['formation_templates']
    bounds = {'null':(0,0,0),'unaligned':(start+1,start+1537,start+1537),
              'short':(start,start+1512,start+1536),'long':(start,start+1560,start+1560),
              'capacity_below_end':(start,start+1536,start+1512),
              'capacity_stride':(start,start+1536,start+1537),
              'capacity_budget':(start,start+1536,start+129*24)}[kind]
    m['put'](m['base']+formations.TEMPLATE_VECTOR_RVA,struct.pack('<QQQ',*bounds))
    with pytest.raises(ValueError):
        load(m)


@pytest.mark.parametrize('bounds', [(0,0,1),(4095,4095,4095),(5000,4999,5000),
                                    (5000,5001,5000),(5000,5001,9097)])
def test_malformed_policy_header_rejects(formation_memory,bounds):
    m = formation_memory
    m['put'](m['base']+formations.POLICY_RVA,struct.pack('<QQQ',*bounds))
    with pytest.raises(ValueError,match='policy bounds'):
        load(m)


def test_byte_policy_storage_can_be_unaligned(formation_memory):
    m = formation_memory
    start = m['formation_policy_address']+1
    m['put'](start,bytes(29)+b'\x01')
    m['put'](m['base']+formations.POLICY_RVA,struct.pack('<QQQ',start,start+30,start+30))
    assert formations.identify(load(m),IP)['native_id'] == 29


def test_only_needed_first70_policy_bytes_are_consumed(formation_memory):
    m = formation_memory
    m['formation_set_policy'](bytes(29)+b'\x01'+bytes(98))
    read = world.ReadSet(m['read'])
    assert formations.identify(load(m,read),IP)['native_id'] == 29
    assert (m['formation_policy_address'],70) in read.observed
    m['put'](m['formation_policy_address']+90,b'\xFF')
    read.verify()


def test_zero_masks_are_valid_no_match_and_not_uninitialized(formation_memory):
    assert formations.identify(load(formation_memory),[0]*11) == {
        'native_id':0,'state':'no_eligible_template_match','name':None}


@pytest.mark.parametrize('index',range(len(formations.NATIVE_SPANS)))
def test_every_native_guard_mismatch_rejects(formation_memory,index):
    m = formation_memory
    rva,raw = formations.NATIVE_SPANS[index]
    m['put'](m['base']+rva,bytes([raw[0]^1]))
    with pytest.raises(ValueError,match='native layout changed'):
        load(m)


@pytest.mark.parametrize('kind', ['guard','policy_header','policy','vector','metadata','record','native'])
def test_supplied_readset_detects_late_context_drift(formation_memory,kind):
    m = formation_memory
    read = world.ReadSet(m['read'])
    formations.identify(load(m,read),IP)
    address = {'guard':m['base']+formations.TEMPLATE_GUARD_RVA,
               'policy_header':m['base']+formations.POLICY_RVA,
               'policy':m['formation_policy_address']+29,
               'vector':m['base']+formations.TEMPLATE_VECTOR_RVA,
               'metadata':m['formation_metadata'], 'record':m['formation_templates'],
               'native':m['base']+formations.NATIVE_SPANS[0][0]}[kind]
    m['put'](address,bytes([m['read'](address,1)[0]^1]))
    with pytest.raises(ValueError,match='changed during read'):
        read.verify()


@pytest.mark.parametrize('kind', ['policy_header','policy','vector','metadata','record','native'])
def test_incomplete_context_reads_reject(formation_memory,kind):
    m = formation_memory
    address = {'policy_header':m['base']+formations.POLICY_RVA,
               'policy':m['formation_policy_address'],
               'vector':m['base']+formations.TEMPLATE_VECTOR_RVA,
               'metadata':m['formation_metadata'],'record':m['formation_templates'],
               'native':m['base']+formations.NATIVE_SPANS[0][0]}[kind]
    def read(at,size):
        raw = m['read'](at,size)
        return raw[:-1] if at==address else raw
    with pytest.raises(ValueError,match='Incomplete'):
        load(m,read)


@pytest.mark.parametrize('identifier,codes,name', [
    (3,CODES,'4-2-3-1 DM AM Wide'),
    (4,[-15,-13,-12,-10,-9,-7,-5,-3,1,4,9],'4-4-1-1 2DM'),
])
def test_name_uses_renderer_projection_not_candidate_id(formation_memory,identifier,codes,name):
    m = formation_memory
    m['formation_set_template'](identifier,codes)
    m['formation_set_policy'](bytes(identifier)+b'\x01')
    masks = [CANONICAL[c+15] for c in codes]
    assert formations.identify(load(m),masks) == {'native_id':identifier,'state':'recognized','name':name}


def test_missing_candidate_uses_template3_name_under_same_fallback(formation_memory):
    m = formation_memory
    m['formation_set_template'](3,CODES)
    m['formation_set_policy'](b'\0\1')
    assert formations.identify(load(m),IP) == {
        'native_id':1,'state':'recognized','name':'4-2-3-1 DM AM Wide'}


@pytest.mark.parametrize('tail', [0,1,3,5,255])
def test_unproved_mentality_tail_preserves_id_without_name(formation_memory,tail):
    m = formation_memory
    m['put'](m['formation_templates']+IDENTIFIERS.index(29)*24+22,bytes([tail]))
    assert formations.identify(load(m),IP) == {'native_id':29,'state':'recognized','name':None}


@pytest.mark.parametrize('tail23', [0,1,255])
def test_unused_tail_byte_does_not_change_proved_name(formation_memory,tail23):
    m = formation_memory
    m['put'](m['formation_templates']+IDENTIFIERS.index(29)*24+23,bytes([tail23]))
    assert formations.identify(load(m),IP)['name'] == '4-2-3-1 DM AM Wide'


def test_packed_high_bits_and_template_permutation_preserve_name(formation_memory):
    m = formation_memory
    address = m['formation_templates']+IDENTIFIERS.index(29)*24
    words = struct.unpack('<11H',m['read'](address,22))
    m['put'](address,struct.pack('<11H',*(word|0xFFC0 for word in reversed(words))))
    assert formations.identify(load(m),IP)['name'] == '4-2-3-1 DM AM Wide'


def test_first_matching_unnamed_template_is_not_skipped_for_later_named_one(formation_memory):
    m = formation_memory
    m['formation_set_template'](3,CODES)
    m['formation_set_template'](4,CODES)
    m['put'](m['formation_templates']+IDENTIFIERS.index(3)*24+22,b'\x05')
    m['formation_set_policy'](b'\0\0\0\1\1')
    assert formations.identify(load(m),IP) == {'native_id':3,'state':'recognized','name':None}


@pytest.mark.parametrize('kind', ['localization','cache','entry'])
def test_legal_missing_naming_prerequisites_preserve_numeric_id(formation_memory,kind):
    m = formation_memory
    address = {'localization':m['base']+formations.LOCALIZATION_RVA,
               'cache':m['base']+formations.NUMERIC_CACHE_RVA,
               'entry':m['formation_numeric_cache']+0x328}[kind]
    m['q'](address,0)
    assert formations.identify(load(m),IP) == {'native_id':29,'state':'recognized','name':None}


@pytest.mark.parametrize('text', ['', '١', 'one', '2 '])
def test_valid_alternate_numeric_cache_strings_are_name_unavailability(formation_memory,text):
    m = formation_memory
    pointer = m['text'](text) if text else m['allocate'](5)
    if not text:m['put'](pointer,bytes(5))
    m['q'](m['formation_numeric_cache']+0x328,pointer)
    assert formations.identify(load(m),IP) == {'native_id':29,'state':'recognized','name':None}


@pytest.mark.parametrize('kind', ['localization','cache','entry'])
def test_malformed_naming_pointers_reject_when_supported_name_requested(formation_memory,kind):
    m = formation_memory
    address = {'localization':m['base']+formations.LOCALIZATION_RVA,
               'cache':m['base']+formations.NUMERIC_CACHE_RVA,
               'entry':m['formation_numeric_cache']+0x328}[kind]
    m['q'](address,1)
    with pytest.raises(ValueError):
        formations.identify(load(m),IP)


@pytest.mark.parametrize('corruption', ['length','utf8','nul','control'])
def test_malformed_numeric_string_rejects_supported_name(formation_memory,corruption):
    m = formation_memory
    text = m['formation_digits'][1]
    if corruption=='length':m['put'](text,struct.pack('<I',513))
    elif corruption=='utf8':m['put'](text+4,b'\xFF')
    elif corruption=='nul':m['put'](text+5,b'x')
    else:m['put'](text+4,b'\n')
    with pytest.raises(ValueError):
        formations.identify(load(m),IP)


@pytest.mark.parametrize('index',range(len(formations.NAME_NATIVE_DIGESTS)))
def test_each_name_native_digest_rejects_supported_name_drift(formation_memory,index):
    m = formation_memory
    rva,_,_ = formations.NAME_NATIVE_DIGESTS[index]
    m['put'](m['base']+rva,bytes([m['read'](m['base']+rva,1)[0]^1]))
    with pytest.raises(ValueError,match='name native layout changed'):
        formations.identify(load(m),IP)


@pytest.mark.parametrize('case', ['unproved_shape','tail','no_match','uninitialized'])
def test_no_naming_reads_for_actual_unsupported_match_or_unavailable_result(formation_memory,case):
    m = formation_memory
    if case=='unproved_shape':
        m['formation_set_template'](3,[-15]*11)
        masks = [1]*11
    else:
        masks = IP
        if case=='tail':m['put'](m['formation_templates']+IDENTIFIERS.index(29)*24+22,b'\x05')
        elif case=='no_match':masks=[0]*11
        else:m['put'](m['base']+formations.TEMPLATE_GUARD_RVA,b'\0')
    forbidden={m['base']+formations.LOCALIZATION_RVA,m['base']+formations.NUMERIC_CACHE_RVA,
               *(m['base']+rva for rva,_,_ in formations.NAME_NATIVE_DIGESTS)}
    def read(address,size):
        assert address not in forbidden
        return m['read'](address,size)
    assert formations.identify(load(m,read),masks)['name'] is None


def test_naming_resources_loaded_only_once_per_private_context(formation_memory):
    m = formation_memory
    calls=[]
    def read(address,size):
        calls.append((address,size))
        return m['read'](address,size)
    context=load(m,read)
    assert formations.identify(context,IP)['name']=='4-2-3-1 DM AM Wide'
    assert formations.identify(context,OOP)['name']=='4-4-1-1 2DM'
    assert calls.count((m['base']+formations.LOCALIZATION_RVA,8))==1
    assert calls.count((m['base']+formations.NUMERIC_CACHE_RVA,8))==1
    assert calls.count((m['formation_digits'][1]+4,2))==1


@pytest.mark.parametrize('kind', ['service','cache','entry','digit','tail','name_code'])
def test_late_naming_resource_mutations_fail_final_readset_verify(formation_memory,kind):
    m=formation_memory
    read=world.ReadSet(m['read'])
    assert formations.identify(load(m,read),IP)['name']=='4-2-3-1 DM AM Wide'
    address={'service':m['base']+formations.LOCALIZATION_RVA,
             'cache':m['base']+formations.NUMERIC_CACHE_RVA,
             'entry':m['formation_numeric_cache']+0x328,'digit':m['formation_digits'][1]+4,
             'tail':m['formation_templates']+IDENTIFIERS.index(29)*24+22,
             'name_code':m['base']+formations.NAME_NATIVE_DIGESTS[0][0]}[kind]
    m['put'](address,bytes([m['read'](address,1)[0]^1]))
    with pytest.raises(ValueError,match='changed during read'):
        read.verify()


def test_numeric_cache_string_pointer_can_be_unaligned(formation_memory):
    m=formation_memory
    address=m['allocate'](7)+1
    m['put'](address,struct.pack('<I',1)+b'1\0')
    m['q'](m['formation_numeric_cache']+0x328,address)
    assert formations.identify(load(m),IP)['name']=='4-2-3-1 DM AM Wide'
