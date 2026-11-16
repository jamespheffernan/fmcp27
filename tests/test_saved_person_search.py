import os
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_person_search as search, snapshot_catalog
from test_saved_club_search import snapshot


@pytest.fixture
def saved(tmp_path):
    contents = b"complete raw component" * 12000
    path = snapshot(tmp_path / 'roster.fm', contents)
    with snapshot_catalog.checked_snapshot(path.name, directory=tmp_path) as (_, _, identity):
        pin = snapshot_catalog.snapshot_id(identity)
    return path, contents, pin


def test_all_bytes_and_pinned_reference_order(saved, monkeypatch):
    path, contents, pin = saved
    layout = SimpleNamespace(person_count=30)
    def locate(data):
        assert data[:] == contents
        return layout
    def lookup(data, incoming, indices):
        assert incoming is layout and data[:] == contents
        assert indices == [6, 9]
        return [{'person_index': i, 'candidates': [], 'state': 'missing', 'search_complete': True,
                 'budget_reasons': [], 'evidence_scope': {}} for i in indices]
    def neighbours(data, incoming, rows, **kwargs):
        assert incoming is layout and kwargs['prefix_probe'] is search.saved_player_wire_prefix.prefix_probe
        return [{**r, 'neighbour_corroboration': {'preferred_geometries': []}} for r in rows]
    monkeypatch.setattr(search.saved_person_neighbours, 'corroborate_candidates', neighbours)
    monkeypatch.setattr(search.saved_name_vectors, 'locate', locate)
    monkeypatch.setattr(search.saved_person_candidates, 'search_candidates', lookup)
    reply = search.get_name_candidates(path.name, [6, 9, 6], pin, directory=path.parent)
    assert reply['snapshot_id'] == pin and reply['declared_person_slots'] == 30
    assert [row['person_index'] for row in reply['people']] == [6, 9, 6]


@pytest.mark.parametrize('indices', [[], [1] * 33, [True], [-1], ['1'], [2**31], None])
def test_invalid_lookup_rejected_before_file_access(tmp_path, indices):
    with pytest.raises(ValueError, match='PERSON'):
        search.get_name_candidates('missing.fm', indices, 'pin', directory=tmp_path)


def test_requires_pin_and_recognizes_stale_roster(saved):
    path, _, pin = saved
    with pytest.raises(ValueError, match='snapshot ID'):
        search.get_name_candidates(path.name, [1], None, directory=path.parent)
    with pytest.raises(ValueError, match='changed'):
        search.get_name_candidates(path.name, [1], pin[::-1], directory=path.parent)


def test_file_replacement_during_search_invalidates_result(saved, monkeypatch):
    path, contents, pin = saved
    monkeypatch.setattr(search.saved_name_vectors, 'locate', lambda data: SimpleNamespace(person_count=5))
    def replace(*args):
        newer = snapshot(path.with_name('next.fm'), contents)
        os.replace(newer, path)
        return []
    monkeypatch.setattr(search.saved_person_neighbours, 'corroborate_candidates',
                        lambda *args, **kwargs: [])
    monkeypatch.setattr(search.saved_person_candidates, 'search_candidates', replace)
    with pytest.raises(ValueError, match='changed during request'):
        search.get_name_candidates(path.name, [1], pin, directory=path.parent)


def test_buffer_slot_released_on_decoder_error(saved, monkeypatch):
    path, _, pin = saved
    def fail(_):
        raise ValueError('unsupported layout')
    monkeypatch.setattr(search.saved_name_vectors, 'locate', fail)
    for _ in range(2):
        with pytest.raises(ValueError, match='unsupported layout'):
            search.get_name_candidates(path.name, [1], pin, directory=path.parent)


def test_preferred_witnesses_and_incomplete_pages_preserve_alternatives():
    def candidate(index):
        return dict(identity={'stored_index': 0}, name_indices=[index, -1, -1], names=[],
                    common_start=index, common_end=40, identity_offset=48, end=60, next_tag=2,
                    neighbour_evidence={'tier':'test', 'preceding':[], 'following':[]})
    row = dict(person_index=0,state='ambiguous',search_complete=True,budget_reasons=[],evidence_scope={},
               candidates=[candidate(1),candidate(2),candidate(3)],
               neighbour_corroboration={'search_complete':True,
                                       'preferred_geometries':[{'common_start':2,'identity_offset':48}]})
    def selected(include=False, offset=0, limit=100):
        page = search._project(row, include, offset, limit)
        return [c['common_start'] for c in page['candidates']], page['next_candidate_offset']
    assert selected() == ([2], None)
    assert selected(True, 1, 1) == ([2], 2)
    assert selected(True, 2, 1) == ([3], None)
    row['neighbour_corroboration']['search_complete'] = False
    assert selected() == ([1,2,3], None)
    row['neighbour_corroboration']['search_complete'] = True
    row['search_complete'] = False
    assert selected() == ([1,2,3], None)
