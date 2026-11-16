import pytest

from fm_live_mcp import staff, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_staff_attributes import attribute_record
from test_world import world_memory


def test_job_read_uses_contract_team_and_implies_club(bridge, monkeypatch, attribute_record):
    m = attribute_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    assert 'contract' not in bridge.get_staff(bridge.session, ref)['staff']
    assert bridge.get_staff(bridge.session, ref, include_job=True)['staff']['contract']['job']['title'] == 'Coach First Team'
    m['put'](m['team'] + 0x28, bytes([12]))
    assert bridge.get_staff(bridge.session, ref, include_job=True)['staff']['contract']['job']['title'] == 'Coach (U18 Team)'
    m['put'](m['staff_contract'] + 0x26, bytes([34]))
    assert bridge.get_staff(bridge.session, ref, include_job=True)['staff']['contract']['job']['title'] == 'GK Coach (U18 Team)'


@pytest.mark.parametrize('job,team,title', [(2,0,'Coach First Team'), (3,0,'Player/Coach First Team'),
    (16,10,'Manager (U21 Team)'), (38,0,'Chief Doctor'), (86,0,'Loan Manager'),
    (14,255,'Scout'), (2,255,None), (255,0,None), (0,0,None)])
def test_job_conversion_handles_combined_and_unmapped_codes(attribute_record, job, team, title):
    m = attribute_record
    m['put'](m['staff_contract'] + 0x26, bytes([job]))
    m['put'](m['team'] + 0x28, bytes([team]))
    result = staff.contract_club(m['read'], m['base'], 0x1000 + m['staff_offset'], include_job=True)['job']
    assert result['title'] == title
    assert result['state'] == ('decoded' if title else 'unmapped_native_job')


def test_null_contract_job_is_distinct_from_unmapped(bridge, monkeypatch, attribute_record):
    m = attribute_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    m['q'](0x1000 + m['staff_offset'] - 0x98, 0)
    assert bridge.get_staff(bridge.session, ref, include_job=True)['staff']['contract']['job'] == {
        'title': None, 'state': 'no_contract'}


@pytest.mark.parametrize('kind', ['full_contract', 'basic_contract'])
def test_shared_job_getter_required(attribute_record, kind):
    m = attribute_record
    table = m['base'] + world.TYPES[kind][0]
    m['staff_contract'] = m['typed'](kind, 40)
    m['q'](0x1000 + m['staff_offset'] - 0x98, m['staff_contract'])
    # Restore ownership after typed fixture fills the object.
    m['q'](m['staff_contract'] + 8, 0x1000 + m['staff_offset'])
    m['q'](m['staff_contract'] + 16, m['team'])
    m['q'](m['staff_contract'] + 24, m['team'])
    m['put'](m['staff_contract'] + 0x26, bytes([38]))
    m['q'](table + 11*8, m['base'] + 0xD8C3C8)
    assert staff.contract_club(m['read'], m['base'], 0x1000 + m['staff_offset'], include_job=True)['job']['title'] == 'Chief Doctor'
    m['q'](table + 11*8, 0)
    with pytest.raises(ValueError, match='getter changed'):
        staff.contract_club(m['read'], m['base'], 0x1000 + m['staff_offset'], include_job=True)


def test_job_filter_works_and_rejects_incomplete_coverage(bridge, monkeypatch, attribute_record):
    m = attribute_record
    club_fixture(bridge, monkeypatch, m)
    found = bridge.query_club_staff(bridge.session, {'attacking': 15}, job_contains=' cOaCh ')
    assert found['matched_count'] == 1 and found['unmapped_job_count'] == 0
    assert bridge.query_club_staff(bridge.session, job_contains='Physio')['matched_count'] == 0
    m['put'](m['staff_contract'] + 0x26, b'\xff')
    all_staff = bridge.query_club_staff(bridge.session)
    assert all_staff['matched_count'] == all_staff['unmapped_job_count'] == 1
    with pytest.raises(BridgeError, match='unmapped'):
        bridge.query_club_staff(bridge.session, job_contains='Physio')
    for value in ('', '   ', 1, 'a'*129):
        with pytest.raises(BridgeError): bridge.query_club_staff(bridge.session, job_contains=value)
    for value in (1, None, 'true'):
        with pytest.raises(BridgeError): bridge.get_club_staff(bridge.session, include_job=value)
