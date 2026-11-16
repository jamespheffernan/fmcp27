"""Source operators versus complete original ARM64; synthetic operands only."""
from datetime import date, timedelta
import json
from pathlib import Path
import struct

import pytest

import test_ucl_requirement26_source as native
from fm_live_mcp import ucl_requirement26_projection as source
from fm_live_mcp import virtual_identity

OPERATORS = json.loads((Path(__file__).parent / 'fixtures/ucl_requirement26_operators_native.json').read_text())


@pytest.fixture
def case(monkeypatch):
    monkeypatch.setattr(native, 'ORIGINAL', OPERATORS)
    def build(rating=20, durations=(40, 40), weeks=-1, day=100):
        cells, primaries, put, q = native.memory(rating, durations, weeks, day)
        for i, primary in enumerate(primaries):
            if durations[i] is not None:
                header, entries = primary + 0x1000, primary + 0x2000
                q(header + 16, entries + 8)
        def read(at, n):
            try: return bytes(cells[at + i] for i in range(n))
            except KeyError as exc: raise ValueError(('Missing synthetic operand', hex(exc.args[0]))) from exc
        context = dict(team=native.TEAM, club=native.CLUB, club_teams=(native.TEAM,),
                       current_date=(date(2030, 1, 1) + timedelta(days=day - 1)).isoformat(), current_rules={})
        return cells, primaries, put, q, read, context
    return build


def captured(primaries, rating=20):
    return dict(stored_player_slot_count=len(primaries), unique_player_count=len(set(primaries)),
        teams=[dict(team_slot=0, address=native.TEAM, player_slots=[dict(slot=i, primary=primary,
            person=None if not primary else dict(record_kind='actual', native_identity=dict(
                database_index=i, native_id=100 + i, random_id=None))) for i, primary in enumerate(primaries)])])


@pytest.mark.parametrize('rating,durations,weeks,day,expected', [
    (14, (40, 40), -1, 100, False), (15, (40, 40), -1, 100, True),
    (20, (40, None), -1, 100, False), (20, (40, 30), -1, 100, False),
    (20, (40, 31), -1, 100, True), (20, (40, 40), 4, 100, False),
    (20, (40, 40), 5, 100, True), (20, (None, None), -1, 100, False),
    (20, (40, 40), -1, 330, True), (20, (0, 0), -1, 100, False),
    (20, (0, 0), 127, 100, True)])
def test_projection_matches_complete_original_positive_negative_filters(case, monkeypatch,
        rating, durations, weeks, day, expected):
    cells, primaries, _, _, read, context = case(rating, durations, weeks, day)
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured(primaries, rating))
    result = source.aggregate(read, native.BASE, context)
    original, trace, reads = native.original(cells, (primaries[0], 26, native.TEAM, 0, 0, 0, 0, 0))
    assert result['native_result'] is bool(original) is expected
    assert result['state'] == 'checked' and result['full_eligibility_evaluated'] is False
    assert len(result['rows']) == len(primaries)
    if expected:
        assert result['known_qualifying_stored_occurrences'] == 2
    assert trace and reads


def test_duplicate_stored_occurrences_keep_native_count(case, monkeypatch):
    cells, primaries, _, q, read, context = case(durations=(40, None))
    q(native.ROSTER + 8, primaries[0])
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured([primaries[0], primaries[0]]))
    result = source.aggregate(read, native.BASE, context)
    original, _, _ = native.original(cells, (primaries[0], 26, native.TEAM, 0, 0, 0, 0, 0))
    assert original == 1 and result['native_result'] is True
    assert result['stored_player_slot_count'] == 2 and result['unique_player_count'] == 1


@pytest.mark.parametrize('durations,weeks,starts,expected_slot', [
    ((40, 40), (-1, -1), (100, 100), 1),
    ((40, 40), (6, 5), (100, 100), 0),
    ((5, 40), (-1, -1), (1, 100), 1),
    ((40, 40), (-1, -1), (100, 150), 1),
    ((0, 0), (0, 0), (100, 100), 1)])
def test_medical_multiple_record_selection_matches_original(case, durations, weeks, starts, expected_slot):
    cells, primaries, put, q, read, context = case(durations=durations)
    primary = primaries[0]
    entries = native.HEAP + 0x20000
    put(entries, bytes(16))
    records = [p + 0x3000 for p in primaries]
    q(primary + 0x1000, entries); q(primary + 0x1008, entries + 16); q(primary + 0x1010, entries + 16)
    for i, record in enumerate(records):
        q(entries + i * 8, record)
        put(record + 0x33, struct.pack('<b', weeks[i]))
        put(record + 0x20, struct.pack('<HH', starts[i], 2030))
    result = source.medical(read, primary, context['current_date'])
    original, trace, _ = native.original(cells, (primary,), entry=0xD09BD0)
    assert original == records[expected_slot]
    assert result['selected_stored_slot_index'] == expected_slot
    assert result['native_record_present'] is True
    assert result['medical_clearance_evaluated'] is False
    if all(starts[i] + durations[i] >= 100 for i in range(2)):
        assert 0x154D890 in trace
    else:
        assert 0x154D890 not in trace  # Expired input is skipped before comparison.


@pytest.mark.parametrize('mode', ['absent', 'empty', 'expired', 'zero_duration'])
def test_empty_absent_expired_and_zero_medical_sources_remain_distinct(case, mode):
    cells, primaries, put, q, read, context = case(durations=(0, 40))
    primary = primaries[0]
    if mode == 'absent': q(primary + 0xF0, 0)
    elif mode == 'empty': put(primary + 0x1000, bytes(24))
    elif mode == 'expired': put(primary + 0x3020, struct.pack('<HH', 1, 2030))
    result = source.medical(read, primary, context['current_date'])
    original, _, _ = native.original(cells, (primary,), entry=0xD09BD0)
    assert result['native_record_present'] is bool(original)
    expected = dict(absent='holder_absent', empty='checked_empty', expired='checked_no_unexpired_native_record',
                    zero_duration='stored_records_present')[mode]
    assert result['source_state'] == expected
    assert result['native_duration_days'] == (0 if mode == 'zero_duration' else None)


@pytest.mark.parametrize('duration', [-367, 367, 32767])
def test_unsupported_medical_duration_is_unknown_not_false(case, duration):
    _, primaries, put, _, read, context = case()
    put(primaries[0] + 0x3028, struct.pack('<h', duration))
    with pytest.raises(source.Unavailable, match='medical_duration'):
        source.medical(read, primaries[0], context['current_date'])


def test_null_medical_record_is_unavailable(case):
    _, primaries, _, q, read, context = case()
    q(primaries[0] + 0x2000, 0)
    with pytest.raises(source.Unavailable, match='null_native_medical_record'):
        source.medical(read, primaries[0], context['current_date'])


@pytest.mark.parametrize('fault', ['unaligned_header', 'oversized_capacity', 'backwards_vector'])
def test_malformed_medical_geometry_rejects(case, fault):
    _, primaries, _, q, read, context = case()
    primary = primaries[0]
    if fault == 'unaligned_header': q(primary + 0xF0, primary + 0x1004)
    elif fault == 'oversized_capacity': q(primary + 0x1010, primary + 0x2000 + 65 * 8)
    else: q(primary + 0x1008, primary + 0x1FF8)
    with pytest.raises(ValueError): source.medical(read, primary, context['current_date'])


def test_unknown_operand_stops_without_false_or_later_exclusions(case, monkeypatch):
    _, primaries, _, _, read, context = case()
    rows = captured([0] + primaries)
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: rows)
    result = source.aggregate(read, native.BASE, context)
    assert result['state'] == 'unavailable' and result['native_result'] is None
    assert result['rows'][0]['reason'] == 'null_native_aggregate_player'
    assert all(row['state'] == 'not_evaluated_after_unavailable_source' for row in result['rows'][1:])
    assert all(row['native_qualifies'] is None for row in result['rows'])


def test_native_threshold_return_preserves_later_unknown_slot(case, monkeypatch):
    _, primaries, _, _, read, context = case()
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured(primaries + [0]))
    result = source.aggregate(read, native.BASE, context)
    assert result['native_result'] is True and result['state'] == 'checked'
    assert result['rows'][-1]['state'] == 'not_reached_after_native_return'
    assert result['rows'][-1]['native_qualifies'] is None


def test_empty_team_roster_has_checked_false_aggregate(case, monkeypatch):
    _, _, _, _, read, context = case()
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured([]))
    result = source.aggregate(read, native.BASE, context)
    assert result['native_result'] is False and result['rows'] == []
    assert result['teams'][0]['state'] == 'captured_empty_roster'


def rule_case(case, monkeypatch, kind=0):
    cells, primaries, put, q, read, context = case()
    primary = primaries[0]
    comp, runtime, owner, bank, table, rule = [native.HEAP + 0x30000 + i * 0x1000 for i in range(6)]
    for at, size in [(comp, 0x200), (runtime, 0x520), (owner, 0x248), (bank, 0x90), (table, 8), (rule, 0x130)]:
        put(at, bytes(size))
    q(native.BASE + source.players.RVA[2] + 0x230, native.BASE + 0xD5C578)
    put(native.BASE + source.players.RVA[2] - 0x240, struct.pack('<q', -0x388))
    q(primary + 0x128, native.TEAM)
    q(native.CLUB + 0x28, native.TEAMS + 8)
    q(native.TEAM + 0x50, comp); put(comp + 8, (7).to_bytes(4, 'little'))
    native_id = 11 if kind == 0 else 13
    put(comp + 12, struct.pack('<i', native_id)); q(comp + 0x60, native.HEAP + 0x70000)
    q(runtime + 0x138, comp); q(runtime + 0x388, owner); q(owner + 0x1F0, bank)
    put(runtime + 0x3BE, bytes((kind,))); put(runtime + 0x3B6, struct.pack('<h', -1))
    put(native.BASE + 0x56D3518, struct.pack('<i', -1))
    q(bank + 0x60, table); q(bank + 0x68, table + 8); q(bank + 0x70, table + 8); q(table, rule)
    put(rule + 0x125, b'\x08'); put(rule + 0x12C, b'\x01'); q(rule + 0xE8, 0x402)
    monkeypatch.setattr(source.teams, 'by_index', lambda *args: (dict(native_id=688),
        dict(address=native.TEAM, owner_address=native.CLUB)))
    monkeypatch.setattr(source.competitions, 'by_index', lambda *args: dict(
        native_id=native_id, database_index=7, random_id=None))
    monkeypatch.setattr(source.competition_stages, 'runtime_context', lambda *args: (
        dict(shared_runtime=False, native_season_code=2030), runtime, (runtime, 0x566C2B8)))
    return cells, primary, put, q, read, dict(comp=comp, runtime=runtime, owner=owner, bank=bank, table=table, rule=rule)


@pytest.mark.parametrize('kind,competition', [(0, 11), (1, 13)])
def test_current_gk_club_rules_keep_competitions_and_selectors_separate(case, monkeypatch, kind, competition):
    _, primary, _, _, read, _ = rule_case(case, monkeypatch, kind)
    public, private = source._current_rule(read, native.BASE, primary, {})
    assert public['competition']['native_id'] == competition
    assert public['native_runtime_kind'] == kind and public['native_selector'] == 8
    assert public['native_d2dcb8'] is False and private['club_address'] == native.CLUB


@pytest.mark.parametrize('fault', ['runtime_kind', 'runtime_type', 'shared', 'owner_absent', 'bit6', 'bit17', 'flag4c0',
    'pointer510', 'owner1', 'owner3', 'signed_minus3', 'bank_absent', 'uninitialized',
    'past_range', 'null_rule', 'restriction14', 'restriction37', 'restriction3', 'restriction31', 'alternate_f2'])
def test_current_club_unsupported_or_uninitialized_operators_stay_unavailable(case, monkeypatch, fault):
    _, primary, put, q, read, a = rule_case(case, monkeypatch)
    if fault == 'runtime_kind': put(a['runtime'] + 0x3BE, b'\x15')
    elif fault == 'runtime_type':
        monkeypatch.setattr(source.competition_stages, 'runtime_context', lambda *args: (
            dict(shared_runtime=False), a['runtime'], (a['runtime'], 0x56736A8)))
    elif fault == 'shared':
        monkeypatch.setattr(source.competition_stages, 'runtime_context', lambda *args: (
            dict(shared_runtime=True), a['runtime'], None))
    elif fault == 'owner_absent': q(a['runtime'] + 0x388, 0)
    elif fault in ('bit6', 'bit17'):
        q(a['runtime'] + 0x4C, 1 << {'bit6': 6, 'bit17': 17}[fault])
    elif fault == 'flag4c0': put(a['runtime'] + 0x4C0, b'\x03')
    elif fault == 'pointer510': q(a['runtime'] + 0x510, native.HEAP)
    elif fault in ('owner1', 'owner3'): put(a['owner'] + 0x23C, bytes((int(fault[-1]),)))
    elif fault == 'signed_minus3': put(a['runtime'] + 0x3B6, struct.pack('<h', -3))
    elif fault == 'bank_absent': q(a['owner'] + 0x1F0, 0)
    elif fault == 'uninitialized': put(a['runtime'] + 0x49, b'\xff')
    elif fault == 'past_range': put(a['runtime'] + 0x49, b'\x01')
    elif fault == 'null_rule': q(a['table'], 0)
    elif fault.startswith('restriction'): q(a['rule'] + 0xE8, 1 << int(fault[11:]))
    else: put(a['rule'] + 0xF2, b'\x01')
    with pytest.raises(source.Unavailable): source._current_rule(read, native.BASE, primary, {})


def test_current_rule_null_team_argument_bypasses_team_override(case, monkeypatch):
    _, primary, _, q, read, a = rule_case(case, monkeypatch)
    q(a['runtime'] + 0x4C, 8)
    public, private = source._current_rule(read, native.BASE, primary, {})
    assert public['native_d2dcb8'] is False and private['rule_address'] == a['rule']


def test_nonmatching_current_team_membership_rejects(case, monkeypatch):
    _, primary, _, _, read, _ = rule_case(case, monkeypatch)
    monkeypatch.setattr(source.teams, 'by_index', lambda *args: ({}, dict(address=1234, owner_address=native.CLUB)))
    with pytest.raises(ValueError, match='membership changed'):
        source._current_rule(read, native.BASE, primary, {})


def test_current_rule_native_dispatch_drift_rejects(case, monkeypatch):
    _, primary, _, q, read, _ = rule_case(case, monkeypatch)
    q(native.BASE + source.players.RVA[2] + 0x230, native.BASE + 0xD5C57C)
    with pytest.raises(ValueError, match='dispatch changed'):
        source._current_rule(read, native.BASE, primary, {})


def test_leap_year_medical_duration_matches_complete_original(case, monkeypatch):
    cells, primaries, put, _, read, context = case(durations=(31, 31), day=60)
    put(native.BASE + 0x56B1DB8, struct.pack('<HH', 60, 2032))
    for primary in primaries: put(primary + 0x3020, struct.pack('<HH', 59, 2032))
    context['current_date'] = '2032-02-29'
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured(primaries))
    result = source.aggregate(read, native.BASE, context)
    original, _, _ = native.original(cells, (primaries[0], 26, native.TEAM, 0, 0, 0, 0, 0))
    assert result['native_result'] is bool(original) is True


def test_source_guard_payloads_match_pinned_operator_hashes():
    guards = {rva: (size, sha) for rva, size, sha in source.ucl.NATIVE_GUARDS}
    guards.update({rva: (size, sha) for rva, size, sha in source.operands.NATIVE_GUARDS})
    guards.update({rva: (size, sha) for rva, size, sha in source.registration.NATIVE_GUARDS})
    import hashlib
    for row in OPERATORS['rows']:
        raw = bytes.fromhex(row['raw_hex'])
        assert hashlib.sha256(raw).hexdigest() == row['sha256']
        if row['rva'] in guards: assert (len(raw), row['sha256']) == guards[row['rva']]
        if row['rva'] == 0x5399CF2:
            assert struct.unpack_from('<H', raw, (26 - 3) * 2)[0] == 0x30


def project_case(case, monkeypatch, rating=20, fixture_day=344):
    _, primaries, put, q, read, context = case(rating=rating)
    fixture = native.HEAP + 0x90000
    put(fixture, bytes(0x58)); put(fixture + 0x4C, struct.pack('<HH', fixture_day, 2030))
    q(native.CLUB + 0x28, native.TEAMS + 8)
    monkeypatch.setattr(source, 'verify_native', lambda *args: None)
    monkeypatch.setattr(source.ucl, 'fixture_context', lambda *args: (
        dict(state='available', native_selector=0), dict(team_address=native.TEAM, club_address=native.CLUB)))
    monkeypatch.setattr(source.prepared_tactics_source, '_team_and_human', lambda *args: ({}, native.HEAP + 0xA0000))
    monkeypatch.setattr(source, '_pending_closed', lambda *args: None)
    return primaries, read, context, fixture


def test_outfield_request_does_not_discover_an_aggregate(case, monkeypatch):
    primaries, read, context, fixture = project_case(case, monkeypatch, rating=14)
    monkeypatch.setattr(source, 'aggregate', lambda *args: pytest.fail('Outfield clause must return before aggregate'))
    r = source.project(read, native.BASE, {}, fixture, {}, context['current_date'],
                       [(f'p{i}', p, 'actual') for i, p in enumerate(primaries)])
    assert r['aggregate'] is None and all(p['native_requirement26'] is False for p in r['players'])
    assert r['current_club_rule_sources'] == [] and r['full_eligibility_evaluated'] is False


@pytest.mark.parametrize('fixture_day', [99, 100])
def test_source_requires_later_calendar_fixture(case, monkeypatch, fixture_day):
    primaries, read, context, fixture = project_case(case, monkeypatch, fixture_day=fixture_day)
    monkeypatch.setattr(source.ucl, 'fixture_context', lambda *args: pytest.fail('Nonfuture phase must remain unavailable'))
    r = source.project(read, native.BASE, {}, fixture, {}, context['current_date'], [('p', primaries[0], 'actual')])
    assert r['fixture_context']['reason'] == 'fixture_not_on_later_calendar_date'
    assert r['players'][0]['native_requirement26'] is None and r['aggregate'] is None


def test_unsupported_pending_context_is_unknown_for_every_requested_row(case, monkeypatch):
    primaries, read, context, fixture = project_case(case, monkeypatch)
    def unsupported(*args): raise source.Unavailable('unsupported_pending_player_registration_context')
    monkeypatch.setattr(source, '_pending_closed', unsupported)
    r = source.project(read, native.BASE, {}, fixture, {}, context['current_date'], [('p', primaries[0], 'actual')])
    assert r['fixture_context']['state'] == 'unavailable'
    assert r['fixture_context']['reason'] == 'unsupported_pending_player_registration_context'
    assert r['players'][0]['native_requirement26'] is None and r['aggregate'] is None


def test_requested_compact_position_getter_is_unknown_without_generation(case, monkeypatch):
    primaries, read, context, fixture = project_case(case, monkeypatch)
    monkeypatch.setattr(source, 'aggregate', lambda *args: pytest.fail('Do not generate/evaluate compact position'))
    r = source.project(read, native.BASE, {}, fixture, {}, context['current_date'], [('p', primaries[0], 'virtual')])
    assert r['players'][0]['native_requirement26'] is None and r['aggregate'] is None
    assert r['players'][0]['reason'] == 'unsupported_requested_player_position_dispatch'


def test_compact_aggregate_null_cast_matches_original_without_profile_generation(case, monkeypatch):
    cells, primaries, put, q, read, context = case()
    compact = native.HEAP + 0x80000
    put(compact, bytes(64))
    vt = native.BASE + source.world.TYPES['virtual_player'][0]
    person_vt = native.BASE + virtual_identity.PERSON_RVA
    q(compact, vt); q(compact + 0x20, person_vt)
    q(vt - 0x18, 0x20); q(person_vt + 0x668, native.BASE + source.VIRTUAL_NULL[0])
    roster = [compact] + primaries
    for i, primary in enumerate(roster): q(native.ROSTER + i * 8, primary)
    q(native.TEAM + 0x40, native.ROSTER + len(roster) * 8)
    packet = captured(roster); packet['teams'][0]['player_slots'][0]['person']['record_kind'] = 'virtual'
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: packet)
    result = source.aggregate(read, native.BASE, context)
    original, trace, _ = native.original(cells, (primaries[0], 26, native.TEAM, 0, 0, 0, 0, 0))
    assert result['native_result'] is bool(original) is True
    assert result['rows'][0]['state'] == 'checked_native_null_player_cast'
    assert result['rows'][0]['native_qualifies'] is False
    assert source.VIRTUAL_NULL[0] in trace


def contract_case(case):
    cells, primaries, put, q, read, context = case()
    primary = primaries[0]
    holder, contract = native.HEAP + 0x74000, native.HEAP + 0x75000
    put(holder, bytes(24)); put(contract, bytes(0x38))
    q(primary + 0x2C0, holder); q(primary + 0x2F0, contract)
    q(native.BASE + source.players.RVA[0] - 0x20, 0x278)
    table = next(at for at, fn in source.ucl.CONTRACT_GETTERS.items() if fn == 0x129FFFC)
    q(contract, native.BASE + table); q(native.BASE + table + 0x90, native.BASE + 0x129FFFC)
    q(contract + 0x10, native.TEAM); put(contract + 0x28, b'\x08')
    return cells, primary, put, q, read, context, contract, table


def test_contract_zero_getter_override_matches_complete_original(case):
    cells, primary, _, _, read, context, _, _ = contract_case(case)
    projected = source.registered(read, native.BASE, primary, native.TEAM, context)
    original, trace, _ = native.original(cells, (primary, native.TEAM, 0, 0, 1), entry=0xD32054)
    assert projected['native_result'] is bool(original) is False
    assert projected['state'] == 'checked_contract_override'
    assert 0x129FFFC in trace and 0xD2DCB8 not in trace


def test_unproved_contract_getter_stays_unknown(case):
    _, primary, _, q, read, context, contract, _ = contract_case(case)
    q(contract, native.BASE + 0x5000000)
    with pytest.raises(source.Unavailable, match='contract_registration_getter'):
        source.registered(read, native.BASE, primary, native.TEAM, context)


def test_contract_method_drift_rejects(case):
    _, primary, _, q, read, context, _, table = contract_case(case)
    q(native.BASE + table + 0x90, native.BASE + 0x129FFFC + 4)
    with pytest.raises(ValueError, match='dispatch changed'):
        source.registered(read, native.BASE, primary, native.TEAM, context)


def test_all_contract_literal_return_values_match_original_operators():
    rows = {row['rva']: bytes.fromhex(row['raw_hex']) for row in OPERATORS['rows']}
    for rva, value in source.CONTRACT_RESULTS.items():
        assert rows[rva] == struct.pack('<II', 0x52800000 | (value << 5), 0xD65F03C0)


@pytest.mark.parametrize('start,duration,record_present', [(100, -1, False), (150, -1, True),
    (150, -31, True), (1, -1, False)])
def test_negative_medical_date_subtraction_matches_complete_original(case, start, duration, record_present):
    cells, primaries, put, _, read, context = case()
    primary = primaries[0]
    put(primary + 0x3020, struct.pack('<HH', start, 2030))
    put(primary + 0x3028, struct.pack('<h', duration))
    result = source.medical(read, primary, context['current_date'])
    original, trace, _ = native.original(cells, (primary,), entry=0xD09BD0)
    assert result['native_record_present'] is bool(original) is record_present
    assert 0x9ABF4 in trace
    assert result['native_duration_days'] == (abs(duration) if record_present else None)


@pytest.mark.parametrize('start_year,duration,current_year,current_day,native_days,expected', [
    (2033, -31, 2032, 306, 30, False),
    (2033, -32, 2032, 306, 31, True),
    (2032, -31, 2031, 305, 31, True)])
def test_reverse_calendar_operator_keeps_native_365_year_branch(case, monkeypatch,
        start_year, duration, current_year, current_day, native_days, expected):
    cells, primaries, put, _, read, context = case(durations=(40, 40))
    put(native.BASE + 0x56B1DB8, struct.pack('<HH', current_day, current_year))
    context['current_date'] = (date(current_year, 1, 1) + timedelta(days=current_day - 1)).isoformat()
    for primary in primaries:
        put(primary + 0x3020, struct.pack('<HH', 1, start_year))
        put(primary + 0x3028, struct.pack('<h', duration))
    monkeypatch.setattr(source.operands, 'collect_operands', lambda *args: captured(primaries))
    result = source.aggregate(read, native.BASE, context)
    original, _, _ = native.original(cells, (primaries[0], 26, native.TEAM, 0, 0, 0, 0, 0))
    assert result['native_result'] is bool(original) is expected
    assert all(row['medical']['native_duration_days'] == native_days for row in result['rows'])
