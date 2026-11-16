"""Offline checks of the people-state tables (promise, player_attribute_history)."""
import json
import struct

from fm_live_mcp.fmdb.sources import people_state as PS


class _Image:
    """Plugin text stub: words at addresses."""

    def __init__(self, words):
        self.words = words

    def file_bytes(self, rva, length):
        return b''.join(struct.pack('<I', self.words.get(rva + i, 0xD503201F)) for i in range(0, length, 4))


def _bl(pc, target):
    return 0x94000000 | (((target - pc) // 4) & 0x3FFFFFF)


def _b(pc, target):
    return 0x14000000 | (((target - pc) // 4) & 0x3FFFFFF)


def test_title_id_follows_mov_movk_then_bl_to_the_translation_lookup():
    # kind 1 on the reference build: mov w1, #0x7f0d; movk w1, #7, lsl 16; bl 0x43DB8B8 -> 491277
    pc = 0x24421E0
    words = {pc: 0x52800001 | (0x7F0D << 5), pc + 4: 0x72A00001 | (7 << 5), pc + 8: _bl(pc + 8, 0x43DB8B8)}
    assert PS._title_id(_Image(words), pc) == 491277


def test_title_id_is_none_on_the_default_branch_and_on_conditional_code():
    pc = 0x2441000
    assert PS._title_id(_Image({pc: _b(pc, 0x2443BFC)}), pc) is None
    assert PS._title_id(_Image({pc: 0x54000040}), pc) is None          # b.eq: not a plain title load


def test_history_rows_name_the_47_native_attribute_fields():
    raw = bytes(range(10, 57))
    value = {'disa': False, 'atrs': [{'valu': 27858, 'atrs': {'data_hex': raw.hex()}, 'srTT': {'data_hex': '010e0e'}},
                                     {'valu': 28633, 'atrs': {'data_hex': raw.hex()}, 'srTT': {'data_hex': '010f0f'}}]}
    rows = PS._history_rows(47009, value, '2030-12-13')
    assert [r[:5] for r in rows] == [(47009, 0, 2, '2030-11', 27858), (47009, 1, 2, '2030-12', 28633)]
    named = json.loads(rows[0][7])
    assert len(named) == 47
    assert named['aerial_reach'] == 10 and named['one_on_ones'] == 20 and named['natural_fitness'] == 56
    assert rows[1][8] == '010f0f'
    assert PS.snapshot_month('2031-01-02', 18, 0) == '2029-08'


def test_history_rows_ignore_values_without_snapshots():
    assert PS._history_rows(1, None) == []
    assert PS._history_rows(1, {'atrs': 'x'}) == []


def test_promise_fields_cover_the_screen_row_keys():
    assert set(PS.PROMISE_LISTS.values()) == {'zWLF', 'vP71', 'tcoS', 'bfN3'}
    assert {'qEjH', 'Iv5a', 'PcSd', 'Pced', 'adP2', 'dxI2'} <= set(PS.PROMISE_FIELDS)


def test_tables_declare_own_club_policies():
    class _Engine:
        base = 0
    tables = {t.name: t for t in PS.tables(_Engine())}
    assert set(tables) == {'promise', 'player_attribute_history', 'squad_hierarchy', 'social_group',
                           'player_happiness_reason', 'player_concern'}
    for t in tables.values():
        assert t.manager['scope'] == 'own_club' and t.manager['own_club_column'] == 'club_idx'
        assert 'club_idx' in [c.name for c in t.columns]
    assert tables['promise'].invalidation == 'content'
    assert tables['player_attribute_history'].invalidation == 'append'
    assert tables['squad_hierarchy'].invalidation == 'content' and tables['social_group'].mode == 'lazy'


def test_tier_thresholds_are_those_of_the_sorting_code():
    # 0x225D89C: >= 0x2328 team leader, >= 0x1D4C highly influential, >= 0x1770 influential, else other
    assert PS.tier_of(9000) == 'team_leader' and PS.tier_of(8999) == 'highly_influential'
    assert PS.tier_of(7500) == 'highly_influential' and PS.tier_of(7499) == 'influential'
    assert PS.tier_of(6000) == 'influential' and PS.tier_of(5999) == 'other'
    assert PS.tier_of(None) is None
    assert set(PS.TIER_LISTS.values()) == {'team_leader', 'highly_influential', 'influential', 'other'}
    assert [g[1] for g in PS.SOCIAL_GROUPS.values()] == ['E3iL', 'E3iM', 'E3iN', 'E3iO']


def test_happiness_rows_skip_the_none_placeholder_and_add_the_playing_time_line():
    got = {'positives': [{'name': 'None', '2   ': -1}], 'negatives': [{'name': 'Unhappy at X', '2   ': 3}],
           'playing_time': 'Is concerned', 'playing_time_level': -20, 'happiness_level': -40, 'morale': 'Poor'}
    rows = PS._happiness_rows(7, got, 414)
    assert [r[:6] for r in rows] == [(7, 0, 'negative', 0, 'Unhappy at X', 3), (7, 1, 'playing_time', 0, 'Is concerned', None)]
    assert rows[1][6] == -20 and rows[0][7:] == (-40, 'Poor', 414)
