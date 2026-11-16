"""fm_get_ui_screen(screen='tactics') reports the manager's tactics, not the UI layer's default.

On a live match (12 November 2026) the COMPETITION_TACTIC handler built from the team record
answered "4-4-2, Balanced, one slot" while the manager had three prepared 4-2-3-1 tactics on
Positive and the match was using one of them. pi-fm advised "Balanced -> Positive" from it."""
from __future__ import annotations

from fm_live_mcp.fmdb import ui_recipes_round2 as R, ui_tools
from test_no_role_duty import duty_mentions


def _position(name, role):
    return {'name': name, 'base_role': {'compiled_english_name': role}}


class _Bridge:
    def __init__(self, match=None, fail=False):
        self.match, self.fail = match, fail

    def get_managed_tactics(self, session_id, coach, formation, instructions, roles):
        assert (formation, instructions, roles) == (True, True, True)
        if self.fail:
            raise RuntimeError('No attached Football Manager session')
        return {'source_state': 'available', 'team': {'native_id': 688},
                'primary_trained_tactic': {'slot_index': 0},
                'slots': [{'slot_index': 0, 'state': 'stored', 'name': 'Hub 4231',
                           'mentality': {'name': 'Positive'},
                           'team_instructions': {'selected_options': [{'native_option_id': 5, 'name': 'Pass Into Space'},
                                                                      {'native_option_id': 99, 'name': None}]},
                           'phases': {'in_possession': {'positions': [_position('GK', 'Goalkeeper'),
                                                                      _position('ST(C)', 'Centre Forward')]},
                                      'out_of_possession': {'positions': [_position('GK', 'Goalkeeper')]}}},
                          {'slot_index': 1, 'state': 'null', 'name': None}]}


def _match(team_id=688, state='available_fixture_bound'):
    return {'state': state, 'displayed_period': 'SecondHalf', 'displayed_score': {'home': 2, 'away': 1},
            'tactics': {'state': 'available', 'sides': [
                {'team': {'native_id': team_id}, 'name': 'Last 30', 'mentality': {'name': 'Positive'},
                 'instructions': {'selected_options': [{'native_option_id': 62, 'name': 'Mid Block'}]},
                 'phases': {'in_possession': [{'position': 'ST(C)', 'base_role': 'Deep-Lying Forward'}]}},
                {'team': {'native_id': 600}, 'name': None, 'mentality': {'name': 'Balanced'},
                 'instructions': {'selected_options': []}, 'phases': {}}]}}


def _read(monkeypatch, bridge, match):
    from fm_live_mcp import current_match_report
    def report(b, session_id, scope, include_tactics, **kwargs):
        assert scope == 'simulation' and include_tactics and kwargs == {'persist_host_observations': False}
        if isinstance(match, Exception):
            raise match
        return match
    monkeypatch.setattr(current_match_report, 'current_match_report', report)
    return ui_tools.manager_tactics(bridge, 'sid')


def test_the_screen_recipe_no_longer_reads_the_default_tactic_handler():
    assert [part for part, *_ in R.SCREENS['tactics']] == ['team']
    assert all(htype != R.COMPETITION_TACTIC for _p, htype, *_ in R.SCREENS['tactics'])


def test_prepared_slots_and_the_tactic_in_use(monkeypatch):
    out = _read(monkeypatch, _Bridge(), _match())
    slot = out['prepared']['slots'][0]
    assert out['prepared']['primary_trained_slot'] == 0
    assert (slot['name'], slot['mentality']) == ('Hub 4231', 'Positive')
    assert slot['team_instructions'] == ['Pass Into Space', 'option 99']
    assert slot['in_possession'] == ['GK Goalkeeper', 'ST(C) Centre Forward']
    assert out['prepared']['slots'][1] == {'slot': 1, 'state': 'null', 'name': None}
    live = out['in_match']
    assert (live['name'], live['mentality'], live['team_instructions']) == ('Last 30', 'Positive', ['Mid Block'])
    assert live['in_possession'] == ['ST(C) Deep-Lying Forward'] and live['score'] == {'home': 2, 'away': 1}
    assert duty_mentions(out) == []


def test_a_role_line_is_the_position_and_the_role_only(monkeypatch):
    """A role in Football Manager 27 has no duty. Sources of an earlier shape, which carried the
    name of the role word's internal flag beside the role, print the same line."""
    bridge, match = _Bridge(), _match()
    prepared = bridge.get_managed_tactics('sid', None, True, True, True)
    prepared['slots'][0]['phases']['in_possession']['positions'][0]['base_role']['duty'] = {'name': 'Defend'}
    bridge.get_managed_tactics = lambda *args: prepared
    match['tactics']['sides'][0]['phases']['in_possession'][0]['duty'] = 'Attack'
    out = _read(monkeypatch, bridge, match)
    assert out['prepared']['slots'][0]['in_possession'] == ['GK Goalkeeper', 'ST(C) Centre Forward']
    assert out['in_match']['in_possession'] == ['ST(C) Deep-Lying Forward']
    assert duty_mentions(out) == []


def test_no_match_and_failures_are_reported_separately(monkeypatch):
    assert _read(monkeypatch, _Bridge(), _match(state='unavailable_no_resident_client'))['in_match'] is None
    assert 'not one of the two sides' in _read(monkeypatch, _Bridge(), _match(team_id=1))['in_match']['unavailable']
    out = _read(monkeypatch, _Bridge(), ValueError('Game state changed during read; retry'))
    assert out['in_match'] == {'unavailable': 'Game state changed during read; retry'} and 'slots' in out['prepared']
    out = _read(monkeypatch, _Bridge(fail=True), _match())
    assert 'No attached' in out['prepared']['unavailable']
