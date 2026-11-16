import json
from pathlib import Path
import struct

import pytest

from fm_live_mcp import finance_person_reference as people, contingent_transfer_people, players, world
from fm_live_mcp import live_contingent_transfer_clauses as query
from fm_live_mcp.bridge import BridgeError
from prepared_tactics_fixture import prepared_tactics_memory
from test_bridge import bridge
from test_club_debt_obligations import debt_memory
from test_club_finance import finance_memory
from test_contingent_transfer_appearance import appearance_memory
from test_database import database_memory
from test_live_contingent_transfer_clauses import live_clauses
from test_live_transfer_debt_obligations import live_debt
from test_players import memory
from test_player_staff import staff_memory
from test_retained_transfer_debt import transfer_memory
from test_teams import team_memory
from test_world import world_memory


@pytest.fixture
def person_memory(appearance_memory):
    m = appearance_memory
    old_root = m['roots']['people']
    root = m['allocate'](0xB0)
    m['put'](root, m['read'](old_root, 0x90))
    m['q'](m['base'] + people.database.TABLES['people'][0], root)
    m['roots']['people'] = root
    m['put'](root + 0x64, b'\0')
    source = m['read'](0x1000, players.SIZE)
    persons = []
    for index, (native, secondary) in enumerate(((100, 100), (12345, 0), (20000, 25000))):
        primary = m['allocate'](players.SIZE)
        m['put'](primary, source)
        m['put'](primary + 0x390, struct.pack('<III', index, native, secondary))
        persons.append(primary + 0x388)
    m['vec'](m['headers']['people'], persons)
    for rva, displacement in ((players.RVA[0], 0), (players.RVA[2], -0x388)):
        info, name = m['allocate'](16), m['allocate'](64) + 1
        m['put'](name, b'N2db13ACTUAL_PLAYERE\0')
        m['q'](info + 8, name)
        m['put'](m['base'] + rva - 16, struct.pack('<qQ', displacement, info))
    m.update(binding_people=persons, binding_person=persons[1])
    return m


def test_native_id_pair_search_is_bounded_and_canonical_names_match(person_memory):
    m = person_memory
    before = dict(m['cells'])
    context = people.context(m['read'], m['base'])
    for secondary in (0, 12345):
        match = people.lookup(m['read'], context, 12345, secondary)
        assert match['state'] == 'matched_native_reference' and match['binary_search_probes'] == 1
        result = people.playing_identity(m['read'], m['base'], context, match)
        assert result['state'] == 'canonical_playing_person'
        assert result['name'] == result['display_name'] == 'Test Müller'
        assert result['database_index'] == 1 and result['native_id'] == 12345 and result['secondary_id'] == 0
    assert m['cells'] == before


def test_combined_playing_person_uses_checked_shared_layout(staff_memory):
    m = staff_memory
    source = json.loads((Path(__file__).parents[1] / 'evidence/finance-person-bindings-20261109/source-bytes.json').read_text())
    for span in source['spans']:
        m['put'](m['base'] + span['rva'], bytes.fromhex(span['hex']))
    m['put'](m['roots']['people'] + 0x64, b'\0')
    context = people.context(m['read'], m['base'])
    match = people.lookup(m['read'], context, 12345, 12345)
    result = people.playing_identity(m['read'], m['base'], context, match)
    assert result['record_kind'] == 'player_staff' and result['name'] == 'Test Müller'


@pytest.mark.parametrize(('native', 'secondary', 'expected'), [(100, 100, 'matched_native_reference'),
    (20000, 25000, 'matched_native_reference'), (20000, 0, 'matched_native_reference'),
    (20000, 20000, 'native_reference_remap_not_evaluated'), (12345, 99, 'native_reference_remap_not_evaluated'),
    (555, 555, 'native_reference_remap_not_evaluated'), (0, 0, 'native_primary_reference_not_positive'),
    (2147483648, 0, 'native_primary_reference_not_positive'),
    (555, 0, 'native_reference_not_resolved'), (555, 4294967295, 'native_reference_not_resolved'),
    (20000, 4294967295, 'native_reference_not_resolved')])
def test_exact_secondary_native_id_and_zero_fallback_rules(person_memory, native, secondary, expected):
    m = person_memory
    result = people.lookup(m['read'], people.context(m['read'], m['base']), native, secondary)
    assert result['state'] == expected
    assert result.get('binary_search_probes', 0) <= 2


def test_native_sort_requirement_is_unavailable_without_sorting_or_shadow_reads(person_memory):
    m = person_memory
    root = m['roots']['people']
    m['put'](root + 0x64, b'\x01'); m['put'](root + 0xA8, b'\x01')
    before = dict(m['cells'])
    def read(address, size):
        assert not root + 0x90 <= address < root + 0xA8
        return m['read'](address, size)
    context = people.context(read, m['base'])
    assert context['state'] == 'native_reference_sort_required'
    assert people.lookup(read, context, 12345, 12345)['state'] == 'native_reference_sort_required'
    assert m['cells'] == before


@pytest.mark.parametrize('sort_flag', [0, 2, 255])
def test_already_indexed_shadow_branch_is_read_only_and_uses_exact_native_flag_predicate(person_memory, sort_flag):
    m = person_memory
    root = m['roots']['people']
    m['put'](root + 0x64, b'\x01'); m['put'](root + 0xA8, bytes([sort_flag]))
    m['vec'](root + 0x90, m['binding_people'])
    context = people.context(m['read'], m['base'])
    assert context['state'] == 'native_shadow_binary_search'
    match = people.lookup(m['read'], context, 12345, 12345)
    assert people.playing_identity(m['read'], m['base'], context, match)['name'] == 'Test Müller'


def test_header_empty_stops_before_shadow_or_remap(person_memory):
    m = person_memory
    m['vec'](m['headers']['people'], [])
    context = people.context(m['read'], m['base'])
    assert context['state'] == 'native_empty_person_header'
    assert people.lookup(m['read'], context, 12345, 12345)['state'] == 'native_empty_person_header'


@pytest.mark.parametrize('fault', ['native_source', 'identity', 'membership', 'rtti', 'name'])
def test_source_or_known_player_corruption_rejects_names(person_memory, fault):
    m = person_memory
    if fault == 'native_source':
        m['put'](m['base'] + people.SOURCE[0][0], b'\0')
        with pytest.raises(ValueError, match='source changed'): people.context(m['read'], m['base'])
        return
    context = people.context(m['read'], m['base'])
    match = people.lookup(m['read'], context, 12345, 12345)
    if fault == 'identity': m['put'](m['binding_person'] + 12, struct.pack('<I', 333))
    elif fault == 'membership': m['q'](context['people']['start'] + 8, m['binding_people'][0])
    elif fault == 'rtti': m['put'](m['base'] + players.RVA[2] - 16, b'\0')
    else: m['put'](0x3004, b'\xff')
    with pytest.raises(ValueError): people.playing_identity(m['read'], m['base'], context, match)


def test_nonplaying_person_kind_stays_unresolved_without_losing_clause(person_memory):
    m = person_memory
    m['q'](m['binding_person'], m['base'] + world.TYPES['manager'][0])
    context = people.context(m['read'], m['base'])
    match = people.lookup(m['read'], context, 12345, 12345)
    assert people.playing_identity(m['read'], m['base'], context, match)['state'] == 'native_person_not_supported_playing_type'


def test_contingent_wrapper_deduplicates_reference_lookup_and_retains_unknowns(person_memory):
    m = person_memory
    m['put'](m['first_clause'] + 8, struct.pack('<II', 12345, 12345))
    result = contingent_transfer_people.decode(m['read'], m['base'], m['club'])
    assert result['person_binding']['unique_reference_count'] == 2
    assert result['person_binding']['resolved_unique_reference_count'] == 1
    first, unknown, alias = result['records']
    assert first['native_person_reference']['name'] == alias['native_person_reference']['name'] == 'Test Müller'
    assert first['native_person_reference']['playing_person']['database_index'] == 1
    assert unknown['native_person_reference']['resolution_state'] == 'native_reference_remap_not_evaluated'
    assert unknown['native_call_amount']['amount'] == 150000


@pytest.mark.parametrize('field', ['flag', 'index_slot', 'person_id', 'name', 'rtti'])
def test_new_name_bindings_are_in_final_physical_read_set(person_memory, field):
    m = person_memory
    m['put'](m['first_clause'] + 8, struct.pack('<II', 12345, 12345))
    read = world.ReadSet(m['read'])
    contingent_transfer_people.decode(read, m['base'], m['club'])
    header_start = int.from_bytes(m['read'](m['headers']['people'], 8), 'little')
    address = {'flag': m['roots']['people'] + 0x64, 'index_slot': header_start + 8,
               'person_id': m['binding_person'] + 12, 'name': 0x3004,
               'rtti': m['base'] + players.RVA[2] - 16}[field]
    m['put'](address, bytes([m['read'](address, 1)[0] ^ 1]))
    with pytest.raises(ValueError, match='changed during read'): read.verify()


@pytest.mark.parametrize('callback', ['public_save', 'final_current'])
def test_public_binding_rechecks_after_final_callbacks(live_clauses, person_memory, monkeypatch, callback):
    m = person_memory
    assert m is live_clauses
    bridge = m['bridge']
    m['put'](m['first_clause'] + 8, struct.pack('<II', 12345, 12345))
    def mutate(): m['put'](0x3004, b'X')
    if callback == 'public_save':
        original = bridge._public_save
        def public(save):
            mutate(); return original(save)
        monkeypatch.setattr(bridge, '_public_save', public)
    else:
        original = bridge._current; calls = []
        def current(session):
            calls.append(1)
            if len(calls) == 3: mutate()
            return original(session)
        monkeypatch.setattr(bridge, '_current', current)
    with pytest.raises(BridgeError, match='changed during read'):
        query.get_club_contingent_transfer_clauses(bridge, bridge.session)
