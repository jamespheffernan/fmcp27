import gzip
import json
from pathlib import Path
import struct

import pytest


def retained():
    path = Path(__file__).parent / 'fixtures/retained_key_passes_lille_136941.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def decode(child):
    from fm_live_mcp.saved_match_player_final_third import decode_player_final_third
    return decode_player_final_third(child)


def test_catalog_publishes_exact_native_counter_scope_without_game_capture(monkeypatch):
    from fm_live_mcp import match_scope_query as module
    def unexpected_capture(*args, **kwargs):
        pytest.fail('Column discovery must not read career memory')
    monkeypatch.setattr(module, 'capture_live', unexpected_capture)
    monkeypatch.setattr(module, 'scoped_capture', unexpected_capture)
    catalog = module.column_catalog()['retained_players']
    assert 'open_play_final_third_passes' in catalog['columns']
    field = catalog['field_provenance']['open_play_final_third_passes']
    assert field['unit'] == 'count'
    assert field['encoding'] == 'signed int16, nonnegative counter profile'
    assert field['official_property_label'] == 'OpenPlayFinalThirdPasses'
    assert 'into-versus-within' in field['scope']
    assert field['independent_serialized_team_oracle'] is False
    assert 'not an entry count' in field['scope']
    assert 'negative' in field['missing_policy']


# Explicit prior same-fixture raw capture, not a newly refreshed live acceptance.
EXPECTED = {2000183134: ('Ewen Jaouen', 0),
 83283239: ('Tiago Santos', 7),
 49037684: ('Oumar Solet', 0),
 83282675: ('Alexsandro Ribeiro', 0),
 67211695: ('Théo Hernández', 11),
 2000182795: ('Archie Gray', 3),
 19375640: ('André', 7),
 2000014559: ('Ernest Poku', 13),
 28126241: ('Oscar Bobb', 12),
 2000107089: ('Matias Fernandez-Pardo', 15),
 2000191846: ('Jayden Danns', 2),
 2000006104: ('Obed Nkambadio', 0),
 2000202178: ('Malcolm Jeng', 0),
 29186052: ("Matt O'Riley", 6),
 49034179: ('Anthony Caci', 2),
 2002071174: ('Adel Moussaoui', 0),
 2000065727: ('Frans Krätzig', 0),
 2000483445: ('Maxima Goffi', 0),
 2000259406: ('Boris Mamuzah Lum', 1),
 2000088490: ('Roony Bardghji', 6),
 2002096899: ('Mourad Bouchiba', 0),
 2002096904: ('Mathieu Biscay', 0),
 2000120348: ('Hamza Igamane', 4),
 98040383: ('Gregor Kobel', 0),
 2000048260: ('Alberto Costa', 9),
 2000094252: ('Beraldo', 0),
 2000027898: ('Shea Charles', 1),
 2000262615: ('El Hadji Malick Diouf', 4),
 2000030130: ('João Neves', 6),
 2000220048: ('Chema Andrés', 7),
 19377206: ('Luiz Henrique', 13),
 2000307251: ('Konstantinos Karetsas', 6),
 2000275657: ('Jay Robinson', 5),
 91187791: ('Nick Woltemade', 1),
 28124573: ('Levi Colwill', 0),
 2000058232: ('Chadi Riad', 1),
 43500245: ('Giovanni Fabbian', 4),
 12093353: ('Karim Konaté', 0),
 28124569: ('Tino Livramento', 0),
 2000053516: ('Adam Wharton', 0),
 2000015300: ('Jamie Gittens', 6),
 2000108691: ('Lewis Hall', 0),
 2000189871: ('Lewis Miley', 3)}


def test_exact_lille_43_canonical_rows_and_distinct_progression_counters():
    from fm_live_mcp.live_match_players import _usage
    from fm_live_mcp.saved_match_player_progression import decode_player_progression
    from fm_live_mcp.saved_match_player_dribbling import decode_player_dribbling
    packet = retained()
    assert packet['native_match_key'] == 136941
    actual = {}
    newcastle = []
    for row in packet['players']:
        child = bytes.fromhex(row['raw_child_hex'])
        count = decode(child)['open_play_final_third_passes']
        person = row['canonical_person_id']
        assert person not in actual
        actual[person] = (row['person_name'], count)
        if row['side_index'] == 1:
            newcastle.append((row['person_name'], count, _usage(child, 90),
                              decode_player_progression(child)['progressive_passes'],
                              decode_player_dribbling(child)['dribbles_made']))
    assert actual == EXPECTED and len(actual) == 43
    assert len(newcastle) == 20 and sum(r[1] for r in newcastle) == 66
    assert sum(r[1] == 0 for r in newcastle) == 7
    by_name = {name: (value, usage, progressive, dribbles)
               for name, value, usage, progressive, dribbles in newcastle}
    assert (by_name['Luiz Henrique'][0], *by_name['Luiz Henrique'][2:]) == (13, 5, 3)
    assert (by_name['Chema Andrés'][0], *by_name['Chema Andrés'][2:]) == (7, 7, 1)
    assert (by_name['Beraldo'][0], *by_name['Beraldo'][2:]) == (0, 4, 0)
    assert by_name['Gregor Kobel'][0] == 0 and by_name['Gregor Kobel'][1]['minutes'] == 90
    unused = [r for r in newcastle if r[2]['appearance_state'] == 'unused_substitute']
    assert len(unused) == 5 and all(r[1] == 0 and r[2]['minutes'] is None for r in unused)


def test_narrow_wide_signed16_alignment_and_other_counters_unchanged():
    from fm_live_mcp.saved_match_player_progression import decode_player_progression
    from fm_live_mcp.saved_match_player_dribbling import decode_player_dribbling
    from fm_live_mcp.saved_match_player_sprinting import decode_player_sprinting
    narrow = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    wide = b'\0' + narrow[1:5] + b'\0' * 4 + narrow[5:]
    assert decode(narrow) == decode(wide)
    for raw, offset in [(narrow, 209), (wide, 213)]:
        for count in [0, 1, 255, 256, 32767]:
            changed = bytearray(raw)
            struct.pack_into('<h', changed, offset, count)
            assert decode(bytes(changed)) == {'open_play_final_third_passes': count}
            for old_decoder in [decode_player_progression, decode_player_dribbling, decode_player_sprinting]:
                assert old_decoder(bytes(changed)) == old_decoder(raw)


@pytest.mark.parametrize('count', [-1, -32768])
def test_negative_raw_count_has_no_invented_sentinel_or_zero_clamp(count):
    raw = bytearray.fromhex(retained()['players'][0]['raw_child_hex'])
    struct.pack_into('<h', raw, 209, count)
    with pytest.raises(ValueError, match='negative native final-third pass counter'):
        decode(bytes(raw))


def test_complete_typed_child_extent_width_and_reference_are_required():
    raw = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    for size in range(len(raw)):
        with pytest.raises(ValueError):
            decode(raw[:size])
    with pytest.raises(ValueError, match='extent mismatch'):
        decode(raw + b'\0')
    for invalid in [None, bytearray(raw), '', 0]:
        with pytest.raises(ValueError, match='complete bytes child'):
            decode(invalid)
    invalid_reference = b'\0' + b'\0' * 4 + b'\1' * 4 + raw[5:]
    with pytest.raises(ValueError, match='reference overflow'):
        decode(invalid_reference)


def test_each_native_name_getter_wire_and_producer_guard_rejects_drift():
    from fm_live_mcp.saved_match_player_final_third import NATIVE_SPANS, verify_native
    spans = dict(NATIVE_SPANS)
    base = 0x100000000
    verify_native(lambda address, size: spans[address - base], base)
    for changed in spans:
        def read(address, size):
            expected = spans[address - base]
            return bytes([expected[0] ^ 1]) + expected[1:] if address - base == changed else expected
        with pytest.raises(ValueError, match='Unsupported native OpenPlayFinalThirdPasses'):
            verify_native(read, base)


def test_scoped_projection_retains_native_units_zero_unknown_and_no_row_states():
    from fm_live_mcp.match_scope_query import ScopedMatchQueries
    from fm_live_mcp.match_dataset import build_connection
    from fm_live_mcp.saved_match_player_final_third import final_third_field_registry
    capture = {'save': {}, 'action_field_provenance': final_third_field_registry(),
               'fixtures': [{'native_match_key': 7, 'fixture': {'date': '2030-11-06'}}]}
    rows = [
        {'fixture_key': 7, 'side_index': 1, 'stored_player_slot': 0,
         'open_play_final_third_passes': 13, 'progressive_passes': 5, 'dribbles_made': 3, 'minutes': 60},
        {'fixture_key': 7, 'side_index': 1, 'stored_player_slot': 1,
         'open_play_final_third_passes': 0, 'minutes': 90},
        {'fixture_key': 7, 'side_index': 1, 'stored_player_slot': 2,
         'open_play_final_third_passes': 0, 'minutes': None, 'appearance_kind': 'unused_substitute'},
        {'fixture_key': 7, 'side_index': 1, 'stored_player_slot': 3, 'minutes': 30},
    ]
    expected = [(13, 60, None), (0, 90, None), (0, None, 'unused_substitute'), (None, 30, None)]
    db = build_connection(capture, retained_players=rows)
    for table in ['retained_players', 'player_match_analysis']:
        assert db.execute(f'SELECT open_play_final_third_passes,minutes,appearance_kind FROM {table} ORDER BY stored_player_slot').fetchall() == expected
    db.close()
    query = ScopedMatchQueries(lambda *args, **kwargs: {'capture': capture, 'retained_players': rows},
                               epoch=lambda *args: 1)
    page = query.query(None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'],
                       fields={'retained_players': ['open_play_final_third_passes', 'minutes', 'appearance_kind']})
    assert [tuple(r['row'][k] for k in ['open_play_final_third_passes', 'minutes', 'appearance_kind']) for r in page['rows']] == expected
    field = page['metadata']['action_field_provenance']['open_play_final_third_passes']
    assert field == final_third_field_registry()['open_play_final_third_passes'] and field['unit'] == 'count'
    empty = ScopedMatchQueries(lambda *args, **kwargs: {'capture': capture}, epoch=lambda *args: 1)
    assert empty.query(None, 's', 688, '2030-11-06', '2030-11-06', tables=['retained_players'],
                       fields={'retained_players': ['open_play_final_third_passes']})['rows'] == []
