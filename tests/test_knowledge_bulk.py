"""Offline tests for the bulk knowledge engine: pure H/Range functions on recorded inputs,
the bulk journal firewall, and input validation. No game access."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fm_live_mcp import knowledge_bulk as kb
from fm_live_mcp import knowledge_field_firewall as firewall
from fm_live_mcp.bridge import BridgeError

FIXTURE = json.loads((Path(__file__).parent / 'fixtures' / 'knowledge_bulk_fixed28.json').read_text())
STATE = {'exact': 2, 'range': 1, 'unknown': 0, 'unavailable': None}


def knowledge(**changes):
    k = dict(failure=None, own_context=False, category=0, score=40, score_failure=None, reciprocal=0,
             node_present=False, context_k=40, context_k_failure=None, report_present=False, report=None,
             person_index=1495, age=24, assessor_bytes=None, range_failure=None, range_inputs=True)
    k.update(changes)
    return k


def recorded(player):
    k = dict(player['knowledge'])
    if k['assessor_bytes'] is not None:
        k['assessor_bytes'] = tuple(k['assessor_bytes'])
    return k


# ---------------------------------------------------------------- H from scores and thresholds

def test_threshold_state_boundaries_and_zero_thresholds():
    assert kb.threshold_state(39, 77, 38) == 0
    assert kb.threshold_state(39, 77, 39) == 1
    assert kb.threshold_state(39, 77, 76) == 1
    assert kb.threshold_state(39, 77, 77) == 2
    assert kb.threshold_state(0, 0, 127) == 0
    with pytest.raises(ValueError):
        kb.threshold_state(39, 77, 128)


def test_field_state_branch_order():
    assert kb.field_state(knowledge(failure='x'), 18) == (None, 'x')
    # Own-club context ignores category, K and a failed score.
    assert kb.field_state(knowledge(own_context=True, category=None, score=None, score_failure='y'), 18) == (2, None)
    # Zero thresholds (category 1) answer unknown before K is consulted.
    assert kb.field_state(knowledge(category=1, score=None, score_failure='K failed'), 18) == (0, None)
    assert kb.field_state(knowledge(score=None, score_failure='K failed'), 18) == (None, 'K failed')
    assert kb.field_state(knowledge(category=3, score=11), 18) == (1, None)   # field18 cat3 = (11, 49)
    assert kb.field_state(knowledge(category=3, score=49), 18) == (2, None)
    assert kb.field_state(knowledge(category=3, score=10), 18) == (0, None)


def test_combined_score_is_signed_max_then_report():
    assert kb.combined_score(0, 40) == 40
    assert kb.combined_score(-5, 30, 66) == 66
    assert kb.combined_score(95, 30, 10) == 95
    assert kb.combined_score(-128, 0) == 0


@pytest.mark.parametrize('player', FIXTURE['players'], ids=lambda p: f"ordinal{p['ordinal']}")
def test_recorded_field_states_equal_tool_cells(player):
    k = recorded(player)
    for field, cell in enumerate(player['visible']):
        assert kb.field_state(k, field)[0] == STATE[cell['state']], (player['ordinal'], field)


@pytest.mark.parametrize('player', FIXTURE['players'], ids=lambda p: f"ordinal{p['ordinal']}")
def test_recorded_star_gates_equal_original_h_replay(player):
    k = recorded(player)
    original = player['original_h_replay']
    assert k['score'] == original['score']
    assert kb.ability_state(k, 0x62)[0] == original['0x62']
    assert kb.ability_state(k, 0x63)[0] == original['0x63']


def test_recorded_state_totals_match_verified_scope():
    counts = dict(exact=0, range=0, unknown=0, unavailable=0)
    for player in FIXTURE['players']:
        for cell in player['visible']:
            counts[cell['state']] += 1
    assert counts == dict(exact=120, range=900, unknown=296, unavailable=0)


def test_ability_state_thresholds():
    assert kb.ability_state(knowledge(score=20), 0x62)[0] == 0
    assert kb.ability_state(knowledge(score=21), 0x62)[0] == 1
    assert kb.ability_state(knowledge(score=71), 0x62)[0] == 2
    assert kb.ability_state(knowledge(score=99), 0x63)[0] == 1
    assert kb.ability_state(knowledge(score=100), 0x63)[0] == 2
    assert kb.ability_state(knowledge(own_context=True, score=None), 0x63)[0] == 2
    assert kb.ability_state(knowledge(score=None, score_failure='K'), 0x62) == (None, 'K')


# ---------------------------------------------------------------- Range projection

@pytest.mark.parametrize('player', FIXTURE['players'], ids=lambda p: f"ordinal{p['ordinal']}")
def test_recorded_ranges_are_reproduced_by_some_getter(player):
    """Every recorded range is the projection of some getter 1..20 with the recorded inputs,
    and that getter lies inside it. The getter itself (a hidden byte) is not recorded."""
    k = recorded(player)
    for field, cell in enumerate(player['visible']):
        if cell['state'] != 'range':
            continue
        hits = [g for g in range(1, 21) if kb.cell_value(field, 1, g, k) ==
                dict(state='range', minimum=cell['minimum'], maximum=cell['maximum'])]
        assert hits, (player['ordinal'], field)
        assert all(cell['minimum'] <= g <= cell['maximum'] for g in hits)


def test_cell_value_exact_range_and_unavailable_shapes():
    k = knowledge(score=30, age=17, person_index=7)
    assert kb.cell_value(18, 2, 13, k) == {'state': 'exact', 'value': 13}
    value = kb.cell_value(18, 1, 13, k)
    assert value['state'] == 'range' and value['minimum'] <= 13 <= value['maximum']
    # Width depends on the age band and K: a young, barely known player gets a wider range.
    wide = kb.cell_value(0, 1, 10, knowledge(score=10, age=16, person_index=0))
    narrow = kb.cell_value(0, 1, 10, knowledge(score=60, age=30, person_index=0))
    assert wide['maximum'] - wide['minimum'] > narrow['maximum'] - narrow['minimum']
    assert kb.cell_value(18, 1, 13, knowledge(range_failure='Unproved range assessor family')) == dict(
        state='unavailable', reason='unavailable_source', detail='Unproved range assessor family')
    assert kb.cell_value(18, 1, 13, knowledge(age=12))['detail'] == 'Native ordinary age must be 0 or 14..100'
    assert kb.cell_value(18, 2, 0, k) == {'state': 'unavailable', 'reason': 'unsupported_native_projection'}


def test_range_placement_follows_person_index_plus_field_mod_7():
    k = knowledge(score=30, age=25)
    shapes = set()
    for index in range(7):
        v = kb.cell_value(0, 1, 10, dict(k, person_index=index))
        shapes.add((v['minimum'] - 10, v['maximum'] - 10))
    assert len(shapes) == 7
    assert kb.cell_value(1, 1, 10, dict(k, person_index=6)) == kb.cell_value(0, 1, 10, dict(k, person_index=7))


def test_winning_sources_and_lowest_thresholds():
    assert kb.winning_sources(knowledge(own_context=True)) == ['own_club']
    assert kb.winning_sources(knowledge(score=40, context_k=40)) == ['context']
    assert kb.winning_sources(knowledge(score=66, context_k=40, report=66)) == ['report']
    assert kb.winning_sources(knowledge(score=50, context_k=50, node_present=True, reciprocal=50)) == ['context', 'node']
    assert kb.winning_sources(knowledge(failure='x')) == []
    assert kb.lowest_thresholds(0) == (3, 41)
    assert kb.lowest_thresholds(1) == (None, None)


def test_population_definitions_count_rows():
    row = dict(state='available', node_present=True, report_present=False, own_club_context=False,
               any_known=True, any_exact=False, all_unknown=False, h_score=40,
               star_gates=dict(current_ability=dict(h_state=1)))
    counts = kb.population_definitions([row, dict(state='unavailable')])
    assert counts['evaluated'] == 2 and counts['unavailable'] == 1
    assert counts['node_present'] == 1 and counts['any_field_range_or_exact'] == 1
    assert counts['ca_star_gate_known'] == 1 and counts['ca_star_gate_exact'] == 0


# ---------------------------------------------------------------- bulk journal firewall

PRIMARY = 0x100000
ATTR = PRIMARY + firewall.ATTRIBUTE_BLOCK_START


def memory():
    return {a: (a * 7) & 255 for a in range(PRIMARY, PRIMARY + 0x400)}


def journal_with(mem, source_type=object):
    bridge = SimpleNamespace(session='s', process='p')
    calls = []

    def physical(address, size):
        calls.append((address, size))
        return bytes(mem[address + i] for i in range(size))
    journal = kb.BulkJournal(physical, bridge)
    journal.forbidden = firewall.Intervals([(ATTR, PRIMARY + firewall.ATTRIBUTE_BLOCK_END)])
    journal.source_type = source_type
    return journal, bridge, calls


class Source:
    def __init__(self, bridge):
        self.bridge, self.session, self.process = bridge, 's', 'p'
        self.subject = SimpleNamespace(primary=PRIMARY)


def test_forbidden_attribute_read_is_refused_and_poisons():
    journal, _, _ = journal_with(memory())
    assert journal.read(PRIMARY, 8)
    with pytest.raises(ValueError, match='forbidden'):
        journal.read(ATTR, 1)
    with pytest.raises(ValueError, match='poisoned'):
        journal.read(PRIMARY + 0x300, 4)


def test_grant_requires_registered_record_and_h_state_at_least_one():
    journal, bridge, _ = journal_with(memory(), Source)
    source = Source(bridge)
    with pytest.raises(ValueError, match='registered'):
        journal.authorize_cell(source, 18)
    journal2, bridge2, _ = journal_with(memory(), Source)
    source2 = Source(bridge2)
    journal2.register(source2, knowledge(category=0, score=10))   # field 18 cat0 = (39, 77): unknown
    with pytest.raises(ValueError, match='does not permit'):
        journal2.authorize_cell(source2, 18)


def test_grant_opens_exactly_one_byte_for_a_known_cell():
    journal, bridge, _ = journal_with(memory(), Source)
    source = Source(bridge)
    journal.register(source, knowledge(category=0, score=40))
    address = journal.authorize_cell(source, 18)
    assert address == PRIMARY + 0x148 + 0x16
    assert journal.read(address, 1) == bytes([(address * 7) & 255])
    with pytest.raises(ValueError, match='forbidden'):
        journal.read(address, 2)


def test_register_refuses_foreign_sources_and_mutation_after_registration():
    journal, bridge, _ = journal_with(memory(), Source)
    with pytest.raises(ValueError, match='bulk approved source'):
        journal.register(object(), knowledge())
    journal, bridge, _ = journal_with(memory(), Source)
    source = Source(bridge)
    record = knowledge(category=0, score=10)
    journal.register(source, record)
    record['score'] = 100   # the journal keeps its own copy
    with pytest.raises(ValueError, match='does not permit'):
        journal.authorize_cell(source, 18)


def test_final_fence_detects_change_and_coalesces_only_outside_forbidden_bytes():
    mem = memory()
    journal, bridge, calls = journal_with(mem, Source)
    for offset in (0, 8, 16, 0x200, 0x208):
        journal.read(PRIMARY + offset, 8)
    source = Source(bridge)
    journal.register(source, knowledge(category=0, score=40))
    granted = journal.authorize_cell(source, 18)
    journal.read(granted, 1)
    calls.clear()
    journal.verify_overlaps()
    journal.verify()
    assert journal.fenced_regions == len(journal.observed) == 6
    assert (granted, 1) in calls                     # attribute byte fenced on its own
    assert not any(a <= ATTR < a + n and (a, n) != (granted, 1) for a, n in calls)
    mem[PRIMARY + 0x204] ^= 1
    journal2, _, _ = journal_with(mem)
    journal2.observed = {k: v for k, v in journal.observed.items() if k != (granted, 1)}
    with pytest.raises(ValueError, match='changed at final physical fence'):
        journal2.verify()


def test_overlapping_read_shapes_must_agree():
    journal, _, _ = journal_with(memory())
    journal.read(PRIMARY, 8)
    journal.observed[(PRIMARY + 4, 8)] = b'\xff' * 8
    with pytest.raises(ValueError, match='Conflicting'):
        journal.verify_overlaps()


def test_forbidden_binding_after_a_hidden_read_is_refused():
    journal, _, _ = journal_with(memory())
    journal.forbidden = firewall.Intervals()
    journal.read(ATTR, 4)
    with pytest.raises(ValueError, match='before forbidden geometry binding'):
        journal.forbidden = firewall.Intervals([(ATTR, ATTR + 8)])


# ---------------------------------------------------------------- input validation

@pytest.mark.parametrize('keys', [[], [1, 1], [-1], [1.5], [('ordinal',)], [('other', 1)], [''], 'abc'])
def test_player_key_validation(keys):
    with pytest.raises(BridgeError):
        kb._validate_keys(keys)


def test_player_key_kinds_accepted():
    assert kb._validate_keys([3, ('ordinal', 5), ('address', 4096), 'ref']) == [3, ('ordinal', 5), ('address', 4096), 'ref']


def test_bridge_or_session_requires_a_genuine_bridge():
    with pytest.raises(BridgeError):
        kb._bridge_and_session(SimpleNamespace(session='s'))
    with pytest.raises(BridgeError):
        kb._bridge_and_session(('not a bridge', 's'))


def test_field_selection_defaults_to_all_47():
    assert kb._field_ids(None) == kb.ALL_FIELDS and len(kb.ALL_FIELDS) == 47
    assert kb._field_ids(['Passing', 0]) == (18, 0)
