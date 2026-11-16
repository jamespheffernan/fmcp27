import json
import struct
from pathlib import Path

import pytest

from fm_live_mcp import club_facilities, world
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory
from test_players import memory
from test_world import world_memory


@pytest.fixture
def facilities_memory(database_memory):
    m = database_memory
    for rva, raw in club_facilities.NATIVE_GUARDS.items():
        m['put'](m['base']+rva, bytes.fromhex(raw))
    secondary = m['allocate'](0x140)
    m['q'](m['club']+0x100, secondary)
    for field, (offset, _, _, _) in club_facilities.FIELDS.items():
        m['put'](secondary+offset, struct.pack('<b', {'training_facilities': 15, 'youth_facilities': 14, 'youth_coaching': -1, 'youth_recruitment': 0}[field]))
    m['secondary'] = secondary
    return m


def reference(bridge, monkeypatch, m):
    bind(bridge, monkeypatch, m)
    _, identity = world.club(m['read'], m['base'], m['club'])
    bridge.club_refs['club'] = dict(address=m['club'], identity=identity, tables=m['tables'], database_index=0)


def test_canonical_stored_levels_and_zero_unassigned(bridge, monkeypatch, facilities_memory):
    m = facilities_memory
    reference(bridge, monkeypatch, m)
    result = club_facilities.get_club_facilities(bridge, bridge.session, 'club')
    assert result['club']['native_id'] == bridge.club_refs['club']['identity'][0]
    assert result['club']['database_index'] == 0
    values = result['facilities']['values']
    assert values['training_facilities']['value'] == 15
    assert values['youth_facilities']['value'] == 14
    assert values['youth_coaching'] == dict(native_value=-1, value=None, state='unassigned', native_property='Cytv', unit='stored native level')
    assert values['youth_recruitment']['value'] == 0
    assert values['youth_recruitment']['state'] == 'stored'
    assert result['facilities']['effective_values'] == 'not_evaluated'


def test_missing_secondary_is_unknown(bridge, monkeypatch, facilities_memory):
    m = facilities_memory
    reference(bridge, monkeypatch, m)
    m['q'](m['club']+0x100, 0)
    out = club_facilities.get_club_facilities(bridge, bridge.session, 'club')['facilities']
    assert out['state'] == 'unavailable_secondary'
    assert all(v['value'] is None and v['native_value'] is None and v['state']=='unavailable_secondary' for v in out['values'].values())


@pytest.mark.parametrize('value', [-128, -2, -1, 0, 1, 20, 21, 127])
def test_signed_native_values_preserved_without_guessing(value, facilities_memory):
    m = facilities_memory
    for offset, *_ in club_facilities.FIELDS.values():
        m['put'](m['secondary']+offset, struct.pack('<b', value))
    out = club_facilities.decode(m['read'], m['base'], m['club'])
    for field, row in out['values'].items():
        assert row['native_value'] == value
        assert row['value'] == (value if 0 <= value <= 20 else None)
        assert row['state'] == ('stored' if 0 <= value <=20 else 'unassigned' if value == -1 and field != 'training_facilities' else 'out_of_editor_range')


@pytest.mark.parametrize('fault', ['guard', 'pointer', 'identity', 'membership', 'rtti', 'changed_field', 'unknown_ref'])
def test_corrupt_or_stale_sources_fail_closed(bridge, monkeypatch, facilities_memory, fault):
    m = facilities_memory
    reference(bridge, monkeypatch, m)
    if fault == 'guard': m['put'](m['base']+next(iter(club_facilities.NATIVE_GUARDS)), bytes(4))
    if fault == 'pointer': m['q'](m['club']+0x100, 17)
    if fault == 'identity': m['put'](m['club']+12, struct.pack('<I', 1234567))
    if fault == 'membership': m['vec'](m['headers']['clubs'], [m['manager']])
    if fault == 'rtti': m['q'](m['club'], 0)
    if fault == 'unknown_ref': bridge.club_refs.clear()
    if fault == 'changed_field':
        original = m['read']; n = 0
        def drifting(address, size):
            nonlocal n
            raw = original(address, size)
            if address == m['secondary']+0x120 and size==14:
                n += 1
                if n > 1: return bytes([raw[0]^1])+raw[1:]
            return raw
        monkeypatch.setattr(bridge, '_read_memory', lambda p,a,n: drifting(a,n))
    with pytest.raises((BridgeError, ValueError)):
        club_facilities.get_club_facilities(bridge, bridge.session, 'club')


def test_real_varied_club_records_and_duplicate_names():
    source = json.loads((Path(__file__).parent/'fixtures/club_facilities_b161.json').read_text())
    assert len(source['records']) == 35
    for row in source['records']:
        assert row['canonical_identity']['native_id']
        raw = bytes.fromhex(row['raw120_12d_hex'])
        def read(address, size):
            if address in club_facilities.NATIVE_GUARDS:
                assert size==4
                return bytes.fromhex(club_facilities.NATIVE_GUARDS[address])
            if address == 0x1100: return struct.pack('<Q',0x2000)
            assert (address,size)==(0x2120,14)
            return raw
        out = club_facilities.decode(read, 0, 0x1000)
        assert {k:v['native_value'] for k,v in out['values'].items()} == row['values']
    newcastle = [r for r in source['records'] if r['club']['name']=='Newcastle United']
    assert {r['canonical_identity']['native_id'] for r in newcastle} == {688,2000290848}
    assert len({tuple(r['values'].values()) for r in newcastle}) == 2
