"""English file binding and actual-scope late-change controls; no live game."""
from copy import deepcopy
from dataclasses import replace
import hashlib
from pathlib import Path
import struct
import pytest
from fm_live_mcp import live_player_concern_history as query, players, virtual_identity, world
from fm_live_mcp.bridge import Bridge, BridgeError
from concern_history_fixture import (live_concerns,agreed_memory,public_assessment_memory,shortlist_public_memory,
    prepared_tactics_memory,member_memory,bridge,database_memory,memory,team_memory,world_memory)
from test_live_player_concern_history import get

import _pinned_build
PLUGIN=_pinned_build.PLUGIN


@pytest.fixture
def verified_english_precondition(live_concerns,monkeypatch):
    """Isolate adapter sequencing from file hashing; helper I/O is tested below.

    This is an injected verified binding, not actual filesystem/live acceptance.
    The core still runs on real typed synthetic memory and pinned native bytes.
    """
    m=live_concerns;calls=[];binding={'path':'labelled verified English fixture','identity':(1,2,3,4,5),'sha256':query.ENGLISH_RESOURCE_SHA256}
    def english(plugin):
        calls.append(plugin);m['events'].append(('english',len(calls)))
        if m.get('on_english'):m['on_english'](len(calls))
        return deepcopy(binding)
    monkeypatch.setattr(query,'_english_binding',english)
    m['english_calls']=calls;m['english_binding']=binding
    return m


def test_optin_decorates_same_raw_rows_and_keeps_context_dependent_templates_null(verified_english_precondition):
    m=verified_english_precondition;result=get(m,include_templates=True);history=result['players'][0]['concern_history']
    assert result['templates_requested']is True and result['english_resource_sha256']==query.ENGLISH_RESOURCE_SHA256
    assert history['native_ring_entry_count']==10 and history['unrendered_description_count']==history['unrendered_description_unknown_count']==2
    first=history['records'][0]['record']['compiled_unrendered_description']
    assert first['native_reason_code']==648 and first['translation_id']is first['english_template']is None
    assert history['records'][3]['record']['compiled_unrendered_description']['english_template']
    assert len(m['english_calls'])==2
    events=m['events'];final_starts=[i for i,event in enumerate(events)if event[0]=='verify_start'][-2:]
    assert max(i for i,event in enumerate(events)if event[0]=='english')<final_starts[0]
    assert all(event[0]in('read','verify_start','verify_end','close')for event in events[final_starts[0]:])


def test_100_alias_template_batch_verifies_resource_twice_not_per_record(verified_english_precondition):
    m=verified_english_precondition;refs=[f'p-{i}'for i in range(100)]
    m['bridge'].player_refs.update({ref:deepcopy(m['initial_binding'])for ref in refs})
    assert get(m,refs,include_templates=True)['count']==100
    assert len(m['english_calls'])==2


def test_last_english_callback_byte_mutation_is_caught_by_final_physical_journal(verified_english_precondition):
    m=verified_english_precondition
    def english(call):
        if call==2:m['put'](m['concern_b']+27,b'\x80')
    m['on_english']=english
    with pytest.raises(BridgeError,match='changed during read'):get(m,include_templates=True)
    assert m['streams'][0].closed


def test_last_english_callback_reference_mutation_is_caught_before_fences(verified_english_precondition):
    m=verified_english_precondition
    def english(call):
        if call==2:m['bridge'].player_refs['p1']['identity']=(99,)
    m['on_english']=english
    with pytest.raises(BridgeError,match='reference binding changed'):get(m,include_templates=True)


def test_last_english_callback_runtime_uuid_mutation_is_in_final_physical_journal(verified_english_precondition):
    m=verified_english_precondition
    def english(call):
        if call==2:m['put'](m['base']+40,b'X')
    m['on_english']=english
    with pytest.raises(BridgeError,match='changed during read'):get(m,include_templates=True)
    assert m['streams'][0].closed


def test_changed_resource_binding_rejects_whole_batch(verified_english_precondition):
    m=verified_english_precondition
    def english(call):
        if call==2:m['english_binding']['identity']=(1,2,3,4,6)
    m['on_english']=english
    with pytest.raises(BridgeError,match='English resource binding changed'):get(m,include_templates=True)


def test_default_raw_never_creates_or_requires_an_english_resource(live_concerns,tmp_path):
    m=live_concerns;plugin=tmp_path/'bundle/Contents/MacOS/plugin';plugin.parent.mkdir(parents=True);plugin.write_bytes(b'plugin fixture')
    m['bridge'].plugin_identity=((str(plugin),1,2,3,4),b'fixture uuid 16b')
    before=set(tmp_path.rglob('*'))
    assert get(m)['templates_requested']is False
    assert set(tmp_path.rglob('*'))==before
    with pytest.raises(BridgeError,match='no partial'):get(m,include_templates=True)
    assert set(tmp_path.rglob('*'))==before


@pytest.mark.parametrize('change',['date','save_count','loaded_career','roster','team_human','refs','plugin','session'])
def test_real_scope_post_yield_context_changes_reject_whole_result(live_concerns,change):
    m=live_concerns
    def current(call):
        if call!=3:return
        if change=='date':m['put'](m['base']+world.CURRENT_DATE,struct.pack('<I',(2030<<16)|263))
        elif change=='save_count':m['put'](m['game']+0xc8,struct.pack('<I',419))
        elif change=='loaded_career':m['q'](m['save']+0x28,m['text']('Changed career'))
        elif change=='roster':m['vec'](m['team']+0x38,[])
        elif change=='team_human':m['q'](m['team']+0x80,m['manager']+8)
        elif change=='refs':m['bridge'].player_refs['p1']['identity']=(99,)
        elif change=='plugin':m['bridge'].plugin_identity=('changed build',)
        else:m['bridge'].session='changed attachment'
    m['on_current']=current
    with pytest.raises(BridgeError,match='no partial'):get(m)
    assert m['streams'][0].closed and m['bridge']._reader is None


@pytest.mark.parametrize('kind',['player_staff','virtual'])
def test_unsupported_roster_kinds_keep_fresh_identity_and_null_history(live_concerns,kind):
    m=live_concerns;primary,person=m['add_person'](kind,1,77,0,'Combined')
    m['vec'](m['headers']['people'],[m['agreed_person'],person]);m['vec'](m['team']+0x38,[m['concern_primary'],primary])
    binding={'address':primary,'tables':m['tables'],'record_kind':kind,'database_index':1,'world_bound':True}
    if kind=='player_staff':binding['identity']=('player_staff',77,'Combined','','2000-02-29',0)
    else:binding.update(binding_kind=virtual_identity.BINDING_KIND,identity=(virtual_identity.BINDING_KIND,1,77,0))
    m['bridge'].player_refs['other']=binding
    result=get(m,['p1','other']);row=result['players'][1]
    assert row['native_identity']=={'database_index':1,'native_id':77,'random_id':0}
    assert row['record_kind']==kind and row['concern_history']['state']=='unsupported_record_kind'
    assert row['concern_history']['records']is row['concern_history']['native_ring_entry_count']is None


def small_resource(tmp_path,monkeypatch):
    plugin=tmp_path/'bundle/Contents/MacOS/plugin';plugin.parent.mkdir(parents=True);plugin.write_bytes(b'plugin fixture')
    resource=plugin.parent.parent/query.ENGLISH_RELATIVE_PATH;resource.parent.mkdir(parents=True);resource.write_bytes(b'Controlled English file fixture')
    monkeypatch.setattr(query,'ENGLISH_RESOURCE_BYTES',resource.stat().st_size)
    monkeypatch.setattr(query,'ENGLISH_RESOURCE_SHA256',hashlib.sha256(resource.read_bytes()).hexdigest())
    return plugin,resource


def test_english_helper_binds_actual_file_descriptor_path_identity_and_digest(tmp_path,monkeypatch):
    plugin,resource=small_resource(tmp_path,monkeypatch)
    result=query._english_binding(((str(plugin),1,2,3,4),bytes(16)))
    assert result['path']==str(resource.resolve())and result['sha256']==hashlib.sha256(resource.read_bytes()).hexdigest()
    assert result==query._english_binding(((str(plugin),1,2,3,4),bytes(16)))


def test_real_player_layout_stamp_shape_reaches_english_file_helper(bridge,tmp_path,monkeypatch):
    # Native verification is explicitly stubbed here. The real Bridge method
    # constructs its stamp, which the actual English file helper must accept.
    plugin,resource=small_resource(tmp_path,monkeypatch)
    process=replace(bridge.process,executable=str(plugin.parent/'fm'),version=players.VERSION)
    monkeypatch.setattr(bridge,'_run',lambda *args:{'images':[{'path':str(plugin),'address':'0x1000'}]})
    monkeypatch.setattr(players,'disk_uuid',lambda path:bytes(16))
    monkeypatch.setattr(players,'verify_runtime',lambda read,base,uuid:tuple(base+rva for rva in players.RVA))
    Bridge._player_layout(bridge,process)
    assert bridge.plugin_identity[0][0]==str(plugin.resolve())
    assert query._english_binding(bridge.plugin_identity)['sha256']==hashlib.sha256(resource.read_bytes()).hexdigest()


@pytest.mark.parametrize('identity',[None,(),('flat path',1,2,3,4),('/flat',bytes(16)),
    (('/nested',1,2,3,4),'not UUID bytes'),(('/nested',1,2,3,4),bytes(15))])
def test_english_helper_rejects_unverified_or_legacy_flat_plugin_stamps(identity):
    with pytest.raises(ValueError,match='Verified game-plugin path'):query._english_binding(identity)


def test_english_helper_rejects_same_size_corruption(tmp_path,monkeypatch):
    plugin,resource=small_resource(tmp_path,monkeypatch);resource.write_bytes(b'X'+resource.read_bytes()[1:])
    with pytest.raises(ValueError,match='digest changed'):query._english_binding(((str(plugin),1,2,3,4),bytes(16)))


def test_english_helper_rejects_change_during_hash(tmp_path,monkeypatch):
    plugin,resource=small_resource(tmp_path,monkeypatch);original=query.hashlib.file_digest
    def mutate(stream,algorithm):
        digest=original(stream,algorithm);resource.write_bytes(resource.read_bytes()+b'changed');return digest
    monkeypatch.setattr(query.hashlib,'file_digest',mutate)
    with pytest.raises(ValueError,match='changed while being read'):query._english_binding(((str(plugin),1,2,3,4),bytes(16)))


@pytest.mark.skipif(not PLUGIN.exists(),reason='Optional installed static English-resource integration; no live process')
def test_real_installed_english_resource_optin_path_with_synthetic_career(live_concerns):
    _pinned_build.language_template()
    m=live_concerns;info=PLUGIN.stat();m['bridge'].plugin_identity=((str(PLUGIN.resolve()),info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns),m['bridge'].plugin_identity[1])
    result=get(m,include_templates=True)
    assert result['english_resource_sha256']=='3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
    assert result['players'][0]['concern_history']['unrendered_description_count']==2
