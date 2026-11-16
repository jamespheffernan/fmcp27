import copy
import gzip
import json
from pathlib import Path
import struct

import pytest
from fm_live_mcp import active_match_shots as query


def source():
    rows = json.loads(gzip.decompress((Path(__file__).parent/'fixtures/retained_shot_maps.json.gz').read_bytes()))
    row = next(row for row in rows if row['key'] == 132398)
    return dict(state='available_engine_source', vectors=[bytes.fromhex(v) for v in row['vectors']],
                events=bytes.fromhex(row['events']), engine_totals=copy.deepcopy(row['teams']),
                client_snapshot_totals=copy.deepcopy(row['teams']), pitch_geometry=None,
                engine_frontier_raw=12345, source_identity=(1, 2, 3))


def test_engine_rows_reuse_normalizers_but_never_claim_display_or_person():
    packet = query.project(source())
    assert len(packet['shots']) == 18
    assert not packet['displayed_time_statistics_verified']
    assert packet['displayed_snapshot_shots'] is None
    assert all(row['actor'] is None and row['clock'] is None for row in packet['shots'])
    assert all(row['temporal_scope'] == 'engine_cumulative_may_be_ahead_of_display' for row in packet['shots'])
    assert packet['client_snapshot_prefix']['state'] == 'matching_stored_order_candidate_unproved_display_binding'
    assert not packet['client_snapshot_prefix']['rows_released_as_display_snapshot']


def test_prefix_mismatch_does_not_hide_verified_engine_rows_or_invent_display_rows():
    value = source(); value['client_snapshot_totals'][0]['expected_goals'] = 99.
    packet = query.project(value)
    assert len(packet['shots']) == 18
    assert packet['client_snapshot_prefix']['state'] == 'unavailable_snapshot_prefix_mismatch'
    assert packet['displayed_snapshot_shots'] is None


def test_unreconciled_engine_side_stays_unknown():
    value = source(); value['engine_totals'][0]['shots'] += 1
    packet = query.project(value)
    assert packet['side_coverage'][0]['shot_count'] is None
    assert all(row['side_index'] == 1 for row in packet['shots'])


def test_missing_source_is_not_zero_shots():
    packet = query.project(dict(state='unavailable_engine_cbe_absent', shots=None))
    assert packet['shots'] is None and not packet['displayed_time_statistics_verified']


def test_observation_order_checks_bytes_without_sorting_or_display_promotion():
    first = source(); second = source()
    assert query.compare_observations(first, second)['state'] == 'stored_order_prefix_stable'
    second['vectors'][0] = second['vectors'][0][48:] + second['vectors'][0][:48]
    assert query.compare_observations(first, second)['state'] == 'stored_order_changed'
    second['source_identity'] = (1, 2, 4)
    with pytest.raises(ValueError, match='identity'):
        query.compare_observations(first, second)


def memory(monkeypatch):
    data = {}
    def put(address, raw):
        data.update({address+i: byte for i, byte in enumerate(raw)})
    def read(address, length):
        assert 0 < length <= 8192
        return bytes(data.get(address+i, 0) for i in range(length))
    base, client, engine, wrapper, stats, cbe = 0x10000000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000
    for address, table in ((client, 0x55fac38), (engine, 0x55fa258), (stats, 0x55fa850), (client+8, 0x56a2380)):
        put(address, struct.pack('<Q', base+table))
    put(engine+0x20, struct.pack('<Q', 123)); put(client+0x138, struct.pack('<Q', 123))
    put(client+0xf8, struct.pack('<Q', wrapper)); put(wrapper+0x18, struct.pack('<Q', engine))
    put(engine+0x14e90, struct.pack('<QQ', stats, cbe))
    for address in (stats, client+8):
        put(address+0x18, struct.pack('<Q', 0x70000))
        for side in range(2):
            pointer = (0x80000 if address == stats else 0x90000) + side*0x1000
            put(address+0x68+side*8, struct.pack('<Q', pointer))
            put(pointer+0x5c, struct.pack('<If', side+10, 0.))
    put(cbe+0x100, struct.pack('<ff', 34., 52.5))
    for address, raw in query.NATIVE_SPANS:
        put(base+address, raw)
    monkeypatch.setattr(query.retained, '_verify_native', lambda *args: None)
    monkeypatch.setattr(query, '_fixture_identity', lambda *args: ('2030-11-02', 11, (10, 688), (11, 713)))
    return read, put, (base, client, engine), cbe


def test_capture_owns_native_source_and_true_zero_vectors(monkeypatch):
    read, put, args, cbe = memory(monkeypatch)
    result = query.capture_source(read, *args)
    assert result['vectors'] == [b'', b''] and result['events'] == b''
    assert query.project(result)['side_coverage'][0]['shot_count'] == 0
    put(args[0]+query.NATIVE_SPANS[0][0], b'bad!')
    with pytest.raises(ValueError, match='binding'):
        query.capture_source(read, *args)


def test_capture_rejects_cross_engine_and_excessive_vector(monkeypatch):
    read, put, args, cbe = memory(monkeypatch)
    put(cbe+8, struct.pack('<QQQ', 0xa0000, 0xa0000+56, 0xa0000+56*(query.MAX_EVENTS+1)))
    with pytest.raises(ValueError, match='geometry or budget'):
        query.capture_source(read, *args)
    put(args[1]+0xf8, struct.pack('<Q', 0xb0000))
    with pytest.raises(ValueError, match='ownership'):
        query.capture_source(read, *args)


def test_capture_rejects_copied_fixture_with_different_identity(monkeypatch):
    read, put, args, cbe = memory(monkeypatch)
    put(args[1]+8+0x18, struct.pack('<Q', 0x71000))
    monkeypatch.setattr(query, '_fixture_identity', lambda read, base, pointer:
                        ('2030-11-02', 11, (10, 688), (11, 713 if pointer == 0x70000 else 714)))
    with pytest.raises(ValueError, match='fixture or sides'):
        query.capture_source(read, *args)


def test_actor_slot_remains_raw_and_unjoined():
    packet = query.project(source())
    assert all('native_actor_slot' in row and 'stored_player_slot' not in row for row in packet['shots'])
    assert all(row['actor_identity_state'] == 'unresolved_active_event_roster_join' for row in packet['shots'])


def test_private_candidates_are_opt_in_and_do_not_change_strict_retained_defaults():
    value = source(); value['engine_totals'][0]['expected_goals'] += .1
    packet = query.project(value)
    assert '_candidates_by_side' not in packet and '_marker_candidates_by_side' not in packet
    assert packet['side_coverage'][0]['shot_count'] is not None
    assert packet['side_coverage'][0]['expected_goals'] is None
    assert all(row['expected_goals'] is None for row in packet['shots'] if row['side_index'] == 0)
    private = query.project(value, _retain_candidates=True)
    assert '_candidates_by_side' in private and '_marker_candidates_by_side' in private
    strict = query.retained.decode_attempts(value['vectors'], value['events'], value['engine_totals'])
    assert strict['side_coverage'][0]['shot_count'] is None
    assert all(row['side_index'] == 1 for row in strict['shots'])


def actual_lille_metric_packet():
    with gzip.open(Path(__file__).parent / 'fixtures/lille_active_shot_metric_control.json.gz', 'rt') as f:
        recorded = json.load(f)
    decoded = recorded['decoded']
    decoded['_candidates_by_side'] = {int(key): value for key, value in decoded['_candidates_by_side'].items()}
    # Every retained row is an error-free statistical attempt in this capture;
    # equal counts establish that its two marker candidate lists are empty.
    assert all(not row['link_errors'] and row['retained_record_count'] == row['statistical_shot_count']
               for row in decoded['side_coverage'])
    decoded['_marker_candidates_by_side'] = {0: [], 1: []}
    return decoded


def test_actual_verified_lille_integer_metrics_survive_two_and_three_ulp_xg_mismatches():
    decoded = actual_lille_metric_packet()
    assert [row['xg_float32_ulp_distance'] for row in decoded['side_coverage']] == [2, 3]
    result = query._metric_projection(decoded)
    assert [row['shot_count'] for row in result['side_coverage']] == [3, 2]
    assert [row['shots_on_target'] for row in result['side_coverage']] == [0, 2]
    assert [row['expected_goals'] for row in result['side_coverage']] == [None, None]
    assert all(row['expected_goals'] is None for row in result['shots'])
    assert len(result['shots']) == 5 and result['own_goal_markers'] == []
    assert [row['checks']['xg_sum_within_one_float32_ulp'] for row in result['side_coverage']] == [False, False]


def test_actual_lille_private_projection_does_not_mutate_recorded_candidates():
    decoded = actual_lille_metric_packet()
    before = copy.deepcopy(decoded)
    query._metric_projection(decoded)
    assert decoded == before


def test_original_slot_actor_join_and_wrong_match_fail_closed():
    value=source();value['match_unique_id']=123
    unnamed=query.project(value)['shots'][0]
    binding={'state':'validated_native_stored_slots','official_match_unique_id':123,'players':[{
        'side_index':unnamed['event_side_index'],'stored_player_slot':unnamed['native_actor_slot'],
        'canonical_person_id':101,'person_index_word':7,'person_name':'Verified shooter','identity_state':'canonical'}]}
    packet=query.project(value,actor_binding=binding)
    named=next(r for r in packet['shots'] if r['event_id']==unnamed['event_id'])
    assert named['actor']['person_name']=='Verified shooter'
    assert named['actor']['stored_player_slot']==unnamed['native_actor_slot']
    assert any(r['actor'] is None for r in packet['shots'])
    binding['official_match_unique_id']=124
    with pytest.raises(ValueError,match='another official match'):query.project(value,actor_binding=binding)


def test_own_goal_primary_actor_uses_event_side_not_beneficiary():
    rows=json.loads(gzip.decompress((Path(__file__).parent/'fixtures/retained_shot_maps.json.gz').read_bytes()))
    r=next(r for r in rows if r['key']==135904)
    value=dict(state='available_engine_source',vectors=[bytes.fromhex(v) for v in r['vectors']],events=bytes.fromhex(r['events']),
        engine_totals=r['teams'],client_snapshot_totals=r['teams'],pitch_geometry=None,
        engine_frontier_raw=30000,source_identity=(1,2,3),match_unique_id=123)
    marker=query.project(value)['own_goal_markers'][0]
    assert marker['event_side_index']!=marker['beneficiary_side_index']
    actor_side,slot=marker['event_side_index'],marker['native_actor_slot']
    binding={'state':'validated_native_stored_slots','official_match_unique_id':123,'players':[
        {'side_index':actor_side,'stored_player_slot':slot,'canonical_person_id':101,'person_index_word':7,'person_name':'Defender'},
        {'side_index':marker['beneficiary_side_index'],'stored_player_slot':slot,'canonical_person_id':102,'person_index_word':8,'person_name':'Beneficiary same slot'}]}
    named=query.project(value,actor_binding=binding)['own_goal_markers'][0]
    assert named['actor']['person_name']=='Defender'
    assert named['beneficiary_side_index']==marker['beneficiary_side_index'] and named['actor']['side_index']==actor_side
