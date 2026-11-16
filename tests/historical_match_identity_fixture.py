"""Explicit TEAM-only replay for immutable pre154 partial statistic journals.

Those journals never claimed the later global PERSON getter operands. Only
marked historical reader instances receive their original identity contract;
unmarked synthetic, genuine154 and production readers retain the current route.
This helper changes no bytes, statistic values, expected results or assertions.
"""
from functools import lru_cache
import gzip
import hashlib
from pathlib import Path
from types import MethodType

import pytest
from fm_live_mcp import active_match_people, world

# SHA256 of the original uncompressed evidence, not a regenerated fixture.
HISTORICAL_FIXTURES = {
    'current_player_aerial147.json.gz':
        '8295f6ea0381fba648a92708fb2aaf1f6bc734a1ae2a707275568a2245490982',
    'current_player_chance_quality147.json.gz':
        'efdbeca0824ca96dfc4196e498f75054267441fa1e4c7d98864366e64a5d5f9e',
    'current_player_defence_running147.json.gz':
        'b6f6e2c93b40de4fab0101157d4ab9e06a7041c44d914529b3388837800eca7e',
    'current_player_delivery147.json.gz':
        '8eddf13eae6a646875031962c44e0e430ba418ec7a860f265db695559477fcbc',
    'current_player_keeper_incident147.json.gz':
        '66972058e0f0481289b22bf848289c64402d4dc4e9086e041533c410e21f4314',
    'current_player_match_statistic_groups147.json.gz':
        '4645342878a03d98c90b5ba32b04ababa29c0b6cb5aae2f2b7e7d79e9a9ce931',
    'current_player_match_statistic_groups33_153.json.gz':
        'a9326919abee50f3b6e12af7cf02fa23ee9b3187f909ffccef45770b1a9a4a40',
    'current_player_match_statistics147.json.gz':
        '12e51bfd9224e8d5a535202823e7a2c4d8ac465ef1295b249ba395fc5f924ed8',
    'current_player_passing140.json.gz':
        '0cdfa3197a6aaf9b1b64f180b8d58779b88b37ce6698fc83bc89e12fabeef3de',
    'current_player_recovery147.json.gz':
        '7391a60fde7d74b50895b211b67176e5c0a5bf4e0eba77650c75372637cc5362',
}


@lru_cache(maxsize=None)
def _validate_fixture(name):
    expected = HISTORICAL_FIXTURES[name]
    raw = gzip.decompress((Path(__file__).parent/'fixtures'/name).read_bytes())
    assert hashlib.sha256(raw).hexdigest() == expected


def _historical_reader(read, base, engine):
    """Follow only explicit ReadSet/wrapper links to a marked fixture harness."""
    seen = set()
    while id(read) not in seen:
        seen.add(id(read))
        if isinstance(read, world.ReadSet):
            read = read.read
        elif isinstance(read, MethodType):
            owner = read.__self__
            name = getattr(owner, 'historical_identity_fixture', None)
            if name not in HISTORICAL_FIXTURES:
                return False
            _validate_fixture(name)
            return owner.base == base and owner.engine == engine
        elif hasattr(read, '__dict__') and 'historical_identity_read' in vars(read):
            read = vars(read)['historical_identity_read']
        else:
            return False
    return False


@pytest.fixture(autouse=True)
def historical_team_identity_contract(monkeypatch):
    current = active_match_people.inspect_canonical

    def versioned(read, base, engine, *, identity_only=False):
        route = (active_match_people._inspect_canonical_team
                 if _historical_reader(read, base, engine) else current)
        return route(read, base, engine, identity_only=identity_only)

    monkeypatch.setattr(active_match_people, 'inspect_canonical', versioned)
    return current
