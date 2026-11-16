"""One coherent owned VM; amounts follow original native common-tail inputs."""
from dataclasses import replace
from pathlib import Path
import struct
import sys

import pytest

from fm_live_mcp import committed_wage_total as total, players, world
from test_committed_wage_payroll_core import Graph, BASE, image, base_service
from test_committed_wage_spending_core import add_offer
from test_committed_wage_reduction import scope


def career(image):
    graph = Graph(image)
    base_service(graph)
    graph.put(graph.contract+0x48, '<I', (2031<<16)|100)
    game, save, info, name = [graph.alloc() for _ in range(4)]
    graph.put(BASE+world.GAME_ROOT, '<Q', game)
    graph.put(BASE+world.SAVE_ROOT, '<Q', save)
    graph.put(game, '<Q', BASE+world.TYPES['game'][0])
    graph.put(save, '<Q', BASE+world.TYPES['save'][0])
    graph.put(save+0x28, '<Q', name)
    text = b'Synthetic combined wage career'
    graph.put(name, '<I', len(text))
    for i, byte in enumerate(text+b'\0'):
        graph.put(name+4+i, '<B', byte)
    graph.put(game+0x38, '<II', (2025<<16)|1, 270000)
    graph.put(game+0xC8, '<I', 42)
    graph.put(save+0x70, '<I', (2030<<16)|100)
    graph.put(game+0x58, '<Q', info)
    graph.vector(info, [])
    graph.manager = struct.unpack('<Q', graph.read(BASE+0x56A49F8, 8))[0]
    graph.vector(graph.manager+0x20, [])
    graph.human = graph.alloc()
    graph.put(graph.human, '<Q', BASE+0x55AC480)
    graph.put(graph.human+0x548, '<QIII', BASE+0x55AD820, 1, 8001, 8001)
    graph.put(graph.team+0x80, '<Q', graph.human)
    graph.table('people', [graph.person, graph.human+0x548])
    graph.vector(graph.human+0x218, [])
    graph.vector(graph.human+0x200, [])
    return graph


def run(graph, lifetime=None):
    return total.calculate(graph.read, BASE, graph.image, club=graph.club,
                           lifetime=lifetime or (lambda: scope(graph)))


def original_common_tail(graph):
    # Separate oracle executes original v138 and original selector too. Only
    # the synthetic graph and original disk source are shared with production.
    from _committed_wage_native_oracle import WholeNative
    native = WholeNative(graph, BASE)
    spans = [(at, at+n, digest) for at, n, digest in total.owner.SOURCE]
    spans += [(0x1300058, 0x1300060, None), (0x1300074, 0x1300088, None)]
    import hashlib
    with open(graph.image[0], 'rb') as image_file:
        for at, end, digest in spans:
            image_file.seek(total.ffp.ARM_SLICE+at)
            raw = image_file.read(end-at)
            assert digest is None or hashlib.sha256(raw).hexdigest() == digest
            native.allowed[at] = (end, raw)
    native.run(0xE830E4, graph.finance, graph.club, 0)
    native.vm.reg_write(total.arm.UC_ARM64_REG_X19, graph.club)
    native.vm.reg_write(total.arm.UC_ARM64_REG_X20, 1)
    native.vm.reg_write(total.arm.UC_ARM64_REG_X21, graph.finance)
    native.vm.reg_write(total.arm.UC_ARM64_REG_SP, 0x70100000)
    native.vm.emu_start(BASE+0xEAEC2C, BASE+0xEAEC88, count=600000)
    assert native.vm.reg_read(total.arm.UC_ARM64_REG_PC) == BASE+0xEAEC88
    value = struct.unpack('<i', struct.pack('<I', native.vm.reg_read(total.arm.UC_ARM64_REG_X21)&0xFFFFFFFF))[0]
    assert 0x1FEBC8C in native.native_calls and 0x1826544 in native.native_calls
    return value, struct.unpack('<6i', native.vm.mem_read(graph.finance+0x810, 24))


@pytest.mark.parametrize('wage', [0, 1, 1200, 1701, 2147483647])
def test_recomputed_total_matches_original_common_tail_and_v138_not_stale_cache(image, wage):
    graph = career(image)
    graph.put(graph.finance+0x810, '<2i', 999999, -1001)
    graph.put(graph.contract+0x20, '<i', wage)
    before = {p:bytes(v) for p,v in graph.pages.items()}
    expected, fields = original_common_tail(graph)
    result = run(graph)
    assert result.committed_signed32 == expected == wage
    assert (result.payroll_810, result.payroll_814, result.pending_818, result.pending_81c, result.pending_820, result.pending_824) == fields
    assert result.native_refresh_admission == 'not_entered_or_simulated'
    assert {p:bytes(v) for p,v in graph.pages.items()} == before


def test_pending_contract_amount_is_not_replaced_with_payroll_or_zero(image):
    graph = career(image)
    offer = add_offer(graph)
    graph.vector(graph.team+0x38, [graph.primary])
    graph.vector(graph.manager+0x20, [offer])
    expected, fields = original_common_tail(graph)
    result = run(graph)
    assert result.committed_signed32 == expected
    # The original reducer subtracts the same player's current1200 within
    # field818; the proposed1500 is a native net300 addition to payroll.
    assert result.pending_818 == fields[2] == 300
    assert result.payroll_814 == fields[1] == 1200
    assert result.committed_signed32 == 1500


@pytest.mark.parametrize('days,expected', [(0, 0), (30, 0), (59, 0), (60, 0), (61, 0), (264, 1200)])
def test_native_contract_expiry_classification_changes_commitment_not_payroll(image, days, expected):
    graph = career(image)
    graph.put(graph.contract+0x48, '<I', (2030<<16)|(100+days))
    native, fields = original_common_tail(graph)
    result = run(graph)
    assert result.committed_signed32 == native == expected
    assert result.payroll_814 == fields[1] == 1200
    assert result.pending_820 == fields[4] == 1200-expected


def test_unproved_kind40_contribution_cannot_return_partial_total(image):
    graph = career(image)
    edit = graph.alloc()
    graph.put(edit, '<Q', BASE+0x55E5380)
    graph.vector(graph.human+0x200, [edit])
    with pytest.raises(ValueError, match='owner contribution unavailable'):
        run(graph)


@pytest.mark.parametrize('mutation', ['wage', 'queue', 'native_tail', 'date', 'save_count', 'padding'])
def test_final_callback_rechecks_all_stages_and_allows_only_unused_padding(image, mutation):
    graph = career(image)
    first = scope(graph)
    calls = 0

    def lifetime():
        nonlocal calls
        calls += 1
        if calls == 4:
            address, fmt, values = {
                'wage': (graph.contract+0x20, '<i', (1701,)),
                'queue': (graph.human+0x200, '<Q', (0,)),
                'native_tail': (BASE+0xEAEC54, '<I', (0,)),
                'date': (BASE+world.CURRENT_DATE, '<I', ((2030<<16)|101,)),
                'save_count': (first.world_identity[0]+0xC8, '<I', (43,)),
                'padding': (graph.finance+0x900, '<B', (231,)),
            }[mutation]
            graph.put(address, fmt, *values)
        return first

    if mutation == 'padding':
        assert run(graph, lifetime).committed_signed32 == 1200
    else:
        with pytest.raises(ValueError):
            run(graph, lifetime)
    assert calls == 4


@pytest.mark.parametrize('field,change', [('plugin_uuid', bytes(16)), ('save_count', 43), ('current_date', '2030-04-11'), ('club_identity', (0, 0, 20, 20))])
def test_initial_scope_is_bound_to_actual_source(image, field, change):
    graph = career(image)
    with pytest.raises(ValueError):
        run(graph, lambda: replace(scope(graph), **{field: change}))


def test_caller_cannot_supply_payroll_offers_or_total(image):
    graph = career(image)
    with pytest.raises(TypeError):
        total.calculate(graph.read, BASE, graph.image, club=graph.club,
                         lifetime=lambda: scope(graph), payroll=1200, selected_offers=(), total=1200)
