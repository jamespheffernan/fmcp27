"""Plural pinned profile composition, partial scale and independent contract opt-in."""
from contextlib import contextmanager
import copy
import json
import os
from pathlib import Path
import struct

import pytest

from fm_live_mcp import saved_player_profile_query as query, saved_person_search, snapshot_catalog
from test_saved_player_form_query import fixture_context
from test_saved_club_search import snapshot

RATING_FIXTURES = json.loads((Path(__file__).parent/'fixtures/saved_player_ratings.json').read_text())['rows']


@pytest.fixture
def context(monkeypatch):
    ctx=fixture_context()
    data=bytearray(ctx['data'])
    source=RATING_FIXTURES[0]
    data[61:130]=bytes.fromhex(source['raw69_hex'])
    struct.pack_into('<hh',data,37,159,-95)
    data[355]=source['scale_byte']
    ctx['data']=bytes(data)
    ctx['ranked'][0]['candidates'][0]['names']=[{'text':'Anthony','raw_hex':'416e74686f6e79'}, {'text':'Gordon','raw_hex':'476f72646f6e'}, None]
    ctx['calls']=[]
    @contextmanager
    def checked(filename,indices,pin,**kwargs):
        assert filename=='source.fm' and pin=='pin'
        ctx['calls'].append(indices)
        yield ctx
    monkeypatch.setattr(saved_person_search,'checked_person_context',checked)
    monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda data,start,bound:dict(start=start,end=180,state='present',f0_start=180))
    monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda data,start,bound:dict(start=start,end=200,state='present',form_start=200))
    return ctx


def get(indices=None,**kwargs):
    return query.get_player_profiles('source.fm',[10]if indices is None else indices,'pin',**kwargs)


def test_compact_complete_profile_fixed_offsets_and_signed_ability(context):
    reply=get();row=reply['people'][0]
    assert row['state']=='available'
    for group,values in RATING_FIXTURES[0]['expected'].items():
        assert row['profile'][group]==values
    assert row['profile']['ability']=={'current':159,'potential':-95}
    assert row['scale_context']['stored_scale_byte']==128
    assert row['scale_context']['attribute_scale']=='1-20'
    assert row['scale_context']['position_scale']=='0-20'
    assert row['source_context']['raw69_start']==61 and row['source_context']['raw69_end']==130
    assert row['source_context']['current_ability_offset']==37 and row['source_context']['potential_ability_offset']==39
    assert row['source_context']['scale_offset']==355
    assert row['source_context']['actual_person_body_unread']
    assert row['unavailable_fields']=={}
    assert row['identity']['native_id_word']==111 and row['identity']['secondary_word']==222
    assert row['name_context']['names']=={'first':'Anthony','second':'Gordon','common':None}
    assert not row['evidence_scope']['certified_person_record']
    assert 'current_contract' not in row


def test_request_order_duplicates_and_one_deduplicated_context(context,monkeypatch):
    missing=copy.deepcopy(context['ranked'][0]);missing.update(person_index=11,state='missing',candidates=[])
    context['ranked'].append(missing)
    original=query.traverse_player;calls=[]
    def track(data,geometry):
        calls.append(geometry['record_start']);return original(data,geometry)
    monkeypatch.setattr(query,'traverse_player',track)
    reply=get([10,11,10])
    assert context['calls']==[[10,11]] and calls==[30]
    assert [r['person_index']for r in reply['people']]==[10,11,10]
    assert [r['state']for r in reply['people']]==['available','unavailable','available']
    assert reply['people'][0]==reply['people'][2]


def test_group_and_named_field_projection(context):
    row=get(fields=['positions','attributes.passing','ability.potential','attributes.passing'])['people'][0]
    assert set(row['profile'])=={'positions','attributes','ability'}
    assert row['profile']['attributes']=={'passing':13}
    assert row['profile']['ability']=={'potential':-95}
    assert len(row['profile']['positions'])==14
    assert row['unavailable_fields']=={}


def test_missing_scale_is_partial_with_usable_positions_and_signed_ability(context,monkeypatch):
    monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=180,state='stopped',stop_reason='unknown_positive_child',next_native_reader='child'))
    row=get()['people'][0]
    assert row['state']=='partial'
    assert row['profile']['attributes']['passing'] is None
    assert row['profile']['positions']==RATING_FIXTURES[0]['expected']['positions']
    assert row['profile']['ability']=={'current':159,'potential':-95}
    assert row['scale_context']['stored_scale_byte'] is None
    assert row['unavailable_fields']['attributes.passing']['state']=='scale_unavailable'
    assert row['unavailable_fields']['attributes.passing']['native_getter_value'] is None
    assert row['source_context']['stop_reason']=='unknown_positive_child'


def test_out_of_domain_nulls_preserve_native_getter_without_erasing_other_ratings(context):
    data=bytearray(context['data']);data[61+query.saved_player_ratings.ATTRIBUTES['passing']]=255;context['data']=bytes(data)
    row=get()['people'][0]
    assert row['state']=='partial' and row['source_context']['player_specific_tail_complete']
    assert row['profile']['attributes']['passing'] is None
    assert row['profile']['attributes']['crossing']==16
    assert row['unavailable_fields']['attributes.passing']==dict(state='raw_outside_supported_domain',raw_u8=255,native_getter_value=1)


def test_zero_low_scale_and_high_scale_follow_getter_not_missing_sentinel(context):
    data=bytearray(context['data']);data[61:130]=bytes(69);data[355]=0;context['data']=bytes(data)
    row=get()['people'][0]
    assert row['state']=='available' and row['profile']['attributes']['passing']==0
    assert row['profile']['positions']['goalkeeper']==0
    data[355]=128;context['data']=bytes(data)
    row=get()['people'][0]
    assert row['profile']['attributes']['passing']==1
    assert row['profile']['positions']['goalkeeper']==0


def test_F0_absence_skips_form_children_but_still_reaches_scale_and_actual(context,monkeypatch):
    data=bytearray(context['data']);data[180:400]=bytes(220);data[218]=128;context['data']=bytes(data)
    monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=180,state='absent'))
    monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:pytest.fail('absentF0'))
    monkeypatch.setattr(query.saved_form_tail,'read_tail',lambda *args:pytest.fail('absentF0'))
    row=get()['people'][0]
    assert row['state']=='available' and row['source_context']['scale_offset']==218
    geometry=row['typed_start_candidates'][0]
    traversed=query.traverse_player(context['data'],geometry)
    assert traversed['state']=='complete' and traversed['actual_person_start']==226
    assert traversed['form_state']=='not_stored_F0_absent'


def test_form_absence_skips_siblings_and_still_walks_player_tail(context,monkeypatch):
    data=bytearray(context['data']);data[200:400]=bytes(200);data[238]=128;context['data']=bytes(data)
    monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:dict(start=180,end=200,state='absent'))
    monkeypatch.setattr(query.saved_form_tail,'read_tail',lambda *args:pytest.fail('absentgroups'))
    row=get()['people'][0]
    assert row['state']=='available' and row['source_context']['scale_offset']==238


def test_present_zero_groups_still_consumes_form_siblings(context):
    data=bytearray(context['data']);data[200:400]=bytes(200);data[241]=128;context['data']=bytes(data)
    row=get()['people'][0]
    assert row['state']=='available'
    assert row['source_context']['checked_ranges']['form_groups']==dict(start=200,end=201)
    assert row['source_context']['checked_ranges']['form_siblings']==dict(start=201,end=203)
    assert row['source_context']['scale_offset']==241


@pytest.mark.parametrize('stage',['front','container','groups','siblings','tail','scale'])
def test_all_traversal_ranges_and_scale_are_bound_to_common_start(context,monkeypatch,stage):
    if stage=='front':monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=401,state='present',f0_start=401))
    elif stage=='container':monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:dict(start=180,end=401,state='present',form_start=401))
    elif stage=='groups':monkeypatch.setattr(query.saved_form_rows,'read_groups',lambda reader:dict(start=200,end=401))
    elif stage=='siblings':monkeypatch.setattr(query.saved_form_tail,'read_tail',lambda *args:dict(start=315,end=401,state='complete',siblings_complete=True))
    else:
        def bad(reader):
            reader.offset=401 if stage=='tail'else 363
            return dict(start=317,end=reader.offset,actual_person_start=reader.offset,complete_player_specific_tail=True,scale_offset=355,scale_byte=127)
        monkeypatch.setattr(query.saved_player_tail,'read_tail',bad)
    row=get()['people'][0]
    assert row['state']=='partial' and row['scale_context']['stored_scale_byte'] is None
    assert row['profile']['attributes']['passing'] is None
    assert not row['source_context']['player_specific_tail_complete']


def test_partial_player_tail_does_not_export_ACTUAL_PERSON_or_decode_contract(context,monkeypatch):
    data=bytearray(context['data']);data[317:319]=b'\1\3';context['data']=bytes(data)
    monkeypatch.setattr(query.saved_primary_contract,'read_primary_contract',lambda *args,**kwargs:pytest.fail('unreachedactual'))
    row=get(include_current_contract=True)['people'][0]
    assert row['state']=='partial' and row['current_contract']['state']=='unavailable'
    traversed=query.traverse_player(context['data'],row['typed_start_candidates'][0])
    assert traversed['actual_person_start'] is None


@pytest.mark.parametrize('which',['search','neighbour','ambiguous'])
def test_incomplete_or_competing_candidates_do_not_choose_profile(context,monkeypatch,which):
    if which=='search':context['ranked'][0]['search_complete']=False
    elif which=='neighbour':context['ranked'][0]['neighbour_corroboration']['search_complete']=False
    else:
        original=query.saved_player_form_query._starts
        def two(*args):
            geometries,rejected,exhausted=original(*args)
            return geometries+[dict(geometries[0],record_start=31)],rejected,exhausted
        monkeypatch.setattr(query.saved_player_form_query,'_starts',two)
    monkeypatch.setattr(query,'traverse_player',lambda *args:pytest.fail('no selection'))
    row=get(include_current_contract=True)['people'][0]
    assert row['state']==('competing_candidates'if which=='ambiguous'else'incomplete_candidates')
    assert row['profile'] is None and row['current_contract']['state']=='unavailable'


def test_optional_contract_is_independent_of_fields_and_preserves_available_ratings(context,monkeypatch):
    calls=[]
    def contract(data,actual,common,**kwargs):
        calls.append((actual,common,kwargs))
        return dict(state='unsupported',reason='other_kind',actual_person_start=actual,exclusive_common_start=common,checked_ranges=[])
    monkeypatch.setattr(query.saved_primary_contract,'read_primary_contract',contract)
    plain=get(fields=['ability'])['people'][0]
    assert 'current_contract'not in plain and calls==[]
    row=get(fields=['ability'],include_current_contract=True)['people'][0]
    assert row['state']=='available' and row['profile']['ability']=={'current':159,'potential':-95}
    assert row['current_contract']['state']=='unsupported'
    assert calls==[(363,400,{'person_index':10,'base_currency_code':None})]


@pytest.mark.parametrize('state',['available','dynamic_expiry','no_current_contract'])
def test_owner_checked_contract_shapes_preserve_dynamic_and_null(context,monkeypatch,state):
    def contract(data,actual,common,**kwargs):
        return dict(state=state,actual_person_start=actual,exclusive_common_start=common,checked_ranges=[],
                    source_kind=-1 if state=='no_current_contract'else 0,
                    source_start=390,source_end=390 if state=='no_current_contract'else 399,
                    owner_person_index=10,primary_contract_wire_complete=state!='no_current_contract',
                    contract_dates=None if state=='no_current_contract'else dict(last_signed='2030-01-01',expires=None if state=='dynamic_expiry'else'2033-06-30'))
    monkeypatch.setattr(query.saved_primary_contract,'read_primary_contract',contract)
    row=get(include_current_contract=True)['people'][0]
    assert row['state']=='available' and row['current_contract']['state']==state
    if state=='dynamic_expiry':assert row['current_contract']['contract_dates']['expires'] is None


def test_contract_owner_or_bounds_mismatch_does_not_erase_ratings(context,monkeypatch):
    monkeypatch.setattr(query.saved_primary_contract,'read_primary_contract',lambda data,actual,common,**kwargs:dict(
        state='available',actual_person_start=actual,exclusive_common_start=common,checked_ranges=[],
        source_kind=0,source_start=390,source_end=399,owner_person_index=11,primary_contract_wire_complete=True))
    row=get(include_current_contract=True)['people'][0]
    assert row['state']=='available' and row['current_contract']['state']=='unsupported'
    assert row['profile']['attributes']['passing']==13


@pytest.mark.parametrize('kwargs',[
    dict(person_indices=[]),dict(person_indices=[True]),dict(person_indices=[-1]),dict(person_indices=[2**31]),dict(person_indices=[10]*33),
    dict(fields=[]),dict(fields=['unknown']),dict(fields=['attributes.nope']),dict(fields=[1]),dict(fields=['positions']*129),
    dict(include_current_contract=1),dict(fields=['current_contract']),
])
def test_invalid_selectors_indices_and_optin_reject_before_source(monkeypatch,kwargs):
    monkeypatch.setattr(saved_person_search,'checked_person_context',lambda *args,**kwargs:pytest.fail('sourceaccess'))
    args=dict(filename='source.fm',person_indices=[10],expected_snapshot_id='pin');args.update(kwargs)
    with pytest.raises(ValueError):query.get_player_profiles(**args)


def test_real_archive_pin_and_postdecode_replacement_abort(tmp_path,monkeypatch):
    ctx=fixture_context();ctx['ranked'][0]['candidates'][0]['names']=[{'text':'a'},{'text':'b'},None]
    path=snapshot(tmp_path/'source.fm',ctx['data'])
    with snapshot_catalog.checked_snapshot(path.name,directory=tmp_path)as(_,_,identity):pin=snapshot_catalog.snapshot_id(identity)
    monkeypatch.setattr(saved_person_search.saved_name_vectors,'locate',lambda data:ctx['layout'])
    monkeypatch.setattr(saved_person_search.saved_person_candidates,'search_candidates',lambda *args:ctx['ranked'])
    monkeypatch.setattr(saved_person_search.saved_person_neighbours,'corroborate_candidates',lambda data,layout,rows,**kw:rows)
    monkeypatch.setattr(query.saved_form_player,'locate_f0',lambda *args:dict(start=30,end=180,state='present',f0_start=180))
    monkeypatch.setattr(query.saved_form_container,'locate_form_groups',lambda *args:dict(start=180,end=200,state='present',form_start=200))
    with pytest.raises(ValueError,match='changed'):
        query.get_player_profiles(path.name,[10],pin[::-1],directory=tmp_path)
    original=query.saved_player_ratings.decode
    def replace(*args):
        result=original(*args);other=snapshot(tmp_path/'other.fm',ctx['data']);os.replace(other,path);return result
    monkeypatch.setattr(query.saved_player_ratings,'decode',replace)
    with pytest.raises(ValueError,match='changed during request'):
        query.get_player_profiles(path.name,[10],pin,directory=tmp_path)


@pytest.mark.parametrize('source', RATING_FIXTURES, ids=lambda row: str(row['identity']['database_index']))
def test_all_28_independent_rating_byte_controls_reach_compact_projection(context, source):
    # These are source-byte controls inside a synthetic qualified envelope;
    # the lead's archive acceptance separately checks their actual boundaries.
    data = bytearray(context['data'])
    data[61:130] = bytes.fromhex(source['raw69_hex'])
    data[355] = source['scale_byte']
    context['data'] = bytes(data)
    row = get()['people'][0]
    assert row['state'] == 'available'
    for group_name, expected in source['expected'].items():
        assert row['profile'][group_name] == expected
    assert row['scale_context']['stored_scale_byte'] == source['scale_byte']


def test_unsupported_position_preserves_signed_getter_without_classification(context):
    data = bytearray(context['data'])
    data[61 + query.saved_player_ratings.POSITIONS['striker']] = 255
    context['data'] = bytes(data)
    row = get()['people'][0]
    assert row['state'] == 'partial' and row['profile']['positions']['striker'] is None
    assert row['unavailable_fields']['positions.striker'] == dict(
        state='raw_outside_supported_domain', raw_u8=255, native_getter_value=-1)
    assert 'is_goalkeeper' not in row['profile']


def test_exported_traversal_checks_initial_offsets_and_bound_before_read(context):
    geometry = get()['people'][0]['typed_start_candidates'][0]
    with pytest.raises(ValueError, match='bound'):
        query.traverse_player(context['data'], dict(geometry, common_start=100))
    with pytest.raises(ValueError, match='geometry'):
        query.traverse_player(context['data'], dict(geometry, wire_profile='raw32'))


def test_new_tool_strict_optin_and_fields_schema():
    import asyncio
    from fm_live_mcp.server import mcp
    tools = asyncio.run(mcp.list_tools())
    tool = next(tool for tool in tools if tool.name == 'fm_get_saved_player_profiles')
    schema = tool.inputSchema
    assert schema['required'] == ['filename', 'person_indices', 'expected_snapshot_id']
    assert schema['properties']['include_current_contract']['type'] == 'boolean'
    assert schema['properties']['include_current_contract']['default'] is False
    assert schema['properties']['person_indices']['maxItems'] == 32
    assert tool.annotations.readOnlyHint is True
