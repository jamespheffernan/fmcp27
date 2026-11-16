import copy
import struct

import pytest

from fm_live_mcp import saved_person_search as search
from fm_live_mcp.saved_player_wire_prefix import prefix_probe
from test_saved_player_wire_prefix import minimal


def source_and_witness(values=((148, 155),), *, ordinal=7):
    data = bytearray()
    previous = []
    for current, potential in values:
        data.extend(struct.pack('<III', ordinal - 1, 321, 654))
        start = len(data)
        raw = bytearray(minimal())
        struct.pack_into('<hh', raw, 7, current, potential)
        data.extend(raw)
        packet = prefix_probe(data, start, len(data), include_ability=True)
        previous.append({'person_index': ordinal - 1, 'identity_offset': start - 12,
                         'end': start, 'target_prefix': packet})
    witness = {'common_start': len(data), 'neighbour_evidence': {
        'preceding': previous, 'following': [], 'tier': 'test'}}
    return bytes(data), witness


def test_signed_values_and_component_source_offsets():
    data, witness = source_and_witness(((-32768, -10),))
    out = search.ability_from_preceding(data, witness, 7)
    assert out['state'] == 'available' and out['ability_fields_complete']
    entry, = out['start_geometries']
    assert entry['current_native_signed16'] == -32768
    assert entry['potential_native_signed16'] == -10
    assert entry['record_start'] == 12 and entry['body_start'] == 13
    assert entry['current_source_offset'] == 19 and entry['potential_source_offset'] == 21
    assert out['native_properties'] == {'current': 'PCAB', 'potential': 'PPAB'}
    assert not out['placement_complete'] and not out['certified_person_record']


@pytest.mark.parametrize('values', [((148, 155), (94, 120)), ((100, 100), (100, 100))])
def test_competing_starts_remain_explicit_even_equal_values(values):
    data, witness = source_and_witness(values)
    out = search.ability_from_preceding(data, witness, 7)
    assert out['state'] == 'ambiguous_start_geometries'
    assert len(out['start_geometries']) == 2
    assert 'current_native_signed16' not in out
    assert [(s['current_native_signed16'], s['potential_native_signed16'])
            for s in out['start_geometries']] == list(values)


def test_same_start_aliases_do_not_fabricate_multiple_starts():
    data, witness = source_and_witness()
    witness['neighbour_evidence']['preceding'] *= 2
    assert len(search.ability_from_preceding(data, witness, 7)['start_geometries']) == 1


def test_following_player_and_unprobed_boundaries_do_not_supply_ability():
    data, witness = source_and_witness()
    packet = witness['neighbour_evidence']['preceding'][0].pop('target_prefix')
    witness['neighbour_evidence']['following'] = [{'next_prefix': packet}]
    assert search.ability_from_preceding(data, witness, 7)['state'] == 'unavailable'


@pytest.mark.parametrize('mutation', ['wrong_start', 'wrong_ordinal', 'source_ordinal', 'past_common',
                                      'wrong_tag', 'wrong_source_offset', 'wrong_value',
                                      'missing_ability', 'missing_tag_marker', 'wrong_profile'])
def test_unverified_target_prefix_or_source_never_supplies_values(mutation):
    data, witness = source_and_witness()
    raw = bytearray(data)
    previous = witness['neighbour_evidence']['preceding'][0]
    packet = previous['target_prefix']
    if mutation == 'wrong_start':
        packet['start'] += 1
    elif mutation == 'wrong_ordinal':
        previous['person_index'] = 7
    elif mutation == 'source_ordinal':
        struct.pack_into('<I', raw, 0, 7)
    elif mutation == 'past_common':
        witness['common_start'] = packet['end'] - 1
    elif mutation == 'wrong_tag':
        raw[packet['start']] = 3
    elif mutation == 'wrong_source_offset':
        packet['ability']['current_source_offset'] += 1
    elif mutation == 'wrong_value':
        packet['ability']['potential_native_signed16'] += 1
    elif mutation == 'missing_ability':
        packet.pop('ability')
    elif mutation == 'missing_tag_marker':
        packet['validated_markers'] = []
    else:
        packet['wire_profile'] = 'different'
    out = search.ability_from_preceding(bytes(raw), witness, 7)
    assert out['state'] == 'unavailable' and out['start_geometries'] == []
    assert out['rejected_preceding_packet_reasons']


def test_prefix_default_shape_unchanged_and_optin_strict():
    data = minimal()
    assert 'ability' not in prefix_probe(data, 0, len(data))
    for bad in (0, 1, None, 'true', [], {}):
        with pytest.raises(ValueError, match='include_ability'):
            prefix_probe(data, 0, len(data), include_ability=bad)
        with pytest.raises(ValueError, match='include_ability'):
            search.get_name_candidates('missing.fm', [1], 'pin', include_ability=bad)


def projected_row(data, witness):
    witness = copy.deepcopy(witness)
    witness.update(identity={'stored_index': 7}, name_indices=[1, 2, -1], names=[],
                   common_end=len(data) + 59, identity_offset=len(data) + 67,
                   end=len(data) + 79, next_tag=2)
    return {'person_index': 7, 'state': 'witnessed', 'search_complete': True,
            'budget_reasons': [], 'evidence_scope': {}, 'candidates': [witness],
            'neighbour_corroboration': {'search_complete': True, 'preferred_geometries': []}}


def test_projection_default_and_false_are_identical_optin_keeps_names():
    data, witness = source_and_witness()
    row = projected_row(data, witness)
    default = search._project(row, False, 0, 100)
    explicit_false = search._project(row, False, 0, 100, include_ability=False, source_data=data)
    assert default == explicit_false and 'ability' not in default['candidates'][0]
    included = search._project(row, False, 0, 100, include_ability=True, source_data=data)
    ability = included['candidates'][0].pop('ability')
    assert included == default
    assert ability['state'] == 'available' and ability['candidate_search_complete']


def test_incomplete_search_is_preserved_beside_checked_fields():
    data, witness = source_and_witness()
    row = projected_row(data, witness)
    row['search_complete'] = False
    included = search._project(row, False, 0, 100, include_ability=True, source_data=data)
    ability = included['candidates'][0]['ability']
    assert ability['state'] == 'available' and ability['candidate_search_complete'] is False
