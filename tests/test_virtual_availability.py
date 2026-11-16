"""Typed synthetic availability tests; warm controls do not establish live warm coverage."""
import json
import struct

import pytest

from fm_live_mcp import player_profile, players, virtual, virtual_identity, world
from personality_fixture import populate_virtual
from test_player_profile import populate as populate_profile
from test_virtual_identity import compact_virtual_memory, database_memory, memory, virtual_memory, world_memory


def decode(m, **kwargs):
    snapshot = world.ReadSet(m['read'])
    result = virtual.decode(snapshot, m['compact'], m['tables'], **kwargs)
    snapshot.verify()
    return result


@pytest.mark.parametrize('cache_index', [-1, -2, -32768])
@pytest.mark.parametrize('include_clubs,include_profile', [(False,False), (True,False), (False,True), (True,True)])
def test_cold_metadata_without_manager_or_dependent_readers(compact_virtual_memory, monkeypatch,
                                                          cache_index, include_clubs, include_profile):
    m = compact_virtual_memory
    m['put'](m['compact']+0x14, struct.pack('<h', cache_index))
    def forbidden(*args, **kwargs):
        pytest.fail('Cold availability entered an expanded reader')
    monkeypatch.setattr(virtual, '_decode_required', forbidden)
    original = m['read']
    def read(address, count):
        assert address != m['base']+virtual.MANAGER_ROOT
        assert not m['cache_manager'] <= address < m['cache_manager']+0x2A8
        assert address != m['warm_cache_address']
        return original(address,count)
    row, identity = virtual.decode(read,m['compact'],m['tables'],include_clubs,include_profile,'available')
    assert identity == ('stored_virtual_identity_v1',1,12345,12345)
    assert row['native_identity'] == {'database_index':1,'native_id':12345,'random_id':None}
    assert row['record_kind'] == 'virtual' and row['profile_state'] == 'identity_only'
    assert row['profile_unavailable_reason'] == 'negative_cache_index'
    assert row['unavailable_fields'] == [*virtual.BASE_PROFILE_FIELDS,
        *(['clubs'] if include_clubs else []), *(['profile'] if include_profile else [])]
    assert all(row[field] is None for field in row['unavailable_fields'])
    assert all(row['field_sources'][field] == 'unavailable_from_verified_sources'
               for field in row['unavailable_fields'])
    assert 'clubs' in row if include_clubs else 'clubs' not in row
    assert 'profile' in row if include_profile else 'profile' not in row
    assert 'roster_context' not in row and 'roster_index' not in row and 'health' not in row
    assert 'on_loan' not in json.dumps(row) and '_raw' not in row


def test_required_cold_uses_typed_absence_and_explicit_policy_guidance(compact_virtual_memory):
    m = compact_virtual_memory
    with pytest.raises(virtual.ProfileUnavailableError) as caught:
        decode(m)
    assert "profile_policy='available'" in str(caught.value)
    assert 'open' not in str(caught.value).lower()
    assert 'game and retry' not in str(caught.value).lower()


@pytest.mark.parametrize('secondary', [0, 54321, 12345])
def test_independent_secondary_identity_is_preserved(compact_virtual_memory, secondary):
    m = compact_virtual_memory
    m['put'](m['compact']+0x30, struct.pack('<I',secondary))
    row, identity = decode(m,profile_policy='available')
    assert identity[-1] == secondary
    assert row['native_identity']['random_id'] == (None if secondary==12345 else secondary)


@pytest.mark.parametrize('fault', ['primary_type','person_type','person_displacement','primary_id',
                                  'canonical_index','canonical_membership','native_getter'])
def test_cold_is_not_fallback_for_corrupt_identity(compact_virtual_memory, fault):
    m = compact_virtual_memory
    if fault == 'primary_type': m['q'](m['compact'],0)
    elif fault == 'person_type': m['q'](m['compact']+0x20,0)
    elif fault == 'person_displacement': m['put'](m['base']+virtual.PERSON_RVA-16,struct.pack('<q',0))
    elif fault == 'primary_id': m['put'](m['compact']+0x2C,bytes(4))
    elif fault == 'canonical_index': m['put'](m['compact']+0x28,struct.pack('<I',2))
    elif fault == 'canonical_membership': m['vec'](m['headers']['people'],[m['regular']+0x388]*2)
    else: m['q'](m['base']+virtual.PERSON_RVA+16,0)
    with pytest.raises(ValueError) as caught:
        decode(m,include_clubs=True,include_profile=True,profile_policy='available')
    assert not isinstance(caught.value,virtual.ProfileUnavailableError)


def test_available_warm_preserves_rich_values_and_changes_only_identity_variant(compact_virtual_memory):
    m = compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    rich, legacy_identity = decode(m,include_clubs=True)
    row, identity = decode(m,include_clubs=True,profile_policy='available')
    assert row['name'] == rich['name'] == 'Test Müller'
    assert row['birth_date'] == rich['birth_date'] == '2000-02-29'
    assert row['attributes'] == rich['attributes'] and row['clubs'] == rich['clubs']
    assert row['profile_state'] == 'cached' and row['unavailable_fields'] == []
    assert row['field_sources']['attributes'] == 'cached_generated_profile'
    assert identity == ('stored_virtual_identity_v1',1,12345,12345)
    assert legacy_identity == ('virtual',12345,'Test','Müller','2000-02-29',12345)
    assert 'native_identity' not in rich and 'profile_state' not in rich


def test_available_warm_optional_profile_uses_existing_validated_route(compact_virtual_memory):
    m = compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    populate_profile(m,m['warm_cache_address'])
    populate_virtual(m)
    for slot,getter in player_profile.VIRTUAL_GETTERS.items():
        m['q'](m['base']+world.TYPES['virtual_player'][0]+slot*8,m['base']+getter)
    row, _ = decode(m,include_profile=True,profile_policy='available')
    assert row['profile']['ability']['current'] == 150
    assert row['profile']['personality']['controversy'] == 0
    assert row['field_sources']['profile'] == 'cached_generated_profile_with_verified_native_defaults'


@pytest.mark.parametrize('fault', ['bounds','null_slot','cache_type','cache_person_type','generated_index',
                                  'secondary_marker','manager','contract','team_index','name','date'])
def test_nonnegative_cache_failures_never_downgrade(compact_virtual_memory, fault):
    m = compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    cached = m['warm_cache_address']
    if fault == 'bounds': m['put'](m['compact']+0x14,struct.pack('<h',5))
    elif fault == 'null_slot': m['vec'](m['cache_manager']+8,[0])
    elif fault == 'cache_type': m['q'](cached,0)
    elif fault == 'cache_person_type': m['q'](cached+0x388,0)
    elif fault == 'generated_index': m['put'](cached+0x390,struct.pack('<I',0))
    elif fault == 'secondary_marker': m['put'](cached+0x398,struct.pack('<I',12345))
    elif fault == 'manager': m['q'](m['cache_manager'],0)
    elif fault == 'contract': m['q'](cached+0x2F0,m['contract'])
    elif fault == 'team_index': m['put'](m['team']+8,struct.pack('<I',3))
    elif fault == 'name': m['q'](cached+0x298,0); m['q'](cached+0x2A0,0)
    elif fault == 'date': m['put'](cached+0x2D0,bytes(4))
    with pytest.raises(ValueError) as caught:
        decode(m,include_clubs=True,profile_policy='available')
    assert not isinstance(caught.value,virtual.ProfileUnavailableError)


def test_availability_changes_across_calls_preserve_compact_identity_without_stale_fields(compact_virtual_memory):
    m = compact_virtual_memory
    cold, first = decode(m,profile_policy='available')
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    warm, second = decode(m,profile_policy='available')
    m['put'](m['compact']+0x14,struct.pack('<h',-1))
    cold_again, third = decode(m,profile_policy='available')
    assert first == second == third
    assert warm['name'] == 'Test Müller' and warm['profile_state'] == 'cached'
    assert cold_again == cold and cold_again['name'] is None


@pytest.mark.parametrize('start,end', [(-1,0),(0,-1)])
def test_midread_cache_transition_is_drift_not_expected_rich_absence(compact_virtual_memory,start,end):
    m = compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',start))
    reads = 0
    def read(address,count):
        nonlocal reads
        if address == m['compact'] and count == 64:
            reads += 1
            if reads == 3: m['put'](m['compact']+0x14,struct.pack('<h',end))
        return m['read'](address,count)
    with pytest.raises(ValueError,match='changed') as caught:
        virtual.decode(read,m['compact'],m['tables'],profile_policy='available')
    assert not isinstance(caught.value,virtual.ProfileUnavailableError)


def test_canonical_source_mutation_is_rejected_by_parent_readset(compact_virtual_memory):
    m = compact_virtual_memory
    snapshot = world.ReadSet(m['read'])
    virtual.decode(snapshot,m['compact'],m['tables'],profile_policy='available')
    m['vec'](m['headers']['people'],[m['regular']+0x388]*2)
    with pytest.raises(ValueError,match='changed'): snapshot.verify()


@pytest.mark.parametrize('policy', [None,True,False,0,[],{},'','Available','optional'])
def test_policy_validation_precedes_any_reads(policy):
    def forbidden(*args): pytest.fail('Invalid policy read native memory')
    with pytest.raises(ValueError,match='profile_policy'):
        virtual.decode(forbidden,0,(),profile_policy=policy)


def test_available_conflicting_cache_preserves_only_independent_compact_identity(compact_virtual_memory):
    m=compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    m['put'](m['warm_cache_address']+0x394,struct.pack('<I',999))
    row,identity=decode(m,include_clubs=True,include_profile=False,profile_policy='available')
    assert identity==('stored_virtual_identity_v1',1,12345,12345)
    assert row['native_identity']['native_id']==12345
    assert row['profile_state']=='identity_only' and row['profile_unavailable_reason']=='cache_identity_mismatch'
    assert all(row[k] is None for k in ('name','display_name','birth_date','attributes','clubs'))
    assert '999' not in json.dumps(row)
    with pytest.raises(players.VirtualCacheIdentityMismatchError):decode(m)


def test_missing_cache_primary_is_not_supported_mismatch(compact_virtual_memory):
    m=compact_virtual_memory
    m['put'](m['compact']+0x14,struct.pack('<h',0))
    m['put'](m['warm_cache_address']+0x394,bytes(4))
    with pytest.raises(ValueError) as caught:decode(m,profile_policy='available')
    assert not isinstance(caught.value,players.VirtualCacheIdentityMismatchError)
