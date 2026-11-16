import struct

import pytest

from fm_live_mcp import auxiliary_database_tables as auxiliary
from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_players import memory
from test_world import world_memory
from test_database import database_memory, bind


@pytest.fixture
def auxiliary_memory(database_memory):
    m = database_memory
    roots, headers = [], []
    for root_rva, table_rva, name in auxiliary.TABLES:
        root = m['allocate'](0x90)
        info, text, header = m['allocate'](16), m['allocate'](len(name) + 1), m['allocate'](24)
        m['put'](text, name + b'\0')
        m['q'](info + 8, text)
        m['put'](m['base'] + table_rva - 16, struct.pack('<qQ', 0, info))
        m['q'](m['base'] + root_rva, root)
        m['q'](root, m['base'] + table_rva)
        m['q'](root + 0x88, header)
        roots.append(root)
        headers.append(header)
    m['auxiliary_roots'], m['auxiliary_headers'] = roots, headers
    return m


def test_empty_resident_instances_and_duplicate_types_are_preserved(auxiliary_memory):
    m = auxiliary_memory
    result = auxiliary.inspect(m['read'], m['base'])
    assert result['resident_global_instance_count'] == 39
    assert result['distinct_resident_object_count'] == 39
    assert result['distinct_native_table_type_count'] == 35
    assert result['empty_instance_count'] == 39
    newgen = [r for r in result['tables'] if r['record_type'] == 'STARTING_NEWGEN_PARAMETER']
    assert [r['instance_ordinal'] for r in newgen] == [1, 2, 3, 4]
    assert all(r['same_type_instance_count'] == 4 for r in newgen)
    assert all(r['state'] == 'resident_empty' and not r['record_fields_decoded'] for r in result['tables'])


def test_populated_vector_and_same_object_alias_do_not_become_absence(auxiliary_memory):
    m = auxiliary_memory
    m['vec'](m['auxiliary_headers'][0], [m['club'], 0])
    # Four newgen instances share one type; an alias must remain explicit.
    first = next(i for i, r in enumerate(auxiliary.TABLES) if b'STARTING_NEWGEN_PARAMETER' in r[2])
    m['q'](m['base'] + auxiliary.TABLES[first + 1][0], m['auxiliary_roots'][first])
    result = auxiliary.inspect(m['read'], m['base'])
    assert result['tables'][0]['record_slot_count'] == 2
    assert result['tables'][0]['state'] == 'resident_with_slots'
    assert result['empty_instance_count'] == 38
    assert result['distinct_resident_object_count'] == 38
    assert result['tables'][first + 1]['same_object_alias_of'] == first


@pytest.mark.parametrize('fault', ['null_root', 'wrong_type', 'displacement', 'bad_bounds'])
def test_auxiliary_guard_failure_rejects_entire_catalog(auxiliary_memory, fault):
    m = auxiliary_memory
    root_rva, table_rva, _ = auxiliary.TABLES[0]
    if fault == 'null_root':
        m['q'](m['base'] + root_rva, 0)
    elif fault == 'wrong_type':
        m['q'](m['auxiliary_roots'][0], 0)
    elif fault == 'displacement':
        m['put'](m['base'] + table_rva - 16, struct.pack('<q', -8))
    else:
        m['put'](m['auxiliary_headers'][0], struct.pack('<QQQ', 4096, 4095, 8192))
    with pytest.raises(ValueError):
        auxiliary.inspect(m['read'], m['base'])


def test_catalog_default_is_unchanged_and_opt_in_uses_same_snapshot(bridge, monkeypatch, auxiliary_memory):
    m = auxiliary_memory
    bind(bridge, monkeypatch, m)
    default = bridge.get_database_catalog(bridge.session)
    expanded = bridge.get_database_catalog(bridge.session, include_auxiliary=True)
    assert 'auxiliary_tables' not in default
    assert default['native_table_counts'] == expanded['native_table_counts']
    assert expanded['auxiliary_tables']['resident_global_instance_count'] == 39
    with pytest.raises(BridgeError, match='boolean'):
        bridge.get_database_catalog(bridge.session, include_auxiliary=1)
