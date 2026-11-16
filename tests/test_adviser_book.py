"""pi-fm's tactic writer on another game build: its census, the rewrite of its files, the reviews.

The tactic writer (adviser/pi/fm-tactic-files.py and its fm_tactic_* siblings) is bound to the
installed game build by fm_live_mcp/adviser_book.py from the `adviser` section of the build's
address map (fmdb/adviser_update.py). These checks need no game; the ones that read both
preserved plugins skip without them.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

from fm_live_mcp import address_book as ab
from fm_live_mcp import adviser_book as adv
from fm_live_mcp.fmdb import address_census as ac

ROOT = Path(__file__).resolve().parents[1]
BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD = BUILDS / '27.0.0.2493426' / 'game_plugin'
NEW = BUILDS / '27.0.1.2503222' / 'game_plugin'
NEW_SHA = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='the preserved 27.0.0 and 27.0.1 plugins are not on this machine')


# --------------------------------------------------------------------------- the census
def test_census_covers_every_in_range_literal_of_the_tactic_writer():
    """A literal address added to the writer without rebuilding its census would keep its pinned
    value on another build. Rebuild with: scripts/fm_update_build.py --adviser-census"""
    census = adv.census()
    scanned = ac.scan(ROOT, census['image_end'], adv.FILES)
    missing = sorted(f'{rel}: {value:#x} (line {line})' for rel, sites in scanned.items()
                     for value, line, *_ in sites if f'{value:#x}' not in census['files'].get(rel, {}))
    assert not missing, f'{len(missing)} in-range literals not in the adviser census, e.g. {missing[:5]}'


def test_census_was_taken_from_these_files():
    """The rewrite refuses a file whose text differs from the census's (adviser_book._source_matches)."""
    census = adv.census()
    assert sorted(census['sources']) == sorted(adv.FILES)
    stale = [rel for rel in adv.FILES
             if hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() != census['sources'][rel]]
    assert not stale, f'rebuild the adviser census (scripts/fm_update_build.py --adviser-census): {stale}'
    assert census['pinned_sha256'] == ab.PINNED_SHA256


def test_census_decisions_on_known_sites():
    files = adv.census()['files']
    tactic = files['adviser/pi/fm-tactic-files.py']
    for word in ('0x410000', '0x200010', '0x201000', '0x402000', '0x400080', '0x800200', '0x2050000',
                 '0x102000', '0x202000'):
        assert tactic[word]['d'] == 'C', word                 # role words and position masks
    core = files['adviser/pi/fm_tactic_native_core.py']
    assert core['0x4856b6c']['d'] == 'A'                      # the body reader
    assert core['0x4856000']['rule'] == 'override:page'       # a page it premaps
    assert core['0x486b000'].get('of') == '0x486b0c0'         # the page of one named address
    assert core['0x4af0000']['rule'] == 'override:range'      # the bound of on-demand code pages
    assert all(row['d'] == 'A' for row in files['adviser/pi/fm_tactic_role_catalog.py'].values())


def test_split_catalog_guard_covers_the_same_bytes():
    """The 4,832-byte guard over 0x4975150 is now one guard per function: on the pinned build they
    tile exactly the old span (so the pinned check is unchanged), and on a later build each function
    is re-derived where the patch put it."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('catalog_for_split_test', ROOT / 'adviser/pi/fm_tactic_role_catalog.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    parts = [g for g in module.NATIVE_GUARDS if 0x4975150 <= g[0] < 0x4976430]
    assert parts[0][0] == 0x4975150 and sum(n for _a, n, _s in parts) == 4832
    assert all(a + n == b for (a, n, _s), (b, _m, _t) in zip(parts, parts[1:]))
    if OLD.is_file():
        raw = OLD.read_bytes()
        whole = raw[0x5ED4000 + 0x4975150:0x5ED4000 + 0x4975150 + 4832]
        assert hashlib.sha256(whole).hexdigest() == 'ca7d8e49ca1535d1250cf7fe2ee242b8ddab4f668167c43646c9c30f86aba336'
        assert all(hashlib.sha256(raw[0x5ED4000 + a:0x5ED4000 + a + n]).hexdigest() == s for a, n, s in parts)


# --------------------------------------------------------------------------- the rewrite
def _section(**over):
    sec = {'values': {'0x4856b6c': {'value': 0x4906798, 'method': 'match:call graph'},
                      '0x4a8e878': {'value': None, 'method': 'unresolved', 'detail': 'function changed'}},
           'per_file': {'demo.py': {'0x4856000': {'value': 0x4906000, 'method': 'page'}}},
           'guards': {'files': {'demo.py': {'a' * 64: 'b' * 64}}, 'lengths': {'demo.py': {'a' * 64: 296}}},
           'identity': {'plugin': {'pinned_sha256': ab.PINNED_SHA256, 'sha256': NEW_SHA},
                        'slice_offset': {'pinned': 0x5ED4000, 'value': 0x5F4C000},
                        'english': {'pinned_sha256': 'e' * 64, 'sha256': 'f' * 64, 'verified': False},
                        'metadata': {'pinned_sha256': 'c' * 64, 'sha256': 'd' * 64, 'verified': True}},
           'disabled': {'demo.py': {'refuses': 'the native code guarded at 0x4a8e878 differs on this build'}}}
    sec.update(over)
    return sec


def _rows(*keys):
    return {k: {'d': 'A', 'rule': 'test', 'kind': 'code', 'sites': []} for k in keys}


SOURCE = f'''
BODY = 0x4856b6c
PAGE = 0x4856000
GONE = 0x4a8e878
WORD = 0x410000
SPAN = (0x4856b6c, 288, "{'a' * 64}")
SLICE = 0x5ED4000
PLUGIN = "{ab.PINNED_SHA256}"
ENGLISH = "{'e' * 64}"
METADATA = "{'c' * 64}"
def use_gone():
    return SLICE + GONE
def refuses():
    return 1
'''


def _run(monkeypatch, sec):
    census = {'image_end': 0x58F4000, 'files': {'demo.py': {**_rows('0x4856b6c', '0x4856000', '0x4a8e878'),
                                                            '0x410000': {'d': 'C', 'rule': 'override:listed',
                                                                         'kind': 'code', 'sites': []}}}}
    monkeypatch.setattr(adv, '_CENSUS', census)
    monkeypatch.setattr(adv, '_STATE', {'state': 'mapped', 'version': '27.0.1.2503222',
                                        'plugin_sha256': NEW_SHA, 'reason': None})
    monkeypatch.setitem(ab.ACTIVE, 'sha256', NEW_SHA)
    monkeypatch.setitem(ab.ACTIVE, 'version', '27.0.1.2503222')
    tree = ast.parse(SOURCE)
    counts = adv.rewrite(tree, 'demo.py', sec)
    ns = {}
    adv._prepare(ns)
    exec(compile(tree, 'demo.py', 'exec'), ns)
    return ns, counts


def test_rewrite_of_a_tactic_writer_file(monkeypatch):
    ns, counts = _run(monkeypatch, _section())
    assert ns['BODY'] == 0x4906798 and ns['PAGE'] == 0x4906000          # value, and a per-file page
    assert ns['WORD'] == 0x410000                                        # a role word stays as written
    assert ns['SPAN'] == (0x4906798, 296, 'b' * 64)                      # guard hash and reviewed length
    assert ns['SLICE'] == 0x5F4C000 and ns['PLUGIN'] == NEW_SHA          # build facts
    assert ns['METADATA'] == 'd' * 64                                    # verified: re-bound
    assert ns['ENGLISH'] == 'e' * 64                                     # not verified: stays pinned, refuses
    assert isinstance(ns['GONE'], ab.Unresolved)
    with pytest.raises(ab.UnresolvedAddress, match='0x4a8e878'):
        ns['use_gone']()
    with pytest.raises(ab.UnresolvedAddress, match='refuses is unavailable on game build 27.0.1.2503222'):
        ns['refuses']()
    assert counts['addresses'] == 3 and counts['unresolved'] == 1 and counts['lengths'] == 1
    assert counts['disabled'] == 1


def test_pinned_build_runs_the_files_as_written(monkeypatch):
    monkeypatch.setattr(adv, '_STATE', {'state': 'pinned', 'version': ab.PINNED_VERSION,
                                        'plugin_sha256': ab.PINNED_SHA256, 'reason': None})
    assert adv.rerun_as_main(ROOT / 'adviser/pi/fm-tactic-files.py', {'__builtins__': __builtins__}) is False
    loader = adv.source_loader('x', ROOT / 'adviser/pi/fm_tactic_native_core.py')
    assert type(loader).__name__ == 'SourceFileLoader'
    adv.install(ROOT / 'adviser/pi')
    assert not any(isinstance(f, adv._Finder) for f in __import__('sys').meta_path)


def test_a_changed_file_is_not_rewritten(monkeypatch, tmp_path):
    monkeypatch.setattr(adv, '_STATE', {'state': 'mapped', 'version': '27.0.1.2503222',
                                        'plugin_sha256': NEW_SHA, 'reason': None})
    copy = tmp_path / 'fm_tactic_native_core.py'
    copy.write_text((ROOT / 'adviser/pi/fm_tactic_native_core.py').read_text() + '\n# edited\n')
    with pytest.raises(adv.AdviserBuildError, match='differs from the text the adviser census'):
        adv.compile_file(copy)


# --------------------------------------------------------------------------- the reviews of 27.0.1
def _reviews():
    doc = json.loads((ROOT / 'fm_live_mcp/fmdb/data/address_overrides.json').read_text())
    build = doc['builds'][NEW_SHA]
    return build.get('adviser_guards') or {}


def test_every_tactic_writer_review_has_evidence():
    reviews = _reviews()
    assert reviews, 'the 27.0.1 reviews of the tactic writer are missing'
    for rel, entries in reviews.items():
        assert rel in adv.FILES
        for key, review in entries.items():
            assert review['verdict'] and len(review['evidence']) > 80, (rel, key)
            assert f'{int(key.split("/")[0], 16):#x}' in adv.census()['files'][rel], (rel, key)


@needs_builds
def test_reviewed_spans_are_the_counterparts_on_27_0_1():
    """Each reviewed span starts at the function the whole-binary match pairs with the pinned one
    (or its aligned instruction), and the pinned bytes are the ones the source's sha256 names."""
    from fm_live_mcp.fmdb import platform_model
    old, new = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    for rel, entries in _reviews().items():
        tree = ast.parse((ROOT / rel).read_text())
        guards = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple) and len(node.elts) == 3 and all(isinstance(e, ast.Constant) for e in node.elts):
                a, n, s = (e.value for e in node.elts)
                if type(a) is int and type(n) is int and isinstance(s, str):
                    guards.setdefault(a, set()).add((n, s))
        for key, review in entries.items():
            a = int(key, 16)
            assert a in guards, (rel, key)
            for n, s in guards[a]:
                assert hashlib.sha256(old.image.file_bytes(a, n)).hexdigest() == s
            b, length = int(review['new'], 16), review.get('length')
            if length is not None:
                assert new.function_of(b) is not None and new.is_code(b)
                assert old.function_of(a)[0] != a or new.function_of(b)[0] == b
