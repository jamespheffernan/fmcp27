import struct

import pytest

from fm_live_mcp import competitions, world
from test_database import database_memory
from test_players import memory
from test_world import world_memory


def competition_fixture(m):
    addresses = []
    for index, name in enumerate(('Test Premier Division', 'Test Continental Cup')):
        a = m['typed']('competition', 0x1B0)
        m['put'](a+8, struct.pack('<III',index,index+100,index+100))
        for offset, value in ((0x40,name),(0x48,name),(0x50,'TST')):
            m['q'](a+offset,m['text'](value))
        m['put'](a+0xF8,b'\xff\x00')
        m['put'](a+0x1AA,b'\x64')
        addresses.append(a)
    m['vec'](m['headers']['competitions'],addresses)
    m['put'](m['base']+competitions.LOOKUP_MODE,b'\x01')
    m['q'](m['base']+world.TYPES['competition'][0]+24,m['base']+competitions.PROPERTY_GETTER)
    m['competitions'] = addresses
    return m


@pytest.fixture
def competition_record(database_memory):
    return competition_fixture(database_memory)


def test_names_membership_and_alternate_native_lookup(competition_record):
    m = competition_record
    expected = {'native_id':100,'random_id':None,'database_index':0,'name':'Test Premier Division',
        'short_name':'Test Premier Division','abbreviation':'TST','name_source':'stored_native_strings'}
    assert competitions.by_index(m['read'],m['base'],0) == expected
    m['put'](m['base']+competitions.LOOKUP_MODE,b'\x00')
    m['put'](m['roots']['competitions']+0x68,bytes(24))
    assert competitions.by_index(m['read'],m['base'],0) == expected
    m['vec'](m['roots']['competitions']+0x68,m['competitions'][:1])
    assert competitions.by_index(m['read'],m['base'],0) == expected
    assert competitions.by_index(m['read'],m['base'],1)['native_id'] == 101


def test_missing_and_empty_names_remain_distinct(competition_record):
    m = competition_record
    m['q'](m['competitions'][0]+0x48,0)
    m['q'](m['competitions'][0]+0x50,m['text'](''))
    row = competitions.by_index(m['read'],m['base'],0)
    assert row['short_name'] is None and row['abbreviation'] == ''


@pytest.mark.parametrize('fault',['bounds','primary_identity','primary_bounds','type','getter','index','zero_id','string','empty_string'])
def test_invalid_competition_reads_fail(competition_record,fault):
    m=competition_record;a=m['competitions'][0]
    if fault=='bounds':m['vec'](m['headers']['competitions'],[])
    elif fault.startswith('primary'):
        m['put'](m['base']+competitions.LOOKUP_MODE,b'\x00')
        m['vec'](m['roots']['competitions']+0x68,list(reversed(m['competitions'])))
        if fault=='primary_bounds':m['q'](m['roots']['competitions']+0x70,1)
    elif fault=='type':m['q'](a,m['base']+world.TYPES['club'][0])
    elif fault=='getter':m['q'](m['base']+world.TYPES['competition'][0]+24,0)
    elif fault=='index':m['put'](a+8,struct.pack('<I',1))
    elif fault=='zero_id':m['put'](a+0xC,bytes(8))
    elif fault=='string':m['q'](a+0x40,m['text']('bad\nname'))
    else:
        text=m['text']('');m['put'](text+4,b'x');m['q'](a+0x40,text)
    with pytest.raises(ValueError):competitions.by_index(m['read'],m['base'],0)


@pytest.mark.parametrize('index',[-1,True,1.5,'0',None])
def test_invalid_selectors(competition_record,index):
    with pytest.raises(ValueError):competitions.by_index(competition_record['read'],competition_record['base'],index)
