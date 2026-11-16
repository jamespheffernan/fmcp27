import struct

import pytest

from fm_live_mcp import staff, staff_attributes as attrs, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import database_memory
from test_players import memory
from test_staff import staff_record, setup, club_fixture
from test_world import world_memory
from personality_fixture import populate as populate_personality


@pytest.fixture
def attribute_record(staff_record):
    m = staff_record
    kind = m['staff_kind']
    _, _, person_offset, data_offset, _ = staff.LAYOUTS[kind]
    populate_personality(m, 0x1000, person_offset)
    nonplayer = data_offset - 8
    vtable, getter = attrs.DISPATCH[kind]
    m['q'](0x1000 + nonplayer, m['base'] + vtable)
    m['q'](m['base'] + vtable + 26 * 8, m['base'] + getter)
    m['put'](m['base'] + vtable - 24, struct.pack('<q', person_offset - 0x110 - nonplayer))
    m['put'](m['base'] + vtable - 16, struct.pack('<q', -nonplayer))
    for group in (attrs.ATTRIBUTES, attrs.TENDENCIES, attrs.BOARD):
        for offset, fifths, _ in group.values():
            m['put'](0x1000 + nonplayer + offset, bytes([78 if fifths else 17]))
    m['put'](0x1000 + person_offset - 0xD0, b'\x0f')
    m['q'](m['base'] + world.TYPES['full_contract'][0] + 11*8, m['base'] + 0xD8C3C8)
    m['put'](m['staff_contract'] + 0x26, bytes([2]))
    m['nonplayer_offset'] = nonplayer
    return m


def test_staff_attributes_decode_all_layouts_and_preserve_default(bridge, monkeypatch, attribute_record):
    m = attribute_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    assert 'attributes' not in bridge.get_staff(bridge.session, ref)['staff']
    record = bridge.get_staff(bridge.session, ref, include_attributes=True)['staff']
    assert len(record['attributes']) == 23 and len(record['tendencies']) == 12 and len(record['board_attributes']) == 4
    assert record['attributes']['attacking'] == 16 and record['tendencies']['attacking'] == 17
    assert record['attributes']['adaptability'] == 15
    assert record['attributes']['authority'] == 17
    # Fresh reads must not reuse ratings from the previous request.
    m['put'](0x1000 + m['nonplayer_offset'] + 0x32, b'\x64')
    assert bridge.get_staff(bridge.session, ref, include_attributes=True)['staff']['attributes']['attacking'] == 20


@pytest.mark.parametrize('raw,expected', [(0, 1), (1, 1), (7, 1), (8, 2), (97, 19), (98, 20), (100, 20)])
def test_scaled_rating_rounding_matches_native_formula(attribute_record, raw, expected):
    m = attribute_record
    m['put'](0x1000 + m['nonplayer_offset'] + 0x32, bytes([raw]))
    record, _ = staff.decode(m['read'], m['base'], 0x1000, include_attributes=True)
    assert record['attributes']['attacking'] == expected


@pytest.mark.parametrize('fault', ['getter', 'adjustment', 'displacement', 'scaled_range', 'direct_range', 'adaptability'])
def test_invalid_attribute_read_expires_reference(bridge, monkeypatch, attribute_record, fault):
    m = attribute_record
    setup(bridge, monkeypatch, m)
    ref = bridge.find_staff(bridge.session, 'Test')['staff'][0]['staff_ref']
    table = m['base'] + attrs.DISPATCH[m['staff_kind']][0]
    if fault == 'getter': m['q'](table + 26*8, 0)
    if fault == 'adjustment': m['q'](table - 24, 0)
    if fault == 'displacement': m['q'](table - 16, 123)
    if fault == 'scaled_range': m['put'](0x1000 + m['nonplayer_offset'] + 0x32, b'\x65')
    if fault == 'direct_range': m['put'](0x1000 + m['nonplayer_offset'] + 0x14, b'\x15')
    if fault == 'adaptability': m['put'](0x1000 + m['staff_offset'] - 0xD0, b'\xff')
    with pytest.raises(BridgeError): bridge.get_staff(bridge.session, ref, include_attributes=True)
    assert ref not in bridge.staff_refs


def test_club_staff_filter_and_invalid_arguments(bridge, monkeypatch, attribute_record):
    m = attribute_record
    club_fixture(bridge, monkeypatch, m)
    result = bridge.query_club_staff(bridge.session, {'attacking': 15, 'motivating': 16}, 'determination')
    assert result['roster_count'] == result['matched_count'] == result['returned_count'] == 1
    assert not result['truncated'] and result['staff'][0]['attributes']['attacking'] == 16
    assert bridge.query_club_staff(bridge.session, {'attacking': 17})['matched_count'] == 0
    for args in ({'minimum_attributes': {'vision': 15}}, {'minimum_attributes': {'attacking': True}},
                 {'minimum_attributes': []}, {'sort_by': 'unknown'}, {'limit': True}):
        with pytest.raises(BridgeError): bridge.query_club_staff(bridge.session, **args)
    for value in ('true', 1, None):
        with pytest.raises(BridgeError): bridge.get_club_staff(bridge.session, include_attributes=value)


def test_staff_filter_ties_and_truncation(bridge, monkeypatch):
    people = [dict(name=name, display_name=name, birth_date='2000-01-01', attributes={'attacking': rating},
                   contract={'job': {'state': 'decoded', 'title': 'Coach First Team'}})
              for name, rating in [('Zulu', 15), ('Alpha', 15), ('Beta', 18), ('Below', 14)]]
    monkeypatch.setattr(bridge, 'get_club_staff', lambda *a, **kw: {
        'observed_at': 'now', 'save': {}, 'club': {}, 'count': 4, 'staff': people, 'limitations': ''})
    result = bridge.query_club_staff(bridge.session, {'attacking': 15}, 'attacking', limit=2)
    assert result['matched_count'] == 3 and result['returned_count'] == 2 and result['truncated']
    assert [p['name'] for p in result['staff']] == ['Beta', 'Alpha']
