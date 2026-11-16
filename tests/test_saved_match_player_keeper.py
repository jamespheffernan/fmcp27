import pytest
import json
from pathlib import Path
from fm_live_mcp import saved_match_player_keeper as keeper
from fm_live_mcp import saved_match_statistics_wire as wire


def child(mode=2):
    width = 4 if mode == 2 else 8
    base = 1 + width + sum((2,5,5,8,4,4,4,4,12,2,1,15,5,4,6,3,3,3,2,2,1,1,8,5,8,5,8)) + sum((1,4,4,16,4,12,9,6,4,4,2,2,2,2,2,2,4,1))
    raw = bytearray(base + 6); raw[0] = mode
    assert wire.player(bytes(raw), 0)['end'] == len(raw)
    return raw


def test_independent_counts_total_and_genuine_zero():
    raw = child(); raw[50:53] = bytes((2,4,1))
    assert keeper.decode_player_keeper(bytes(raw)) == dict(saves_held=2,saves_parried=4,saves_tipped=1,total_saves=7)
    assert set(keeper.decode_player_keeper(bytes(child())).values()) == {0}


def test_wide_person_reference_and_native_total_byte_mask():
    raw = child(0); raw[54:57] = bytes((255,2,1))
    assert keeper.decode_player_keeper(bytes(raw)) == dict(saves_held=255,saves_parried=2,saves_tipped=1,total_saves=2)


def test_incomplete_and_trailing_children_fail_closed():
    raw = bytes(child())
    for end in range(len(raw)):
        with pytest.raises(ValueError): keeper.decode_player_keeper(raw[:end])
    with pytest.raises(ValueError, match='extent'): keeper.decode_player_keeper(raw+b'\0')


def test_registry_has_official_names_and_no_psxg_claim():
    fields = keeper.field_registry()
    assert fields['saves_held']['property_key'] == '0x65636333'
    assert fields['total_saves']['native_expression'] == '(saves_held+saves_parried+saves_tipped)&255'
    assert len(fields) == 4


def test_actual_arsenal_cup_active_huber_unused_kobel_and_opponent_identity():
    packet = json.loads((Path(__file__).parent/'fixtures/keeper_cup_136159.json').read_text())
    rows = {row['name']: row for row in packet['rows']}
    expected = {'Silas Huber': (2000111044,90,(2,4,0,6)),
                'Gregor Kobel': (98040383,None,(0,0,0,0)),
                'Samuel Soares': (83257052,90,(1,0,2,3))}
    for name,(identity,minutes,counts) in expected.items():
        row = rows[name]
        assert row['canonical_person_id'] == identity and row['minutes'] == minutes
        decoded = keeper.decode_player_keeper(bytes.fromhex(row['raw_child_hex']))
        assert tuple(decoded.values()) == counts
        unused = bool(row['source']['flags5c'] & 32) and row['source']['on_minute'] == 0
        assert unused == (name == 'Gregor Kobel')
