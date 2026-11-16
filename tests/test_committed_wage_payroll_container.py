"""The native rule getter receives NATIONAL_TEAM_CONTAINER, not NATION."""
from pathlib import Path
import importlib.util
import sys

import pytest

from fm_live_mcp import committed_wage_payroll_core as payroll, world
from test_committed_wage_payroll_core import Graph, BASE, image, base_service


def container_graph(image):
    graph = Graph(image)
    base_service(graph)
    container, gender_links, extension, group, season, rules = [graph.alloc() for _ in range(6)]
    graph.put(container, '<QIII', BASE+world.TYPES['national_team_container'][0], 0, 1001, 1001)
    graph.table('national_team_containers', [container])
    graph.put(graph.club+0xD8, '<Q', gender_links)
    graph.put(gender_links+0x110, '<Q', container)
    graph.put(container+0x170, '<Q', extension)
    graph.put(extension+0x128, '<Q', group)
    graph.put(group+0x38, '<Q', season)
    graph.put(season+0x1F0, '<Q', rules)
    # Exact non-generating route: native getter returns the retained null +78.
    graph.put(rules+0x78, '<Q', 0)
    return graph, container


def test_actual_container_route_matches_separate_whole_native_code(image):
    from _committed_wage_native_oracle import WholeNative
    graph, _ = container_graph(image)
    native = WholeNative(graph, BASE)
    expected, fields = native.payroll()
    result = graph.run()
    assert 0x13E798C in native.native_calls
    assert (expected, fields[0], fields[1]) == (result.spending_signed32, result.field_810, result.field_814) == (1200, 1200, 1200)


def test_old_nation_guard_refused_exact_container_source(image):
    path = Path(__file__).parent/'fixtures/committed-wage-payroll-before-container-owner.py'
    spec = importlib.util.spec_from_file_location('fm_live_mcp.payroll_before_container', path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    graph, _ = container_graph(image)
    with pytest.raises(ValueError, match='Unexpected native nation type'):
        old.calculate(graph.read, BASE, image, club=graph.club, lifetime=lambda: ('synthetic', 1))
    assert graph.run().spending_signed32 == 1200


@pytest.mark.parametrize('fault', ['nation_alias', 'index', 'native_id', 'canonical_slot'])
def test_near_valid_container_inputs_do_not_bypass_canonical_guard(image, fault):
    graph, container = container_graph(image)
    if fault == 'nation_alias':
        graph.put(container, '<Q', BASE+world.TYPES['nation'][0])
    elif fault == 'index':
        graph.put(container+8, '<I', 1)
    elif fault == 'native_id':
        graph.put(container+12, '<I', 0)
    else:
        graph.table('national_team_containers', [graph.club])
    with pytest.raises(ValueError):
        graph.run()


def test_late_container_identity_change_refuses(image):
    graph, container = container_graph(image)
    calls = 0

    def lifetime():
        nonlocal calls
        calls += 1
        if calls == 2:
            graph.put(container+12, '<I', 1002)
        return ('synthetic', 1)

    with pytest.raises(ValueError):
        payroll.calculate(graph.read, BASE, image, club=graph.club, lifetime=lifetime)
