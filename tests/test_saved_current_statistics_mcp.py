"""Public strict inputs and real current-wire/rank state composition."""
import asyncio
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest
from mcp.server.fastmcp.exceptions import ToolError

from fm_live_mcp import saved_current_statistics as current, server
from test_saved_current_statistics import component, name_target, query_source, record, stats

TOOL = 'fm_compare_saved_current_player_statistics'
ARGS = dict(filename='career.fm', person_indices=[1], expected_snapshot_id='a' * 64)


def invoke(**changes):
    return asyncio.run(server.mcp.call_tool(TOOL, {**ARGS, **changes}))[1]


def test_public_schema_and_read_only_boundary():
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == TOOL)
    schema = tool.inputSchema
    assert set(schema['required']) == {'filename', 'person_indices', 'expected_snapshot_id'}
    assert set(schema['properties']) == set(ARGS) | {'category_code', 'minimum_minutes'}
    indices = schema['properties']['person_indices']
    assert indices['minItems'] == 1 and indices['maxItems'] == 32
    assert indices['items']['minimum'] == 0 and indices['items']['exclusiveMaximum'] == 2**31
    assert schema['properties']['category_code'] == dict(default=1, minimum=0, maximum=5,
                                                         title='Category Code', type='integer')
    assert schema['properties']['minimum_minutes']['default'] == 270
    assert schema['properties']['minimum_minutes']['minimum'] == 1
    assert schema['properties']['minimum_minutes']['maximum'] == 32767
    assert schema['properties']['expected_snapshot_id']['pattern'] == '^[0-9a-f]{64}$'
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False and tool.annotations.openWorldHint is False
    text = tool.description.lower()
    assert 'not proven statistics for the selected roster' in text
    assert 'not match or registration eligibility' in text
    assert 'ambiguous display name' in text and 'season' in text


@pytest.mark.parametrize('changes', [
    {'person_indices': []}, {'person_indices': [True]}, {'person_indices': ['1']},
    {'person_indices': [-1]}, {'person_indices': [2**31]}, {'person_indices': [1] * 33},
    {'category_code': True}, {'category_code': '1'}, {'category_code': -1}, {'category_code': 6},
    {'minimum_minutes': True}, {'minimum_minutes': '270'}, {'minimum_minutes': 0}, {'minimum_minutes': 32768},
    {'expected_snapshot_id': ''}, {'expected_snapshot_id': 'A' * 64},
    {'expected_snapshot_id': None}, {'filename': True}, {'filename': ''},
])
def test_strict_public_rejection_precedes_source_access(changes):
    with patch.object(current, 'compare_current_statistics') as called:
        with pytest.raises(ToolError, match='validation'):
            invoke(**changes)
        called.assert_not_called()


def test_public_dispatch_preserves_default_and_selected_values():
    with patch.object(current, 'compare_current_statistics', return_value={'ok': True}) as called:
        assert invoke(person_indices=[2, 1, 2], category_code=3, minimum_minutes=1) == {'ok': True}
        called.assert_called_once_with('career.fm', [2, 1, 2], 'a' * 64, category_code=3, minimum_minutes=1)


def test_public_real_wire_preserves_all_states_and_source_failure(query_source):
    query_source['raw'] = component(record(1, bucket=stats(minutes=270)), record(2),
                                    record(3, bucket=stats(minutes=-1)), record(4, bucket=stats(minutes=0)),
                                    record(5, bucket=stats(minutes=269)), record(6, bucket=stats(goals=255, minutes=270)))
    result = invoke(person_indices=list(range(1, 8)))
    assert [p['state'] for p in result['people']] == ['eligible', 'serialized_null_category', 'negative_minutes',
        'no_playing_time', 'below_minimum_minutes', 'missing_goals_or_assists', 'no_serialized_current_entry']
    assert result['people'][-1]['goal_contributions'] is None
    query_source['source_fail'] = True
    with pytest.raises(ToolError, match='source changed'):
        invoke()


def test_public_all28_actual_wire_fixture_and_separate_Gordon_ambiguity(query_source):
    fixture = json.loads((Path(__file__).parent / 'fixtures/saved_current_statistics_roster.json').read_text())
    targets = []
    bodies = []
    for row in fixture['rows']:
        raw = bytes.fromhex(row['record_hex'])
        assert hashlib.sha256(raw).hexdigest() == row['record_sha256']
        bodies.append(raw)
        target = name_target(row['person_index'])
        target['candidates'][0]['identity'].update(native_id_word=row['native_id'], secondary_word=row['secondary_id'])
        if row['person_index'] == 13009:
            target['candidates'].append({**target['candidates'][0],
                'identity': dict(stored_index=13009, native_id_word=8711, secondary_word=4294967040)})
        targets.append(target)
    query_source.update(raw=component(*bodies), person_count=170478, names=targets)
    result = invoke(person_indices=[row['person_index'] for row in fixture['rows']])
    assert result['evaluated_count'] == 28 and result['eligible_count'] == 13
    assert result['ranking_person_indices'] == [row['person_index'] for row in fixture['ranking']]
    by = {row['person_index']: row for row in result['people']}
    for expected in fixture['ranking']:
        assert by[expected['person_index']]['per90_exact'] == dict(zip(('numerator', 'denominator'), expected['fraction']))
    assert by[13009]['name_context']['state'] == 'ambiguous_candidates'
    assert by[13009]['name_context']['selected'] is None
    assert by[13009]['current']['statistics']['minutes'] == 463
    assert by[13009]['per90_exact'] == dict(numerator=180, denominator=463)
    assert query_source['source_count'] == 1
