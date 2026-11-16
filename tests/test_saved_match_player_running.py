import gzip
import json
import math
from pathlib import Path
import struct

import pytest

from fm_live_mcp.saved_match_player_running import (
    NATIVE_SPANS, decode_player_running, running_field_registry, verify_native,
)
from fm_live_mcp.live_match_players import _usage


def retained():
    path = Path(__file__).parent / 'fixtures/retained_key_passes_lille_136941.json.gz'
    return json.loads(gzip.decompress(path.read_bytes()))


def test_genuine_lille_all43_player_rows_and_newcastle_census():
    fixture = retained()
    assert fixture['native_match_key'] == 136941
    rows = fixture['players']
    assert len(rows) == 43
    decoded = []
    for row in rows:
        child = bytes.fromhex(row['raw_child_hex'])
        value = decode_player_running(child)['distance_metres']
        assert math.isfinite(value) and value >= 0
        if row['side_index'] == 1:
            decoded.append((row, value, _usage(child, 90)))
    assert len(decoded) == 20
    assert sum(value > 0 for _, value, _ in decoded) == 15
    unused = [(row, value, usage) for row, value, usage in decoded if value == 0]
    assert len(unused) == 5
    assert {row['person_name'] for row, _, _ in unused} == {
        'Levi Colwill', 'Karim Konaté', 'Tino Livramento', 'Adam Wharton', 'Lewis Hall',
    }
    assert all(usage['appearance_state'] == 'unused_substitute' and usage['minutes'] is None
               for _, _, usage in unused)
    by_name = {row['person_name']: value for row, value, _ in decoded}
    # Same-scope fresh retained readback, not values inferred from tracking or season stats.
    assert by_name['Konstantinos Karetsas'] == 13174.189453125
    assert by_name['Chema Andrés'] == 12508.89453125
    assert by_name['Alberto Costa'] == 12489.2685546875
    assert max(by_name, key=by_name.get) == 'Konstantinos Karetsas'


def test_wide_reference_and_zero_are_unscaled_metres():
    narrow = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    wide = b'\0' + narrow[1:5] + b'\0' * 4 + narrow[5:]
    assert decode_player_running(narrow) == decode_player_running(wide)
    for raw, offset in ((narrow, 140), (wide, 144)):
        changed = bytearray(raw)
        struct.pack_into('<f', changed, offset, 0)
        assert decode_player_running(bytes(changed)) == {'distance_metres': 0.0}
        struct.pack_into('<f', changed, offset, 12345.5)
        assert decode_player_running(bytes(changed)) == {'distance_metres': 12345.5}


@pytest.mark.parametrize('invalid', [-1.0, float('inf'), -float('inf'), float('nan')])
def test_invalid_distance_never_becomes_zero(invalid):
    raw = bytearray.fromhex(retained()['players'][0]['raw_child_hex'])
    struct.pack_into('<f', raw, 140, invalid)
    with pytest.raises(ValueError, match='Invalid stored player distance'):
        decode_player_running(bytes(raw))


def test_child_extent_and_type_are_checked_before_publication():
    raw = bytes.fromhex(retained()['players'][0]['raw_child_hex'])
    for size in range(len(raw)):
        with pytest.raises(ValueError):
            decode_player_running(raw[:size])
    with pytest.raises(ValueError, match='extent mismatch'):
        decode_player_running(raw + b'\0')
    for invalid in (None, '', bytearray(raw), 0):
        with pytest.raises(ValueError, match='complete bytes child'):
            decode_player_running(invalid)


def test_every_native_field_key_scale_and_wire_guard_rejects_drift():
    spans = dict(NATIVE_SPANS)
    base = 0x100000000
    verify_native(lambda address, size: spans[address - base], base)
    for changed in spans:
        def read(address, size):
            expected = spans[address - base]
            return bytes([expected[0] ^ 1]) + expected[1:] if address - base == changed else expected
        with pytest.raises(ValueError, match='Unsupported native DistanceRan mapping'):
            verify_native(read, base)


def test_sql_and_public_scoped_query_preserve_unused_missing_and_field_units():
    from fm_live_mcp.match_data_query import MatchDataQueries
    from fm_live_mcp.match_dataset import build_connection
    fixture = {'date': '2030-11-06', 'home_team': {'native_id': 858},
               'away_team': {'native_id': 688}, 'competition': {'native_id': 1301394}}
    capture = {'save': {}, 'fixtures': [{'native_match_key': 136941, 'fixture': fixture}],
               'action_field_provenance': running_field_registry()}
    rows = [
        {'fixture_key': 136941, 'side_index': 1, 'stored_player_slot': 0,
         'person_index_word': 1, 'distance_metres': 12345.5, 'minutes': 90},
        {'fixture_key': 136941, 'side_index': 1, 'stored_player_slot': 1,
         'person_index_word': 2, 'distance_metres': 0.0, 'minutes': None,
         'appearance_kind': 'unused_substitute'},
        {'fixture_key': 136941, 'side_index': 1, 'stored_player_slot': 2,
         'person_index_word': 3, 'minutes': 30},
    ]
    db = build_connection(capture, retained_players=rows)
    assert db.execute('select distance_metres,minutes,appearance_kind from retained_players order by stored_player_slot').fetchall() == [
        (12345.5, 90, None), (0.0, None, 'unused_substitute'), (None, 30, None),
    ]
    assert db.execute('select distance_metres from player_match_analysis order by stored_player_slot').fetchall() == [(12345.5,), (0.0,), (None,)]
    db.close()
    data = {'capture': capture, 'retained_players': rows}
    query = MatchDataQueries(capture=lambda *args, **kwargs: data, epoch=lambda *args: 'epoch')
    page = query.query(None, 's', ['ref'], 'retained_players', fields=['distance_metres', 'minutes', 'appearance_kind'])
    assert page['rows'] == [
        {'distance_metres': 12345.5, 'minutes': 90, 'appearance_kind': None},
        {'distance_metres': 0.0, 'minutes': None, 'appearance_kind': 'unused_substitute'},
        {'distance_metres': None, 'minutes': 30, 'appearance_kind': None},
    ]
    assert page['metadata']['action_field_provenance']['distance_metres']['unit'] == 'metres'
    empty = MatchDataQueries(capture=lambda *args, **kwargs: {'capture': capture}, epoch=lambda *args: 'epoch')
    assert empty.query(None, 's', ['ref'], 'retained_players', fields=['distance_metres'])['rows'] == []
    assert running_field_registry()['distance_metres']['independent_serialized_team_oracle'] is False
