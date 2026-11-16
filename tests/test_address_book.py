"""The address book: the census covers the tree, unresolved addresses refuse, the rewrite is exact."""
from __future__ import annotations

import ast
import types

import pytest

from fm_live_mcp import address_book as ab
from fm_live_mcp.fmdb import address_census as ac


def test_census_covers_every_in_range_literal_of_the_tree():
    """A literal address added without rebuilding the census would keep its pinned value on
    another build. Rebuild with: scripts/fmdb_rebase.py <pinned plugin> --census --write"""
    census = ab.census()
    scanned = ac.scan(ac.PACKAGE, census['image_end'])
    missing = sorted(f'{rel}: {value:#x} (line {line})' for rel, sites in scanned.items()
                     for value, line, *_ in sites if f'{value:#x}' not in census['files'].get(rel, {}))
    assert not missing, f'{len(missing)} in-range literals not in the address census, e.g. {missing[:5]}'


def test_census_decisions_on_known_sites():
    files = ab.census()['files']
    assert files['players.py']['0x5588ee8']['d'] == 'A'                  # players.RVA[0], a vtable
    assert files['captured_match_query.py']['0x40000']['d'] == 'C'       # MAX_RESPONSE_BYTES = 262144
    assert files['active_match_shots.py']['0x14e90']['d'] == 'C'         # engine + 0x14e90 (offset)
    assert files['_concern_template_definitions.py']['0x99c7c']['d'] == 'C'   # a template id
    assert all(row['d'] == 'C' for rel, e in files.items() if rel.startswith('person_wire/') for row in e.values())


def test_guard_addresses_below_0x10000_are_in_the_census():
    """The game's static initialisers sit below 0x10000. Four native guards check them; the census
    ignored every literal under that floor, so on 27.0.1 they kept their pinned addresses and the
    frame tool and the playback events refused (found on a live match, 12 November 2026)."""
    files = ab.census()['files']
    for rel, keys in (('active_match_entity_identity.py', ('0xd6c4', '0xdb74', '0xdbb8')),
                      ('playback_event_source.py', ('0xe204',))):
        for key in keys:
            assert (files[rel][key]['d'], files[rel][key]['rule'], files[rel][key]['kind']) == ('A', 'guard', 'code')
    sites = ac.literal_sites(
        'SPANS = ((0xD6C4, bytes.fromhex("012c80525f832b95")), (0x480, "00112233445566778899"), (55000, b"ab"))\n'
        'STRIDE = 0xD6C4\nROW = record + 0xE204\n', 0x58F4000)
    # only the hexadecimal address of a guard, at or above the first code address
    assert [(value, 'guard' in features) for value, _l, _c, _s, _scope, features in sites] == [(0xD6C4, True)]


def test_rewrite_translates_a_low_guard_address_and_leaves_other_small_numbers(monkeypatch):
    row = {'d': 'A', 'rule': 'guard', 'kind': 'code', 'sites': []}
    _with_map(monkeypatch, {0xD6C4: 0xD790}, rows={'0xd6c4': row}, guards={'aabbccdd': '11223344'})
    ns, counts = _run('SPANS = ((0xD6C4, bytes.fromhex("aabbccdd")),)\nSIZE = 0x160\nOTHER = 0xD6C8\n')
    assert ns['SPANS'] == ((0xD790, bytes.fromhex('11223344')),)
    assert ns['SIZE'] == 0x160 and ns['OTHER'] == 0xD6C8 and counts['unknown'] == 0


def test_unresolved_refuses_inside_functions_and_propagates_at_module_level():
    u = ab.Unresolved(0x1234, 'function changed')

    def use():
        return u + 8

    with pytest.raises(ab.UnresolvedAddress, match='0x1234'):
        use()
    for op in (lambda: int(u), lambda: bool(u), lambda: u < 3, lambda: f'{u:#x}', lambda: u == 0x1234,
               lambda: [1][u], lambda: u & 0xFF):
        with pytest.raises(ab.UnresolvedAddress):
            op()
    namespace = {'u': u}
    exec(compile('x = u + 8\ntable = {u: 1, 5: u}\n', '<module-level>', 'exec'), namespace)
    assert isinstance(namespace['x'], ab.Unresolved)
    assert namespace['table'][5] is u and u in namespace['table'] and u == u
    assert '0x1234' in repr(u)


def _with_map(monkeypatch, values, *, rows, guards=None, disabled=None, identity=None):
    census = {'image_end': 0x58F4000, 'files': {'demo.py': rows}}
    monkeypatch.setattr(ab, '_CENSUS', census)
    monkeypatch.setattr(ab, 'MAP', {'values': {}})
    monkeypatch.setattr(ab, '_VALUES', values)
    monkeypatch.setattr(ab, '_REASONS', {k: 'gone' for k, v in values.items() if v is None})
    monkeypatch.setattr(ab, '_PER_FILE', {})
    monkeypatch.setattr(ab, '_GUARDS', {'demo.py': guards or {}})
    monkeypatch.setattr(ab, '_DISABLED', {'demo.py': disabled or {}})
    monkeypatch.setitem(ab.ACTIVE, 'sha256', (identity or ('b' * 64, '27.0.1.1'))[0])
    monkeypatch.setitem(ab.ACTIVE, 'version', (identity or ('b' * 64, '27.0.1.1'))[1])


def _run(source):
    tree = ast.parse(source)
    counts = ab.rewrite(tree, 'demo.py')
    ns = {'__fmcp_address__': ab._address, '__fmcp_refuse__': ab._refuse_call}
    exec(compile(tree, 'demo.py', 'exec'), ns)
    return ns, counts


def test_rewrite_is_exact(monkeypatch):
    row = lambda d: {'d': d, 'rule': 'test', 'kind': 'code', 'sites': []}    # noqa: E731
    _with_map(monkeypatch, {0x1000000: 0x1000040, 0x2000000: None},
              rows={'0x1000000': row('A'), '0x2000000': row('A'), '0x186a0': row('C')},
              guards={'aabbccdd': '11223344'}, disabled={'off': 'decoder disagrees'})
    ns, counts = _run(
        'A = 0x1000000\nB = 0x2000000\nBUDGET = 100000\nSPAN = (0x1000000, bytes.fromhex("aabbccdd"))\n'
        f'BUILD = "{ab.PINNED_VERSION}"\nSHA = "{ab.PINNED_SHA256}"\n'
        'def read_b(base):\n    return base + B\n'
        'def off():\n    return 1\n')
    assert ns['A'] == 0x1000040 and ns['BUDGET'] == 100000
    assert ns['SPAN'] == (0x1000040, bytes.fromhex('11223344'))
    assert ns['BUILD'] == '27.0.1.1' and ns['SHA'] == 'b' * 64
    assert isinstance(ns['B'], ab.Unresolved)
    with pytest.raises(ab.UnresolvedAddress, match='0x2000000'):
        ns['read_b'](0x100000000)
    with pytest.raises(ab.UnresolvedAddress, match='decoder disagrees'):
        ns['off']()
    assert counts['addresses'] == 2 and counts['unresolved'] == 1 and counts['guards'] == 1


def test_refusal_names_the_command(monkeypatch):
    monkeypatch.setitem(ab.ACTIVE, 'state', 'unsupported')
    monkeypatch.setitem(ab.ACTIVE, 'installed_sha256', None)
    text = ab.refusal('27.0.1.2600000', 'c' * 64)
    assert 'scripts/fm_update_build.py --installed' in text and '27.0.1.2600000' in text


def test_unavailable_tools_follow_calls_and_module_tables(monkeypatch):
    helper = types.ModuleType('fm_live_mcp._demo_helper')
    exec('TABLE = (1, 2)\ndef inspect():\n    return TABLE\n', helper.__dict__)
    tools = types.ModuleType('fm_live_mcp._demo_tools')
    tools.__dict__['helper'] = helper
    exec('def tool_a():\n    return helper.inspect()\ndef tool_b():\n    return 1\n', tools.__dict__)
    monkeypatch.setattr(ab, 'unresolved_sites',
                        lambda: {('fm_live_mcp._demo_helper', 'module:TABLE'): [(0x56D3288, 'no referencing code')]})
    out = ab.unavailable_tools({'a': tools.tool_a, 'b': tools.tool_b})
    assert list(out) == ['a'] and '0x56d3288' in out['a'][0]


def test_bridge_refuses_another_build_with_the_command(monkeypatch):
    from types import SimpleNamespace
    from fm_live_mcp import bridge
    monkeypatch.setitem(ab.ACTIVE, 'state', 'unsupported')
    process = bridge.Process(pid=1, executable='/x/fm.app/Contents/MacOS/fm', started='', version='27.0.1.2600000',
                             bundle_id='com.SportsInteractive.FootballManager27', executable_stamp='')
    with pytest.raises(bridge.BridgeError, match='fm_update_build.py --installed'):
        bridge.Bridge._player_layout(SimpleNamespace(), process)


def test_manager_walker_refuses_when_disabled(monkeypatch):
    monkeypatch.setattr(ab, 'MAP', {'disabled_managers': {'AGENT_MANAGER': 'allocation size changed'}})
    from fm_live_mcp.fmdb.sources import managers_market
    with pytest.raises(ab.UnresolvedAddress, match='AGENT_MANAGER'):
        managers_market.manager(None, 'AGENT_MANAGER')
