import gzip
import json
from pathlib import Path

import pytest

from fm_live_mcp.saved_match_player_sprinting import (
    NATIVE_SPANS, decode_player_sprinting, sprinting_field_registry, verify_native,
)
from fm_live_mcp.saved_match_player_running import decode_player_running, running_field_registry
from fm_live_mcp.live_match_players import _usage


def retained():
    path = Path(__file__).parent / 'fixtures/retained_key_passes_lille_136941.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


# Frozen expectations from exact independent current-career retained raw readback.
EXPECTED = {2000183134: ('Ewen Jaouen', 0),
 83283239: ('Tiago Santos', 8),
 49037684: ('Oumar Solet', 2),
 83282675: ('Alexsandro Ribeiro', 2),
 67211695: ('Théo Hernández', 14),
 2000182795: ('Archie Gray', 10),
 19375640: ('André', 10),
 2000014559: ('Ernest Poku', 12),
 28126241: ('Oscar Bobb', 10),
 2000107089: ('Matias Fernandez-Pardo', 16),
 2000191846: ('Jayden Danns', 6),
 2000006104: ('Obed Nkambadio', 0),
 2000202178: ('Malcolm Jeng', 0),
 29186052: ("Matt O'Riley", 11),
 49034179: ('Anthony Caci', 6),
 2002071174: ('Adel Moussaoui', 0),
 2000065727: ('Frans Krätzig', 0),
 2000483445: ('Maxima Goffi', 0),
 2000259406: ('Boris Mamuzah Lum', 2),
 2000088490: ('Roony Bardghji', 10),
 2002096899: ('Mourad Bouchiba', 0),
 2002096904: ('Mathieu Biscay', 0),
 2000120348: ('Hamza Igamane', 0),
 98040383: ('Gregor Kobel', 0),
 2000048260: ('Alberto Costa', 10),
 2000094252: ('Beraldo', 1),
 2000027898: ('Shea Charles', 3),
 2000262615: ('El Hadji Malick Diouf', 15),
 2000030130: ('João Neves', 7),
 2000220048: ('Chema Andrés', 7),
 19377206: ('Luiz Henrique', 6),
 2000307251: ('Konstantinos Karetsas', 4),
 2000275657: ('Jay Robinson', 7),
 91187791: ('Nick Woltemade', 6),
 28124573: ('Levi Colwill', 0),
 2000058232: ('Chadi Riad', 2),
 43500245: ('Giovanni Fabbian', 3),
 12093353: ('Karim Konaté', 0),
 28124569: ('Tino Livramento', 0),
 2000053516: ('Adam Wharton', 0),
 2000015300: ('Jamie Gittens', 2),
 2000108691: ('Lewis Hall', 0),
 2000189871: ('Lewis Miley', 5)}


def test_genuine_lille_all43_canonical_names_counts_and_distance_comparison():
    packet = retained()
    assert packet['native_match_key'] == 136941
    actual = {}
    newcastle = []
    for row in packet['players']:
        child = bytes.fromhex(row['raw_child_hex'])
        count = decode_player_sprinting(child)['sprints']
        person = row['canonical_person_id']
        assert person not in actual
        actual[person] = (row['person_name'], count)
        if row['side_index'] == 1:
            newcastle.append((row, count, decode_player_running(child)['distance_metres'], _usage(child, 90)))
    assert actual == EXPECTED and len(actual) == 43
    assert len(newcastle) == 20
    assert sum(count > 0 for _, count, _, _ in newcastle) == 14
    assert sum(count == 0 for _, count, _, _ in newcastle) == 6
    by_name = {row['person_name']: (count, distance, usage) for row, count, distance, usage in newcastle}
    assert max(by_name, key=lambda name: by_name[name][0]) == 'El Hadji Malick Diouf'
    assert by_name['El Hadji Malick Diouf'][:2] == (15, 7905.45166015625)
    assert by_name['Konstantinos Karetsas'][:2] == (4, 13174.189453125)
    assert by_name['Alberto Costa'][:2] == (10, 12489.2685546875)
    kobel = by_name['Gregor Kobel']
    assert kobel[0] == 0 and kobel[1] == 3823.915283203125 and kobel[2]['minutes'] == 90
    unused = [(row, count, distance, usage) for row, count, distance, usage in newcastle
              if usage['appearance_state'] == 'unused_substitute']
    assert len(unused) == 5
    assert all(count == 0 and distance == 0.0 and usage['minutes'] is None
               for _, count, distance, usage in unused)


def test_narrow_wide_unsigned_count_has_no_scaling_or_255_sentinel():
    narrow = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    wide = b'\0' + narrow[1:5] + b'\0' * 4 + narrow[5:]
    assert decode_player_sprinting(narrow) == decode_player_sprinting(wide)
    for raw, offset in ((narrow, 190), (wide, 194)):
        for count in (0, 1, 127, 254, 255):
            changed = bytearray(raw)
            changed[offset] = count
            assert decode_player_sprinting(bytes(changed)) == {'sprints': count}
            assert decode_player_running(bytes(changed)) == decode_player_running(raw)


def test_incomplete_wrong_type_and_trailing_children_reject_before_publication():
    raw = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    for size in range(len(raw)):
        with pytest.raises(ValueError):
            decode_player_sprinting(raw[:size])
    with pytest.raises(ValueError, match='extent mismatch'):
        decode_player_sprinting(raw + b'\0')
    for invalid in (None, '', bytearray(raw), 0):
        with pytest.raises(ValueError, match='complete bytes child'):
            decode_player_sprinting(invalid)
    invalid_reference = b'\0' + b'\0' * 4 + b'\1' * 4 + raw[5:]
    with pytest.raises(ValueError, match='reference overflow'):
        decode_player_sprinting(invalid_reference)


def test_each_native_property_getter_exporter_and_wire_span_rejects_drift():
    spans = dict(NATIVE_SPANS)
    base = 0x100000000
    verify_native(lambda address, size: spans[address - base], base)
    for changed in spans:
        def read(address, size):
            expected = spans[address - base]
            return bytes([expected[0] ^ 1]) + expected[1:] if address - base == changed else expected
        with pytest.raises(ValueError, match='Unsupported native Sprints mapping'):
            verify_native(read, base)


def test_sprints_catalog_is_capture_free_and_retains_distance_provenance(monkeypatch):
    from fm_live_mcp import match_scope_query as module
    def unexpected_capture(*args, **kwargs):
        pytest.fail('Column discovery must not capture career memory')
    monkeypatch.setattr(module, 'capture_live', unexpected_capture)
    monkeypatch.setattr(module, 'scoped_capture', unexpected_capture)
    catalog = module.column_catalog()['retained_players']
    assert 'sprints' in catalog['columns']
    provenance = catalog['field_provenance']['sprints']
    assert provenance == sprinting_field_registry()['sprints']
    assert provenance['unit'] == 'count' and provenance['encoding'] == 'unsigned byte'
    assert provenance['official_property_label'] == 'Sprints'
    assert 'one retained fixture/player row' in provenance['scope']
    assert '0..255' in provenance['scope'] and 'no 255 sentinel' in provenance['scope']
    assert 'No speed/intensity threshold' in provenance['scope']
    assert 'Missing source or player row is unavailable, never zero' in provenance['missing_policy']
    assert catalog['field_provenance']['distance_metres'] == running_field_registry()['distance_metres']


def test_sql_and_scoped_response_preserve_count_zero_null_and_distance_metadata():
    from fm_live_mcp.match_scope_query import ScopedMatchQueries
    from fm_live_mcp.match_dataset import build_connection
    registry = {**running_field_registry(), **sprinting_field_registry()}
    capture = {'save': {}, 'action_field_provenance': registry,
               'fixtures': [{'native_match_key': 7, 'fixture': {'date': '2030-11-06'}}]}
    rows = [
        {'fixture_key': 7, 'stored_player_slot': 0, 'side_index': 1, 'sprints': 15,
         'distance_metres': 7905.45166015625, 'minutes': 56},
        {'fixture_key': 7, 'stored_player_slot': 1, 'side_index': 1, 'sprints': 0,
         'distance_metres': 3823.915283203125, 'minutes': 90},
        {'fixture_key': 7, 'stored_player_slot': 2, 'side_index': 1, 'sprints': 0,
         'distance_metres': 0.0, 'minutes': None, 'appearance_kind': 'unused_substitute'},
        {'fixture_key': 7, 'stored_player_slot': 3, 'side_index': 1, 'minutes': 30},
    ]
    db = build_connection(capture, retained_players=rows)
    expected = [(15, 7905.45166015625, 56, None), (0, 3823.915283203125, 90, None),
                (0, 0.0, None, 'unused_substitute'), (None, None, 30, None)]
    for table in ['retained_players', 'player_match_analysis']:
        actual = db.execute(f'SELECT sprints,distance_metres,minutes,appearance_kind FROM {table} ORDER BY stored_player_slot').fetchall()
        assert actual == expected
    db.close()
    query = ScopedMatchQueries(lambda *args, **kwargs: {'capture': capture, 'retained_players': rows},
                               epoch=lambda *args: 1)
    result = query.query(None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'],
                         fields={'retained_players': ['sprints', 'distance_metres', 'minutes', 'appearance_kind']})
    assert [tuple(r['row'][k] for k in ['sprints', 'distance_metres', 'minutes', 'appearance_kind']) for r in result['rows']] == expected
    assert result['metadata']['action_field_provenance'] == registry
    assert result['metadata']['action_field_provenance']['sprints']['unit'] == 'count'
    assert result['metadata']['action_field_provenance']['distance_metres']['unit'] == 'metres'
    empty = ScopedMatchQueries(lambda *args, **kwargs: {'capture': capture}, epoch=lambda *args: 1)
    assert empty.query(None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'],
                       fields={'retained_players': ['sprints']})['rows'] == []
