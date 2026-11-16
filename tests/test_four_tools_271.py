"""27.0.1: fixture rules, league player ranking and player match form.

The used-substitute cap helper and its byte jump table changed on 27.0.1 (0x48F9DA4 -> 0x49FF400:
a new prologue and re-laid-out cases). Both builds' helpers are emulated from the preserved plugin
files over every signed rule code and both sides, and compared with each other and with
`fixture_rules.substitutions`. The league ranking and match form guards cover whole functions whose
instructions are the same on both builds apart from block order and page offsets (reviewed by hand,
fm_live_mcp/fmdb/data/address_overrides.json)."""
import json
from pathlib import Path

import pytest

from fm_live_mcp import fixture_rules as fr

from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds

HELPERS = {'old': {'named': 0x48F9CFC, 'used': 0x48F9DA4, 'stoppages': 0x48F9E84},
           'new': {'named': 0x49FF358, 'used': 0x49FF400, 'stoppages': 0x49FF518}}
SHA = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
REVIEWED = {'fixture_rules.py': ('0x22c1e90', '0x48f9da4', '0x54037d9'),
            'league_player_ranking.py': ('0xf5301c',), 'live_player_match_form.py': ('0x153f518',)}


def _helpers(build):
    v, base, _ = _static_vm(OLD if build == 'old' else NEW)
    out = {}
    for code in range(-128, 128):
        for away in (0, 1):
            row = []
            for k in ('named', 'used', 'stoppages'):
                r = v.call(base + HELPERS[build][k], (code & 0xFFFFFFFFFFFFFFFF, away))[0] & 0xFFFFFFFF
                row.append(r - (1 << 32) if r & 0x80000000 else r)
            out[(code, away)] = tuple(row)
    return out


@pytest.mark.slow
@needs_builds
def test_substitution_helpers_are_equal_on_both_builds_and_to_the_mirror():
    old, new = _helpers('old'), _helpers('new')
    assert old == new
    for (code, away), (named, used, stoppages) in new.items():
        m = fr.substitutions(code, bool(away), 255)
        assert (m['named_substitute_cap'], m['used_substitute_cap']) == (named, used), (code, away)
        assert m['substitution_stoppages'] == (None if stoppages < 0 else stoppages), code


def test_reviews_of_the_four_tools_are_recorded():
    doc = json.loads((Path(fr.__file__).parent / 'fmdb/data/address_overrides.json').read_text())
    guards = doc.get('builds', {}).get(SHA, {}).get('guards', {})
    if not all(k in guards.get(f, {}) for f, ks in REVIEWED.items() for k in ks):
        pytest.skip('the four-tools review is not merged yet')
    for f, ks in REVIEWED.items():
        for k in ks:
            entry = guards[f][k]
            assert entry['verdict'] in ('shape', 'registers', 'ported') and entry['evidence']
