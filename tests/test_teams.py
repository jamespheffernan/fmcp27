import struct

import pytest

from fm_live_mcp import teams, world
from test_competitions import competition_fixture
from test_database import database_memory
from test_geography import add_geography
from test_players import memory
from test_world import world_memory


@pytest.fixture
def team_memory(database_memory):
    m = add_geography(competition_fixture(database_memory))
    addresses, owners = [], [m['club']]
    for kind in ('national_team_container', 'league_body_club'):
        owner = m['typed'](kind, 0x180)
        index = len(owners)
        m['put'](owner + 8, struct.pack('<III', index, index+700, index+700))
        if kind == 'national_team_container':
            m['q'](owner + 0x170, m['geography']['nation'][0])
        else:
            m['q'](owner + 0xC0, m['text']('League'))
        owners.append(owner)
    m['put'](m['club'] + 8, struct.pack('<I', 0))
    for i,owner in enumerate(owners):
        kind = 'national_team' if i == 1 else 'team'
        team = m['typed'](kind, 0xB8)
        m['put'](team+8,struct.pack('<III',i,i+50,i+900 if i==1 else i+50))
        m['put'](team+0x28,struct.pack('<bB',i,1))
        m['q'](team+0x30,owner)
        m['q'](team+0x50,m['competitions'][0])
        m['q'](team+0x68,m['competitions'][1])
        m['vec'](team+0x38, [0x1000] if i<2 else [])
        # Preserve the managed coach's existing team backlink.
        m['vec'](owner+0x18, [team, m['team']] if i==0 else [team])
        addresses.append(team)
    for kind,getter in teams.GETTERS.items():
        m['q'](m['base'] + world.TYPES[kind][0] + 24, m['base']+getter)
    m['put'](owners[1]+8, struct.pack('<I',0))
    m['vec'](m['headers']['national_team_containers'],[owners[1]])
    m['vec'](m['headers']['teams'],addresses)
    m['vec'](m['headers']['clubs'],owners)
    m.update(team_addresses=addresses, owners=owners)
    return m


def test_team_kinds_owner_names_nation_and_random_ids(team_memory):
    m=team_memory
    rows=[teams.by_index(m['read'],m['base'],i)[0] for i in range(3)]
    assert [r['kind'] for r in rows] == ['team','national_team','team']
    assert [r['native_type_code'] for r in rows] == [0,1,2]  # Not uint16 with the adjacent flag.
    assert [r['random_id'] for r in rows] == [None,901,None]
    assert rows[0]['owner']['name']=='Test United'
    assert rows[1]['owner']['nation']['short_name']=='England'
    assert 'name' not in rows[1]['owner']
    assert rows[2]['owner']['name']=='League' and rows[2]['owner']['short_name'] is None


@pytest.mark.parametrize('mode', [0,2,3,255])
def test_primary_lookup_requires_exact_mode_one_and_has_no_fallback(team_memory,mode):
    m=team_memory
    m['put'](m['base']+teams.LOOKUP_MODE,bytes([mode]))
    m['put'](m['roots']['teams']+0x68,bytes(24))
    info=teams.lookup(m['read'],m['base'])
    assert info['lookup_count']==0
    with pytest.raises(ValueError,match='selected native lookup'):
        teams.by_index(m['read'],m['base'],0)
    m['vec'](m['roots']['teams']+0x68,m['team_addresses'][:1])
    assert teams.by_index(m['read'],m['base'],0)[0]['native_id']==50
    with pytest.raises(ValueError):teams.by_index(m['read'],m['base'],1)


@pytest.mark.parametrize('assignment,offset,fallback', [('current',0x50,False),('next',0x50,True),
                                                       ('secondary',0x68,False),('next_secondary',0x68,True)])
def test_assignment_fallbacks(team_memory,assignment,offset,fallback):
    m=team_memory;a=m['team_addresses'][0]
    pointer,used=teams.selection(m['read'],a,assignment)
    assert pointer == int.from_bytes(m['read'](a+offset,8),'little') and used is fallback
    if fallback:
        m['q'](a+teams.ASSIGNMENTS[assignment],m['competitions'][1])
        assert teams.selection(m['read'],a,assignment)==(m['competitions'][1],False)


@pytest.mark.parametrize('fault',['team_type','team_rtti','team_getter','team_index','team_id','team_lookup',
                                  'owner_type','owner_getter','owner_id','owner_index','owner_membership',
                                  'backlink','nation','string','empty_string'])
def test_invalid_records_fail_closed(team_memory,fault):
    m=team_memory;a=m['team_addresses'][0];owner=m['owners'][0]
    if fault=='team_type':m['q'](a,0)
    elif fault=='team_rtti':m['q'](m['base']+world.TYPES['team'][0]-16,8)
    elif fault=='team_getter':m['q'](m['base']+world.TYPES['team'][0]+24,0)
    elif fault=='team_index':m['put'](a+8,struct.pack('<I',2))
    elif fault=='team_id':m['put'](a+12,bytes(4))
    elif fault=='team_lookup':
        m['put'](m['base']+teams.LOOKUP_MODE,b'\x00')
        m['vec'](m['roots']['teams']+0x68,list(reversed(m['team_addresses'])))
    elif fault=='owner_type':m['q'](owner,m['base']+world.TYPES['nation'][0])
    elif fault=='owner_getter':m['q'](m['base']+world.TYPES['club'][0]+24,0)
    elif fault=='owner_id':m['put'](owner+12,bytes(4))
    elif fault=='owner_index':m['put'](owner+8,struct.pack('<I',99))
    elif fault=='owner_membership':m['vec'](m['headers']['clubs'],m['owners'][1:])
    elif fault=='backlink':m['vec'](owner+0x18,[m['team']])
    elif fault=='nation':
        m['q'](m['owners'][1]+0x170,owner);a=m['team_addresses'][1]
    elif fault=='string':m['q'](owner+0xC0,m['text']('bad\nname'))
    else:
        string=m['text']('');m['put'](string+4,b'x');m['q'](owner+0xC0,string)
    with pytest.raises((ValueError,KeyError)):
        teams.by_index(m['read'],m['base'],m['team_addresses'].index(a))


def test_null_owner_and_empty_string_are_distinct(team_memory):
    m=team_memory
    m['q'](m['owners'][0]+0xC0,m['text'](''))
    assert teams.by_index(m['read'],m['base'],0)[0]['owner']['name']==''
    m['q'](m['team_addresses'][0]+0x30,0)
    row,binding=teams.by_index(m['read'],m['base'],0)
    assert row['owner'] is None and binding['owner_address']==0 and binding['owner_identity'] is None
