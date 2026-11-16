"""Existing public adapter on literal retained genuine bytes, with no process IO.

The real canonical scope, ReadSets, fixture/PERSON rebind and production source
operators run. Only physical transport/process/layout discovery are synthetic.
"""
from datetime import date
import gzip
import hashlib
import json
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import bridge as bridge_module, database, fixtures, players, world
from fm_live_mcp import ucl_registration as adapter
from fm_live_mcp.bridge import Bridge, BridgeError

PACKET = Path(__file__).parent/'fixtures/ucl_requirement26_context2.json.gz'


@pytest.fixture
def recorded(monkeypatch):
    raw = gzip.decompress(PACKET.read_bytes())
    assert hashlib.sha256(raw).hexdigest()=='e020409a08956dc73c4eb3e4a1eb877a43bfcd38556067b9be4648e0e14db046'
    packet = json.loads(raw)
    assert packet['detach']=={'detached':True}and packet['source_before']==packet['source_after']
    cells = {}
    for row in packet['journal']:
        for index,value in enumerate(bytes.fromhex(row['raw_hex'])):
            at = row['address']+index
            assert at not in cells or cells[at]==value
            cells[at] = value
    events,hooks = [],{}
    def read(at,n):
        events.append(('read',at,n))
        try:return bytes(cells[at+i]for i in range(n))
        except KeyError as error:raise ValueError(('Missing literal recorded byte',hex(error.args[0])))from error
    class Stream:
        def __init__(self,helper,pid):self.closed=False;self.pid=pid
        def read(self,at,n):
            assert not self.closed
            return read(at,n)
        def close(self):self.closed=True;events.append(('close',))
    monkeypatch.setattr(bridge_module,'ReadStream',Stream)
    bridge = Bridge()
    bridge.session,bridge.process = 'recorded-session',SimpleNamespace(pid=-1)
    bridge.plugin_identity = ('recorded-plugin',packet['plugin_identity']['uuid_hex'])
    base = packet['base']
    tables = tuple(base+rva for rva in players.RVA)
    count = 0
    def current(session):
        nonlocal count
        count += 1
        events.append(('callback',count))
        if count in hooks:hooks[count](bridge)
        if bridge.session!=session:raise BridgeError('Recorded session changed')
        return bridge.process
    monkeypatch.setattr(bridge,'_current',current)
    monkeypatch.setattr(bridge,'_player_layout',lambda process:tables)
    save,identity = world.loaded(read,base)
    bridge.world_identity = identity
    refs = []
    for person in packet['requested_people']:
        primary = person['primary']
        _,identity = players.decode(read,primary,tables)
        ref = str(person['person']['database_index'])
        refs.append(ref)
        bridge.player_refs[ref] = dict(tables=tables,address=primary,identity=identity,
            record_kind='actual',world_bound=True,database_index=person['person']['database_index'])
    # Rediscover one matching retained bucket. Missing other buckets are not
    # treated as empty; this does not claim a complete fixture population.
    _,years,inventory = fixtures.catalog(read,base)
    day = date.fromisoformat(packet['fixture_date'])
    ordinal = day.timetuple().tm_yday
    binding = None
    for group in range(len(years[day.year]['groups'])):
        try:entries,route = fixtures.bucket(read,years[day.year],ordinal,group)
        except ValueError:continue
        if packet['fixture_address'] in entries:
            decoded = fixtures.record(read,base,packet['fixture_address'],day.year,ordinal,{})
            assert binding is None
            binding = dict(tables=tables,year=day.year,day=ordinal,group=group,
                slot=entries.index(packet['fixture_address']),group_address=years[day.year]['groups'][group],
                route=route,address=packet['fixture_address'],identity=decoded['identity'],catalog_identity=inventory)
    assert binding is not None
    bridge.fixture_refs['recorded-fixture'] = binding
    events.clear()
    def invoke():return adapter.get_player_ucl_registration(bridge,bridge.session,'recorded-fixture',refs)
    return dict(bridge=bridge,packet=packet,cells=cells,refs=refs,invoke=invoke,events=events,hooks=hooks,read=read)


def test_existing_public_adapter_reproduces_retained_genuine_registration_inputs(recorded):
    result = recorded['invoke']()
    assert result['count']==result['unique_person_count']==19
    assert [row['player_ref']for row in result['players']]==recorded['refs']
    assert result['fixture_context']['native_selector']==0
    assert result['save']['current_date']=='2030-11-30'and result['fixture']['date']=='2030-12-10'
    skipped = 0
    for row in result['players']:
        first = row['requirement14']['native_requirement14'] is True
        if first:
            skipped += 1
            assert row['requirement26']['state']=='not_evaluated_first_requirement14_sufficient'
            assert row['requirement26']['native_result'] is None
        else:
            assert row['requirement26']['native_result'] is False
        covered = row['registration']['native_predicate_result'] is True or first
        assert row['registration_covered_by_current_sources'] is (True if covered else None)
    assert 0<skipped<19
    assert result['requirement26_aggregate']['native_result'] is False
    assert result['requirement26_aggregate']['stored_player_slot_count']==77
    assert len(result['requirement26_aggregate']['rows'])==77
    assert {row['competition']['native_id']for row in result['requirement26_current_club_rule_sources']}=={11,13}
    assert result['current_selection_verified'] is result['full_eligibility_evaluated'] is False
    assert recorded['bridge']._reader is None
    last = recorded['events'].index(('callback',5))
    assert all(event[0] in ('read','close')for event in recorded['events'][last+1:])


@pytest.mark.parametrize('callback',[3,5])
@pytest.mark.parametrize('source',['native_code','medical_holder','canonical_PERSON','current_rule'])
def test_literal_genuine_source_drift_before_and_after_final_rebind_rejects(recorded,callback,source):
    p = recorded['packet']
    keeper = p['requested_people'][0]['primary']
    address = dict(native_code=p['base']+0x177AA7C,medical_holder=keeper+0xF0,
        canonical_PERSON=keeper+0x388+12,current_rule=p['requirement26_goalkeeper_current_club_rules'][0]['runtime']+0x49)[source]
    def mutate(bridge):recorded['cells'][address] ^= 1
    recorded['hooks'][callback] = mutate
    with pytest.raises(BridgeError,match='no partial result'):recorded['invoke']()
    assert recorded['bridge']._reader is None
    assert recorded['events'][-1]==('close',)


@pytest.mark.parametrize('durations,expected',[((35,35),True),((35,None),False),((30,35),False)])
def test_declared_medical_overlay_reaches_existing_public_tool_with_original_native_expectation(recorded,durations,expected):
    # These are synthetic medical controls over genuine registration/identity
    # sources, matching the independently hardened complete-original scenarios.
    p,read,cells = recorded['packet'],recorded['read'],recorded['cells']
    data = p['requirement26_operands']
    context = dict(team=p['current_team'],club=data['club_address'],
        club_teams=tuple(row['address']for row in data['teams']),current_date=p['current_read_date'],current_rules={})
    keepers = []
    for team in data['teams']:
        for slot in team['player_slots']or []:
            person,primary = slot['person'],slot['primary']
            if (person and person.get('goalkeeper_position_rating',0)>=15 and primary not in keepers
                    and adapter.requirement26_source._registered_any(read,p['base'],primary,context)['native_result']):
                keepers.append(primary)
    assert len(keepers)==2
    def put(at,raw):cells.update((at+i,value)for i,value in enumerate(raw))
    today = date.fromisoformat(p['current_read_date'])
    for index,(primary,duration)in enumerate(zip(keepers,durations,strict=True)):
        if duration is None:continue
        header = 0x500000000000+index*0x10000
        entries,record = header+0x1000,header+0x2000
        put(header,struct.pack('<QQQ',entries,entries+8,entries+8))
        put(entries,struct.pack('<Q',record))
        raw = bytearray(0x40)
        struct.pack_into('<HH',raw,0x20,today.timetuple().tm_yday,today.year)
        struct.pack_into('<h',raw,0x28,duration)
        struct.pack_into('<b',raw,0x33,-1)
        put(record,raw)
        put(primary+0xF0,struct.pack('<Q',header))
    result = recorded['invoke']()
    assert result['requirement26_aggregate']['native_result'] is expected
    keeper = next(row for row in result['players']if row['native_identity']['native_id']==98040383)
    assert keeper['requirement26']['native_result'] is expected
    assert keeper['registration_covered_by_current_sources'] is True
    assert result['full_eligibility_evaluated'] is False
