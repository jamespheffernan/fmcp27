"""Virtual roster null cast remains separate from actual-player event inputs."""
from pathlib import Path
import importlib.util
import struct
import sys

import pytest

from fm_live_mcp import committed_wage_payroll_core as payroll, virtual_identity, virtual, world
from test_committed_wage_payroll_core import Graph, BASE, image, base_service


def add_virtual(graph, cache=-1, aliases=1):
    primary = graph.alloc()
    graph.put(primary, '<Q', BASE+world.TYPES['virtual_player'][0])
    graph.put(primary+8, '<i', 0)
    graph.put(primary+0x14, '<h', cache)
    graph.put(primary+0x20, '<QIII', BASE+virtual_identity.PERSON_RVA, 1, 10001, 10001)
    graph.table('people', [graph.person, primary+0x20])
    graph.vector(graph.team+0x38, [graph.primary]+[primary]*aliases)
    return primary


@pytest.mark.parametrize('cache', [-1, 0, 32767])
def test_native_payroll_visits_virtual_null_cast_without_reading_generated_profile(image, monkeypatch, cache):
    graph = Graph(image)
    base_service(graph)
    primary = add_virtual(graph, cache)
    original = graph.read(primary, 64)
    entry = payroll._PayrollCPU._instruction
    visited = []
    read = graph.read

    def bounded(address, size):
        assert not address <= BASE+virtual.MANAGER_ROOT < address+size
        return read(address, size)

    def observe(self, vm, pc, size, user):
        if pc-self.base in (0xCA4A6C, 0xCA49DC):
            visited.append(pc-self.base)
        return entry(self, vm, pc, size, user)

    monkeypatch.setattr(payroll._PayrollCPU, '_instruction', observe)
    result = payroll.calculate(bounded, BASE, image, club=graph.club, lifetime=lambda: ('synthetic', 1))
    assert result.spending_signed32 == result.field_810 == result.field_814 == 1200
    assert visited.count(0xCA4A6C) == visited.count(0xCA49DC) == 1
    assert graph.read(primary, 64) == original


def test_native_payroll_keeps_virtual_aliases_and_matches_separate_whole_code(image):
    from _committed_wage_native_oracle import WholeNative
    graph = Graph(image)
    base_service(graph)
    add_virtual(graph, aliases=2)
    native = WholeNative(graph, BASE)
    value, fields = native.payroll()
    result = graph.run()
    assert (value, fields[0], fields[1]) == (result.spending_signed32, result.field_810, result.field_814) == (1200, 1200, 1200)
    assert 0xCA4A6C in native.native_calls and 0xCA49DC in native.native_calls


def test_old_payroll_refuses_same_valid_virtual_roster(image):
    path = Path(__file__).parent/'fixtures/committed-wage-payroll-before-virtual.py'
    spec = importlib.util.spec_from_file_location('fm_live_mcp.payroll_before_virtual', path)
    old = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = old
    spec.loader.exec_module(old)
    graph = Graph(image)
    base_service(graph)
    add_virtual(graph)
    with pytest.raises(ValueError, match='unsupported payroll roster primary'):
        old.calculate(graph.read, BASE, image, club=graph.club, lifetime=lambda: ('synthetic', 1))
    assert graph.run().spending_signed32 == 1200


@pytest.mark.parametrize('fault', ['player_slot', 'player_code', 'common_slot', 'primary_delta', 'person_membership'])
def test_invalid_virtual_binding_refuses_payroll(image, fault):
    graph = Graph(image)
    base_service(graph)
    primary = add_virtual(graph)
    if fault == 'player_slot':
        graph.put(BASE+virtual_identity.PERSON_RVA+0x6E0, '<Q', BASE+0xCA49DC)
    elif fault == 'player_code':
        graph.put(BASE+0xCA4A6C, '<II', 0xD2800020, 0xD65F03C0)
    elif fault == 'common_slot':
        graph.put(BASE+virtual_identity.PERSON_RVA+0x668, '<Q', BASE+0xCA4A6C)
    elif fault == 'primary_delta':
        graph.put(BASE+world.TYPES['virtual_player'][0]-0x18, '<q', 0x28)
    else:
        graph.put(primary+0x28, '<I', 0)
    with pytest.raises(ValueError):
        graph.run()


def test_final_callback_change_to_virtual_cast_refuses(image):
    graph = Graph(image)
    base_service(graph)
    add_virtual(graph)
    calls = 0

    def lifetime():
        nonlocal calls
        calls += 1
        if calls == 2:
            graph.put(BASE+virtual_identity.PERSON_RVA+0x6E0, '<Q', BASE+0xCA49DC)
        return ('synthetic', 1)

    with pytest.raises(ValueError):
        payroll.calculate(graph.read, BASE, image, club=graph.club, lifetime=lifetime)


def test_actual_player_event_validator_still_refuses_virtual(image):
    graph = Graph(image)
    primary = add_virtual(graph)
    with open(image[0], 'rb') as binary:
        cpu = payroll._PayrollCPU(world.ReadSet(graph.read), graph.read, BASE, binary, graph.finance, graph.club)
        try:
            with pytest.raises(ValueError, match='unsupported payroll roster primary'):
                cpu._primary(primary)
            # Exercise the real handler too: widening roster preflight must not
            # authorize a virtual primary at the distinct salary-event boundary.
            for index, value in enumerate((graph.finance, graph.club, primary)):
                cpu.vm.reg_write(payroll.arm.UC_ARM64_REG_X0+index, value)
            with pytest.raises(ValueError, match='unsupported payroll roster primary'):
                cpu._instruction(cpu.vm, BASE+0xE89018, 4, None)
        finally:
            cpu.close()
