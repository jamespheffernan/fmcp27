"""Canonical synthetic source joins; no native-ID-only or name-based fallback."""
import struct
import pytest
from fm_live_mcp import saved_starting_history_names as names, saved_starting_career as career
from test_saved_club_search import database
from test_saved_squad_search import club
from test_saved_team_search import team
from test_saved_world_search import framed
from test_saved_competition_records import record as competition


def source(clubs=None, teams=None, competitions=None, footer=None):
    return (database(clubs if clubs is not None else [club(0, 688, team_indices=(0,), name='Preston North End')])
            + framed(competitions or []) + framed([])*7 + bytes(12) + framed([])*5
            + framed(teams if teams is not None else [team(0, 650, secondary_id=7)], footer=footer))


def row(t=(650,7), c=(11,22)):
    raw=career.ROW.pack(2020,0,1,0,0,0,*t,*c,0,0,0,0)
    return career.decode_row(raw)


def test_exact_pairs_and_source_attribution():
    data=source(competitions=[b'\0'+competition(native_id=11,secondary_id=22,branch=4,name='Stored League')])
    context=names.prepare(data);rows=[row(),row(t=(650,650)),row(t=(0xffffffff,0xffffffff))]
    names.enrich(data,context,rows)
    ref=rows[0]['team_reference']
    assert ref['name']=='Preston North End' and ref['owner_link_source']=='team_backlink'
    assert ref['club']=={'database_index':0,'native_id':688,'secondary_id':688}
    assert ref['name_source']=='same_snapshot_reciprocal_CLUB_record'
    assert rows[0]['competition_reference']['name']=='Stored League'
    assert rows[0]['competition_reference']['name_source']=='same_snapshot_stored_COMP_record'
    assert rows[1]['team_reference']['state']=='identity_not_found'
    assert rows[2]['team_reference']==row(t=(0xffffffff,0xffffffff))['team_reference']
    assert context.counts==(1,0) and context.memory_bytes<4096


@pytest.mark.parametrize('clubs,teams,state',[
    ([club(0,688,team_indices=(0,))],[team(0,650,secondary_id=7,owner=None)],'resolved_owning_club'),
    ([club(0,688,team_indices=(0,))],[team(0,650,secondary_id=7,owner=1)],'conflicting_club_owner'),
    ([club(0,688)],[team(0,650,secondary_id=7)],'missing_reciprocal_club'),
    ([club(0,688,team_indices=(0,0))],[team(0,650,secondary_id=7)],'ambiguous_club_membership'),
    ([club(0,688,team_indices=(0,))],[team(0,650,secondary_id=7,owner_kind=1)],'non_club_team_owner'),
    ([club(0,688,team_indices=(0,1))],[team(0,650,secondary_id=7),team(1,650,secondary_id=7)],'ambiguous_identity_pair'),
])
def test_owner_and_identity_failures(clubs,teams,state):
    data=source(clubs,teams);context=names.prepare(data);rows=[row()]
    names.enrich(data,context,rows);ref=rows[0]['team_reference']
    assert ref['state']==state
    if state=='resolved_owning_club':assert ref['owner_link_source']=='club_vector_fixup'
    else:assert ref['name']is None


def test_complete_table_checked_after_requested_row():
    data=source(teams=[team(0,650,secondary_id=7),team(1,9)])
    for raw in (data[:-1], data[:-9]+struct.pack('<IBI',250001,0,0)):
        with pytest.raises(ValueError):names.prepare(raw)


def test_cache_bounded_and_no_source_bytes():
    names._CACHE.clear()
    context=names.prepare(source())
    for i in range(6):names.publish(bytes([i]),context)
    assert len(names._CACHE)==4
    assert sum(c.memory_bytes for c in names._CACHE.values())<=names.MAX_CACHE_BYTES
    assert all(not isinstance(v,(bytes,bytearray,memoryview,dict)) for v in vars(context).values())
    names._CACHE.clear()


@pytest.mark.parametrize('value',[None,0,1,'true',[]])
def test_strict_opt_in(value):
    with pytest.raises(ValueError,match='name selection'):
        career.get_starting_history('absent.fm',0,'pin',include_names=value)


def compressed(tmp_path,monkeypatch,*,late=False):
    import test_saved_player_history as prior
    import test_saved_starting_career as old
    import test_saved_competition_state as archives
    from fm_live_mcp import saved_population as population,snapshot_catalog
    from fm_live_mcp.person_wire import parse_record
    prefix=source(teams=[team(0,650,secondary_id=650)])
    body=prior.player()
    native=prior.history._signed(parse_record(body,0,0,limit=len(body))['identity']['native_id_word'])
    database=prefix+body+old.anchor(((native,0),))
    monkeypatch.setattr(archives,'world_database',lambda _:database)
    monkeypatch.setattr(population.saved_name_vectors,'locate',lambda data:prior.Layout(
        data,person_offset=len(prefix),person_records_offset=len(prefix)))
    monkeypatch.setattr(population,'_LAST_LAYOUT',None)
    monkeypatch.setattr(population,'_PREFIXES',__import__('collections').OrderedDict())
    monkeypatch.setattr(career,'_CONTEXT_COUNTS',__import__('collections').OrderedDict())
    monkeypatch.setattr(names,'_CACHE',__import__('collections').OrderedDict())
    path=archives.archive(tmp_path/'names.fm',[],{'pl_hist_ls.dat':old.index((0,))+(b'bad' if late else b''),
                      'pl_hist_dt.cmt':b'\x03\x01tmc.\x03\x00'+old.wire()})
    pin=snapshot_catalog.inspect_snapshot(path.name,directory=tmp_path,limit=1)['snapshot_id']
    return path,pin


def test_compressed_public_opt_in_default_and_cache(tmp_path,monkeypatch):
    path,pin=compressed(tmp_path,monkeypatch)
    def query(**kw):return career.get_starting_history(path.name,0,pin,directory=tmp_path,**kw)
    default=query();explicit=query(include_names=False)
    assert {k:v for k,v in default.items() if k!='PERSON_coverage'}=={k:v for k,v in explicit.items() if k!='PERSON_coverage'}
    assert not names._CACHE
    named=query(include_names=True)
    assert named['rows'][0]['team_reference']['name']=='Preston North End'
    assert named['rows'][0]['team_reference']['native_id_word']==650
    assert default['rows'][0]['team_reference']['name']is None
    assert len(names._CACHE)==1
    monkeypatch.setattr(names,'prepare',lambda _:pytest.fail('canonical context rebuilt on verified digest hit'))
    assert query(include_names=True)==named
    with pytest.raises(ValueError,match='identity changed'):
        career.get_starting_history(path.name,0,'stale',directory=tmp_path,include_names=True)


def test_compressed_late_failure_never_publishes_names(tmp_path,monkeypatch):
    from fm_live_mcp import saved_population as population
    path,pin=compressed(tmp_path,monkeypatch,late=True)
    with pytest.raises(ValueError):
        career.get_starting_history(path.name,0,pin,directory=tmp_path,include_names=True)
    assert not names._CACHE and not career._CONTEXT_COUNTS and population._LAST_LAYOUT is None


def test_competition_ambiguity_and_unserialized_names():
    competitions=[b'\0'+competition(ordinal=i,native_id=11,secondary_id=22) for i in range(2)]
    data=source(competitions=competitions);rows=[row()]
    names.enrich(data,names.prepare(data),rows)
    ref=rows[0]['competition_reference']
    assert ref['state']=='ambiguous_identity_pair' and ref['candidate_count']==2 and ref['name']is None
    data=source(competitions=competitions[:1]);rows=[row()]
    names.enrich(data,names.prepare(data),rows)
    ref=rows[0]['competition_reference']
    assert ref['state']=='matched_identity_pair' and ref['name']is None
    assert ref['stored_name_state']=='not_serialized_by_this_record'


def test_zero_words_are_not_invented_sentinels():
    data=source(teams=[team(0,0,secondary_id=0)])
    rows=[row(t=(0,0)),row(t=(0xffffffff,0))]
    names.enrich(data,names.prepare(data),rows)
    assert rows[0]['team_reference']['state']=='resolved_owning_club'
    assert rows[1]['team_reference']['state']=='identity_not_found'


def test_candidate_projection_cap_retains_ambiguity():
    data=source(teams=[team(i,650,secondary_id=7) for i in range(25)])
    rows=[row()];names.enrich(data,names.prepare(data),rows)
    ref=rows[0]['team_reference']
    assert ref['state']=='ambiguous_identity_pair' and ref['candidate_count']==25
    assert len(ref['candidate_database_indices'])==20 and ref['candidates_omitted']==5


def test_cache_aggregate_budget(monkeypatch):
    from collections import OrderedDict
    monkeypatch.setattr(names,'_CACHE',OrderedDict())
    context=names.prepare(source())
    monkeypatch.setattr(names,'MAX_CACHE_BYTES',context.memory_bytes*2)
    for index in range(4):names.publish(index,context)
    assert list(names._CACHE)==[2,3]
    monkeypatch.setattr(names,'MAX_CACHE_BYTES',context.memory_bytes-1)
    with pytest.raises(ValueError,match='cache budget'):names.publish(5,context)
