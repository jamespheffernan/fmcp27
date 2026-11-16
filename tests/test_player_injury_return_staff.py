"""Typed staff selection uses native first-match order, not best medical rating."""
import struct
import pytest
from fm_live_mcp import player_injury_return as source,staff,world,database
from test_staff import staff_record
from test_database import database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def medical_staff(staff_record):
    m=staff_record;fields=staff.LAYOUTS[m['staff_kind']]
    teams=database.table(m['read'],m['base'],'teams')
    m['q'](teams['start'],m['team'])
    m['put'](m['team']+8,struct.pack('<III',0,688,688))
    m['put'](m['club']+0xba,b'\0');m['put'](m['club']+0x163,b'\x10')
    m['vec'](m['club']+0x60,[0x1000])
    m['put'](m['base']+fields[0]-0x18,struct.pack('<q',fields[2]-0x110))
    contract=m['typed']('full_contract',0xd0);m['q'](contract+8,0x1000+fields[2]);m['q'](contract+0x10,m['team']);m['q'](contract+0x18,m['team'])
    m['q'](0x1000+fields[2]-0x98,contract)
    m['q'](m['base']+world.TYPES['full_contract'][0]+0x90,m['base']+0x129fffc)
    m['q'](m['base']+world.TYPES['full_contract'][0]+0x70,m['base']+0x129a4b8)
    m['put'](contract+0x26,b'\x32');m['put'](contract+0xc2,b'\0')
    nonplayer=0x1000+fields[3]-8
    m['put'](nonplayer+0xda,struct.pack('<H',150));m['put'](nonplayer+0x30,b'\x60');m['put'](nonplayer+0x2e,b'\x54')
    m['medical_contract']=contract
    return m


def select(m):
    return source._head_physio(m['read'],m['base'],m['club'],database.table(m['read'],m['base'],'people'))


def test_first_primary_role_match_and_supported_skill_class(medical_staff):
    m=medical_staff
    if m['staff_kind']!='staff':
        with pytest.raises(source.UnsupportedEstimate,match='selected_medical_staff_class'):select(m)
        return
    r=select(m)
    assert r['native_identity']['database_index']==0 and r['native_staff_slot']==0
    assert r['native_role_code']==50 and r['display_name']=='Test Müller'
    assert r['raw_medical_inputs']=={'native_DA_u16':150,'physiotherapy_raw_signed8':96,'people_management_raw_signed8':84}


def test_alternate_role_only_consulted_when_primary_does_not_match(medical_staff):
    m=medical_staff
    if m['staff_kind']!='staff':
        with pytest.raises(source.UnsupportedEstimate,match='selected_medical_staff_class'):select(m)
        return
    # Unknown alternate getter cannot invalidate a primary-role early return.
    m['q'](m['base']+world.TYPES['full_contract'][0]+0x70,0x12340000)
    assert select(m)['native_role_code']==50
    m['put'](m['medical_contract']+0x26,b'\x0c')
    with pytest.raises(source.UnsupportedEstimate,match='alternate_role'):select(m)
    m['q'](m['base']+world.TYPES['full_contract'][0]+0x70,m['base']+0x129a4b8)
    m['put'](m['medical_contract']+0xc2,b'\x33')
    assert select(m)['native_role_code']==51


def test_no_matching_head_is_unknown_not_best_physio_fallback(medical_staff):
    m=medical_staff;m['put'](m['medical_contract']+0x26,b'\x0c')
    with pytest.raises(source.UnsupportedEstimate,match='fallback_not_supported'):select(m)


def test_complex_affiliations_and_auxiliary_contracts_remain_unknown(medical_staff):
    m=medical_staff
    m['put'](m['club']+0x163,b'\0');m['vec'](m['club']+0x118,[m['club']])
    with pytest.raises(source.UnsupportedEstimate,match='affiliation'):select(m)
    m['put'](m['club']+0x163,b'\x10')
    fields=staff.LAYOUTS[m['staff_kind']];m['q'](0x1000+fields[2]-0x98,0)
    m['q'](0x1000+fields[2]-0x90,m['medical_contract'])
    with pytest.raises(source.UnsupportedEstimate,match='auxiliary'):select(m)


def test_null_staff_slots_preserve_native_order(medical_staff):
    m=medical_staff
    if m['staff_kind']!='staff':
        with pytest.raises(source.UnsupportedEstimate,match='selected_medical_staff_class'):select(m)
        return
    m['vec'](m['club']+0x60,[0,0x1000])
    assert select(m)['native_staff_slot']==1


def test_staff_contract_team_requires_canonical_membership(medical_staff):
    m=medical_staff
    teams=database.table(m['read'],m['base'],'teams')
    m['q'](teams['start'],m['club'])
    with pytest.raises(ValueError,match='canonical table membership'):
        select(m)
