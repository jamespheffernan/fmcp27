import struct

import pytest

from fm_live_mcp import personality, players, staff, virtual
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory, bind
from test_player_profile import profile_memory, populate, decode
from personality_fixture import populate_virtual
from fm_live_mcp import player_profile
from test_player_staff import staff_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_staff_attributes import attribute_record
from test_virtual import virtual_memory
from test_world import world_memory


EXPECTED = {'adaptability': 11, 'ambition': 12, 'loyalty': 13, 'pressure': 14,
            'professionalism': 15, 'sportsmanship': 16, 'temperament': 17, 'controversy': 18}


def person_offset(m):
    return 0x480 if players.u64(m['read'](0x1000, 8)) == m['base'] + players.STAFF_RVA[0] else 0x388


def test_player_personality_all_layouts_and_native_virtual_default(profile_memory):
    m = profile_memory
    result = decode(m)['profile']
    expected = {**EXPECTED, **({'controversy': 0} if m['is_virtual'] else {})}
    assert result['personality'] == expected and result['personality_scale'] == '0–20'
    assert result['personality_native_defaults'] == (['controversy'] if m['is_virtual'] else [])
    # A cached controversy byte does not replace the virtual getter's constant.
    if m['is_virtual']:
        m['put'](0x12BF, b'\xff')
        assert decode(m)['profile']['personality']['controversy'] == 0


@pytest.mark.parametrize('value', [0, 20, 21, 127, 255])
def test_direct_ratings_preserve_bounds_and_reject_invalid(profile_memory, value):
    m = profile_memory
    m['put'](0x1000 + person_offset(m) - 0xCC, bytes([value]))
    if value <= 20:
        assert decode(m)['profile']['personality']['professionalism'] == value
    else:
        with pytest.raises(ValueError, match='Personality rating'): decode(m)


@pytest.mark.parametrize('fault', ['getter', 'adjustment'])
def test_person_dispatch_changes_fail(profile_memory, fault):
    m = profile_memory
    table = players.u64(m['read'](0x1000 + person_offset(m), 8))
    m['q'](table + 182*8 if fault == 'getter' else table - (182*8+16), 0)
    with pytest.raises(ValueError, match='Personality'): decode(m)


@pytest.mark.parametrize('fault', ['compact_getter', 'compact_adjustment', 'cache_adjustment', 'pressure_delegate'])
def test_virtual_personality_dispatch_changes_fail(virtual_memory, fault):
    m = virtual_memory
    populate(m, 0x1000)
    populate_virtual(m)
    m['is_virtual'] = True
    for slot, getter in player_profile.VIRTUAL_GETTERS.items():
        m['q'](m['base'] + 0x55CAC48 + slot*8, m['base'] + getter)
    if fault == 'compact_getter': m['q'](m['base'] + virtual.PERSON_RVA + 178*8, 0)
    if fault == 'compact_adjustment': m['q'](m['base'] + virtual.PERSON_RVA - (176*8+16), 0)
    if fault == 'cache_adjustment': m['q'](m['tables'][0]-32, 0)
    if fault == 'pressure_delegate': m['q'](m['base'] + 0x5589A90 + 75*8, 0)
    with pytest.raises(ValueError, match='[Pp]ersonality'): decode(m)


def test_player_personality_mutation_expires_reference(bridge, monkeypatch, profile_memory):
    m = profile_memory
    bind(bridge, monkeypatch, m)
    ref = bridge.get_managed_squad(bridge.session)['players'][0]['player_ref']
    original = personality.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        for address in {0x1000, m.get('regular', 0x1000)}:
            m['put'](address + person_offset(m) - 0xCC, b'\x14')
        return result
    monkeypatch.setattr(personality, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'): bridge.get_player(bridge.session, ref, include_profile=True)
    assert ref not in bridge.player_refs


def test_staff_personality_shared_ratings_and_fresh_queries(bridge, monkeypatch, attribute_record):
    m = attribute_record
    club_fixture(bridge, monkeypatch, m)
    person = bridge.get_club_staff(bridge.session, include_attributes=True)['staff'][0]
    assert person['personality'] == {**EXPECTED, 'adaptability': 15}
    assert 'personality' not in bridge.get_staff(bridge.session, person['staff_ref'])['staff']
    result = bridge.query_club_staff(bridge.session, minimum_personality={'professionalism': 15}, sort_by='personality.pressure')
    assert result['matched_count'] == 1 and result['staff'][0]['personality']['pressure'] == 14
    m['put'](0x1000 + m['staff_offset'] - 0xCC, b'\x0e')
    assert bridge.query_club_staff(bridge.session, minimum_personality={'professionalism': 15})['matched_count'] == 0


def test_staff_personality_detects_mutation(bridge, monkeypatch, attribute_record):
    m = attribute_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    original = personality.decode
    def mutate(*a, **kw):
        result = original(*a, **kw)
        m['put'](0x1000 + m['staff_offset'] - 0xCC, b'\x14')
        return result
    monkeypatch.setattr(personality, 'decode', mutate)
    with pytest.raises(BridgeError, match='changed'): bridge.get_staff(bridge.session, ref, include_attributes=True)
    assert ref not in bridge.staff_refs


@pytest.mark.parametrize('args', [{'minimum_personality': []}, {'minimum_personality': {'ambition': True}},
    {'minimum_personality': {'pressure': -1}}, {'minimum_personality': {'professionalism': 21}},
    {'minimum_personality': {'invented': 10}}, {'sort_by': 'personality.invented'}, {'sort_by': []}])
def test_staff_query_validation_before_reads(bridge, monkeypatch, args):
    monkeypatch.setattr(bridge, 'get_club_staff', lambda *a, **kw: pytest.fail('read before validation'))
    with pytest.raises(BridgeError): bridge.query_club_staff(bridge.session, **args)


def test_staff_personality_filter_sort_and_truncation(bridge, monkeypatch):
    rows = [{'display_name': name, 'birth_date': '2000-01-01', 'attributes': {'motivating': motivating},
             'personality': {'professionalism': pro, 'ambition': ambition},
             'contract': {'job': {'title': 'Coach', 'state': 'decoded'}}}
            for name, motivating, pro, ambition in [('A', 15, 17, 13), ('B', 16, 17, 13), ('C', 16, 20, 12), ('D', 14, 20, 20)]]
    monkeypatch.setattr(bridge, 'get_club_staff', lambda *a, **kw: {'staff': rows, 'count': len(rows),
        'observed_at': 'now', 'save': {}, 'club': {}, 'limitations': ''})
    result = bridge.query_club_staff(bridge.session, minimum_attributes={'motivating': 15},
        minimum_personality={'professionalism': 17, 'ambition': 13}, sort_by='personality.professionalism', job_contains='coach', limit=1)
    assert result['matched_count'] == 2 and result['returned_count'] == 1 and result['truncated']
    assert result['staff'][0]['display_name'] == 'A'
