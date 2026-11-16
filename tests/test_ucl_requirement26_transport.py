"""Private transport qualification; public composition remains lead-owned."""
import asyncio
from copy import deepcopy

import pytest
from mcp.server.fastmcp import FastMCP

from test_ucl_registration import bridge as canonical_bridge, CELLS
from fm_live_mcp import ucl_requirement26_transport as transport, ucl_requirement26_tools as tools
from fm_live_mcp.bridge import BridgeError

EXTRA = dict(roster=0x3000, goalkeeper_club=0x3008, goalkeeper_comp=0x3010,
             goalkeeper_rule=0x3018, goalkeeper_medical=0x3020)


@pytest.fixture
def bridge(canonical_bridge, monkeypatch):
    b = canonical_bridge
    for address in EXTRA.values(): b.cells[address] = b'\x01'
    def project(read, base, coach, fixture_address, decoded, current_date, subjects):
        values = {name: read(address, 1)[0] for name, address in EXTRA.items()}
        read(CELLS['phase'], 1)
        future = current_date < '2030-12-10'
        rows = [dict(player_ref=ref, state='checked' if future and kind == 'actual' else 'unavailable',
            native_requirement26=bool(read(primary + 17, 1)[0]) if future and kind == 'actual' else None,
            goalkeeper_position_rating=20 if kind == 'actual' else None,
            full_eligibility_evaluated=False) for ref, primary, kind in subjects]
        return dict(fixture_context=dict(state='available' if future else 'unavailable',
            current_read_date=current_date, fixture_date='2030-12-10'),
            players=rows, aggregate=dict(state='checked', native_result=False,
                stored_player_slot_count=values['roster'], medical_source=values['goalkeeper_medical']),
            current_club_rule_sources=[dict(club=values['goalkeeper_club'],
                competition=values['goalkeeper_comp'], rule=values['goalkeeper_rule'])])
    monkeypatch.setattr(transport.source, 'project', project)
    return b


def invoke(bridge, **kwargs):
    return transport.get_player_ucl_requirement26(bridge, 'session', kwargs.pop('fixture_ref', 'fixture'),
                                                  kwargs.pop('player_refs', ['p0', 'p1', 'p2']), **kwargs)


def test_explicit_batch_keeps_clause_results_and_overall_verification_separate(bridge):
    r = invoke(bridge)
    assert [p['native_requirement26'] for p in r['players']] == [False, True, False]
    assert all(p['full_eligibility_evaluated'] is False for p in r['players'])
    assert r['full_eligibility_evaluated'] is r['medical_clearance_evaluated'] is False
    assert r['current_selection_verified'] is False and r['population_scope'] == 'explicit_existing_player_refs'
    assert r['fixture_context']['current_read_date'] == '2030-11-26'
    assert r['fixture']['date'] == '2030-12-10'
    assert r['current_club_rule_sources'] == [dict(club=1, competition=1, rule=1)]
    assert r['count'] == r['unique_person_count'] == 3
    assert r['atomic'] is r['saved_file_fallback'] is False
    assert 'eligible' not in r and 'ineligible' not in r
    last = bridge.events.index(('callback', 5))
    assert all(event[0] in ('read', 'close') for event in bridge.events[last + 1:])
    assert bridge.closed


@pytest.mark.parametrize('callback', [3, 5])
@pytest.mark.parametrize('name', list(CELLS) + list(EXTRA))
def test_every_bound_context_and_gk_source_drift_rejects(bridge, callback, name):
    address = {**CELLS, **EXTRA}[name]
    def mutate(b):
        old = b.cells[address]
        b.cells[address] = bytes((old[0] ^ 1,)) + old[1:]
    bridge.hooks[callback] = mutate
    with pytest.raises(BridgeError, match='no partial result'):
        invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('callback', [3, 5])
@pytest.mark.parametrize('name', ['session', 'process', 'plugin', 'world', 'fixture_ref', 'person_ref'])
def test_root_context_and_refs_drift_rejects(bridge, callback, name):
    def mutate(b):
        if name == 'session': b.session = 'other'
        elif name == 'process': b.process = ('other', 13)
        elif name == 'plugin': b.plugin_identity = ('other', 2)
        elif name == 'world': b.world_identity = ('other', b'W')
        elif name == 'fixture_ref': b.fixture_refs['fixture']['slot'] = 1
        else: b.player_refs['p2']['identity'] = (2, 3, 4)
    bridge.hooks[callback] = mutate
    with pytest.raises(BridgeError, match='no partial result'): invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('offset', [0, 4, 8, 18])
@pytest.mark.parametrize('callback', [3, 5])
def test_requested_person_full_identity_or_type_drift_rejects(bridge, offset, callback):
    address = bridge.player_refs['p1']['address'] + offset
    def mutate(b):
        old = b.cells[address]; b.cells[address] = bytes((old[0] ^ 1,)) + old[1:]
    bridge.hooks[callback] = mutate
    with pytest.raises(BridgeError): invoke(bridge)


@pytest.mark.parametrize('refs', [None, [], (), ['p0', 'p0'], ['p0'] * 33, [''], [True], [1], ['x' * 257]])
def test_strict_population_bounds_without_default(bridge, refs):
    with pytest.raises(BridgeError): invoke(bridge, player_refs=refs)
    assert bridge.calls == 0


@pytest.mark.parametrize('value', [None, '', True, 1, 'x' * 257])
def test_strict_fixture_bounds(bridge, value):
    with pytest.raises(BridgeError): invoke(bridge, fixture_ref=value)
    assert bridge.calls == 0


def test_all32_requested_alias_rows_preserved(bridge):
    binding = deepcopy(bridge.player_refs['p0'])
    refs = [f'alias{i}' for i in range(32)]
    bridge.player_refs = {ref: deepcopy(binding) for ref in refs}
    r = invoke(bridge, player_refs=refs)
    assert [p['player_ref'] for p in r['players']] == refs
    assert r['count'] == 32 and r['unique_person_count'] == 1


@pytest.mark.parametrize('kind', [b'v', b'c'])
def test_canonical_unsupported_class_stays_unknown(bridge, kind):
    bridge.cells[bridge.player_refs['p0']['address'] + 18] = kind
    row = invoke(bridge, player_refs=['p0'])['players'][0]
    assert row['state'] == 'unavailable' and row['native_requirement26'] is None


def test_source_population_coverage_gap_rejects(bridge, monkeypatch):
    old = transport.source.project
    def missing(*args):
        result = old(*args); result['players'].pop(); return result
    monkeypatch.setattr(transport.source, 'project', missing)
    with pytest.raises(BridgeError, match='coverage changed'): invoke(bridge)


def test_private_sdk_tool_declares_exact_contract_and_readonly(monkeypatch):
    calls, b = [], object()
    def delegate(*args): calls.append(args); return {'ok': True}
    monkeypatch.setattr(tools, 'get_player_ucl_requirement26', delegate)
    mcp = FastMCP(); tools.register_ucl_requirement26_tools(mcp, b)
    tool, = asyncio.run(mcp.list_tools())
    assert tool.name == 'fm_get_player_ucl_requirement26'
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is tool.annotations.openWorldHint is False
    assert set(tool.inputSchema['required']) == {'session_id', 'fixture_ref', 'player_refs'}
    bounds = tool.inputSchema['properties']['player_refs']
    assert bounds['minItems'] == 1 and bounds['maxItems'] == 32 and bounds['uniqueItems'] is True
    result = asyncio.run(mcp.call_tool(tool.name,
        dict(session_id='session', fixture_ref='fixture', player_refs=['p0'])))[1]
    assert result == {'ok': True} and calls == [(b, 'session', 'fixture', ['p0'], None)]
