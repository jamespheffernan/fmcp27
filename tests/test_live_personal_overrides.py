import struct
from copy import deepcopy

import pytest

from fm_live_mcp import live_personal_overrides as source, live_tactical_assignments_source as tactical, world
from test_live_tactical_assignments_source import two_phase
from test_live_in_possession_source import context
from test_bridge import bridge


@pytest.fixture
def personal(two_phase):
    memory,base,creator=two_phase['memory'],two_phase['base'],two_phase['creator']
    for rva,raw in source.NATIVE_SPANS:memory.put(base+rva,raw)
    for offset in source.MAP_OFFSETS.values():
        header=creator+offset
        memory.pack(header,'<QQQ',header+8,0,0)
    return two_phase


def inspect(c,phase='both',include=True):
    read=world.ReadSet(c['memory'].read)
    r=tactical.inspect(read,c['base'],c['coach'],phase,include_personal_overrides=include)
    read.verify()
    return r


def record(mask,activation=1,role=1):
    raw=bytearray(72)
    struct.pack_into('<I',raw,0,mask)
    raw[0x20]=activation
    struct.pack_into('<Q',raw,0x40,role)
    return bytes(raw)


def node(c,phase,key,records,*,address=0xb0000,start=0xc0000):
    memory=c['memory'];header=c['creator']+source.MAP_OFFSETS[phase]
    memory.pack(header,'<QQQ',address,address,1)
    memory.put(address,b'\0'*64)
    memory.pack(address+0x20,'<I',key)
    memory.pack(address+0x28,'<QQQ',start,start+len(records)*72,start+len(records)*72)
    memory.put(start,b''.join(records))
    return address


def first(c,phase='in_possession'):
    return inspect(c)['phases'][phase]['assignments'][0]['personal_override']


def test_empty_phase_maps_prove_absence_only_when_requested(personal):
    default=inspect(personal,include=False)
    assert 'personal_override_context'not in default
    assert all('personal_override'not in row for p in default['phases'].values()for row in p['assignments'])
    r=inspect(personal)
    assert all(p['state']=='available' and p['person_key_count']==0 for p in r['personal_override_context']['phases'].values())
    assert all(row['personal_override']['state']=='absent'for p in r['phases'].values()for row in p['assignments'])
    assert not r['personal_override_context']['effective_roles_established']
    assert not r['personal_override_context']['all_instructions_established']
    for phase in r['phases']:
        stripped=deepcopy(r['phases'][phase])
        for row in stripped['assignments']:row.pop('personal_override')
        assert stripped==default['phases'][phase]


def test_positive_exact_and_strict_agree_without_effective_claim(personal):
    node(personal,'in_possession',0,[record(1,1,1<<1)])
    row=first(personal)
    assert row['state']=='present' and row['lookup_policies_agree']
    assert row['exact_position_lookup']['stored_role']['compiled_english_name']=='Centre-Back'
    assert row['effective_role_state']=='not_established' and row['instructions_state']=='not_decoded'
    assert inspect(personal)['phases']['in_possession']['assignments'][0]['stored_base_role']['compiled_english_name']=='Goalkeeper'


def test_all_activation_bytes_keep_policy_difference(personal):
    for activation in range(256):
        node(personal,'in_possession',0,[record(1,activation)])
        row=first(personal)
        assert row['exact_position_lookup']['activation_raw_u8']==activation
        assert row['exact_position_lookup']['state']==('inactive'if activation==0 else 'present')
        assert row['strict_ip_role_lookup']['state']==('present'if activation==1 else 'inactive')
        assert row['state']==('inactive'if activation==0 else 'present'if activation==1 else 'policy_dependent')


def test_first_matching_inactive_blocks_later_active(personal):
    node(personal,'in_possession',0,[record(1,0),record(1,1)])
    row=first(personal)
    assert row['state']=='inactive' and row['exact_position_lookup']['record_index']==0


def test_wrong_person_key_does_not_borrow_override(personal):
    node(personal,'in_possession',99,[record(1)])
    row=first(personal)
    assert row['state']=='absent' and row['reason']=='no_personal_entry'


def test_wrong_position_is_absent_not_a_nearby_match(personal):
    node(personal,'in_possession',0,[record(4)])
    row=first(personal)
    assert row['state']=='absent' and row['reason']=='no_matching_position_record'


def test_normalized_ip_lookup_is_distinct_from_exact_mask(personal):
    # FirstDM(CR) clears side bits to0x80 in the strict helper.
    node(personal,'in_possession',5,[record(0x80,1)])
    row=inspect(personal)['phases']['in_possession']['assignments'][5]['personal_override']
    assert row['state']=='policy_dependent'
    assert row['exact_position_lookup']['state']=='absent'
    assert row['strict_ip_role_lookup']['state']=='present'


def test_different_phase_maps_and_role_filters_remain_independent(personal):
    node(personal,'in_possession',0,[record(1,1,1<<2)])
    node(personal,'out_of_possession',0,[record(1,0,1<<2)],address=0xd0000,start=0xe0000)
    r=inspect(personal)
    ip=r['phases']['in_possession']['assignments'][0]['personal_override']
    oop=r['phases']['out_of_possession']['assignments'][0]['personal_override']
    assert ip['state']=='present' and oop['state']=='inactive'
    assert ip['exact_position_lookup']['stored_role']['compiled_english_name']=='Full-Back'
    assert oop['exact_position_lookup']['stored_role']['compiled_english_name']=='Line-Holding Goalkeeper'
    assert 'strict_ip_role_lookup'not in oop


def test_phase_filter_does_not_traverse_unrequested_map(personal):
    bad=personal['creator']+source.MAP_OFFSETS['out_of_possession']
    personal['memory'].pack(bad,'<QQQ',0,0,1)
    r=inspect(personal,'in_possession')
    assert list(r['personal_override_context']['phases'])==['in_possession']
    assert r['personal_override_context']['phases']['in_possession']['state']=='available'


def test_missing_creator_is_unavailable_not_absent(personal):
    personal['memory'].pack(0x20000,'<Q',0)
    r=inspect(personal)
    assert all(p['state']=='unavailable'for p in r['personal_override_context']['phases'].values())
    assert all(p['person_key_count']is None for p in r['personal_override_context']['phases'].values())


def test_empty_person_slot_has_no_override_subject(personal):
    personal['sheet']['slots'][0].update(person=None,state='empty_slot')
    row=first(personal)
    assert row['state']=='unavailable' and row['reason']=='empty_selection_slot'


@pytest.mark.parametrize('malformed',['cycle','count','order','begin','vector','budget'])
def test_malformed_or_budget_limited_source_never_absent(personal,malformed):
    address=node(personal,'in_possession',0,[record(1)])
    memory=personal['memory'];header=personal['creator']+0x760
    if malformed=='cycle':memory.pack(address,'<Q',address)
    if malformed=='count':memory.pack(header+0x10,'<Q',2)
    if malformed=='begin':memory.pack(header,'<Q',address+8)
    if malformed=='order':
        memory.pack(header+0x10,'<Q',2)
        memory.pack(address+8,'<Q',address+0x100)
        memory.put(address+0x100,memory.read(address,64))
        memory.pack(address+0x100,'<QQ',0,0)
    if malformed=='vector':memory.pack(address+0x30,'<Q',0xc0001)
    if malformed=='budget':memory.pack(header+0x10,'<Q',source.MAX_NODES+1)
    row=first(personal)
    assert row['state']=='unavailable'
    assert inspect(personal)['personal_override_context']['phases']['in_possession']['state']=='unavailable'
    assert inspect(personal)['phases']['in_possession']['assignments'][0]['position']['name']=='GK'


def test_vector_budget_is_unavailable_not_absence(personal):
    address=node(personal,'in_possession',0,[])
    personal['memory'].pack(address+0x28,'<QQQ',0xc0000,0xc0000,0xc0000+129*72)
    assert first(personal)['state']=='unavailable'


def test_empty_vector_distinct_from_missing_key(personal):
    node(personal,'in_possession',0,[])
    row=first(personal)
    assert row['state']=='absent' and row['reason']=='no_matching_position_record'


def test_each_native_guard_required(personal):
    for rva,raw in source.NATIVE_SPANS:
        personal['memory'].put(personal['base']+rva,bytes([raw[0]^1]))
        with pytest.raises(ValueError):inspect(personal)
        personal['memory'].put(personal['base']+rva,raw)


def test_changed_map_or_record_rejected_before_publication(personal):
    node(personal,'in_possession',0,[record(1)])
    for target in(personal['creator']+0x760,0xc0000):
        read=world.ReadSet(personal['memory'].read)
        tactical.inspect(read,personal['base'],personal['coach'],include_personal_overrides=True)
        before=personal['memory'].read(target,1)
        personal['memory'].put(target,bytes([before[0]^1]))
        with pytest.raises(ValueError):read.verify()
        personal['memory'].put(target,before)


def test_default_does_not_read_override_maps(personal):
    reads=[]
    def read(address,length):
        reads.append((address,length));return personal['memory'].read(address,length)
    tactical.inspect(read,personal['base'],personal['coach'])
    assert not any(address in(personal['creator']+0x760,personal['creator']+0x778)for address,_ in reads)


def test_allocated_empty_vector_never_issues_zero_size_native_read(personal):
    node(personal,'in_possession',0,[])
    def read(address,length):
        assert length>0, 'Native Bridge rejects zero-sized reads'
        return personal['memory'].read(address,length)
    snapshot=world.ReadSet(read)
    result=tactical.inspect(snapshot,personal['base'],personal['coach'],include_personal_overrides=True)
    snapshot.verify()
    row=result['phases']['in_possession']['assignments'][0]['personal_override']
    assert row['state']=='absent' and row['reason']=='no_matching_position_record'


def test_pointer_bearing_record_storage_never_reaches_public_projection(personal):
    import json
    raw=bytearray(record(1,1,1<<1))
    pointers=(0x0000007A12345678,0x0000007B23456780,0x0000007C34567888,
              0x0000007D45678990,0x0000007E56789A98,0x0000007F6789ABA0)
    for offset,pointer in zip((8,16,24,40,48,56),pointers):struct.pack_into('<Q',raw,offset,pointer)
    node(personal,'in_possession',0,[bytes(raw)])
    result=inspect(personal)
    encoded=json.dumps(result)
    assert 'record_raw_hex'not in encoded
    for pointer in pointers:
        assert str(pointer)not in encoded
        assert hex(pointer)not in encoded
        assert struct.pack('<Q',pointer).hex()not in encoded
    override=result['phases']['in_possession']['assignments'][0]['personal_override']
    assert override['state']=='present'
    assert override['exact_position_lookup']['stored_role']['raw_encoding']=='0x0000000000000002'


def test_pointer_words_absent_from_complete_public_tool_response(personal,bridge,monkeypatch):
    import json
    from contextlib import nullcontext
    from fm_live_mcp import players,server
    raw=bytearray(record(1,1,1<<1))
    pointers=(0x0000007A12345678,0x0000007B23456780,0x0000007C34567888,
              0x0000007D45678990,0x0000007E56789A98,0x0000007F6789ABA0)
    for offset,pointer in zip((8,16,24,40,48,56),pointers):struct.pack_into('<Q',raw,offset,pointer)
    node(personal,'in_possession',0,[bytes(raw)])
    coach={**personal['coach'],'name':'Coach','club':{'name':'Club'}}
    save={'name':'Career','current_date':'2030-10-28','coaches':[coach]}
    read=world.ReadSet(personal['memory'].read)
    monkeypatch.setattr(bridge,'_read_scope',lambda session:nullcontext())
    monkeypatch.setattr(bridge,'_player_layout',lambda process:tuple(personal['base']+rva for rva in players.RVA))
    monkeypatch.setattr(bridge,'_world_state',lambda *args:(read,save,None))
    monkeypatch.setattr(server,'bridge',bridge)
    result=server.fm_get_managed_tactical_assignments(bridge.session,include_personal_overrides=True)
    encoded=json.dumps(result)
    for pointer in pointers:
        assert str(pointer)not in encoded
        assert hex(pointer)not in encoded
        assert struct.pack('<Q',pointer).hex()not in encoded
    assert 'record_raw_hex'not in encoded
    assert result['phases']['in_possession']['assignments'][0]['personal_override']['state']=='present'
