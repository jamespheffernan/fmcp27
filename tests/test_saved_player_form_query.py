"""Pinned public form composition: selection, source bounds, row pagination."""
from contextlib import contextmanager
import copy
import os
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_player_form_query as query, saved_person_search, snapshot_catalog
from test_saved_club_search import snapshot
from test_saved_form_rows import ACTUAL_ROW, absent, group


def fixture_context():
    data = bytearray(500)
    struct.pack_into('<IB', data, 0, 100, 1)
    struct.pack_into('<III', data, 18, 9, 33, 44)
    data[30] = 2
    common = struct.pack('<iBiBiB', 1, 0, 2, 0, -1, 0) + bytes(4 + 38 + 2)
    data[400:459] = common
    struct.pack_into('<III', data, 467, 10, 111, 222)
    data[479] = 16
    forms = b'\3' + group([absent(), absent()], owner=0) + group([], kind=60, owner=0xffffffff) + group([ACTUAL_ROW], owner=545)
    data[200:200 + len(forms)] = forms
    prefix = dict(start=30, end=157, state='typed_prefix_stopped', native_reader='0xCFD388',
                  wire_profile=query.saved_player_wire_prefix.WIRE_PROFILE,
                  validated_markers=[dict(offset=30, kind='ACTUAL_PLAYER_tag', value=2)])
    candidate = dict(common_start=400, common_end=459, identity_offset=467, end=479,
                     identity=dict(stored_index=10, native_id_word=111, secondary_word=222),
                     name_indices=[1, 2, -1],
                     neighbour_evidence={'preceding': [dict(person_index=9, end=30, identity_offset=18,
                                                            target_prefix=prefix)]})
    target = dict(person_index=10, state='witnessed', search_complete=True, budget_reasons=[],
                  evidence_scope={'certified_person_record': False}, candidates=[candidate],
                  neighbour_corroboration={'search_complete': True})
    return dict(data=bytes(data), layout=SimpleNamespace(person_count=100, person_offset=0,
                                                       name_counts=dict(first=10, second=10, common=10)),
                ranked=[target], snapshot_id='pin', saved_metadata={'status': 'unknown'})


@pytest.fixture
def context(monkeypatch):
    ctx = fixture_context()
    @contextmanager
    def checked(filename, indices, pin, **kwargs):
        assert filename == 'source.fm' and indices == [10] and pin == 'pin'
        yield ctx
    monkeypatch.setattr(saved_person_search, 'checked_person_context', checked)
    monkeypatch.setattr(query.saved_form_player, 'locate_f0',
                        lambda data, start, bound: dict(start=start, end=180, state='present', f0_start=180))
    monkeypatch.setattr(query.saved_form_container, 'locate_form_groups',
                        lambda data, start, bound: dict(start=start, end=200, state='present', form_start=200))
    return ctx


def get(**kwargs):
    return query.get_player_form('source.fm', 10, 'pin', **kwargs)


def test_original_pagination_across_empty_groups_and_nullable_stats(context):
    first = get(limit=2)
    form = first['form']
    assert form['state'] == 'available' and form['form_groups_complete']
    assert form['total_row_count'] == 3 and form['next_offset'] == 2
    assert [r['form_row_index'] for r in form['rows']] == [0, 1]
    assert [r['group_ordinal'] for r in form['rows']] == [0, 0]
    assert form['rows'][0]['date'] == form['rows'][1]['date']
    assert form['rows'][0]['stats']['goals'] is None
    assert form['rows'][0]['stats']['rating_tenths'] is None
    assert form['rows'][0]['stats']['played_minutes'] is None
    assert form['rows'][0]['stats']['played_minutes_state'] == 'not_stored'
    assert [(g['group_ordinal'], g['serialized_row_count']) for g in form['groups']] == [(0, 2), (1, 0), (2, 1)]
    assert form['groups'][0]['stored_group_team_index'] == 0
    assert form['groups'][0]['owner_reference_table'] == 'TEAM_BASE'
    assert form['groups'][1]['owner_reference_word'] == 0xffffffff
    assert form['groups'][1]['stored_group_team_index'] is None
    assert form['groups'][2]['stored_group_team_index'] == 545
    last = get(offset=2, limit=2)['form']
    assert [(r['form_row_index'], r['group_ordinal'], r['row_index']) for r in last['rows']] == [(2, 2, 0)]
    assert last['rows'][0]['stats']['goals'] == 3
    assert last['rows'][0]['stats']['played_minutes'] == 67
    assert last['rows'][0]['date']['value'] == '2030-07-10'  # Do not infer/filter by snapshot date.
    assert last['next_offset'] is None and len(last['groups']) == 3
    assert not first['evidence_scope']['certified_person_record']
    assert not first['evidence_scope']['reference_identities_resolved']


def test_wholly_read_empty_section_differs_from_absent_and_missing(context, monkeypatch):
    data = bytearray(context['data']); data[200] = 0; context['data'] = bytes(data)
    form = get()['form']
    assert form['state'] == 'available' and form['total_row_count'] == 0
    assert form['group_count'] == 0 and form['form_groups_complete'] and form['form_section_present']
    monkeypatch.setattr(query.saved_form_player, 'locate_f0',
                        lambda *args: dict(start=30, end=180, state='absent'))
    form = get()['form']
    assert form['state'] == 'absent' and form['form_section_present'] is False
    assert form['total_row_count'] is None and not form['form_groups_complete']
    context['ranked'][0]['candidates'] = []
    form = get()['form']
    assert form['state'] == 'unavailable' and form['form_section_present'] is None
    assert form['total_row_count'] is None


def test_actual_form_absence_and_stops_are_distinct(context, monkeypatch):
    monkeypatch.setattr(query.saved_form_container, 'locate_form_groups',
                        lambda *args: dict(start=180, end=200, state='absent'))
    assert get()['form']['state'] == 'absent'
    monkeypatch.setattr(query.saved_form_container, 'locate_form_groups',
                        lambda *args: dict(start=180, end=200, state='stopped', stop_reason='positive_unparsed', next_native_reader='child'))
    form = get()['form']
    assert form['state'] == 'stopped' and form['reason'] == 'positive_unparsed'
    assert form['total_row_count'] is None and not form['form_groups_complete']


@pytest.mark.parametrize('which', ['candidate', 'neighbour'])
def test_incomplete_search_never_chooses_candidate(context, monkeypatch, which):
    target = context['ranked'][0]
    if which == 'candidate':
        target['search_complete'] = False
        target['budget_reasons'] = ['source_budget']
    else:
        target['neighbour_corroboration']['search_complete'] = False
    monkeypatch.setattr(query.saved_form_player, 'locate_f0', lambda *args: pytest.fail('must not decode an incomplete selection'))
    reply = get()
    assert reply['form']['state'] == 'incomplete_candidates' and reply['form']['rows'] == []
    assert reply['typed_start_candidates']


def test_competing_starts_retained_without_preference_filter(context, monkeypatch):
    other = copy.deepcopy(context['ranked'][0]['candidates'][0])
    previous = other['neighbour_evidence']['preceding'][0]
    previous.update(identity_offset=19, end=31)
    previous['target_prefix'].update(start=31, end=158,
                                    validated_markers=[dict(offset=31, kind='ACTUAL_PLAYER_tag', value=2)])
    # A second independently reported start is byte-bound; both stay candidates.
    monkeypatch.setattr(query.saved_person_neighbours, '_common_packet', lambda *args: {})
    data = bytearray(context['data']);struct.pack_into('<I', data, 19, 9);data[31]=2
    # Restore the first preceding ordinal too by using a non-overlapping second start.
    previous.update(identity_offset=50, end=62)
    previous['target_prefix'].update(start=62, end=189,
                                    validated_markers=[dict(offset=62, kind='ACTUAL_PLAYER_tag', value=2)])
    struct.pack_into('<I', data, 18, 9);struct.pack_into('<I', data, 50, 9);data[30]=data[62]=2
    context['data'] = bytes(data)
    context['ranked'][0]['candidates'].append(other)
    context['ranked'][0]['neighbour_corroboration']['preferred_geometries'] = [{'common_start':400,'identity_offset':467}]
    monkeypatch.setattr(query.saved_form_player, 'locate_f0', lambda *args: pytest.fail('must not choose a competing start'))
    reply = get()
    assert reply['form']['state'] == 'competing_candidates'
    assert [g['record_start'] for g in reply['typed_start_candidates']] == [30, 62]


@pytest.mark.parametrize('damage', ['source_ordinal', 'source_tag', 'prefix_profile', 'tag_marker', 'bound', 'identity_word'])
def test_unbound_typed_packets_never_qualify(context, damage):
    target = context['ranked'][0];w = target['candidates'][0]
    previous = w['neighbour_evidence']['preceding'][0]
    data = bytearray(context['data'])
    if damage == 'source_ordinal':struct.pack_into('<I', data,18,8)
    elif damage == 'source_tag':data[30]=3
    elif damage == 'prefix_profile':previous['target_prefix']['wire_profile']='other'
    elif damage == 'tag_marker':previous['target_prefix']['validated_markers']=[]
    elif damage == 'bound':previous['target_prefix']['end']=401
    else:w['identity']['native_id_word']=0
    context['data']=bytes(data)
    assert get()['form']['state'] == 'unavailable'


@pytest.mark.parametrize('stage', ['front', 'container', 'groups'])
def test_every_handoff_is_bounded_by_common_start(context, monkeypatch, stage):
    if stage == 'front':
        monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=401,state='present',f0_start=401))
    elif stage == 'container':
        monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:dict(start=180,end=401,state='present',form_start=401))
    else:
        monkeypatch.setattr(query.saved_form_rows,'read_groups',lambda reader:dict(start=200,end=401))
    form = get()['form']
    assert form['state'] == 'stopped' and 'bound' in form['reason']
    assert form['rows'] == [] and form['total_row_count'] is None


def test_unsupported_row_after_requested_page_does_not_return_partial_success(context):
    data = bytearray(context['data'])
    # The final group's first row version follows group0 (10+30), emptygroup1(10), group2header(10).
    data[200+1+40+10+10]=255
    context['data']=bytes(data)
    form=get(limit=1)['form']
    assert form['state']=='stopped' and form['rows']==[] and form['total_row_count'] is None


def test_original_row_offset_past_end_is_empty_complete_page(context):
    form=get(offset=100)['form']
    assert form['state']=='available' and form['rows']==[] and form['total_row_count']==3
    assert form['next_offset'] is None and len(form['groups'])==3


def test_geometry_work_budget_is_explicit_incomplete(context, monkeypatch):
    monkeypatch.setattr(query,'MAX_INSPECTED_PACKETS',0)
    result=get()
    assert result['form']['state']=='incomplete_candidates'
    assert not result['candidate_search']['typed_start_summary_complete']


def test_empty_group_summary_cap_cannot_be_silently_truncated(context, monkeypatch):
    monkeypatch.setattr(query,'MAX_GROUP_SUMMARIES',2)
    form=get()['form']
    assert form['state']=='stopped' and form['groups']==[] and form['group_count'] is None


@pytest.mark.parametrize('kwargs', [dict(person_index=True),dict(person_index=-1),dict(offset=True),dict(offset=-1),dict(limit=0),dict(limit=501),dict(limit=True)])
def test_invalid_arguments_rejected_before_source_access(monkeypatch, kwargs):
    monkeypatch.setattr(saved_person_search,'checked_person_context',lambda *args,**kw:pytest.fail('source access'))
    args=dict(filename='source.fm',person_index=10,expected_snapshot_id='pin');args.update(kwargs)
    with pytest.raises(ValueError):query.get_player_form(**args)


def test_real_archive_pin_and_replacement_gate(tmp_path, monkeypatch):
    ctx=fixture_context();path=snapshot(tmp_path/'source.fm',ctx['data'])
    with snapshot_catalog.checked_snapshot(path.name,directory=tmp_path)as(_,_,identity):pin=snapshot_catalog.snapshot_id(identity)
    monkeypatch.setattr(saved_person_search.saved_name_vectors,'locate',lambda data:ctx['layout'])
    monkeypatch.setattr(saved_person_search.saved_person_candidates,'search_candidates',lambda *args:[ctx['ranked'][0]])
    monkeypatch.setattr(saved_person_search.saved_person_neighbours,'corroborate_candidates',lambda data,layout,rows,**kw:rows)
    monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=180,state='present',f0_start=180))
    monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:dict(start=180,end=200,state='present',form_start=200))
    result=query.get_player_form(path.name,10,pin,directory=tmp_path)
    assert result['snapshot_id']==pin and result['form']['state']=='available'
    with pytest.raises(ValueError,match='changed'):
        query.get_player_form(path.name,10,pin[::-1],directory=tmp_path)
    original=query.saved_form_rows.read_groups
    def replace(reader):
        result=original(reader)
        other=snapshot(tmp_path/'other.fm',ctx['data']);os.replace(other,path)
        return result
    monkeypatch.setattr(query.saved_form_rows,'read_groups',replace)
    with pytest.raises(ValueError,match='changed during request'):
        query.get_player_form(path.name,10,pin,directory=tmp_path)


def test_empty_group_zero_and_null_owner_survive_row_pagination(context):
    raw = b'\3' + group([], owner=0) + group([], kind=60, owner=0xffffffff) + group([ACTUAL_ROW], owner=545)
    data = bytearray(context['data']);data[200:200+len(raw)] = raw;context['data'] = bytes(data)
    result = get(limit=1)['form']
    assert result['state'] == 'available' and result['total_row_count'] == 1
    assert [(g['group_ordinal'], g['serialized_row_count']) for g in result['groups']] == [(0,0),(1,0),(2,1)]
    assert result['groups'][0]['stored_group_team_index'] == 0
    assert result['groups'][1]['stored_group_team_index'] is None
    assert result['rows'][0]['group_ordinal'] == 2 and result['rows'][0]['row_index'] == 0
    assert result['rows'][0]['form_row_index'] == 0


def test_zero_rating_row_is_retained_as_stored_not_absent(context):
    # Last group's first row starts after the original two absent rows and empty group.
    row_start = 200 + 1 + 40 + 10 + 10
    data = bytearray(context['data']);data[row_start+40] = 0;context['data'] = bytes(data)
    result = get(offset=2)['form']
    assert result['total_row_count'] == 3 and len(result['rows']) == 1
    stats = result['rows'][0]['stats']
    assert stats['state'] == 'stored' and stats['rating_tenths'] == 0
    assert stats['native_rating_nonzero_filter_passes'] is False
    assert stats['rating_zero_reason'] == 'not_established'


def test_present_zero_duration_is_paged_without_unused_or_starter_inference(context):
    row_start = 200 + 1 + 40 + 10 + 10
    data = bytearray(context['data'])
    data[row_start + 35] = 90  # Native on-minute field; present zero is meaningful.
    data[row_start + 39] = 0
    context['data'] = bytes(data)
    result = get(offset=2, limit=1)
    row = result['form']['rows'][0]
    assert (row['form_row_index'], row['group_ordinal'], row['row_index']) == (2, 2, 0)
    assert row['stats']['played_minutes'] == 0
    assert row['stats']['played_minutes_state'] == 'stored'
    assert row['stats']['played_minutes_raw_u8'] == 0
    assert 'unused' not in row['stats'] and 'starter' not in row['stats']
    assert result['evidence_scope']['appearance_status'].startswith('not inferred')
