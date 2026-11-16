import struct

import pytest

from fm_live_mcp.match_player_position import read_position
from fm_live_mcp.match_scope_query import column_catalog


@pytest.mark.parametrize('reference_bytes', [4, 8])
def test_reads_only_the_official_position_word(reference_bytes):
    child = bytearray(reference_bytes + 135)
    for property_offset, value in ((3, 2048), (8, 1049600), (105, 2048), (118, 256)):
        struct.pack_into('<BI', child, reference_bytes + property_offset, 2, value)
    assert read_position(child, reference_bytes) == {
        'stored_match_position_mask': 1049600, 'stored_match_position': 'M(CL)',
        'stored_match_position_state': 'named',
    }


def test_unmapped_mask_is_distinct_from_unrecognized_encoding():
    child = bytearray(17)
    struct.pack_into('<BI', child, 12, 2, 0xFFFFFFFF)
    assert read_position(child, 4) == {
        'stored_match_position_mask': 0xFFFFFFFF, 'stored_match_position': None,
        'stored_match_position_state': 'unmapped_mask',
    }
    child[12] = 9
    assert read_position(child, 4)['stored_match_position_mask'] is None
    with pytest.raises(ValueError, match='Incomplete'):
        read_position(child[:-1], 4)


def test_position_catalog_exposes_wire_source_and_limits():
    catalog = column_catalog()['retained_players']
    assert 'stored_match_position' in catalog['columns']
    assert 'participation separately' in catalog['field_provenance']['stored_match_position']['scope']



def test_real_substituted_player_with_minutes_and_zero_mask_survives_sql_projection():
    import gzip
    from pathlib import Path
    from fm_live_mcp.live_match_players import decode_retained_players
    from fm_live_mcp.match_dataset import build_connection

    frame = gzip.decompress((Path(__file__).parent / 'fixtures/player_actions_b142_132100.bin.gz').read_bytes())
    rows = decode_retained_players(frame, 132100)
    capture = {'fixtures': [{'native_match_key': 132100, 'fixture': {}}]}
    db = build_connection(capture, retained_players=rows)
    try:
        values = db.execute('SELECT person_index_word, minutes, stored_match_position_mask, '
                            'stored_match_position, stored_match_position_state FROM player_match_analysis '
                            'WHERE side_index=0 AND stored_player_slot IN (2,4) ORDER BY stored_player_slot').fetchall()
        assert values == [(37623, 90, 2097168, 'D(CR)', 'named'), (41999, 69, 0, None, 'zero_mask')]
    finally:
        db.close()
