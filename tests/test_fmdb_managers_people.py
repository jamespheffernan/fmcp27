"""People-side manager tables (fmdb/sources/managers_people.py, fmdb/mgr_walk_people.py), offline."""
from __future__ import annotations

from collections import Counter

from fm_live_mcp.fmdb import mgr_walk_people as MW
from fm_live_mcp.fmdb.sources import MANAGER_SCOPES, managers_people

LANE = {'INTERACTION_MANAGER', 'MORALE_MANAGER', 'DISPUTE_MANAGER', 'DYNAMICS_PIVOTAL_MOMENTS_MANAGER',
        'TEAM_TALK_MANAGER', 'TEAM_BLEND_MANAGER', 'AWOL_MANAGER', 'PERSON_PROGRESSION_MANAGER', 'INJURY_MANAGER',
        'REGENERATION_MANAGER', 'RETIREMENT_MANAGER', 'AWARD_MANAGER', 'HALL_OF_FAME_MANAGER',
        'ACHIEVEMENTS_MANAGER', 'OFFICIAL_STATS_MANAGER', 'SIMULATED_STATS_MANAGER', 'STATS_OUTPUT_MANAGER'}


def test_every_lane_manager_is_declared_once_with_its_root_and_size():
    names = [m.name for m in MW.MANAGERS]
    assert set(names) == LANE and len(names) == len(LANE)
    assert len({m.root for m in MW.MANAGERS}) == len(LANE)
    for m in MW.MANAGERS:
        assert 8 <= m.size <= 0x200 and m.size % 8 == 0, m.name
        offsets = list(m.vectors) + list(m.maps) + list(m.pointers)
        assert len(offsets) == len(set(offsets)), m.name
        # containers sit after the vtables and the id, and inside the allocation
        assert all(0x18 <= o and o + (8 if o in m.pointers else 24) <= m.size for o in offsets), m.name
    # managers the world constructor allocates with only vtables and id
    assert {m.name for m in MW.MANAGERS if m.size <= 0x18} == {
        'TEAM_BLEND_MANAGER', 'PERSON_PROGRESSION_MANAGER', 'STATS_OUTPUT_MANAGER'}


def test_rtti_names_are_demangled_only_for_plain_and_nested_forms():
    assert MW._demangle_simple('15YEAR_AWARD_DATA') == 'YEAR_AWARD_DATA'
    assert MW._demangle_simple('N2db5AWARDE') == 'db::AWARD'
    assert MW._demangle_simple('N2db23PLAYER_HEIGHTS_TEMPLATEE') == 'db::PLAYER_HEIGHTS_TEMPLATE'
    templ = 'N2db14OBJECT_STORAGEINS_19RETIRED_PERSON_DATAEiEE'
    assert MW._demangle_simple(templ) == templ           # templates stay as stored
    assert MW._demangle_simple('') == ''


class _Engine:
    base = 0


def test_tables_declare_columns_policies_and_content_invalidation():
    tabs = {t.name: t for t in managers_people.tables(_Engine())}
    assert set(tabs) == {'people_manager', 'people_manager_container', 'people_manager_element',
                         'interaction_item', 'award_schedule', 'hall_of_fame_entry', 'injury_case',
                         'retirement_entry'}
    for t in tabs.values():
        cols = [c.name for c in t.columns]
        assert len(cols) == len(set(cols)), t.name
        assert t.build_mode == 'lazy' and t.refresh == 'content' and callable(t.fingerprint), t.name
        assert t.manager['scope'] in MANAGER_SCOPES and t.manager.get('reason'), t.name
        for col in t.manager.get('own_club_columns', ()):
            assert col in cols, (t.name, col)
    scopes = Counter(t.manager['scope'] for t in tabs.values())
    assert tabs['interaction_item'].manager['scope'] == 'own_club'
    assert tabs['hall_of_fame_entry'].manager['scope'] == 'public'
    assert tabs['award_schedule'].manager['scope'] == 'public'
    assert scopes['never'] == 4
    # the item layout stays inside the bytes read per item
    assert all(off + {'<I': 4, '<Q': 8, '<i': 4, '<H': 2, '<B': 1}[fmt] <= managers_people.ITEM_SIZE
               for off, fmt in managers_people.ITEM.values())


def test_map_header_check():
    m = MW.BY_NAME['TEAM_TALK_MANAGER']
    obj = 0x1000
    empty = MW._map(m, obj, (obj + 8).to_bytes(8, 'little') + bytes(16), 0)
    assert empty.status == 'empty' and empty.count == 0
    full = MW._map(m, obj, (0x5000).to_bytes(8, 'little') + (0x5000).to_bytes(8, 'little') +
                   (1).to_bytes(8, 'little'), 0)
    assert full.status == 'ok' and full.count == 1
    bad = MW._map(m, obj, bytes(8) + (0x5000).to_bytes(8, 'little') + bytes(8), 0)
    assert bad.status.startswith('invalid')
