import pytest
from fm_live_mcp import player_ban_source as source, competitions


def projection(kind=1, index=662):
    return {'records': [{'native_kind': kind, 'unmapped_scope_context_word': index,
                         'native_properties': {'badd': 1, 'badm': 0},
                         'eligibility_state': 'not_evaluated'}]}


def read(address, size):
    return dict(source.COMP_SCOPE_SPANS)[address-0x100000000]


def test_canonical_identity_not_name_join(monkeypatch):
    def lookup(r, b, i):
        assert (b, i) == (0x100000000, 662)
        return {'native_id': 1301427, 'database_index': i, 'name': 'Same name'}
    monkeypatch.setattr(competitions, 'by_index', lookup)
    row = source.resolve_competition_scopes(read, 0x100000000, projection())['records'][0]
    assert row['scope']['competition']['native_id'] == 1301427
    assert row['stored_match_balance']['matches'] == 1
    assert row['eligibility_state'] == 'not_evaluated'


def test_unsupported_kind_never_borrows_competition(monkeypatch):
    monkeypatch.setattr(competitions, 'by_index', lambda *a: pytest.fail('untyped lookup'))
    p = projection(kind=2)
    assert source.resolve_competition_scopes(read, 0x100000000, p) == p
    assert 'scope' not in p['records'][0]


def test_mismatched_typed_scope_rejects(monkeypatch):
    def lookup(*args):
        raise ValueError('Primary and canonical competition identities disagree')
    monkeypatch.setattr(competitions, 'by_index', lookup)
    with pytest.raises(ValueError, match='identities disagree'):
        source.resolve_competition_scopes(read, 0x100000000, projection())


def test_route_drift_rejects():
    with pytest.raises(ValueError, match='operand route changed'):
        source.resolve_competition_scopes(lambda a,n: bytes(n), 0x100000000, projection())


def test_sentinel_and_unsupported_count_are_explicit():
    p = projection(index=-1)
    p['records'][0]['native_properties']['badm'] = 2
    row = source.resolve_competition_scopes(read, 0x100000000, p)['records'][0]
    assert row['scope'] == {'state': 'native_competition_sentinel', 'competition': None}
    assert row['stored_match_balance']['matches'] is None
