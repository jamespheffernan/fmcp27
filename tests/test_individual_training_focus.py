"""Synthetic typed controls plus direct pinned on-disk native-source checks.

These tests never attach to the game or invoke native functions. They do not
supply the separate real managed-roster acceptance required by the MCP adapter.
"""
import hashlib
import mmap
from pathlib import Path
import re
import struct

import pytest

from fm_live_mcp import assessment_people, database, individual_training_focus as focus, individual_training_intensity as intensity, players, virtual_identity
from test_database import database_memory
from test_players import memory
from test_shortlist_members import member_memory
from test_teams import team_memory
from test_world import world_memory

import _pinned_build
PLUGIN = _pinned_build.PLUGIN
SLICE = 0x5ED4000


@pytest.fixture(scope='module')
def native_image():
    with PLUGIN.open('rb') as stream:
        assert hashlib.file_digest(stream, 'sha256').hexdigest() == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as image:
            yield image


@pytest.fixture
def focus_memory(team_memory, member_memory, native_image):
    assert team_memory is member_memory
    m = team_memory
    for rva, size, expected in focus.NATIVE_GUARDS + intensity.NATIVE_GUARDS:
        raw = native_image[SLICE+rva:SLICE+rva+size]
        assert hashlib.sha256(raw).hexdigest() == expected
        m['put'](m['base'] + rva, raw)
    for rva, raw in assessment_people.NATIVE_SPANS:
        assert native_image[SLICE+rva:SLICE+rva+len(raw)] == raw
        m['put'](m['base']+rva, raw)
    m['focus_child'] = m['allocate'](10)
    m['put'](m['focus_child'], bytes(6)+b'\x18'+bytes(3))
    m['q'](0x1190, m['focus_child'])
    m['focus_binding'] = {'address':0x1000, 'tables':m['tables'], 'database_index':0,
                          'world_bound':True, 'record_kind':'actual',
                          'identity':(12345,'Test','Müller','2000-02-29',12345)}
    return m


def inspect(m, *, read=None, binding=None, people=None, team=None, tables=None):
    return focus.inspect(read or m['read'], m['base'], m['tables'] if tables is None else tables,
                         database.table(m['read'],m['base'],'people') if people is None else people,
                         m['focus_binding'] if binding is None else binding,
                         team_address=m['team_addresses'][0] if team is None else team)


def _native_keys(image):
    """Follow the actual native enum switch to its first resource-key call.

    This independent integer decoder handles just the source case instructions;
    it derives code-to-key associations from the installed binary, not an output
    fixture or the implementation's FOCUS constant.
    """
    def word(a):
        return struct.unpack_from('<I',image,SLICE+a)[0]
    result = {}
    for code in range(33):
        entry = struct.unpack_from('<H',image,SLICE+0x5393B5A+code*2)[0]
        pc = 0x132747C+4*entry
        regs = {}
        for _ in range(40):
            w=word(pc);a=pc;pc+=4;rd=w&31;rn=(w>>5)&31
            if w&0x7F800000==0x52800000: # MOVZ W
                regs[rd]=((w>>5)&65535)<<(((w>>21)&3)*16)
            elif w&0x7F800000==0x72800000: # MOVK W
                shift=((w>>21)&3)*16
                regs[rd]=(regs.get(rd,0)&~(65535<<shift))|(((w>>5)&65535)<<shift)
            elif w&0xFF000000==0x11000000: # ADD immediate W
                regs[rd]=regs[rn]+(((w>>10)&4095)<<(12 if w&(1<<22) else 0))
            elif w&0xFF200000==0x2A000000: # ORR shifted-register W
                assert (w>>10)&63==0 and (w>>22)&3==0
                regs[rd]=regs[rn]|regs[(w>>16)&31]
            elif w&0xFF800000==0x32000000: # ORR logical immediate W
                imms=(w>>10)&63;immr=(w>>16)&63
                length=(~imms&63).bit_length()-1
                size=1<<length;s=imms&(size-1);r=immr&(size-1)
                bits=(1<<(s+1))-1;mask=(1<<size)-1
                rotated=((bits>>r)|(bits<<(size-r)))&mask
                value=sum(rotated<<i for i in range(0,32,size))
                regs[rd]=regs[rn]|value
            elif w&0x7C000000==0x14000000:
                off=w&0x3FFFFFF;off=off-(1<<26) if off&(1<<25) else off
                target=a+off*4
                if w&0x80000000:
                    assert target==0x43DB8B8
                    result[code]=regs[1]
                    break
                pc=target
            # ADD/ADRP X8 prepare the output buffer and do not change W keys.
            else:
                assert w&0xFF000000==0x91000000 or w&0x9F000000==0x90000000
        else:
            pytest.fail('Native focus case did not reach its resource call')
    return result


def test_all_33_names_match_native_switch_and_pinned_english(native_image):
    english=_pinned_build.language_template()
    assert hashlib.file_digest(english.open('rb'),'sha256').hexdigest()==focus.ENGLISH_SHA256
    labels={int(k):v.split('[COMMENT')[0] for k,v in re.findall(r'^KEY-(\d+): (.*)$',english.read_text(),re.M)}
    keys=_native_keys(native_image)
    assert len(keys)==33
    assert focus.FOCUS=={code:(key,labels[key]) for code,key in keys.items()}
    assert focus.FOCUS[0][1]=='Quickness Rehab'
    assert focus.FOCUS[24][1]=='Crossing'
    assert focus.FOCUS[32][1]=='GK Distribution'


def test_all_256_codes_through_typed_reader(focus_memory):
    m=focus_memory;counts={}
    for raw in range(256):
        m['put'](m['focus_child']+6,bytes([raw]))
        r=inspect(m);f=r['additional_focus']
        assert r['source_state']=='present_child' and r['record_kind']=='actual'
        assert r['native_identity']=={'database_index':0,'native_id':12345,'random_id':None}
        assert r['name']==r['display_name']=='Test Müller' and r['name_state']=='available'
        assert f['raw_code']==raw and f['native_code']==(raw if raw<128 else raw-256)
        counts[f['state']]=counts.get(f['state'],0)+1
        if raw<=32:
            assert (f['english_resource_key'],f['english_definition_name'])==focus.FOCUS[raw]
        else:
            assert f['english_resource_key'] is f['english_definition_name'] is None
    assert counts=={'stored_named_focus':33,'unknown_native_code':222,'unset':1}


def test_missing_and_explicit_unset_are_distinct_and_zero_is_named(focus_memory):
    m=focus_memory;m['q'](0x1190,0)
    missing=inspect(m)
    assert missing['source_state']=='missing_child'
    assert missing['additional_focus']['raw_code']==255
    m['q'](0x1190,m['focus_child']);m['put'](m['focus_child']+6,b'\xff')
    unset=inspect(m)
    assert unset['source_state']=='present_child'
    assert unset['additional_focus']==missing['additional_focus']
    assert unset['additional_focus']['native_code']==-1 and unset['additional_focus']['state']=='unset'
    m['put'](m['focus_child']+6,b'\0')
    zero=inspect(m)['additional_focus']
    assert zero['state']=='stored_named_focus' and zero['english_definition_name']=='Quickness Rehab'


@pytest.mark.parametrize('slot',[0,1,2,3,4,5,6,7])
def test_actual_stride_ten_pool_cells_allow_non_eight_alignment(focus_memory,slot):
    m=focus_memory;start=m['allocate'](80)
    for i in range(8):m['put'](start+10*i,bytes(6)+bytes([9+i])+bytes(3))
    child=start+10*slot;m['q'](0x1190,child)
    assert child%8 in (0,2,4,6)
    assert inspect(m)['additional_focus']['raw_code']==9+slot
    # Neighbor cells and every requested source byte remain untouched.
    assert m['read'](start,80)==b''.join(bytes(6)+bytes([9+i])+bytes(3) for i in range(8))


@pytest.mark.parametrize('width',range(10))
def test_complete_record_policy_rejects_truncated_child_even_if_getter_byte_exists(focus_memory,width):
    m=focus_memory;child=m['focus_child']
    def short(a,n):
        if a==child and n==10:return m['read'](a,width)
        return m['read'](a,n)
    with pytest.raises(ValueError,match='Incomplete'):inspect(m,read=short)


@pytest.mark.parametrize('child',[1,4095,(1<<64)-10,(1<<64)-1])
def test_invalid_plain_child_range_is_not_unset(focus_memory,child):
    m=focus_memory;m['q'](0x1190,child)
    with pytest.raises(ValueError,match='source address'):inspect(m)


def test_reader_does_not_decode_attributes_or_call_native_functions(focus_memory,monkeypatch):
    m=focus_memory
    monkeypatch.setattr(players,'decode',lambda *a,**kw:pytest.fail('Rich player decode'))
    def limited(a,n):
        if 0x1148<=a<0x118D or (a<0x118D and a+n>0x1148):pytest.fail('Attribute bytes read')
        return m['read'](a,n)
    assert inspect(m,read=limited)['additional_focus']['english_definition_name']=='Crossing'


@pytest.mark.parametrize('guard',range(14))
def test_each_exact_native_guard_refuses_mutation(focus_memory,guard):
    m=focus_memory;rva,_,_=focus.NATIVE_GUARDS[guard];a=m['base']+rva
    m['put'](a,bytes([m['read'](a,1)[0]^1]))
    with pytest.raises(ValueError,match='native source changed'):inspect(m)


@pytest.mark.parametrize('fault',[
    'primary_type','playing_type','person_type','primary_displacement','person_displacement',
    'rtti_name','person_cast','person_cast_offset','person_index','person_id','person_membership',
    'saved_identity','saved_identity_type','saved_index','saved_index_type','binding_type',
    'team_type','team_index','team_membership','team_owner','roster','roster_duplicate','base_table',
])
def test_corrupt_type_identity_and_owner_sources_reject(focus_memory,fault):
    m=focus_memory;base=m['base'];binding=dict(m['focus_binding']);team=m['team_addresses'][0];tables=m['tables']
    if fault=='primary_type':m['q'](0x1000,base+0x1234)
    elif fault=='playing_type':m['q'](0x1140,0)
    elif fault=='person_type':m['q'](0x1388,0)
    elif fault=='primary_displacement':m['put'](tables[0]-16,struct.pack('<q',8))
    elif fault=='person_displacement':m['put'](tables[2]-16,struct.pack('<q',-0x480))
    elif fault=='rtti_name':
        info=players.u64(m['read'](tables[2]-8,8));text=players.u64(m['read'](info+8,8));m['put'](text,b'X')
    elif fault=='person_cast':m['q'](tables[2]+0x668,0)
    elif fault=='person_cast_offset':m['put'](tables[2]-0x678,struct.pack('<q',-0x480))
    elif fault=='person_index':m['put'](0x1390,struct.pack('<I',1))
    elif fault=='person_id':m['put'](0x1394,struct.pack('<I',77))
    elif fault=='person_membership':m['vec'](m['headers']['people'],[m['club']])
    elif fault=='saved_identity':binding['identity']=(77,*binding['identity'][1:])
    elif fault=='saved_identity_type':binding['identity']=(12345.0,*binding['identity'][1:])
    elif fault=='saved_index':binding['database_index']=1
    elif fault=='saved_index_type':binding['database_index']=False
    elif fault=='binding_type':binding['record_kind']='player_staff'
    elif fault=='team_type':m['q'](team,0)
    elif fault=='team_index':m['put'](team+8,struct.pack('<I',1))
    elif fault=='team_membership':m['vec'](m['headers']['teams'],list(reversed(m['team_addresses'])))
    elif fault=='team_owner':m['q'](team+0x30,0x1000)
    elif fault=='roster':m['vec'](team+0x38,[])
    elif fault=='roster_duplicate':m['vec'](team+0x38,[0x1000,0x1000])
    elif fault=='base_table':tables=(tables[0]+8,*tables[1:])
    with pytest.raises((ValueError,KeyError)):inspect(m,binding=binding,tables=tables)


@pytest.mark.parametrize('address',[1,0x1001])
def test_object_pointer_alignment_remains_strict(focus_memory,address):
    m=focus_memory;b=dict(m['focus_binding']);b['address']=address
    with pytest.raises(ValueError,match='source address'):inspect(m,binding=b)
    with pytest.raises(ValueError,match='source address'):inspect(m,team=address)


@pytest.mark.parametrize('where',['pointer','focus','last_child_byte','person_id','roster','native'])
def test_internal_consumed_byte_recheck_detects_drift(focus_memory,where):
    m=focus_memory;child=m['focus_child'];reads={}
    if where=='pointer':target,size=0x1190,8
    elif where in ('focus','last_child_byte'):target,size=child,10
    elif where=='person_id':target,size=0x1388,20
    elif where=='roster':target,size=m['team_addresses'][0]+0x38,24
    else:target,size=m['base']+focus.NATIVE_GUARDS[0][0],focus.NATIVE_GUARDS[0][1]
    def changing(a,n):
        key=(a,n);reads[key]=reads.get(key,0)+1
        raw=m['read'](a,n)
        if key==(target,size) and reads[key]==2:
            value=bytearray(raw);index=9 if where=='last_child_byte' else 0;value[index]^=1;return bytes(value)
        return raw
    with pytest.raises(ValueError,match='changed'):inspect(m,read=changing)


@pytest.mark.parametrize('kind',['player_staff','virtual'])
def test_known_other_records_are_explicitly_unsupported_without_training_reads(focus_memory,kind):
    m=focus_memory;primary,person=m['add_person'](kind,0,77,0,'Combined')
    m['vec'](m['headers']['people'],[person]);m['vec'](m['team_addresses'][0]+0x38,[primary])
    binding={'address':primary,'tables':m['tables'],'record_kind':kind,'database_index':0}
    if kind=='player_staff':binding['identity']=('player_staff',77,'Combined','','2000-02-29',0)
    else:
        binding.update(binding_kind=virtual_identity.BINDING_KIND,
                       identity=(virtual_identity.BINDING_KIND,0,77,0))
    def limited(a,n):
        if a in (primary+0x190, primary+0x1eb):pytest.fail('Unsupported training source read')
        return m['read'](a,n)
    r=inspect(m,binding=binding,read=limited)
    assert r['source_state']=='unsupported_record_kind' and r['record_kind']==kind
    assert r['additional_focus'] is None
    assert r['club_training_intensity'] is None
    assert r['native_identity']=={'database_index':0,'native_id':77,'random_id':0}
    assert r['name'] is r['display_name'] is None and r['name_state']=='unsupported_record_kind'


@pytest.mark.parametrize('value',[-1,256,True,1.0,None,'24'])
def test_raw_enum_input_types_are_strict(value):
    with pytest.raises(ValueError):focus.focus(value)


@pytest.mark.parametrize('guard',range(len(assessment_people.NATIVE_SPANS)))
def test_dependency_cast_guards_are_checked_without_rich_decode(focus_memory,guard):
    m=focus_memory;rva,raw=assessment_people.NATIVE_SPANS[guard];a=m['base']+rva
    m['put'](a,bytes([raw[0]^1]))
    with pytest.raises(ValueError,match='native layout changed'):inspect(m)


@pytest.mark.parametrize('secondary',[0,12346,0xFFFFFFFF])
def test_independent_secondary_identity_word_is_preserved(focus_memory,secondary):
    m=focus_memory;m['put'](0x1398,struct.pack('<I',secondary));b=dict(m['focus_binding'])
    b['identity']=(*b['identity'][:-1],secondary)
    r=inspect(m,binding=b)
    assert r['additional_focus']['raw_code']==24
    assert r['native_identity']['random_id']==secondary


@pytest.mark.parametrize('identity_field',['first_name','common_name','birth_day','birth_year','identity_length','identity_bool','binding_kind'])
def test_identity_inputs_cannot_silently_retarget_reference(focus_memory,identity_field):
    m=focus_memory;b=dict(m['focus_binding'])
    if identity_field=='first_name':m['put'](0x3004,b'Best')
    elif identity_field=='common_name':m['q'](0x12A8,0x1001)
    elif identity_field=='birth_day':m['put'](0x12D0,struct.pack('<HH',366,2001))
    elif identity_field=='birth_year':m['put'](0x12D0,struct.pack('<HH',60,1849))
    elif identity_field=='identity_length':b['identity']=b['identity'][:-1]
    elif identity_field=='identity_bool':b['identity']=(True,*b['identity'][1:])
    else:b['binding_kind']=virtual_identity.BINDING_KIND
    with pytest.raises((ValueError,KeyError)):inspect(m,binding=b)


def test_common_name_is_display_only_and_fallback_for_missing_first_last(focus_memory):
    m=focus_memory;handle=m['allocate'](8);m['q'](handle,m['text']('Beto'));m['q'](0x12A8,handle)
    r=inspect(m)
    assert r['name']=='Test Müller' and r['display_name']=='Beto' and r['name_state']=='available'
    m['q'](0x1298,0);m['q'](0x12A0,0);b=dict(m['focus_binding'])
    b['identity']=(12345,'','','2000-02-29',12345)
    r=inspect(m,binding=b)
    assert r['name']==r['display_name']=='Beto' and r['name_state']=='available'


def test_name_absence_does_not_become_empty_success(focus_memory):
    m=focus_memory;m['q'](0x1298,0);m['q'](0x12A0,0)
    b=dict(m['focus_binding']);b['identity']=(12345,'','','2000-02-29',12345)
    with pytest.raises(ValueError,match='no readable name'):inspect(m,binding=b)
