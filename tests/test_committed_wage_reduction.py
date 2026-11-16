"""Synthetic career sources, original native selector oracle and actual v88 VM.

No process attach, game call or current payroll observation occurs here.
"""
from dataclasses import replace
from types import SimpleNamespace
import struct

import pytest

from fm_live_mcp import committed_wage_reduction as composed
from fm_live_mcp import committed_wage_offer_selection as selector
from fm_live_mcp import committed_wage_spending_core as reducer
from fm_live_mcp import players, world
from test_committed_wage_spending_core import BASE, Graph, add_offer, image
import test_committed_wage_offer_selection as selector_oracle


def career(image, combined=False):
    graph = Graph(image, combined)
    game, save, info, name = (graph.alloc() for _ in range(4))
    graph.put(BASE+world.GAME_ROOT, '<Q', game)
    graph.put(BASE+world.SAVE_ROOT, '<Q', save)
    graph.put(game, '<Q', BASE+world.TYPES['game'][0])
    graph.put(save, '<Q', BASE+world.TYPES['save'][0])
    graph.put(save+0x28, '<Q', name)
    graph.put(name, '<I', len(b'Synthetic wage career'))
    for i, byte in enumerate(b'Synthetic wage career\0'):
        graph.put(name+4+i, '<B', byte)
    graph.put(game+0x38, '<II', (2025<<16)|1, 270000)
    graph.put(game+0xc8, '<I', 42)
    graph.put(save+0x70, '<I', (2030<<16)|100)
    graph.put(game+0x58, '<Q', info)
    graph.vector(info, [])
    graph.manager = struct.unpack('<Q', graph.read(BASE+0x56a49f8, 8))[0]
    graph.vector(graph.manager+0x20, [])
    return graph


def scope(graph):
    record, identity = world.loaded(graph.read, BASE)
    return composed.FinancialLifetime(
        (4242, '/synthetic/fm', 'synthetic-start-identity', players.VERSION,
         'com.SportsInteractive.FootballManager27', 'synthetic-executable-stamp'),
        graph.image, players.macho_uuid(graph.read(BASE, 16384)), BASE, identity,
        record['save_count'], record['current_date'],
        (graph.club, *struct.unpack('<III', graph.read(graph.club+8, 12))))


def run(graph, lifetime=None):
    return composed.calculate(graph.read, BASE, graph.image, club=graph.club,
                              lifetime=lifetime or (lambda: scope(graph)))


def native_selected(graph, monkeypatch):
    # The frozen oracle executes original1826544/1826744, with their genuine
    # retained virtual getter bytes. Only source transport is flattened here.
    memory = {}
    for page, raw in {**graph.static, **graph.pages}.items():
        memory.update((page+i, value) for i, value in enumerate(raw))
    for offset, raw in selector_oracle.NATIVE.items():
        memory.update((BASE+offset+i, value) for i, value in enumerate(raw))
    monkeypatch.setattr(selector_oracle, 'BASE', BASE)
    source = SimpleNamespace(data=memory, manager=graph.manager, team=graph.team)
    return selector_oracle.native_selection(source)


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('trade,expected', [(True, 1200), (False, 1500)])
def test_real_selector_and_reducer_compose_with_whole_native_selector_oracle(image, monkeypatch, combined, trade, expected):
    graph = career(image, combined)
    offer = add_offer(graph, trade=trade)
    graph.vector(graph.manager+0x20, [offer])
    result = run(graph)
    assert tuple(row.address for row in result.selection.selected) == native_selected(graph, monkeypatch) == (offer,)
    assert result.reduction.field_818 == result.reduction.returned_signed32 == expected
    assert result.first_team == graph.team
    assert result.club_identity == (graph.club, 0, 20, 20)
    assert result.reduction.selected_offer_addresses == (offer,)
    assert graph.read(offer+8, 4) == struct.pack('<I', 1)


def cached(graph, values):
    header = graph.alloc()
    graph.put(graph.ext+0x20, '<Q', header)
    begin = graph.alloc()
    for i, value in enumerate(values):
        graph.put(begin+4*i, '<i', value)
    graph.put(header, '<QQQ', begin, begin+4*len(values), begin+4*len(values))
    return begin


def test_cache_authority_duplicate_order_and_omissions_drive_actual_arithmetic(image, monkeypatch):
    graph = career(image)
    first = add_offer(graph, trade=True)
    omitted = add_offer(graph, trade=True)
    graph.vector(graph.manager+0x20, [first, omitted, 0, first])
    cached(graph, [3, -1, 99, 0, 3, 2])
    result = run(graph)
    addresses = tuple(row.address for row in result.selection.selected)
    assert addresses == native_selected(graph, monkeypatch) == (first, first, first)
    assert [row.manager_slot for row in result.selection.selected] == [3, 0, 3]
    assert [row.source_ordinal for row in result.selection.selected] == [0, 3, 4]
    assert result.reduction.field_818 == 3600


def test_empty_cache_is_genuine_zero_offer_selection_with_nonzero_roster_classification(image, monkeypatch):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    graph.vector(graph.team+0x38, [graph.primary])
    graph.vector(graph.manager+0x20, [offer])
    cached(graph, [])
    result = run(graph)
    assert tuple(result.selection.selected) == native_selected(graph, monkeypatch) == ()
    assert result.selection.source == 'club_cached_indices'
    assert result.reduction.field_818 == 0 and result.reduction.field_820 == 1200


@pytest.mark.parametrize('mutation', ['selector_cache', 'wage', 'date', 'save_count', 'club', 'service', 'padding'])
def test_final_callback_cannot_invalidate_either_stage_silently(image, mutation):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    graph.vector(graph.manager+0x20, [offer])
    cache = cached(graph, [0])
    assert run(graph).reduction.field_818 == 1200
    calls = 0
    def lifetime():
        nonlocal calls
        calls += 1
        value = scope(graph)
        if calls == 3:
            address, fmt, changed = {
                'selector_cache': (cache, '<i', -1),
                'wage': (graph.contract+0x20, '<i', 1300),
                'date': (BASE+world.CURRENT_DATE, '<I', (2030<<16)|101),
                'save_count': (value.world_identity[0]+0xc8, '<I', 43),
                'club': (graph.club+0xc, '<I', 21),
                'service': (BASE+0x56d2c68, '<Q', 0),
                'padding': (graph.finance+0x900, '<B', 254),
            }[mutation]
            graph.put(address, fmt, changed)
        return value
    if mutation == 'padding':
        assert run(graph, lifetime).reduction.field_818 == 1200
    else:
        with pytest.raises(ValueError, match='changed'):
            run(graph, lifetime)
    assert calls == 3


@pytest.mark.parametrize('field', ['process_identity', 'plugin_uuid', 'world_identity', 'save_count', 'current_date', 'club_identity'])
def test_each_caller_owned_lifetime_dimension_remains_bound(image, field):
    graph = career(image)
    original = scope(graph)
    changes = {
        'process_identity': (4242, '/synthetic/fm', 'other-start', players.VERSION,
                             'com.SportsInteractive.FootballManager27', 'synthetic-executable-stamp'),
        'plugin_uuid': bytes(16), 'world_identity': ('other',), 'save_count': 43,
        'current_date': '2030-04-11', 'club_identity': (graph.club, 0, 21, 21),
    }
    calls = 0
    def lifetime():
        nonlocal calls
        calls += 1
        return original if calls == 1 else replace(original, **{field: changes[field]})
    with pytest.raises(reducer.SourceUnavailable, match='lifetime changed'):
        run(graph, lifetime)


def test_callback_assertion_boolean_cannot_stand_for_full_context(image):
    graph = career(image)
    with pytest.raises(reducer.SourceUnavailable, match='full caller-owned'):
        run(graph, lambda: True)


@pytest.mark.parametrize('mode', [0, 1, 2, 3, 128, 255])
@pytest.mark.parametrize('index,expected', [(0, 1200), (-1, 0), (9, 0)])
def test_native_resolved_person_overlay_is_carried_into_reducer_without_source_write(image, monkeypatch, mode, index, expected):
    from fm_live_mcp import virtual_identity
    graph = career(image)
    offer = add_offer(graph, trade=True)
    virtual = graph.alloc()
    person = virtual+0x20
    graph.put(virtual, '<Q', BASE+world.TYPES['virtual_player'][0])
    graph.put(person, '<QiI', BASE+virtual_identity.PERSON_RVA, index, 0xffffffff)
    graph.put(offer+0x38, '<Q', person)
    graph.put(BASE+0x56d34e0, '<B', mode)
    graph.vector(graph.manager+0x20, [offer])
    result = run(graph)
    assert tuple(row.address for row in result.selection.selected) == native_selected(graph, monkeypatch)
    assert result.selection.selected[0].person_address == (graph.person if index == 0 else 0)
    assert result.reduction.field_818 == expected
    assert struct.unpack('<Q', graph.read(offer+0x38, 8))[0] == person


def test_selection_needing_generation_never_reduces_earlier_accepted_offers(image, monkeypatch):
    graph = career(image)
    accepted = add_offer(graph, trade=True)
    unknown = add_offer(graph, trade=True)
    club, team, ext = (graph.alloc() for _ in range(3))
    graph.put(club, '<QIII', BASE+world.TYPES['club'][0], 1, 21, 21)
    graph.put(team, '<QIII', BASE+world.TYPES['team'][0], 1, 31, 31)
    graph.put(team+0x30, '<Q', club)
    graph.put(club+0x100, '<Q', ext)
    graph.vector(club+0x18, [team])
    graph.table('clubs', [graph.club, club])
    graph.table('teams', [graph.team, team])
    graph.put(unknown+0x40, '<Q', team)
    graph.put(unknown+0x50, '<Q', 0)
    graph.put(unknown+0x8e, '<B', 0)
    graph.vector(graph.manager+0x20, [accepted, unknown])
    # Prime only selector transport pages for the full native oracle.
    selected = selector.select_offers(graph.read, BASE, graph.team)
    assert selected.state == 'unavailable' and selected.selected is None
    assert native_selected(graph, monkeypatch) == 'generation'
    called = []
    def forbidden_reduction(*args, **kwargs):
        called.append(True)
        raise AssertionError('partial native input selection reached financial arithmetic')
    monkeypatch.setattr(reducer, 'calculate', forbidden_reduction)
    with pytest.raises(reducer.SourceUnavailable, match='selection unavailable'):
        run(graph)
    assert called == []


def test_actual_first_team_is_derived_instead_of_accepting_a_caller_selection(image):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    graph.vector(graph.manager+0x20, [offer])
    graph.put(graph.team+0x30, '<Q', 0)
    with pytest.raises(reducer.SourceUnavailable, match='first TEAM owner'):
        run(graph)


def test_empty_native_club_team_list_is_distinct_from_missing_context(image):
    graph = career(image)
    graph.vector(graph.club+0x18, [])
    result = run(graph)
    assert result.first_team == 0 and result.selection.selected == ()
    assert (result.reduction.field_818, result.reduction.field_81c,
            result.reduction.field_820, result.reduction.field_824) == (0, 0, 0, 0)


@pytest.mark.parametrize('corruption', ['uuid', 'world', 'date', 'count', 'club'])
def test_initial_context_must_match_actual_typed_source(image, corruption):
    graph = career(image)
    value = scope(graph)
    altered = {
        'uuid': {'plugin_uuid': bytes(16)},
        'world': {'world_identity': ('another-career',)},
        'date': {'current_date': '2030-04-11'},
        'count': {'save_count': 43},
        'club': {'club_identity': (graph.club, 0, 22, 22)},
    }[corruption]
    with pytest.raises(reducer.SourceUnavailable, match='changed'):
        run(graph, lambda: replace(value, **altered))


def second_club_team(graph):
    club, team, ext = (graph.alloc() for _ in range(3))
    graph.put(club, '<QIII', BASE+world.TYPES['club'][0], 1, 21, 21)
    graph.put(team, '<QIII', BASE+world.TYPES['team'][0], 1, 31, 31)
    graph.put(team+0x30, '<Q', club)
    graph.put(club+0x100, '<Q', ext)
    graph.vector(club+0x18, [team])
    graph.table('clubs', [graph.club, club])
    graph.table('teams', [graph.team, team])
    return team


def test_selected_alternate_cache_effect_is_visible_only_in_local_reducer_source(image, monkeypatch):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    source = second_club_team(graph)
    graph.put(offer+0x40, '<Q', source)
    graph.vector(graph.manager+0x20, [offer])
    real_calculate = reducer.calculate
    observed = []
    def observe(read, *args, **kwargs):
        observed.append(struct.unpack('<Q', read(offer+0x48, 8))[0])
        return real_calculate(read, *args, **kwargs)
    monkeypatch.setattr(reducer, 'calculate', observe)
    result = run(graph)
    assert tuple(row.address for row in result.selection.selected) == native_selected(graph, monkeypatch) == (offer,)
    assert result.reduction.field_818 == -1200
    assert observed == [source]
    assert graph.read(offer+0x48, 8) == bytes(8)


def test_final_selector_alternate_cache_drift_cannot_hide_behind_local_overlay(image):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    source = second_club_team(graph)
    graph.put(offer+0x40, '<Q', source)
    graph.vector(graph.manager+0x20, [offer])
    assert run(graph).reduction.field_818 == -1200
    calls = 0
    def lifetime():
        nonlocal calls
        calls += 1
        value = scope(graph)
        if calls == 3:
            graph.put(offer+0x48, '<Q', source)
        return value
    with pytest.raises(ValueError, match='changed'):
        run(graph, lifetime)
    assert calls == 3


def test_missing_full_service_does_not_turn_valid_selection_into_a_financial_answer(image):
    graph = career(image)
    offer = add_offer(graph, trade=True)
    graph.vector(graph.manager+0x20, [offer])
    assert run(graph).reduction.field_818 == 1200
    graph.put(BASE+0x56d2c68, '<Q', 0)
    with pytest.raises(reducer.SourceUnavailable, match='full finance service root'):
        run(graph)
    assert struct.unpack('<4i', graph.read(graph.finance+0x818, 16)) == (91, 92, 93, 94)


def test_composed_api_has_no_caller_provided_offer_or_total_shortcut(image):
    graph = career(image)
    with pytest.raises(TypeError, match='unexpected keyword'):
        composed.calculate(graph.read, BASE, graph.image, club=graph.club,
                           lifetime=lambda: scope(graph), selected_offers=(), field_818=999)
