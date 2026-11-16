"""Persistent marker controls; no overall registration/eligibility inference."""
import struct

import pytest

from fm_live_mcp import player_registration_source as source

PRIMARY, TEAM, HOLDER, START = 0x10000, 0x20000, 0x30000, 0x40000
# Genuine current13Nov2030 Gordon/Wharton relation. Relocation changes only its
# process-specific TEAM pointer; its stored16-byte payload is retained.
CAPTURED = bytes.fromhex('28ed97897c00000000000419080000ff')


def record(kind=25, selector=8, team=TEAM, transport=4):
    raw = bytearray(CAPTURED)
    struct.pack_into('<Q', raw, 0, team)
    raw[10:13] = bytes((transport, kind, selector))
    return bytes(raw)


def reader(records=(), holder=True):
    memory = {PRIMARY+0x2C0: struct.pack('<Q', HOLDER if holder else 0)}
    memory[HOLDER] = struct.pack('<QQQ', START, START+16*len(records), START+16*len(records))
    if records:
        memory[START] = b''.join(records)
    def read(at, size):
        raw = memory[at]
        assert len(raw) == size
        return raw
    return read, memory


def project(records=(), **kwargs):
    read, _ = reader(records, **kwargs)
    return source.project(read, PRIMARY, 'actual', TEAM, 8)


def test_genuine_committed_marker_retains_unknown_temporal_and_verdict_fields():
    result = project([record()])
    assert result['source_state'] == 'present_marker'
    assert result['selected_marker'] == dict(native_slot_index=0, native_kind=25,
        state='native_committed_marker', native_selector=8, selector_match='exact',
        unmapped_metadata_byte=0)
    for key in ('submission_date', 'marker_season', 'marker_competition', 'registration_verdict'):
        assert result[key] is None
    assert result['eligibility_state'] == 'not_evaluated'


def test_exact_context_absence_is_not_unregistered():
    for row in (record(team=TEAM+8), record(selector=19), record(transport=3), record(kind=24)):
        result = project([row])
        assert result['source_state'] == 'present_no_matching_marker'
        assert result['selected_marker'] is None and result['registration_verdict'] is None


def test_newest_matching_record_wins_and_pending_states_remain_distinct():
    for kind, state in ((26, 'native_temporary_addition'), (27, 'native_temporary_removal'),
                        (28, 'unmapped_native_marker_kind'), (29, 'unmapped_native_marker_kind')):
        marker = project([record(), record(kind=kind)])['selected_marker']
        assert marker['native_slot_index'] == 1 and marker['state'] == state
    assert project([record(), record(selector=19)])['selected_marker']['native_slot_index'] == 0


def test_kind56_bypasses_selector_without_inventing_meaning():
    marker = project([record(kind=56, selector=19)])['selected_marker']
    assert marker['state'] == 'unmapped_native_marker_kind'
    assert marker['selector_match'] == 'native_kind56_bypass'


def test_missing_holder_empty_vector_and_unsupported_types_stay_distinct():
    assert project(holder=False)['source_state'] == 'holder_absent'
    assert project()['source_state'] == 'present_empty'
    for kind in ('player_staff', 'virtual'):
        assert source.project(lambda *_: pytest.fail('must not read unsupported type'),
            PRIMARY, kind, TEAM, 8)['source_state'] == 'unsupported_record_kind'


@pytest.mark.parametrize('header', [(START,START+1,START+16),
    (START,START+16,START+8),(START,START,START+16*126), (0,16,16)])
def test_malformed_vectors_fail_closed(header):
    read, memory = reader()
    memory[HOLDER] = struct.pack('<QQQ', *header)
    with pytest.raises(ValueError, match='vector'):
        source.project(read, PRIMARY, 'actual', TEAM, 8)


def test_native_guard_mutation_is_rejected():
    with pytest.raises(ValueError, match='changed'):
        source.verify_native(lambda at,size: bytes(size), 0x100000)


def predicate_reader(monkeypatch, rows=(), current_owner=0x50000, contract_flag=0):
    from fm_live_mcp import players, teams
    base, club, current, contract = 0x1000000, 0x50000, 0x60000, 0x70000
    read, memory = reader(rows)
    person_vt = base+players.RVA[2]
    memory.update({PRIMARY: struct.pack('<Q', base+players.RVA[0]),
        base+players.RVA[0]-0x20: struct.pack('<q', 0x278),
        PRIMARY+0x388: struct.pack('<Q', person_vt),
        person_vt+0x230: struct.pack('<Q', base+0xD5C578),
        person_vt-0x240: struct.pack('<q', -0x388),
        PRIMARY+0x128: struct.pack('<Q', current), current+8: struct.pack('<I', 545),
        current+0x2F: b'\0', PRIMARY+0x2F0: struct.pack('<Q', contract),
        contract+0x28: bytes((contract_flag,))})
    monkeypatch.setattr(teams, 'by_index', lambda *_: ({}, dict(address=current, owner_address=current_owner)))
    binding = dict(base=base, club_address=club, team_address=TEAM, selector=8)
    return read, memory, binding


def test_native_predicate_distinguishes_committed_and_temporary_native_true(monkeypatch):
    for kind in (25, 26):
        read, _, binding = predicate_reader(monkeypatch, [record(kind=kind)])
        result = source.current_predicate(read, PRIMARY, 'actual', binding)
        assert result['native_predicate_result'] is True
        assert result['marker']['selected_marker']['native_kind'] == kind
        assert result['complete_submitted_population_evaluated'] is False
        assert result['fixture_eligibility_evaluated'] is False


def test_native_false_retains_empty_or_pending_removal_source(monkeypatch):
    for rows in ([], [record(kind=27)]):
        read, _, binding = predicate_reader(monkeypatch, rows)
        result = source.current_predicate(read, PRIMARY, 'actual', binding)
        assert result['source_state'] == 'available'
        assert result['native_predicate_result'] is False


def test_current_predicate_rejects_inapplicable_context_and_contract_override(monkeypatch):
    for kwargs, reason in ((dict(current_owner=0x50008), 'player_current_team_outside_managed_club'),
                           (dict(contract_flag=8), 'unsupported_contract_registration_override')):
        read, _, binding = predicate_reader(monkeypatch, [record()], **kwargs)
        result = source.current_predicate(read, PRIMARY, 'actual', binding)
        assert result['source_state'] == 'unavailable' and result['native_predicate_result'] is None
        assert result['reason'] == reason


def test_current_predicate_rejects_identity_or_virtual_getter_drift(monkeypatch):
    from fm_live_mcp import players
    read, memory, binding = predicate_reader(monkeypatch, [record()])
    memory[binding['base']+players.RVA[2]+0x230] = struct.pack('<Q', 0xDEAD0000)
    with pytest.raises(ValueError, match='current-team getter'):
        source.current_predicate(read, PRIMARY, 'actual', binding)


def test_current_context_missing_is_unknown_without_reads():
    result = source.current_predicate(lambda *_: pytest.fail('must not read'), PRIMARY, 'actual', None)
    assert result['native_predicate_result'] is None


@pytest.mark.parametrize('value', [None, 0, 1, 'true', []])
def test_public_registration_opt_in_requires_strict_boolean(value):
    from fm_live_mcp.bridge import Bridge, BridgeError
    with pytest.raises(BridgeError, match='include_registration'):
        Bridge().get_managed_league_age_exemptions('not-attached', include_registration=value)


def test_public_wrapper_preserves_default_and_forwards_opt_in(monkeypatch):
    from fm_live_mcp import server
    calls = []
    monkeypatch.setattr(server.bridge, 'get_managed_league_age_exemptions',
        lambda *args, **kwargs: calls.append((args, kwargs)) or {})
    server.fm_get_managed_league_age_exemptions('session', 'Coach')
    server.fm_get_managed_league_age_exemptions('session', include_registration=True)
    assert calls == [(('session', 'Coach'), {}),
                     (('session', None), {'include_registration': True})]


def test_outside_club_stays_unknown_even_when_marker_holder_is_absent(monkeypatch):
    read, memory, binding = predicate_reader(monkeypatch, current_owner=0x50008)
    memory[PRIMARY+0x2C0] = struct.pack('<Q', 0)
    result = source.current_predicate(read, PRIMARY, 'actual', binding)
    assert result['source_state'] == 'unavailable'
    assert result['native_predicate_result'] is None
    assert result['reason'] == 'player_current_team_outside_managed_club'


def current_context_reader(monkeypatch, first=(), second=()):
    """In-memory native session vectors; canonical club/rule guards are separate controls."""
    from fm_live_mcp import league_age_exemptions, prepared_tactics_source
    base, club, comp, human = 0x1000000, 0x50000, 0x80000, 0x90000
    runtime, owner, bank, rule = 0xA0000, 0xB0000, 0xC0000, 0xD0000
    memory = {
        TEAM+0x50: struct.pack('<Q', comp), comp+0xB0: struct.pack('<Q', runtime),
        runtime+0x388: struct.pack('<Q', owner), runtime+0x4C: bytes(4),
        runtime+0x138: bytes(8), base+0x56D3518: struct.pack('<i', -1),
        owner+0x1F0: struct.pack('<Q', bank), runtime+0x49: bytes(1),
        bank+0x60: struct.pack('<QQQ', 0xE0000, 0xE0008, 0xE0008),
        0xE0000: struct.pack('<Q', rule), rule+0xE8: bytes(8),
    }
    for vector_index, (offset, sessions) in enumerate(((0x200, first), (0x218, second))):
        start = 0xF0000+vector_index*0x10000
        memory[human+offset] = struct.pack('<QQQ', start, start+8*len(sessions),
                                          start+8*len(sessions)) if sessions else bytes(24)
        entries = []
        for slot, item in enumerate(sessions):
            if item is None:
                entries.append(0)
                continue
            rva, kind = item
            session = 0x110000+vector_index*0x10000+slot*0x100
            vt = session+0x40
            entries.append(session)
            memory[session] = struct.pack('<Q', vt)
            memory[vt+0x10] = struct.pack('<Q', base+rva)
            memory[base+rva] = struct.pack('<II', 0x52800000 | (kind << 5), 0xD65F03C0)
        if sessions:
            memory[start] = struct.pack(f'<{len(entries)}Q', *entries)
    monkeypatch.setattr(source, 'verify_native', lambda *_: None)
    monkeypatch.setattr(league_age_exemptions, 'verify_native', lambda *_: None)
    monkeypatch.setattr(prepared_tactics_source, '_team_and_human', lambda *_: (TEAM, human))
    monkeypatch.setattr(league_age_exemptions, 'context', lambda *_: (
        dict(source_state='available', reason='native_current_competition_rule3',
             team={'native_id': 688}, competition={'native_id': 11}, native_season_code=2030), club))
    def read(at, size):
        raw = memory[at]
        assert len(raw) == size
        return raw
    return read, memory, base


@pytest.mark.parametrize('vector', ['first', 'second'])
@pytest.mark.parametrize('rows,expected', [([record()], True), ([], False)])
def test_kind23_pending_context_preserves_native_registration_true_and_false(monkeypatch, vector, rows, expected):
    read, memory, base = current_context_reader(monkeypatch, **{
        vector: ((0x22A8DB8, 37), None, (0x22D3820, 23))})
    _, player_memory, _ = predicate_reader(monkeypatch, rows)
    memory.update(player_memory)
    context, binding = source.current_league_context(read, base, {'team_address': TEAM}, '2030-11-13')
    assert context['source_state'] == 'available'
    assert context['pending_context_kinds'] == [37, 23]
    assert binding['selector'] == 8
    result = source.current_predicate(read, PRIMARY, 'actual', binding)
    assert result['source_state'] == 'available'
    assert result['native_predicate_result'] is expected
    assert result['fixture_eligibility_evaluated'] is False


@pytest.mark.parametrize('sessions', [((0x22D3828, 23),), ((0x22D3828, 19),),
    ((0x22D3820, 23), (0x22D3828, 19))])
@pytest.mark.parametrize('vector', ['first', 'second'])
def test_unpinned_leaf_or_kind19_keeps_current_context_unknown(monkeypatch, sessions, vector):
    read, _, base = current_context_reader(monkeypatch, **{vector: sessions})
    context, binding = source.current_league_context(read, base, {'team_address': TEAM}, '2030-11-13')
    assert context['source_state'] == 'unavailable'
    assert context['reason'] == 'unsupported_pending_player_context_kind'
    assert binding is None
    result = source.current_predicate(lambda *_: pytest.fail('unknown context must not read players'),
                                      PRIMARY, 'actual', binding)
    assert result['native_predicate_result'] is None


@pytest.mark.parametrize('changed_kind', [19, 24])
def test_pinned_kind23_getter_changed_literal_is_rejected(monkeypatch, changed_kind):
    read, _, base = current_context_reader(monkeypatch, first=((0x22D3820, changed_kind),))
    with pytest.raises(ValueError, match='kind leaf changed'):
        source.current_league_context(read, base, {'team_address': TEAM}, '2030-11-13')
