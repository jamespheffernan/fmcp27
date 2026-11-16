"""Synthetic adapter/fence controls; original native replay is separate evidence."""
import asyncio
from contextlib import contextmanager
from copy import deepcopy
from threading import RLock

import pytest
from mcp.server.fastmcp import FastMCP

from fm_live_mcp import ucl_registration as adapter, ucl_registration_tools as tools, world
from fm_live_mcp.bridge import BridgeError

BASE = 0x10000000
TABLES = (BASE + adapter.players.RVA[0], BASE + 0x1000)
CELLS = {'world': 0x2000, 'date': 0x2008, 'catalog': 0x2020, 'bucket': 0x2028,
         'fixture': 0x2030, 'owner': 0x2038, 'human': 0x2040, 'phase': 0x2048}
REAL_PERSON = adapter._person


class Bridge:
    """Mirror canonical150 final_verify sequencing over mutable bounded bytes."""

    def __init__(self):
        self.lock = RLock()
        self.session, self.process = 'session', ('process', 12)
        self.plugin_identity, self.world_identity = ('plugin', 1), ('world', b'W')
        self.cells = {address: raw for address, raw in zip(CELLS.values(),
                      (b'W', b'2030-11-26', b'I', b'B', b'F', b'O', b'H', b'P'))}
        self.calls, self.events, self.hooks, self.journals = 0, [], {}, []
        self.closed = False
        self.fixture_refs = {'fixture': dict(tables=TABLES, year=2030, day=344, slot=0,
            group=0, group_address=0x9000, address=0x8000,
            catalog_identity=(b'I',), route=(b'B',), identity=(b'F',))}
        self.player_refs = {}
        for i in range(3):
            address = 0x10000 + i * 0x1000
            words = (i, 100 + i, 200 + i)
            for j, word in enumerate(words):
                self.cells[address + j * 4] = word.to_bytes(4, 'little')
            self.cells[address + 16] = bytes((1 if i == 0 else 0,))
            self.cells[address + 17] = bytes((1 if i == 1 else 0,))
            self.cells[address + 18] = b'a'
            self.cells[address + 19] = bytes((2 if i == 2 else 0,))
            self.player_refs[f'p{i}'] = dict(tables=TABLES, address=address, identity=words,
                                            record_kind='actual', world_bound=True)

    def read(self, address, length):
        self.events.append(('read', address, length))
        value = self.cells.get(address)
        if value is None or len(value) != length:
            raise ValueError('Missing synthetic operand')
        return value

    def _current(self, session_id):
        self.calls += 1
        self.events.append(('callback', self.calls))
        if self.calls in self.hooks:
            self.hooks[self.calls](self)
        if self.session != session_id:
            raise BridgeError('Session changed')
        return self.process

    def _player_layout(self, process):
        self.events.append(('layout',))
        return TABLES

    def _world_state(self, process, tables):
        read = world.ReadSet(self.read)
        self.journals.append(read)
        identity = ('world', read(CELLS['world'], 1))
        coach = dict(name='Coach', club='Newcastle', team_index=7)
        save = dict(current_date=read(CELLS['date'], 10).decode(), coaches=[coach])
        return read, save, identity

    def _select_coach(self, save, name):
        self.events.append(('coach',))
        if name is not None and name != 'Coach':
            raise BridgeError('Select one active coach')
        return save['coaches'][0]

    def _public_save(self, save):
        self.events.append(('public_save',))
        return deepcopy(save)

    @contextmanager
    def _read_scope(self, session_id, *, final_verify):
        self._current(session_id)
        try:
            yield
            self._current(session_id)
            final_verify()
        finally:
            self.closed = True
            self.events.append(('close',))


@pytest.fixture
def bridge(monkeypatch):
    bridge = Bridge()

    def team(read, base, coach):
        return dict(native_id=7, owner=read(CELLS['owner'], 1).hex()), read(CELLS['human'], 1).hex()

    def catalog(read, base):
        return None, {2030: {'groups': (0x9000,)}}, (read(CELLS['catalog'], 1),)

    def bucket(read, year, day, group):
        assert year == {'groups': (0x9000,)} and day == 344 and group == 0
        return [0x8000], (read(CELLS['bucket'], 1),)

    def record(read, base, address, year, day, cache):
        assert address == 0x8000
        return dict(identity=(read(CELLS['fixture'], 1),), kind='fixture',
                    competition=dict(native_id=1301394), team_ids=((1, 10), (7, 20)))

    def person(read, base, tables, people, binding):
        if type(binding) is not dict or binding.get('tables') != TABLES:
            raise ValueError('Expired player ref')
        primary = binding['address']
        words = tuple(int.from_bytes(read(primary + j * 4, 4), 'little') for j in range(3))
        if words != binding['identity']:
            raise ValueError('Canonical PERSON words changed')
        kinds = {b'a': 'actual', b'v': 'virtual', b'c': 'player_staff'}
        kind = kinds[read(primary + 18, 1)]
        return primary + 0x388, dict(native_identity=dict(database_index=words[0],
            native_id=words[1], random_id=words[2]), record_kind=kind, display_name=f'Person {words[1]}')

    def context(read, base, coach, address, decoded, current_date):
        phase = read(CELLS['phase'], 1)
        return dict(state='available', native_selector=0, phase=phase.hex()), dict(phase=phase)

    def registered(read, primary, kind, binding):
        result = bool(read(primary + 16, 1)[0]) if kind == 'actual' and binding else None
        return dict(state='available' if result is not None else 'unavailable', native_predicate_result=result)

    def exemption(read, primary, kind, binding):
        result = bool(read(primary + 17, 1)[0]) if kind == 'actual' and binding else None
        return dict(state='available' if result is not None else 'unavailable', native_requirement14=result,
                    registration_exempt=True if result else None)

    def requirement26(read, base, coach, address, decoded, current_date, subjects):
        # This fixture isolates incumbent adapter/fence behavior. The real
        # projection and complete original parity have dedicated controls.
        return dict(fixture_context=dict(state='unavailable'), aggregate=None,
            current_club_rule_sources=[], players=[dict(player_ref=ref, state='unavailable',
                native_requirement26=None, reason='native_requirement26_not_supported')
                for ref, _, _ in subjects])

    def suspension_context(read, base, address, decoded, current_date):
        assert address == 0x8000 and decoded['kind'] == 'fixture'
        phase = read(CELLS['phase'], 1)
        return dict(state='available', reason='synthetic', phase=phase.hex()), dict(phase=phase)

    def suspension(read, base, primary, kind, binding):
        assert binding['phase'] == read(CELLS['phase'], 1)
        code = read(primary + 19, 1)[0] if kind == 'actual' else 2
        value = {0: False, 1: True}.get(code)
        return dict(state='checked' if value is not None else 'unavailable', reason='synthetic',
                    native_suspended=value, personal_record_count=None, record_context=None,
                    overall_fixture_eligibility='not_evaluated')

    monkeypatch.setattr(adapter.suspensions, 'context', suspension_context)
    monkeypatch.setattr(adapter.suspensions, 'project', suspension)
    monkeypatch.setattr(adapter.prepared_tactics_source, '_team_and_human', team)
    monkeypatch.setattr(adapter.fixtures, 'catalog', catalog)
    monkeypatch.setattr(adapter.fixtures, 'bucket', bucket)
    monkeypatch.setattr(adapter.fixtures, 'record', record)
    monkeypatch.setattr(adapter.database, 'table', lambda read, base, name: {'count': 3})
    monkeypatch.setattr(adapter, '_person', person)
    monkeypatch.setattr(adapter.source, 'fixture_context', context)
    monkeypatch.setattr(adapter.source, 'registered', registered)
    monkeypatch.setattr(adapter.source, 'requirement14', exemption)
    monkeypatch.setattr(adapter.requirement26_source, 'project', requirement26)
    return bridge


def invoke(bridge, **kwargs):
    return adapter.get_player_ucl_registration(bridge, 'session', kwargs.pop('fixture_ref', 'fixture'),
                                               kwargs.pop('player_refs', ['p0', 'p1', 'p2']), **kwargs)


def test_explicit_batch_separates_registered_exempt_and_unknown(bridge):
    result = invoke(bridge)
    registered, exempt, unknown = result['players']
    assert registered['registration']['native_predicate_result'] is True
    assert exempt['registration']['native_predicate_result'] is False
    assert exempt['requirement14']['native_requirement14'] is True
    assert exempt['requirement26']['state'] == 'not_evaluated_first_requirement14_sufficient'
    assert [row['registration_covered_by_current_sources'] for row in result['players']] == [True, True, None]
    assert unknown['requirement26']['reason'] == 'native_requirement26_not_supported'
    assert all(row['full_eligibility_evaluated'] is False for row in result['players'])
    assert result['fixture_context']['current_read_date'] == '2030-11-26'
    assert result['fixture_context']['fixture_date'] == '2030-12-10'
    assert result['count'] == result['unique_person_count'] == 3
    assert result['population_scope'] == 'explicit_existing_player_refs'
    assert result['current_selection_verified'] is result['full_eligibility_evaluated'] is False
    assert result['atomic'] is result['saved_file_fallback'] is False
    assert all(row['loan_state'] == 'not_evaluated' for row in result['players'])
    assert bridge.closed and bridge.calls == 5 and len(bridge.journals) == 2
    last_callback = bridge.events.index(('callback', 5))
    assert all(event[0] in ('read', 'close') for event in bridge.events[last_callback + 1:])
    assert bridge.events[-1] == ('close',)


def test_suspension_is_separate_from_registration_and_never_clears(bridge):
    bridge.cells[bridge.player_refs['p0']['address'] + 19] = b'\x01'   # registered and suspended
    bridge.cells[bridge.player_refs['p2']['address'] + 19] = b'\x00'   # no suspension, not registered
    result = invoke(bridge, include_fixture_suspension=True)
    registered, exempt, plain = result['players']
    assert registered['fixture_suspension']['native_suspended'] is True
    assert registered['registration']['native_predicate_result'] is True
    assert registered['fixture_eligibility_evidence']['reading'] == 'adverse_native_suspension_fact'
    assert registered['fixture_eligibility_evidence']['registration']['coverage'] == 'covered_by_current_sources'
    # Negative suspension does not register: coverage stays unknown.
    assert plain['fixture_suspension']['native_suspended'] is False
    assert plain['registration_covered_by_current_sources'] is None
    evidence = plain['fixture_eligibility_evidence']
    assert evidence['registration']['coverage'] == 'unknown'
    assert evidence['reading'] == 'registration_unresolved'
    assert evidence['suspension']['establishes_registration'] is False
    # Native false coexists with the age exemption; suspension false is not clearance.
    assert exempt['registration']['native_predicate_result'] is False
    exempt_evidence = exempt['fixture_eligibility_evidence']
    assert exempt_evidence['registration']['native_false_registration_with_exemption'] is True
    assert exempt_evidence['registration']['satisfied_by'] == ['requirement14']
    assert exempt_evidence['registration']['clauses']['requirement26'] == 'not_evaluated'
    assert exempt_evidence['reading'] == 'registration_covered_and_no_native_suspension_found'
    for row in result['players']:
        e = row['fixture_eligibility_evidence']
        assert e['fixture_eligibility'] == 'not_evaluated'
        assert e['clearance_established'] is e['exclusion_established'] is False
        assert 'submitted_squad_list' in e['not_evaluated'] and 'medical_clearance' in e['not_evaluated']
    assert result['fixture_suspension_context']['fixture_ref'] == 'fixture'
    assert result['fixture_suspension_context']['as_of_date'] == '2030-11-26'
    assert result['full_eligibility_evaluated'] is False
    assert 'suspension_binding' not in result and 'suspension_context' not in result


def test_default_response_omits_suspension_and_never_reads_it(bridge, monkeypatch):
    for name in ('context', 'project'):
        monkeypatch.setattr(adapter.suspensions, name, lambda *args: pytest.fail('Suspension read without opt-in'))
    result = invoke(bridge)
    assert not {'fixture_suspension_context', 'fixture_suspension_scope', 'fixture_eligibility_scope'} & set(result)
    assert all('fixture_suspension' not in row and 'fixture_eligibility_evidence' not in row
               for row in result['players'])


@pytest.mark.parametrize('value', [1, 'true', None, 0])
def test_include_fixture_suspension_must_be_boolean(bridge, value):
    with pytest.raises(BridgeError, match='must be a boolean'):
        invoke(bridge, include_fixture_suspension=value)
    assert bridge.calls == 0


@pytest.mark.parametrize('callback', [3, 5])
def test_suspension_drift_after_context_rejects(bridge, callback):
    address = bridge.player_refs['p1']['address'] + 19
    bridge.hooks[callback] = lambda b: b.cells.__setitem__(address, b'\x01')
    with pytest.raises(BridgeError, match='no partial result'):
        invoke(bridge, include_fixture_suspension=True)
    assert bridge.closed


def test_unknown_suspension_with_covered_registration_stays_unknown(bridge):
    bridge.cells[bridge.player_refs['p0']['address'] + 19] = b'\x02'
    row = invoke(bridge, player_refs=['p0'], include_fixture_suspension=True)['players'][0]
    assert row['fixture_suspension']['native_suspended'] is None
    assert row['fixture_eligibility_evidence']['reading'] == 'registration_covered_suspension_unknown'


def test_unsupported_class_has_unknown_suspension_and_registration(bridge):
    bridge.cells[bridge.player_refs['p0']['address'] + 18] = b'v'
    row = invoke(bridge, player_refs=['p0'], include_fixture_suspension=True)['players'][0]
    assert row['fixture_suspension']['state'] == 'unavailable'
    assert row['fixture_eligibility_evidence']['reading'] == 'registration_unresolved'


@pytest.mark.parametrize('refs', (None, [], (), ['p0'] * 2, ['p0'] * 33, [''], [True], [1], ['x' * 257]))
def test_invalid_population_has_no_default_or_partial(bridge, refs):
    with pytest.raises(BridgeError, match='1 through 32 distinct'):
        invoke(bridge, player_refs=refs)
    assert bridge.calls == 0


@pytest.mark.parametrize('field,value', [('fixture_ref', ''), ('fixture_ref', None),
    ('fixture_ref', 'x' * 257), ('fixture_ref', True), ('coach_name', ''), ('coach_name', 1),
    ('coach_name', 'x' * 257)])
def test_invalid_fixture_and_coach_bounds(bridge, field, value):
    with pytest.raises(BridgeError):
        invoke(bridge, **{field: value})
    assert bridge.calls == 0


def test_maximum_batch_preserves_distinct_alias_rows(bridge):
    original = deepcopy(bridge.player_refs['p0'])
    refs = [f'alias{i}' for i in range(32)]
    bridge.player_refs = {ref: deepcopy(original) for ref in refs}
    result = invoke(bridge, player_refs=refs, coach_name='Coach')
    assert [row['player_ref'] for row in result['players']] == refs
    assert result['count'] == 32 and result['unique_person_count'] == 1
    assert bridge.journals[0].observed[(original['address'] + 16, 1)] == b'\x01'


@pytest.mark.parametrize('kind', [b'v', b'c'])
def test_canonical_unsupported_class_stays_unknown(bridge, kind):
    bridge.cells[bridge.player_refs['p0']['address'] + 18] = kind
    row = invoke(bridge, player_refs=['p0'])['players'][0]
    assert row['registration']['native_predicate_result'] is None
    assert row['requirement14']['native_requirement14'] is None
    assert row['registration_covered_by_current_sources'] is None


@pytest.mark.parametrize('current', ['2030-12-10', '2030-12-11'])
def test_nonfuture_fixture_returns_unknown_current_inputs(bridge, current):
    bridge.cells[CELLS['date']] = current.encode()
    result = invoke(bridge)
    assert result['fixture_context']['reason'] == 'fixture_not_on_later_calendar_date'
    assert all(row['registration']['native_predicate_result'] is None for row in result['players'])
    assert all(row['registration_covered_by_current_sources'] is None for row in result['players'])


@pytest.mark.parametrize('key,value', [('tables', list(TABLES)), ('tables', (0,)), ('year', True),
    ('year', 1849), ('day', 0), ('day', 366), ('group', -1), ('group', True),
    ('group', 1), ('group_address', 0), ('slot', -1), ('slot', True), ('slot', 1),
    ('address', True), ('address', 0x8004), ('address', 0), ('address', 2 ** 64),
    ('catalog_identity', ('bad',)), ('route', ('bad',)), ('identity', ('bad',))])
def test_invalid_fixture_binding_rejects_batch(bridge, key, value):
    bridge.fixture_refs['fixture'][key] = value
    with pytest.raises(BridgeError, match='no partial result'):
        invoke(bridge)
    assert bridge.closed


def test_expired_person_ref_rejects_whole_batch(bridge):
    del bridge.player_refs['p1']
    with pytest.raises(BridgeError, match='Expired player'):
        invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('callback', [3, 5])
@pytest.mark.parametrize('key', list(CELLS) + ['primary', 'secondary', 'index', 'registered', 'exempt', 'kind'])
def test_physical_drift_before_seal_and_after_last_callback_rejects(bridge, callback, key):
    address = CELLS.get(key)
    if address is None:
        address = bridge.player_refs['p1']['address'] + dict(index=0, primary=4, secondary=8,
                                                          registered=16, exempt=17, kind=18)[key]
    def mutate(b):
        old = b.cells[address]
        b.cells[address] = bytes([old[0] ^ 1]) + old[1:]
    bridge.hooks[callback] = mutate
    with pytest.raises(BridgeError, match='no partial result'):
        invoke(bridge)
    assert bridge.closed


@pytest.mark.parametrize('callback', [3, 5])
@pytest.mark.parametrize('key', ['session', 'process', 'plugin', 'world_cache', 'fixture_ref', 'player_ref'])
def test_context_and_root_cache_drift_rejects(bridge, callback, key):
    def mutate(b):
        if key == 'session': b.session = 'other'
        elif key == 'process': b.process = ('other', 13)
        elif key == 'plugin': b.plugin_identity = ('other', 2)
        elif key == 'world_cache': b.world_identity = ('other', b'W')
        elif key == 'fixture_ref': b.fixture_refs['fixture']['slot'] = 1
        else: b.player_refs['p2']['identity'] = (2, 1, 1)
    bridge.hooks[callback] = mutate
    with pytest.raises(BridgeError):
        invoke(bridge)
    assert bridge.closed


def test_coach_rebind_drift_rejects(bridge):
    old = bridge._select_coach
    def coach(save, name):
        result = deepcopy(old(save, name))
        if bridge.calls >= 4:
            result['name'] = 'Changed coach'
        return result
    bridge._select_coach = coach
    with pytest.raises(BridgeError, match='owner/person/phase result changed'):
        invoke(bridge)


def test_layout_rebind_drift_rejects(bridge):
    bridge._player_layout = lambda process: TABLES if bridge.calls < 4 else (0,)
    with pytest.raises(BridgeError, match='plugin/build changed'):
        invoke(bridge)


def test_real_person_delegates_actual_refs_without_profile_generation(monkeypatch):
    binding = dict(tables=TABLES, address=0x10000, world_bound=True)
    calls = []
    def bound(*args):
        calls.append(args)
        return 0x10388, dict(record_kind='actual')
    monkeypatch.setattr(adapter.assessment_people, 'bound_player', bound)
    result = REAL_PERSON(lambda at, n: (BASE + adapter.players.RVA[0]).to_bytes(8, 'little'),
                         BASE, TABLES, {'count': 1}, binding)
    assert result == (0x10388, dict(record_kind='actual')) and len(calls) == 1


@pytest.mark.parametrize('fault', [None, 'tables', 'world_bound', 'identity', 'bool_word', 'kind', 'index'])
def test_real_compact_identity_is_exact_and_never_generated(monkeypatch, fault):
    identity = ('virtual', 1, 100, 200)
    binding = dict(tables=TABLES, address=0x10000, world_bound=True,
                   binding_kind=adapter.virtual_identity.BINDING_KIND, identity=identity,
                   record_kind='virtual', database_index=1)
    compact = dict(identity=identity, native_identity=dict(database_index=1, native_id=100, random_id=200))
    monkeypatch.setattr(adapter.virtual_identity, 'inspect', lambda *args: deepcopy(compact))
    monkeypatch.setattr(adapter.assessment_people, 'bound_player', lambda *args: pytest.fail('Generated/delegated compact'))
    if fault == 'tables': binding['tables'] = list(TABLES)
    elif fault == 'world_bound': binding['world_bound'] = 1
    elif fault == 'identity': binding['identity'] = ('virtual', 1, 101, 200)
    elif fault == 'bool_word': binding['identity'] = ('virtual', True, 100, 200)
    elif fault == 'kind': binding['record_kind'] = 'actual'
    elif fault == 'index': binding['database_index'] = True
    read = lambda at, n: (BASE + world.TYPES['virtual_player'][0]).to_bytes(8, 'little')
    if fault:
        with pytest.raises(ValueError): REAL_PERSON(read, BASE, TABLES, {}, binding)
    else:
        person, public = REAL_PERSON(read, BASE, TABLES, {}, binding)
        assert person == 0x10020 and public['record_kind'] == 'virtual'
        assert public['native_identity'] == compact['native_identity']


def test_real_sdk_contract_and_readonly_annotations():
    mcp = FastMCP()
    tools.register_ucl_registration_tools(mcp, object())
    tool, = asyncio.run(mcp.list_tools())
    assert tool.name == 'fm_get_player_ucl_registration'
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is tool.annotations.openWorldHint is False
    schema = tool.inputSchema
    assert set(schema['required']) == {'session_id', 'fixture_ref', 'player_refs'}
    assert set(schema['properties']) == {'session_id', 'fixture_ref', 'player_refs', 'coach_name',
                                         'include_fixture_suspension'}
    assert schema['properties']['include_fixture_suspension']['default'] is False
    refs = schema['properties']['player_refs']
    assert refs['minItems'] == 1 and refs['maxItems'] == 32 and refs['uniqueItems'] is True
    assert refs['items']['minLength'] == 1 and refs['items']['maxLength'] == 256
    assert 'No current-XI/bench or historical-selection default' in tool.description


def test_real_sdk_wrapper_forwards_explicit_arguments(monkeypatch):
    calls = []
    bridge = object()
    def delegate(*args):
        calls.append(args)
        return {'ok': True}
    monkeypatch.setattr(tools, 'get_player_ucl_registration', delegate)
    mcp = FastMCP()
    tools.register_ucl_registration_tools(mcp, bridge)
    result = asyncio.run(mcp.call_tool('fm_get_player_ucl_registration',
        dict(session_id='session', fixture_ref='fixture', player_refs=['p0'], coach_name='Coach')))[1]
    assert result == {'ok': True}
    assert calls == [(bridge, 'session', 'fixture', ['p0'], 'Coach', False)]
    calls.clear()
    asyncio.run(mcp.call_tool('fm_get_player_ucl_registration',
        dict(session_id='session', fixture_ref='fixture', player_refs=['p0'], include_fixture_suspension=True)))
    assert calls == [(bridge, 'session', 'fixture', ['p0'], None, True)]
