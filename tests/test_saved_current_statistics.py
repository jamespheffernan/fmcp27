import io
import struct
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_current_statistics as current
from fm_live_mcp.saved_component_stream import Reader


def stats(*, starts=1, subs=0, goals=0, assists=0, minutes=90, rating=70,
          denominator=1, advanced=None):
    compact = bytearray(17)
    struct.pack_into('<hh', compact, 0, rating, minutes)
    compact[4:9] = bytes((starts, subs, denominator, goals, assists))
    return b'\x07' + compact + (bytes(136) if advanced is None else advanced)


def record(owner, *, bucket=None, category=1, extra=(), items=(), packed=None):
    slots = [(b'\x01' + bucket) if slot == category and bucket is not None else b'\x00'
             for slot in range(8)]
    body = struct.pack('<iIIIHBB', owner, 123, 45, 67, 8, 9, 10) + b''.join(slots) + bytes(20)
    body += struct.pack('<I', len(extra)) + b''.join(extra)
    body += struct.pack('<I', len(items)) + b''.join(items)
    return b'\x01' + body + b'\x10' + (bytes(48) if packed is None else packed)


def component(*rows):
    return current.ENVELOPE + b''.join(rows) + b'\x00' + struct.pack('<4I', 1, 2, 3, 4)


def read(raw, wanted=None, category=1, count=100):
    reader = Reader(io.BytesIO(raw), len(raw))
    return current.read_current(reader, {1} if wanted is None else wanted, count, category)


def test_available_null_absent_and_zero_are_distinct():
    rows, coverage = read(component(record(1, bucket=stats(minutes=0, starts=0)), record(3)), {1, 2, 3})
    assert rows[1]['state'] == 'available'
    assert rows[1]['statistics']['minutes'] == 0
    assert rows[2]['state'] == 'no_serialized_current_entry'
    assert rows[3]['state'] == 'serialized_null_category'
    assert rows[2]['statistics'] is rows[3]['statistics'] is None
    assert coverage['complete_source'] and coverage['physical_record_count'] == 2
    assert coverage['end'] == len(component(record(1, bucket=stats(minutes=0, starts=0)), record(3)))
    assert coverage['manager_footer']['native_08_0c_10_14_u32'] == [1, 2, 3, 4]


def test_empty_component_and_unordered_owners():
    rows, coverage = read(component())
    assert rows[1]['state'] == 'no_serialized_current_entry'
    assert coverage['physical_record_count'] == 0
    rows, coverage = read(component(record(8), record(1), record(2)), {1, 8})
    assert rows[1]['source_record_ordinal'] == 1
    assert rows[8]['source_record_ordinal'] == 0
    assert coverage['distinct_owner_count'] == 3


@pytest.mark.parametrize('category', range(6))
def test_six_category_codes(category):
    rows, _ = read(component(record(1, bucket=stats(goals=3), category=category)), category=category)
    assert rows[1]['statistics']['goals'] == 3
    assert len(rows[1]['primary_slot_presence']) == 6
    assert rows[1]['unlabelled_slot_presence'] == [False, False]


def test_signed_stats_sentinel_and_serialized_pointer_uncertainty():
    rows, _ = read(component(record(1, bucket=stats(starts=255, goals=255, minutes=-4, rating=-5,
                                                   advanced=struct.pack('<68h', -1, *([0] * 67))))))
    decoded = rows[1]['statistics']
    assert decoded['minutes'] == -4 and decoded['total_rating_tenths'] == -5
    assert decoded['starting_appearances'] is decoded['goals'] is decoded['total_appearances'] is None
    assert decoded['native_raw']['goals'] == 255
    assert decoded['native_getter_values']['goals'] == -1
    assert 'pointer_not_recorded' in decoded['advanced_values_state']
    assert 'advanced' not in decoded


def test_additional_teams_raw_items_and_bitfields_checked_but_not_merged():
    additional = b'\x00' + struct.pack('<i', 4) + b'\x01' + stats(goals=200) + b'\x00' * 5
    nullable_identity = b'\x00' + struct.pack('<i', -1) + b'\x00' * 6
    rows, coverage = read(component(record(1, bucket=stats(goals=2), extra=(additional, nullable_identity),
                                            items=(b'\x02' + bytes(7),), packed=bytes((127, 31, 15)) * 16)))
    assert rows[1]['statistics']['goals'] == 2
    assert rows[1]['additional_team_record_count'] == coverage['additional_team_record_count'] == 2
    assert coverage['raw_item_count'] == 1
    assert not coverage['additional_TEAM_reference_identities_resolved']


@pytest.mark.parametrize('owners', [(1, 1), (2, 2), (-1,), (100,)])
def test_duplicate_or_invalid_owner_including_nonmatches_fails(owners):
    with pytest.raises(ValueError, match='owner'):
        read(component(*(record(owner) for owner in owners)))


@pytest.mark.parametrize('raw', [
    b'\x04' + current.ENVELOPE[1:] + b'\x00' + bytes(16),
    current.ENVELOPE + b'\x02' + bytes(20),
    component(record(1, bucket=b'\x08' + stats()[1:])),
    component(record(1, items=(b'\x03' + bytes(7),))),
    component(record(1, packed=b'\x80' + bytes(47))),
    component(record(1)) + b'x',
])
def test_unsupported_markers_versions_and_trailing_bytes(raw):
    with pytest.raises(ValueError):
        read(raw)


def test_corrupt_presence_reference_and_count_budgets():
    raw = bytearray(component(record(1)))
    raw[29] = 2
    with pytest.raises(ValueError, match='presence'):
        read(raw)
    for marker, index in ((1, 1), (2, 1), (0, -2)):
        extra = bytes([marker]) + struct.pack('<i', index) + bytes(6)
        with pytest.raises(ValueError, match='reference'):
            read(component(record(1, extra=(extra,))))
    for field, value, match in ((57, current.MAX_ADDITIONAL_TEAMS + 1, 'Additional'),
                                (61, current.MAX_RAW_ITEMS + 1, 'raw-item')):
        raw = bytearray(component(record(1)))
        struct.pack_into('<I', raw, field, value)
        with pytest.raises(ValueError, match=match):
            read(raw)


def test_all_truncations_are_rejected():
    raw = component(record(1, bucket=stats()), record(2))
    for end in range(len(raw)):
        with pytest.raises(ValueError):
            read(raw[:end])


@pytest.mark.parametrize('kwargs', [dict(category=6), dict(category=True), dict(count=1),
                                    dict(wanted=set()), dict(wanted={True})])
def test_invalid_pure_cohort_inputs(kwargs):
    with pytest.raises(ValueError):
        read(component(), **kwargs)


def name_target(index, *, complete=True, alternatives=1):
    return {'person_index': index, 'search_complete': complete, 'budget_reasons': [] if complete else ['work'],
            'candidates': [dict(identity=dict(stored_index=index, native_id_word=100 + index + n, secondary_word=200 + index),
                                names=[{'text': 'Same'}, {'text': 'Name'}, None], name_indices=[1, 2, -1])
                           for n in range(alternatives)]}


@pytest.fixture
def query_source(monkeypatch):
    state = {'raw': component(), 'names': None, 'person_count': 100, 'source_count': 0, 'source_fail': False, 'name_fail': False,
             'paths': ['root/rgman/player_stats.dat'], 'finished': True}
    @contextmanager
    def names(filename, pin, directory):
        yield b'', SimpleNamespace(person_count=state['person_count']), pin, {'date': '2030-10-28'}
        if state['name_fail']:
            raise ValueError('name source changed on exit')
    monkeypatch.setattr(current, 'checked_name_source', names)
    monkeypatch.setattr(current.saved_person_candidates, 'search_candidates',
                        lambda data, layout, indices: state['names'] or [name_target(i) for i in indices])
    @contextmanager
    def snapshot(filename, directory=None):
        state['source_count'] += 1
        yield None, [SimpleNamespace(path=p, uncompressed_size=len(state['raw'])) for p in state['paths']], 'identity'
        if state['source_fail']:
            raise ValueError('statistics source changed on exit')
    monkeypatch.setattr(current.snapshot_catalog, 'checked_snapshot', snapshot)
    monkeypatch.setattr(current.snapshot_catalog, 'snapshot_id', lambda identity: 'a' * 64)
    @contextmanager
    def opened(handle, entry):
        source = io.BytesIO(state['raw'])
        source.finished = state['finished']
        yield Reader(source, len(state['raw']))
    monkeypatch.setattr(current.saved_component_stream, 'open_component', opened)
    return state


def query(indices, **kwargs):
    return current.compare_current_statistics('career.fm', indices, 'a' * 64, **kwargs)


def test_query_exact_rank_ties_minimum_duplicates_and_one_scan(query_source):
    query_source['raw'] = component(record(1, bucket=stats(goals=2, assists=1, minutes=270)),
                                    record(2, bucket=stats(goals=1, minutes=90)),
                                    record(3, bucket=stats(goals=4, minutes=360)),
                                    record(4, bucket=stats(goals=1, minutes=269)))
    result = query([3, 1, 2, 4, 3], minimum_minutes=90)
    assert query_source['source_count'] == 1
    assert result['evaluated_person_indices'] == [3, 1, 2, 4]
    assert result['ranking_person_indices'] == [1, 2, 3, 4]
    assert [p['rank'] for p in result['people']] == [1, 1, 1, 4]
    assert result['people'][0]['per90_exact'] == {'numerator': 1, 'denominator': 1}
    assert result['people'][0]['current']['statistics']['starting_appearances'] == 1
    assert result['requested_person_indices'] == [3, 1, 2, 4, 3]
    assert result['evidence_scope']['season_year'] is None
    assert 'selected-team attribution not established' in result['evidence_scope']['statistics']


def test_query_all_classifications_no_zero_imputation(query_source):
    query_source['raw'] = component(record(1), record(2, bucket=stats(minutes=-1)),
                                    record(3, bucket=stats(minutes=0)), record(4, bucket=stats(minutes=269)),
                                    record(5, bucket=stats(goals=255, minutes=270)), record(6, bucket=stats(minutes=270)))
    result = query(list(range(1, 8)))
    assert [p['state'] for p in result['people']] == [
        'serialized_null_category', 'negative_minutes', 'no_playing_time', 'below_minimum_minutes',
        'missing_goals_or_assists', 'eligible', 'no_serialized_current_entry']
    assert result['ranking_person_indices'] == [6]
    assert result['people'][-1]['goal_contributions'] is None


def test_names_remain_independent_ambiguous_unavailable_and_incomplete(query_source):
    query_source['raw'] = component(*(record(i, bucket=stats(minutes=300, goals=i)) for i in range(1, 4)))
    query_source['names'] = [name_target(1, alternatives=2), name_target(2, alternatives=0),
                            name_target(3, complete=False)]
    result = query([1, 2, 3])
    assert [p['name_context']['state'] for p in result['people']] == ['ambiguous_candidates', 'unavailable', 'incomplete']
    assert result['ranking_person_indices'] == [3, 2, 1]
    assert all(p['name_context']['selected'] is None for p in result['people'])


@pytest.mark.parametrize('flag', ['source_fail', 'name_fail'])
def test_exit_recheck_failure_never_returns_result(query_source, flag):
    query_source[flag] = True
    with pytest.raises(ValueError, match='source changed'):
        query([1])


def test_frame_finish_and_duplicate_component_guards(query_source):
    query_source['finished'] = False
    with pytest.raises(ValueError, match='frame'):
        query([1])
    query_source['finished'] = True
    query_source['paths'] *= 2
    with pytest.raises(ValueError, match='one root'):
        query([1])


@pytest.mark.parametrize('indices,kwargs', [([], {}), ([True], {}), ([100], {}), ([1], {'category_code': True}),
                                          ([1], {'minimum_minutes': 0}), ([1], {'minimum_minutes': True})])
def test_query_input_validation(query_source, indices, kwargs):
    with pytest.raises(ValueError):
        query(indices, **kwargs)


def test_four_actual_Gordon_records_use_exact_bytes():
    import hashlib
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/saved_current_statistics.json').read_text())
    for case in fixture['records']:
        raw = bytes.fromhex(case['record_hex'])
        assert hashlib.sha256(raw).hexdigest() == case['record_sha256']
        decoded, coverage = read(component(raw), {13009}, count=170478)
        stats_row = decoded[13009]['statistics']
        assert {key: stats_row[key] for key in case['expected']} == case['expected']
        assert coverage['complete_source']


def test_distinct_name_geometries_are_not_collapsed_to_a_single_identity():
    target = name_target(1)
    first = target['candidates'][0]
    first.update(common_start=100, identity_offset=200, end=212)
    second = {**first, 'common_start': 300, 'identity_offset': 400, 'end': 412}
    target['candidates'].append(second)
    names = current._names(target)
    assert names['state'] == 'ambiguous_candidates'
    assert names['selected'] is None and names['candidate_count'] == 2


def test_name_null_and_undecodable_text_remain_distinct():
    target = name_target(1)
    target['candidates'][0]['names'][0] = {'text': None, 'raw_hex': 'ff'}
    names = current._names(target)
    assert names['selected']['name_fields'][0]['state'] == 'unsupported_encoding'
    assert names['selected']['name_fields'][2]['state'] == 'null_reference'


def test_exact_original_roster_records_match_independent_all28_rank(query_source):
    import hashlib
    import json
    from pathlib import Path
    fixture = json.loads((Path(__file__).parent / 'fixtures/saved_current_statistics_roster.json').read_text())
    bodies = []
    targets = []
    for row in fixture['rows']:
        raw = bytes.fromhex(row['record_hex'])
        assert hashlib.sha256(raw).hexdigest() == row['record_sha256']
        bodies.append(raw)
        target = name_target(row['person_index'])
        target['candidates'][0]['identity'].update(native_id_word=row['native_id'], secondary_word=row['secondary_id'])
        targets.append(target)
    query_source.update(raw=component(*bodies), person_count=170478, names=targets + [name_target(0, alternatives=0)])
    result = query([row['person_index'] for row in fixture['rows']] + [0])
    assert query_source['source_count'] == 1
    assert result['ranking_person_indices'] == [row['person_index'] for row in fixture['ranking']]
    assert result['eligible_count'] == 13
    by_index = {row['person_index']: row for row in result['people']}
    for row in fixture['rows']:
        decoded = by_index[row['person_index']]['current']['statistics']
        expected = row['expected_league']
        for key, source in [('starting_appearances', 'starts'), ('sub_appearances', 'subs'),
                            ('goals', 'goals'), ('assists', 'assists'), ('minutes', 'minutes')]:
            assert decoded[key] == expected[source]
    for expected in fixture['ranking']:
        assert by_index[expected['person_index']]['per90_exact'] == dict(zip(('numerator', 'denominator'), expected['fraction']))
    assert by_index[0]['state'] == 'no_serialized_current_entry'
    assert by_index[0]['goal_contributions'] is None
