"""Per-field route table (fmdb/fieldroutes.py) and the club_finance source: offline and live-gated tests."""
from __future__ import annotations

import array
from pathlib import Path
import sys

import pytest

from fm_live_mcp.fmdb import fieldroutes
from fm_live_mcp.fmdb.sources import club_finance

ROOT = Path(__file__).resolve().parents[1]


# --------------------------------------------------------------------------- data file
def test_route_table_covers_the_coverage_gaps():
    pairs = fieldroutes.pairs()
    by_outcome = {}
    for row in pairs.values():
        by_outcome[row.get('coverage')] = by_outcome.get(row.get('coverage'), 0) + 1
    # coverage run of 2026-11-11: 505 not claimed, 477 unset, 12 unavailable (+ snapshot-only rows)
    assert by_outcome['not_handled'] == 505
    assert by_outcome['unset'] == 477
    assert by_outcome['unavailable'] == 12
    assert {row['category'] for row in pairs.values()} <= set(fieldroutes.CATEGORIES)
    assert all(row['reason'] for row in pairs.values())


def test_starting_tables_are_empty_and_classified():
    doc = fieldroutes._document()
    assert doc['starting_tables'] and set(doc['starting_tables'].values()) == {0}
    row = fieldroutes.pairs()['club.CMWE']
    assert row['category'] == 'starting_table'
    assert '0x16e9cc8' in row['functions']          # STARTING_CLUB_DEBT getter


def test_known_routes():
    assert fieldroutes.alias('club', 'Ctbu') == 'Ctfc'
    assert fieldroutes.alias('club', 'Crmb') == 'Cwrb'
    assert fieldroutes.alias('club', 'CcfE') == 'Ccfa'
    assert fieldroutes.alias('club', 'Cnam') is None
    assert fieldroutes.emulate_anyway('club', 'CSbR')
    assert fieldroutes.emulate_anyway('c4tm', 'C4nm')           # sampling: 4th teams are rare
    assert not fieldroutes.emulate_anyway('club', 'RP00')
    assert fieldroutes.pairs()['club.RP00']['category'] == 'constructed_key'
    assert 'next route' in fieldroutes.reason('club', 'CMWE')


def test_categorise_rules():
    starting = {'STARTING_CLUB_DEBT': 0}
    cat = lambda row, rt='club', code='Xxxx': fieldroutes.categorise(rt, code, row, starting)[0]  # noqa: E731
    assert cat({'census': {'value': 3, 'nh': 10}}) == 'sampling'
    assert cat({'census': {'unavailable:thread-local RNG state': 9, 'nh': 1}}) == 'emulator'
    assert cat({'kinds': ['in_starting_getter', 'starting_getter'], 'census': {'nh': 5}}) == 'starting_table'
    assert cat({'kinds': ['in_own', 'in_getter'], 'census': {'unset': 5}}) == 'claimed_unset'
    assert cat({'kinds': ['in_getter'], 'census': {'nh': 5}}) == 'other_record'
    assert cat({'kinds': ['setter'], 'function_count': 1}) == 'setter_only'
    assert cat({'kinds': ['editor'], 'function_count': 1}) == 'editor_only'
    # round 2: the legacy responsibility rows are superseded by the TCrs list (club, natc)
    assert cat({'function_count': 0}, code='RJ07') == 'superseded'
    assert cat({'function_count': 0}, rt='team', code='RJ07') == 'constructed_key'
    assert cat({'function_count': 0}, code='Cedp') == 'constructed_key'
    assert cat({}, code='Ctbu') == 'live_route'


# --------------------------------------------------------------------------- static scan helpers
class _FakeImage:
    def __init__(self, words, lo=0x1000):
        self.text_range = (lo, lo + 4 * len(words))
        self._words = array.array('I', words)

    def file_bytes(self, rva, length):
        lo = self.text_range[0]
        return self._words.tobytes()[rva - lo: rva - lo + length]


def _movz(rd, imm, hw=0):
    return 0x52800000 | (hw << 21) | (imm << 5) | rd


def _movk(rd, imm, hw=1):
    return 0x72800000 | (hw << 21) | (imm << 5) | rd


def test_fourcc_sites_pairs_and_derived_constants():
    cnag = int.from_bytes(b'Cnag', 'big')
    words = [_movz(8, cnag & 0xFFFF), _movk(8, cnag >> 16),
             0x11000000 | (6 << 10) | (8 << 5) | 9,          # add w9, w8, #6 -> 'Cnam'
             0xD65F03C0]                                     # ret
    img = _FakeImage(words)
    sites = fieldroutes.fourcc_sites(img, starts=[0x1000])
    assert sites['Cnag'] == [0x1004]
    assert sites['Cnam'] == [0x1008]


def test_call_targets():
    lo = 0x1000
    words = array.array('I', [0x94000004, 0x17FFFFFF])     # bl +16 ; b -4
    assert fieldroutes.call_targets(words, lo, lo, lo + 8) == {lo + 16, lo}


def test_function_roles():
    roles = fieldroutes.function_roles({
        0x10: [('db::CLUB', 3)], 0x20: [('db::CLUB', 2)], 0x30: [('db::STARTING_CLUB_DEBT', 3)],
        0x40: [('GAME_CLUB', 22)], 0x50: [('EDITOR', 22)]})
    assert roles == {0x10: ['getter'], 0x20: ['setter'], 0x30: ['starting_getter'], 0x40: ['game'], 0x50: ['editor']}


def test_language_text():
    path = fieldroutes.DEFAULT_APP / fieldroutes.LTF_RELATIVE
    if not path.is_file():
        pytest.skip('FM27 language template not installed')
    assert fieldroutes.language_text(636403) == '4-2-4 DM Wide'
    assert fieldroutes.language_text(227312) == 'Worldwide'
    assert fieldroutes.language_text(1) is None or isinstance(fieldroutes.language_text(1), str)


# --------------------------------------------------------------------------- snapshot integration
def test_snapshot_columns_ask_the_live_keys():
    from fm_live_mcp.fmdb import catalog, snapshot
    try:
        cat = catalog.load_catalog()
    except (OSError, catalog.CatalogError):
        pytest.skip('editor.fmf not installed')
    cols = {c.name: c for c in snapshot.columns_for(cat, 'club')}
    assert cols['transfer_budget'].code == 'Ctfc' and cols['transfer_budget'].routed_from == 'Ctbu'
    assert cols['corporate_facilities'].code == 'Ccfa'
    assert cols['remaining_player_wage_budget'].code == 'Cwrb'
    assert 'Ctbu' in snapshot._route_note(cols['transfer_budget'])
    assert snapshot._route_emulates(cols['scouting_budget'])


# --------------------------------------------------------------------------- club_finance source
class _Result:
    def __init__(self, value, kind='int'):
        self.value, self.kind, self.handled, self.view = value, kind, True, 'game'


class _Engine:
    def __init__(self, values):
        self.values = values

    def get_property(self, record, key):
        v = self.values.get(key)
        return _Result(v, 'null' if v is None else 'int')

    def table_entries(self, kind):
        return [0, 0x1000], ()

    def __len__(self):
        return 2


def test_club_finance_rows_and_columns():
    names = [c.name for c in club_finance.columns()]
    assert len(names) == len(set(names)) and names[0] == 'idx'
    engine = _Engine({'Ccba': 26390569, 'Cwwb': 5465947, 'Cwrb': 490410, 'ClPa': 258727924, 'Ctfc': 92979220})
    (table,) = club_finance.tables(engine)
    rows = list(table.rows())
    assert len(rows) == 1 and len(rows[0]) == len(names)
    row = dict(zip(names, rows[0]))
    assert row['idx'] == 1
    assert row['wage_budget_annual'] == 284229244          # the managed club's finances screen
    assert row['remaining_wage_budget_annual'] == 25501320  # "about 25.5M per year remaining"
    assert row['transfer_budget_finance_Cntb'] is None
    assert table.cost_note.startswith('lazy')
    assert list(table.rows([5])) == [] and len(list(table.rows([1]))) == 1   # rows for given idx only


# --------------------------------------------------------------------------- live
def _live_available():
    try:
        from fm_live_mcp.bridge import discover_processes
        return bool(discover_processes()) and (ROOT / 'build' / 'fm_live_helper').exists()
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _live_available(), reason='FM27 not running or helper missing')
def test_live_club_finance_matches_hand_built():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_club_finance_check
    assert fmdb_club_finance_check.main(['--clubs', '12']) == 0
