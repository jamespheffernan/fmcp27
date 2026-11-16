"""Optional installed labels never change same-save injury identity or core access."""
import pytest
from fm_live_mcp import saved_injury_labels as labels, saved_population as population
from test_saved_player_injury_history import save, query, injury, stored
from test_saved_injury_labels import archive


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.setattr(population,'_LAST_LAYOUT',None)
    population._PREFIXES.clear()
    yield
    population._PREFIXES.clear()


def test_default_and_explicit_false_never_open_resource_and_match(tmp_path, monkeypatch):
    source = save(tmp_path,monkeypatch)
    monkeypatch.setattr(labels,'load_english_injury_labels',lambda: (_ for _ in ()).throw(AssertionError('Unexpected resource read')))
    default = query(source)
    population._PREFIXES.clear(); population._LAST_LAYOUT=None
    explicit = query(source,include_installed_names=False)
    assert explicit == default
    assert 'installed_injury_labels' not in default
    assert all('installed_injury_label' not in row for row in default['rows'])


def test_exact_resource_enriches_primary_ids_preserves_saved_names_and_duplicate_order(tmp_path, monkeypatch):
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',archive(tmp_path))
    source = save(tmp_path,monkeypatch,injuries=[injury(0,100,84),injury(1,84,100)])
    r = query(source,include_installed_names=True)
    assert r['state']=='available' and r['selected_row_count']==3
    assert [row['installed_injury_label']['name'] for row in r['rows']]==['bruised ankle','hernia','hernia']
    assert [row['entry_index'] for row in r['rows']]==[0,1,2]
    assert [row['injury_reference']['identity']['native_id'] for row in r['rows']]==[100,84,84]
    assert [row['injury_reference']['identity']['secondary_id'] for row in r['rows']]==[84,100,100]
    assert all(row['injury_reference']['identity']['display_name'] is None for row in r['rows'])
    assert all(row['injury_reference']['identity']['name_state']=='not_serialized_in_checked_row' for row in r['rows'])
    assert all(row['installed_injury_label']['source']=='installed_database_baseline' for row in r['rows'])
    assert all(row['installed_injury_label']['state']=='available' for row in r['rows'])
    assert r['installed_injury_labels']['status']=='available' and 'labels' not in r['installed_injury_labels']
    assert r['installed_injury_labels']['metadata']['career_display_equivalence']=='unverified'
    assert r['current_availability']=={'state':'not_assessed_by_history_source','value':None}
    page = query(source,injury_native_ids=[100],include_installed_names=True,limit=1)
    assert page['selected_row_count']==1 and page['rows'][0]['installed_injury_label']['sentence_name']=='a bruised ankle'


@pytest.mark.parametrize('state',['unavailable','unsupported'])
def test_optional_resource_failure_preserves_core_rows(tmp_path,monkeypatch,state):
    if state=='unavailable': path=tmp_path/'missing'
    else: path=archive(tmp_path,b'wrong revision')
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',path)
    r=query(save(tmp_path,monkeypatch),include_installed_names=True)
    assert r['state']=='available' and r['selected_row_count']==3
    assert r['installed_injury_labels']['status']==state
    assert all(row['installed_injury_label']['state']=='resource_'+state for row in r['rows'])
    assert all(row['installed_injury_label']['name'] is None for row in r['rows'])


def test_missing_resource_id_and_unresolved_saved_reference_stay_distinct(tmp_path,monkeypatch):
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',archive(tmp_path))
    dt=b'\x03\x01tmc.\x02\0'+stored(0)+stored(-1)+stored(99)
    r=query(save(tmp_path,monkeypatch,injuries=[injury(0,0xFFFFFFFF)],offsets=(0,16,32),dt=dt),include_installed_names=True)
    assert [row['installed_injury_label']['state'] for row in r['rows']]==['native_id_not_in_resource','unresolved_saved_reference','unresolved_saved_reference']
    assert all(row['installed_injury_label']['name'] is None for row in r['rows'])
    assert r['rows'][0]['injury_reference']['identity']['native_id']==0xFFFFFFFF


@pytest.mark.parametrize('value',[None,0,1,'true',[],{}])
def test_strict_opt_in_validation_before_archive_access(value):
    from fm_live_mcp.saved_player_injury_history import get_injury_history
    with pytest.raises(ValueError,match='include_installed_names'):
        get_injury_history('missing.fm',0,'pin',include_installed_names=value)


def test_snapshot_change_during_optional_read_does_not_publish_source_cache(tmp_path,monkeypatch):
    import os
    source=save(tmp_path,monkeypatch)
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',archive(tmp_path))
    original=labels.load_english_injury_labels
    def changed():
        result=original()
        st=source[0].stat()
        os.utime(source[0],ns=(st.st_atime_ns,st.st_mtime_ns+1_000_000))
        return result
    monkeypatch.setattr(labels,'load_english_injury_labels',changed)
    with pytest.raises(ValueError,match='changed'):
        query(source,include_installed_names=True)
    assert not population._PREFIXES and population._LAST_LAYOUT is None
