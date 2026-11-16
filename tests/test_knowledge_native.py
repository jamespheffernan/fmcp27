"""knowledge_native: pure parts offline; the emulated operands and search admission live-gated."""
import os

import pytest

from fm_live_mcp import knowledge_native as kn
from fm_live_mcp.knowledge_field_firewall import Intervals


def test_blank_forbidden_zeroes_only_forbidden_bytes():
    forbidden = Intervals([(0x10010, 0x10020), (0x10ff0, 0x11010), (0x20000, 0x20010)])
    page = bytes(range(256)) * 16
    data, spans = kn.blank_forbidden(0x10000, page, forbidden.ranges, forbidden.starts)
    assert spans == [(0x10010, 0x10020), (0x10ff0, 0x11000)]
    assert data[0x10:0x20] == bytes(16) and data[0xff0:] == bytes(16)
    assert data[:0x10] == page[:0x10] and data[0x20:0xff0] == page[0x20:0xff0]
    untouched, none = kn.blank_forbidden(0x30000, page, forbidden.ranges, forbidden.starts)
    assert untouched == page and none == []


def test_merge_loads():
    assert kn.merge_loads({(0x100, 8), (0x104, 8), (0x200, 4), (0x10c, 4), (0x110, 1)}) == \
        [(0x100, 0x111), (0x200, 0x204)]
    assert kn.merge_loads({(0x100, 8), (0x108, 8)}) == [(0x100, 0x110)]
    assert kn.merge_loads({(0x100, 8), (0x200, 8)}) == [(0x100, 0x108), (0x200, 0x208)]
    assert kn.merge_loads({(0x100, 16), (0x104, 4)}) == [(0x100, 0x110)]


@pytest.mark.parametrize('name,message,expected', [
    ('relation_mask', 'Unproved owned CLUB node family', True),
    ('relation_mask', 'Reached unproved 17bb4c0 selection; absence is not native null', True),
    ('relation_mask', 'Unproved transfer predicate contract type', True),
    ('transfer_predicate', 'Unproved transfer predicate contract type', True),
    ('transfer_predicate', 'Unproved owned CLUB node family', False),
    ('relation_mask', 'Unproved nonnull owner-parent relation composition', False),
    ('club_score', 'Unproved owned CLUB node family', False),
])
def test_refusal_matches_only_the_three_known_reasons(name, message, expected):
    assert kn.refusal_matches(name, ValueError(message)) is expected


class _Entity:
    def __init__(self, address, primary=None):
        self.address, self.primary = address, primary


class _Base:
    """Stand-in for the bulk source: scripted Python operand answers."""
    answers = {}

    def __init__(self):
        self.owner = _Entity(0x10, primary=0x1000)
        self.subject = _Entity(0x20, primary=0x2000)

    def _operand(self, name, *args):
        answer = self.answers[name]
        if isinstance(answer, Exception):
            raise answer
        return answer


class _Native:
    def __init__(self):
        self.calls = []

    def relation_mask(self, human, subject):
        self.calls.append(('relation_mask', human, subject))
        return 0x5FE

    def transfer_predicate(self, subject, club):
        self.calls.append(('transfer_predicate', subject, club))
        return True


def _source(answers, verify=None):
    native = _Native()
    base = type('Scripted', (_Base,), {'answers': answers})
    return kn.source_type(base, native, verify=verify)(), native


def test_python_answers_pass_through_untouched():
    source, native = _source({'relation_mask': 0, 'transfer_predicate': False, 'other': 7})
    assert source._operand('relation_mask') == 0
    assert source._operand('transfer_predicate', _Entity(0x20, 0x2000), _Entity(0x30)) is False
    assert source._operand('other') == 7
    assert native.calls == []


def test_known_refusals_are_answered_natively_with_the_k_arguments():
    source, native = _source({'relation_mask': ValueError('Unproved owned CLUB node family'),
                              'transfer_predicate': ValueError('Unproved transfer predicate contract type')})
    assert source._operand('relation_mask') == 0x5FE
    assert source._operand('transfer_predicate', _Entity(0x20, 0x2000), _Entity(0x30)) is True
    assert native.calls == [('relation_mask', 0x1000, 0x2000), ('transfer_predicate', 0x2000, 0x30)]


def test_other_refusals_still_propagate():
    source, native = _source({'relation_mask': ValueError('Unproved subject-parent relation service')})
    with pytest.raises(ValueError, match='subject-parent'):
        source._operand('relation_mask')
    assert native.calls == []


def test_verify_mode_counts_agreement_without_changing_the_answer():
    verify = {}
    source, _ = _source({'relation_mask': 0x5FE, 'transfer_predicate': False}, verify)
    assert source._operand('relation_mask') == 0x5FE
    assert source._operand('transfer_predicate', _Entity(0x20, 0x2000), _Entity(0x30)) is False
    assert verify == {'relation_mask_equal': 1, 'transfer_predicate_different': 1}


# --------------------------------------------------------------------------- live (FM27 attached)

@pytest.fixture(scope='module')
def live():
    if os.environ.get('FM_LIVE_REGRESSION') == '0':
        pytest.skip('FM_LIVE_REGRESSION=0')
    from fm_live_mcp import bridge as bridge_module
    bridge = bridge_module.Bridge()
    if not bridge.helper.is_file():
        pytest.skip('native helper not built')
    try:
        session_id = bridge.attach()['session_id']
    except Exception as exc:
        pytest.skip(f'FM27 is not attached: {exc}')
    yield bridge, session_id
    bridge.detach()


def test_live_native_operands_agree_with_python_where_python_answers(live):
    from fm_live_mcp import knowledge_bulk as kb
    keys, _ = kb.random_ordinals(live, 150, seed=7)
    result = kb.player_knowledge_summary(live, keys, native='verify')
    verify = result['native_operands']['verify']
    assert not any(key.endswith('_different') or key.endswith('_refused') for key in verify), verify
    assert verify.get('relation_mask_equal', 0) > 100


def test_live_native_rows_equal_default_rows_on_fixed_ordinals_and_squad(live):
    """The default path equals the tool (tests/test_knowledge_bulk_live.py); native=True must
    equal the default path wherever the default path answered: the fixed 28 x 47 and the squad."""
    from fm_live_mcp import knowledge_bulk as kb
    from test_knowledge_bulk_live import FIXED_ORDINALS
    bridge, session_id = live
    refs = [p['player_ref'] for p in bridge.get_managed_squad(session_id)['players']]
    for keys in ([('ordinal', o) for o in FIXED_ORDINALS], refs):
        plain = kb.visible_attributes_bulk(live, keys)
        native = kb.visible_attributes_bulk(live, keys, native=True)
        assert 'native_operands' not in plain
        assert [p['fields'] for p in plain['players']] == [p['fields'] for p in native['players']]
        assert plain['state_counts'] == native['state_counts']


def test_live_search_admission_matches_the_evidence_subjects(live):
    import json
    from pathlib import Path
    path = Path('/Volumes/4TB Private/Offloaded/FMCP 27/evidence/knowledge-perceived-ability-20261110/'
                'replay-search-admission-20261110.json')
    if not path.is_file():
        pytest.skip('evidence packet not available')
    subjects = json.loads(path.read_text())['subjects']
    result = kn.search_admission(live, [('ordinal', s['ordinal']) for s in subjects])
    for subject, row in zip(subjects, result['players']):
        assert (row['admitted'], row['club_leaf'], row['same_club']) == \
            (subject['admitted'], subject['club_leaf'], subject['same_club'])


def test_live_search_admission_admits_the_own_squad_by_same_club(live):
    bridge, session_id = live
    refs = [p['player_ref'] for p in bridge.get_managed_squad(session_id)['players']]
    result = kn.search_admission(live, refs)
    assert all(row['admitted'] and row['same_club'] for row in result['players'])
