"""Real native total and adapter/schema on explicit synthetic career memory."""
import asyncio
from contextlib import contextmanager
from dataclasses import replace
import json
import hashlib
from pathlib import Path
import struct
import threading
import types

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import committed_wage_tools as tools, live_committed_wage_spending as query
from fm_live_mcp import players, world
from fm_live_mcp.bridge import Bridge, BridgeError, Process
from test_committed_wage_total import career, run, scope, BASE, image


def managed_career(image):
    graph = career(image)

    def text(value):
        out = graph.alloc()
        raw = value.encode()+b'\0'
        graph.put(out, '<I', len(raw)-1)
        for i, byte in enumerate(raw):
            graph.put(out+4+i, '<B', byte)
        return out

    for offset, name in [(0x458, 'Synthetic'), (0x460, 'Coach')]:
        handle = graph.alloc()
        graph.put(handle, '<Q', text(name))
        graph.put(graph.human+offset, '<Q', handle)
    graph.put(graph.club+0xC0, '<Q', text('Synthetic United'))
    graph.put(graph.club+0xC8, '<Q', text('Synthetic'))
    contract = graph.alloc()
    graph.put(graph.human+0x4B0, '<Q', contract)
    graph.put(contract+8, '<QQQ', graph.human+0x548, graph.team, graph.team)
    user = graph.alloc()
    graph.put(user+0x148, '<Q', graph.human)
    graph.vector(user+0xC0, [graph.human])
    game = struct.unpack('<Q', graph.read(BASE+world.GAME_ROOT, 8))[0]
    info = struct.unpack('<Q', graph.read(game+0x58, 8))[0]
    graph.vector(info, [user])
    currency = graph.alloc()
    graph.put(currency, '<QIII', BASE+world.TYPES['currency'][0], 0, 86, 86)
    graph.put(currency+0x18, '<Q', text('United Kingdom Pound'))
    graph.put(currency+0x38, '<f', 1.0)
    # The base-currency enum is already in pinned read-only source. Do not
    # replace its whole static page and erase adjacent native RTTI strings.
    graph.table('currencies', [currency])
    graph.currency = currency
    return graph


class SyntheticBridge:
    _select_coach = staticmethod(Bridge._select_coach)
    _public_save = staticmethod(Bridge._public_save)

    def __init__(self, graph):
        self.graph = graph
        self.lock = threading.RLock()
        self.session = 'synthetic-current-attachment'
        self.process = Process(*scope(graph).process_identity)
        self.plugin_identity = (graph.image, players.macho_uuid(graph.read(BASE, 16384)))
        self.world_identity = None
        self.current_calls = 0

    def _current(self, session):
        if session != self.session:
            raise BridgeError('Unknown session')
        self.current_calls += 1
        return self.process

    @contextmanager
    def _read_scope(self, session):
        self._current(session)
        yield

    def _player_layout(self, process):
        assert process == self.process
        return tuple(BASE+rva for rva in players.RVA)

    def _world_state(self, process, tables):
        read = world.ReadSet(lambda a,n:self._read_memory(process,a,n))
        save, identity = world.loaded(read, BASE)
        self.world_identity = identity
        return read, save, identity

    def _read_memory(self, process, address, count):
        assert process == self.process
        return self.graph.read(address, count)


@pytest.fixture
def live(image):
    graph = managed_career(image)
    return graph, SyntheticBridge(graph)


def get(live):
    return query.get_club_committed_wage_spending(live[1], live[1].session, 'Synthetic Coach')


def test_actual_native_total_selected_adapter_currency_and_schema(live):
    graph, bridge = live
    expected = run(graph)
    before = {p:bytes(v) for p,v in graph.pages.items()}
    actual = get(live)
    assert actual['committed_wage_spending'] == dict(state='recomputed', amount=expected.committed_signed32, currency='GBP', period='week')
    assert actual['committed_wage_spending']['amount'] == actual['current_wage_spending']['amount'] == 1200
    assert actual['club'] == dict(name='Synthetic United', short_name='Synthetic', database_index=0, native_id=20, random_id=None)
    assert actual['save']['current_date'] == '2030-04-10' and actual['coach'] == 'Synthetic Coach'
    assert actual['native_refresh_admission'] == 'not_entered_or_simulated'
    assert not actual['game_writes'] and not actual['native_game_functions_executed'] and not actual['atomic'] and not actual['saved_file_fallback']
    assert 'address' not in json.dumps(actual)
    assert {p:bytes(v) for p,v in graph.pages.items()} == before

    async def check():
        mcp = FastMCP('Synthetic native wage commitment adapter')
        tools.register_committed_wage_tools(mcp, bridge)
        tool, = await mcp.list_tools()
        assert tool.name == 'fm_get_club_committed_wage_spending'
        assert tool.annotations.readOnlyHint and not tool.annotations.destructiveHint and not tool.annotations.openWorldHint
        assert set(tool.inputSchema['properties']) == {'session_id', 'coach_name'}
        assert tool.inputSchema['required'] == ['session_id']
        _, result = await mcp.call_tool(tool.name, {'session_id':bridge.session, 'coach_name':'Synthetic Coach'})
        assert result['committed_wage_spending'] == actual['committed_wage_spending']
    asyncio.run(check())


@pytest.mark.parametrize('field,value', [('session_id', ''), ('session_id', True), ('session_id', 'x'*129), ('coach_name', ''), ('coach_name', True), ('coach_name', 'x'*257)])
def test_invalid_public_controls_refuse_before_source_scope(live, field, value):
    bridge = live[1]
    kwargs = dict(session_id=bridge.session, coach_name='Synthetic Coach')
    kwargs[field] = value
    with pytest.raises(BridgeError):
        query.get_club_committed_wage_spending(bridge, **kwargs)
    assert bridge.current_calls == 0


def test_currency_cannot_change_after_native_calculation_and_escape_outer_checks(live, monkeypatch):
    graph, _ = live
    original = query.total.calculate

    def calculate(*args, **kwargs):
        result = original(*args, **kwargs)
        graph.put(graph.currency+0x38, '<f', 1.5)
        return result

    monkeypatch.setattr(query.total, 'calculate', calculate)
    source = Path(query.__file__).read_text()
    marker = '            for context in contexts:\n                context.verify()\n\n            def amount(value):'
    old_source = source.replace(marker, '\n            def amount(value):')
    assert hashlib.sha256(old_source.encode()).hexdigest() == 'faf184ac3013928a64f71a12dd6f44dabf8c26e7c1eb065cac979e78217c6bef'
    old = types.ModuleType('fm_live_mcp.prior_committed_adapter')
    old.__package__ = 'fm_live_mcp'
    exec(compile(old_source, 'prior_committed_adapter', 'exec'), old.__dict__)
    stale = old.get_club_committed_wage_spending(live[1], live[1].session, 'Synthetic Coach')
    assert stale['committed_wage_spending']['amount'] == 1200
    assert struct.unpack('<f', graph.read(graph.currency+0x38, 4))[0] == 1.5
    graph.put(graph.currency+0x38, '<f', 1.0)
    with pytest.raises(BridgeError, match='no partial result'):
        get(live)


@pytest.mark.parametrize('mutation', ['date', 'count', 'club', 'human', 'contract_wage', 'currency', 'process', 'plugin', 'padding'])
def test_final_adapter_callback_cannot_hide_changed_context_or_consumed_money(live, mutation):
    graph, bridge = live
    original = bridge._current
    calls = 0

    def current(session):
        nonlocal calls
        calls += 1
        value = original(session)
        # Adapter: scope1, initial2, each core lifetime has two checks.
        # The fourth/final core lifetime ends at current10.
        if calls == 10:
            if mutation == 'date':graph.put(BASE+world.CURRENT_DATE, '<I', (2030<<16)|101)
            elif mutation == 'count':graph.put(scope(graph).world_identity[0]+0xC8, '<I', 43)
            elif mutation == 'club':graph.put(graph.club+16, '<I', 21)
            elif mutation == 'human':graph.put(graph.team+0x80, '<Q', 0)
            elif mutation == 'contract_wage':graph.put(graph.contract+0x20, '<i', 1701)
            elif mutation == 'currency':graph.put(graph.currency+0x38, '<f', 1.5)
            elif mutation == 'process':return replace(value, started='replacement')
            elif mutation == 'plugin':bridge.plugin_identity = ('changed',)
            else:graph.put(graph.finance+0x900, '<B', 99)
        return value

    bridge._current = current
    if mutation == 'padding':
        assert get(live)['committed_wage_spending']['amount'] == 1200
    else:
        with pytest.raises(BridgeError, match='no partial result'):
            get(live)
    assert calls == 10
