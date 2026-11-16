"""Regressions for independent entity identities and valid absent name parts."""
import struct
import pytest

from fm_live_mcp import competitions,database,geography,player_health,players,stadium_changes,virtual,wages,world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory,reader,TABLES
from test_world import world_memory
from test_database import database_memory,bind,receipt
from test_geography import geo_memory
from test_competitions import competition_record
from test_player_staff import staff_memory
from test_player_health import health_memory
from test_contract_dates import dated_record
from test_staff import staff_record,club_fixture
from test_wages import wage_record
from test_stadiums import stadium_memory
from test_teams import team_memory
from test_stadium_changes import changes_memory
from test_virtual import virtual_memory


@pytest.mark.parametrize('secondary',[0,999])
def test_club_accepts_independent_secondary_id(world_memory,secondary):
    m=world_memory;m['put'](m['club']+16,struct.pack('<I',secondary))
    assert world.club(m['read'],m['base'],m['club'])[0]['name']=='Test United'


@pytest.mark.parametrize('secondary',[0,999])
def test_competition_accepts_independent_secondary_id(competition_record,secondary):
    m=competition_record;m['put'](m['competitions'][0]+16,struct.pack('<I',secondary))
    assert competitions.by_index(m['read'],m['base'],0)['native_id']==100


@pytest.mark.parametrize('secondary',[0,999])
@pytest.mark.parametrize('kind',list(geography.FIELDS))
def test_geography_accepts_independent_secondary_id(geo_memory,secondary,kind):
    m=geo_memory
    getter,table_kind,fields=geography.FIELDS[kind]
    a=m['typed'](kind,0x40)
    m['put'](a+8,struct.pack('<III',0,200,secondary))
    m['q'](m['base']+world.TYPES[kind][0]+24,m['base']+getter)
    for field,offset in fields:m['q'](a+offset,m['text']('Test'))
    m['vec'](m['headers'][table_kind],[a])
    assert geography.record(m['read'],m['base'],a,kind)['native_id']==200


@pytest.mark.parametrize('secondary',[0,999])
def test_stadium_change_accepts_independent_secondary_id(changes_memory,secondary):
    m=changes_memory;a=m['change_addresses'][0];m['put'](a+16,struct.pack('<I',secondary))
    assert stadium_changes.identity(m['read'],m['base'],a)['native_id']==500


@pytest.mark.parametrize('secondary',[0,999])
def test_health_accepts_independent_definition_secondary_id(health_memory,secondary):
    m=health_memory;m['put'](m['injury_definition']+16,struct.pack('<I',secondary))
    assert player_health.decode(m['read'],m['base'],0x1000)['injuries'][0]['name']=='thigh strain'


@pytest.mark.parametrize('secondary',[0,999])
def test_wages_accept_independent_base_currency_secondary_id(wage_record,secondary):
    m=wage_record;m['put'](m['currency']+16,struct.pack('<I',secondary))
    assert wages.decode(m['read'],m['base'],m['person'])['currency']=='GBP'


@pytest.mark.parametrize('secondary',[0,999])
def test_virtual_compact_secondary_id_is_not_cache_identity(virtual_memory,secondary):
    m=virtual_memory;m['put'](m['compact']+0x30,struct.pack('<I',secondary))
    assert virtual.decode(m['read'],m['compact'],m['tables'])[0]['name']=='Test Müller'


@pytest.mark.parametrize('offset',[0x298,0x2a0,0x2a8])
@pytest.mark.parametrize('state',['null_target','empty_string'])
def test_optional_name_parts_accept_valid_absence(memory,offset,state):
    handle=0x2200;pointer=0 if state=='null_target' else 0x3200
    struct.pack_into('<Q',memory,0x1000+offset,handle)
    struct.pack_into('<Q',memory,handle,pointer)
    result,_=players.decode(reader(memory),0x1000,TABLES)
    assert result['name']


@pytest.mark.parametrize('method',['find_save_players','find_staff','find_clubs','query_save_players'])
@pytest.mark.parametrize('cursor',['',[],False,0])
def test_empty_cursor_is_rejected_before_scanning(bridge,monkeypatch,database_memory,method,cursor):
    bind(bridge,monkeypatch,database_memory)
    monkeypatch.setattr(bridge,'_run',lambda *a: pytest.fail('scan executed with empty cursor'))
    args={} if method=='query_save_players' else {'name':'Test'}
    with pytest.raises(BridgeError,match='cursor'):
        getattr(bridge,method)(bridge.session,cursor=cursor,**args)
