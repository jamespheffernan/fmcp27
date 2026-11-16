import struct

import pytest

from fm_live_mcp import geography, media_sources, world
from test_geography import geo_memory, database_memory, memory, world_memory


@pytest.fixture
def outlet(geo_memory):
    m = geo_memory
    address = m['typed']('media_source', 0xE8)
    m['q'](m['base'] + world.TYPES['media_source'][0] + 24, m['base'] + geography.FIELDS['media_source'][0])
    m['put'](address + 8, struct.pack('<III', 0, 117, 192))
    m['q'](address + 0x18, m['text']('Press Test'))
    m['vec'](m['headers']['media_sources'], [address])
    m['vec'](address + 0x50, [m['geography']['nation'][0], 0, m['geography']['nation'][0]])
    m['q'](address + 0xB8, m['geography']['continent'][0])
    m['put'](address + 0xC0, bytes([6, 0, 0, 1]))
    m['put'](address + 0xE0, bytes([2, 4]))
    return m, address


def test_named_fields_and_direct_links(outlet):
    m, address = outlet
    row, binding = media_sources.record(m['read'], m['base'], address, include_details=True)
    assert row['name'] == 'Press Test' and binding['native_id'] == 117
    assert row['style'] == {'code': 6, 'label': 'Analytical'}
    assert row['scope']['label'] == 'National' and row['publication_period']['label'] == 'Weekday Morning'
    assert row['is_fake'] is False and row['attends_press_conferences'] is True
    assert row['continent']['name'] == 'Europe' and row['city'] is None
    assert [n and n['short_name'] for n in row['nations']] == ['England', None, 'England']


def test_unknown_codes_and_bad_vector(outlet):
    m, address = outlet
    m['put'](address + 0xC2, bytes([7, 255]))
    m['put'](address + 0xE0, bytes([255, 90]))
    row, _ = media_sources.record(m['read'], m['base'], address, include_details=True)
    assert row['is_fake'] is None and row['attends_press_conferences'] is None
    assert row['scope'] == {'code': 90, 'label': None}
    assert row['publication_period'] == {'code': -1, 'label': None}
    m['put'](address + 0x50, struct.pack('<QQQ', 4096, 4112, 4104))
    with pytest.raises(ValueError, match='nations vector'):
        media_sources.record(m['read'], m['base'], address, include_details=True)
