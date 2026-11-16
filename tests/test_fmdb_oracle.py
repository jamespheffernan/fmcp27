"""Offline tests for the differential oracle: mapping structure, comparison rules and report text."""
import struct
import sys
from pathlib import Path

import pytest

from fm_live_mcp.fmdb.extras import DERIVED

from fm_live_mcp.fmdb import oracle_map as om
from fm_live_mcp.fmdb.variant import RecordRef, SiDate

ROOT = Path(__file__).resolve().parent.parent


class FakeContext(om.Context):
    def __init__(self, names=None, labels=None):
        self.names, self.labels = names or {}, labels or {}

    def resolve_name(self, ref, kind):
        return self.names[(ref.table, ref.unique_id)]

    def resolve_uid(self, ref):
        return ref.unique_id

    def resolve_index_name(self, kind, index):
        return self.names[(kind, index)]

    def enum_label(self, rtype, code, value):
        return self.labels.get((rtype, code, value))


def entry(rule, codes=('XXXX',), **params):
    return om.Entry('f.g', 'x', 'player', 'a.b', 'play', tuple(codes), rule, tuple(params.items()))


def check(rule, tool, gen, ctx=None, codes=None, **params):
    codes = codes or tuple(gen)
    return om.compare(entry(rule, codes, **params), tool, gen, ctx or FakeContext())[0]


# -- structure ----------------------------------------------------------------------------

def test_every_entry_is_well_formed():
    keys = set()
    for e in om.ENTRIES:
        assert e.key not in keys, e.key
        keys.add(e.key)
        assert e.call in om.CALLS, e.key
        assert e.rule in om.RULES, e.key
        assert e.sample_family in om.SAMPLES, e.key
        assert e.codes and all((len(c) == 4 and c.isascii()) or c[2:] in DERIVED.get(e.rtype, {})
                               for c in e.codes), e.key
        assert e.path and not e.path.startswith('.'), e.key
        assert e.family in om.FAMILY_TITLES, e.family
        assert e.rtype in {'pers', 'play', 'nnpl', 'club', 'comp', 'stad', 'city', 'curr', 'nati', 'cont'}, e.key
        if e.rule == 'enum_label':
            assert e.param('rtype') and e.param('code') in e.codes, e.key
        if e.rule == 'ref_name':
            assert e.param('kind') in om.REF_KINDS, e.key
        if e.via:
            assert e.sample, 'a via entry names its sampled family explicitly'


def test_each_call_is_used_and_declared_completely():
    used = {e.call for e in om.ENTRIES}
    assert used == set(om.CALLS)
    for call in om.CALLS.values():
        assert call.ref_kwarg and call.ref_table
        assert call.method.isidentifier() or ':' in call.method


def test_family_coverage_floor():
    families = {e.family for e in om.ENTRIES}
    for needed in ('player.identity', 'player.attributes', 'player.goalkeeping', 'player.hidden', 'player.ability',
                   'player.feet', 'player.positions', 'player.personality', 'player.health', 'player.contract',
                   'player.value', 'staff.attributes', 'staff.job', 'club.identity', 'club.finance',
                   'club.facilities', 'competition.identity', 'stadium.capacity', 'city.identity',
                   'currency.identity', 'nation.identity'):
        assert needed in families, needed
    per = {}
    for e in om.ENTRIES:
        per.setdefault(e.family.split('.')[0], 0)
        per[e.family.split('.')[0]] += 1
    assert per['player'] >= 100 and per['staff'] >= 60


def test_player_attribute_tables_are_complete():
    shown = [e for e in om.ENTRIES if e.family == 'player.attributes']
    raw = [e for e in om.ENTRIES if e.family == 'player.attributes_raw']
    assert len(shown) == len(raw) == 36
    assert len({e.codes for e in shown}) == 36 and len({e.codes for e in raw}) == 36
    assert len([e for e in om.ENTRIES if e.family == 'player.goalkeeping']) == 11
    assert len([e for e in om.ENTRIES if e.family == 'player.hidden']) == 5


def test_codes_match_existing_tool_modules():
    from fm_live_mcp import club_facilities, personality, player_profile, staff_attributes
    by_field = {(e.family, e.field): e.codes[0] for e in om.ENTRIES}
    for name, (_, code, _) in player_profile.GOALKEEPING.items():
        assert by_field[('player.goalkeeping_raw', name)] == code
    for name, (_, code, _) in player_profile.HIDDEN.items():
        assert by_field[('player.hidden_raw', name)] == code
    for name, (_, code, _) in player_profile.FEET.items():
        assert by_field[('player.feet_raw', name)] == code
    for name, fields in player_profile.POSITIONS.items():
        assert by_field[('player.positions', name)] == fields[3]
    for name, fields in personality.FIELDS.items():
        assert by_field[('player.personality', name)] == fields[3]
        assert by_field[('staff.personality', name)] == fields[3]
    for name, (_, _, code) in staff_attributes.ATTRIBUTES.items():
        assert by_field[('staff.attributes', name)] == code
    for name, (_, _, code) in staff_attributes.TENDENCIES.items():
        assert by_field[('staff.tendencies', name)] == code
    for name, (_, _, code) in staff_attributes.BOARD.items():
        assert by_field[('staff.board', name)] == code
    for name, fields in club_facilities.FIELDS.items():
        assert by_field[('club.facilities', name)] == fields[1]


def test_codes_exist_in_the_editor_catalog():
    from fm_live_mcp.fmdb import catalog
    if not catalog.DEFAULT_EDITOR_FMF.exists():
        pytest.skip('editor.fmf not installed')
    cat = catalog.load_catalog()
    missing = [(e.key, c) for e in om.ENTRIES for c in e.codes
               if not c.startswith('x:') and cat.field(e.rtype, c) is None
               and (e.rtype, c) not in om.OUTSIDE_CATALOG]
    assert not missing, missing


def test_enum_label_entries_have_labels_in_the_catalog():
    from fm_live_mcp.fmdb import catalog
    if not catalog.DEFAULT_EDITOR_FMF.exists():
        pytest.skip('editor.fmf not installed')
    cat = catalog.load_catalog()
    for e in om.ENTRIES:
        if e.rule == 'enum_label':
            f = cat.field(e.param('rtype'), e.param('code'))
            labels = f.enum or cat.enums.get(f.enum_ref or '', {})
            assert labels, e.key


def test_unmapped_and_gaps_are_well_formed():
    for u in om.UNMAPPED:
        assert u.family and u.field and u.tried and u.reason
    for g in om.TOOL_GAPS:
        assert len(g.code) == 4 and g.name and g.reason
    for key, (klass, reading) in om.FINDINGS.items():
        assert klass in om.CLASSES, key
        assert reading, key


# -- get_path -----------------------------------------------------------------------------

def test_get_path():
    doc = {'a': {'b': [{'c': 1}, {'c': 2}]}, 'n': None}
    assert om.get_path(doc, 'a.b[1].c') == 2
    assert om.get_path(doc, 'a.b[-1].c') == 2
    assert om.get_path(doc, 'n') is None
    assert om.get_path(doc, 'a.x') is om.MISSING
    assert om.get_path(doc, 'a.b[2].c') is om.MISSING
    assert om.get_path(doc, 'n.z') is om.MISSING
    assert om.get_path(doc, '') is doc


# -- rules --------------------------------------------------------------------------------

def test_exact_distinguishes_bool_and_int():
    assert check('exact', 5, {'A': 5})
    assert not check('exact', 5, {'A': 6})
    assert not check('exact', 1, {'A': True})
    assert check('bool', True, {'A': True})
    assert not check('bool', False, {'A': True})


def test_fifths_rule_matches_native_conversion():
    for raw in range(0, 101):
        assert check('fifths_raw', max(1, (raw + 2) // 5), {'PDxx': raw})
    assert not check('fifths_raw', 16, {'PDcr': 90})
    assert not check('fifths_raw', 1, {'PDcr': 101})  # outside the verified stored range
    assert check('direct_raw', 7, {'NDat': 7})


def test_blob_rule_reads_byte_one():
    assert check('blob_byte', 16, {'Pcro': b'\x01\x10\x10\x10'}, index=1)
    assert not check('blob_byte', 15, {'Pcro': b'\x01\x10\x10\x10'}, index=1)
    assert not check('blob_byte', 16, {'Pcro': None}, index=1)
    assert not check('blob_byte', 16, {'Pcro': b'\x01'}, index=1)


def test_date_rule():
    assert check('date_iso', '2033-06-30', {'Pcex': SiDate('2033-06-30')})
    assert not check('date_iso', '2033-06-29', {'Pcex': SiDate('2033-06-30')})


def test_float32_rule():
    widened = struct.unpack('<f', struct.pack('<f', 50.730735778808594))[0]
    assert check('float32', widened, {'Slat': widened})
    assert not check('float32', 50.7307, {'Slat': widened})
    assert check('float32', 50.7307, {'Slat': 50.73071}, rel=1e-5)


def test_string_and_empty_rules():
    assert check('string', 'Newcastle United', {'Cnam': 'Newcastle United'})
    assert not check('string', 'United States Dollar', {'Cnam': 'U.S. Dollar'})
    assert check('string', '', {'Cnam': None})
    assert check('empty_as_null', None, {'Scnm': ''})
    assert not check('empty_as_null', 'X', {'Scnm': ''})


def test_name_rules():
    gen = {'Pfna': 'Anthony', 'Psna': 'Gordon', 'Pcna': ''}
    assert check('full_name', 'Anthony Gordon', gen)
    assert check('display_name', 'Anthony Gordon', gen)
    gen = {'Pfna': 'Luiz', 'Psna': 'Henrique', 'Pcna': 'Luiz Henrique'}
    assert check('display_name', 'Luiz Henrique', gen)
    assert check('full_name', 'Luiz Henrique', gen)
    # a regular player with a null surname and a populated common name
    gen = {'Pfna': '', 'Psna': '', 'Pcna': 'Beraldo'}
    assert check('full_name', 'Beraldo', gen)
    assert not check('full_name', 'Beraldo Lima', gen)


def test_enum_label_rule_folds_case_and_punctuation():
    ctx = FakeContext(labels={('pers', 'Pcst', 1): 'Full Time', ('pers', 'Pcst', 4): 'Non-Contract'})
    assert check('enum_label', 'Full Time', {'Pcst': 1}, ctx, rtype='pers', code='Pcst')
    assert check('enum_label', 'Non Contract', {'Pcst': 4}, ctx, rtype='pers', code='Pcst')
    assert not check('enum_label', 'Part Time', {'Pcst': 1}, ctx, rtype='pers', code='Pcst')
    ok, detail = om.compare(entry('enum_label', ('Pcst',), rtype='pers', code='Pcst'), 'X', {'Pcst': 9}, ctx)
    assert not ok and 'no editor label' in detail


def test_reference_rules():
    ref = RecordRef('Ttea', 688, 688)
    ctx = FakeContext(names={('Ttea', 688): 'Newcastle United'})
    assert check('ref_name', 'Newcastle United', {'Pcti': ref}, ctx, kind='club')
    assert not check('ref_name', 'Newcastle Jets FC', {'Pcti': ref}, ctx, kind='club')
    assert not check('ref_name', 'x', {'Pcti': None}, ctx, kind='club')
    assert check('ref_name', 'Newcastle United', {'Ptaj': {'Ttea': ref}}, ctx, kind='club', key='Ttea')
    assert check('ref_name', 'newcastle united', {'Pcti': ref}, ctx, kind='club', fold=True)
    assert check('ref_uid', 688, {'Pcti': ref}, ctx)
    assert not check('ref_uid', 689, {'Pcti': ref}, ctx)


def test_list_and_presence_rules():
    assert check('list_len', 1, {'Pijl': [{'a': 1}]})
    assert not check('list_len', 1, {'Pijl': []})
    assert check('presence', 1, {'injr': {'injr': 31}})
    assert check('presence', 0, {'injr': None})
    assert not check('presence', 1, {'injr': None})
    assert not check('presence', 0, {'injr': {'injr': 31}})


def test_unset_and_date_unset_rules():
    assert check('unset', 0, {'Sucy': None}, unset=(0, -1))
    assert check('unset', -1, {'dbty': None}, unset=(-1,))
    assert check('unset', 5, {'Scas': 5})
    assert not check('unset', 5, {'Scas': None})
    assert not check('unset', 1, {'Soty': None}, unset=(0,))
    assert check('date_unset', None, {'Sprl': SiDate('1900-01-01')})
    assert check('date_unset', '1904-01-01', {'Sbld': SiDate('1904-01-01')})
    assert not check('date_unset', None, {'Sbld': SiDate('1904-01-01')})


def test_key_extraction_and_index_name():
    gen = {'injr': {'injr': 31, 'iida': SiDate('2030-11-02', 64)}}
    assert check('date_iso', '2030-11-02', gen, key='iida')
    ctx = FakeContext(names={('injury', 31): 'Partially Torn Hamstring'})
    assert check('index_name', 'partially torn hamstring', gen, ctx, key='injr', kind='injury')
    assert not check('index_name', 'hip injury', gen, ctx, key='injr', kind='injury')
    assert not check('index_name', 'x', {'injr': None}, ctx, key='injr', kind='injury')


def test_int_tolerance():
    assert check('int_tol', 10, {'A': 11}, tol=1)
    assert not check('int_tol', 10, {'A': 13}, tol=1)


# -- driver pieces (no game needed) -----------------------------------------------------------

@pytest.fixture(scope='module')
def oracle():
    sys.path.insert(0, str(ROOT / 'scripts'))
    import fmdb_oracle
    return fmdb_oracle


class FakeLive:
    """Just enough of Live for `evaluate`: scripted property results per (address, code)."""

    def __init__(self, values):
        self.values = values

    def prop(self, address, code):
        from fm_live_mcp.fmdb.vm import PropertyResult, CallStats, Unavailable
        value = self.values.get((address, code), 'MISSING')
        if value == 'UNAVAILABLE':
            return PropertyResult(code, Unavailable('external call _fseeko'), None, None, CallStats())
        if value == 'UNHANDLED':
            return PropertyResult(code, None, 'null', False, CallStats())
        if value is None:
            return PropertyResult(code, None, 'null', True, CallStats())
        return PropertyResult(code, value, 'int', True, CallStats())


def test_evaluate_statuses(oracle):
    e = om.Entry('player.health', 'condition', 'player', 'health.condition', 'play', ('Pcon',), 'exact')
    live = FakeLive({(1, 'Pcon'): 6894})
    docs = {'player': {'health': {'condition': 6894}}}
    ctx = FakeContext()
    assert oracle.evaluate(live, ctx, e, 1, docs)[0] == 'match'
    assert oracle.evaluate(live, ctx, e, 1, {'player': {'health': {'condition': 5000}}})[0] == 'mismatch'
    assert oracle.evaluate(live, ctx, e, 1, {'player': {'health': {}}})[0] == 'tool_unavailable'
    assert oracle.evaluate(live, ctx, e, 1, {'player': {'health': {'condition': None}}})[0] == 'tool_unavailable'
    assert oracle.evaluate(live, ctx, e, 1, {'player': RuntimeError('x')})[0] == 'tool_unavailable'
    assert oracle.evaluate(FakeLive({(1, 'Pcon'): 'UNAVAILABLE'}), ctx, e, 1, docs)[0] == 'generic_unavailable'
    assert oracle.evaluate(FakeLive({(1, 'Pcon'): 'UNHANDLED'}), ctx, e, 1, docs)[0] == 'generic_unavailable'
    # tool value absent and the getter does not claim the key: both readers report the value as absent
    assert oracle.evaluate(FakeLive({(1, 'Pcon'): 'UNHANDLED'}), ctx, e, 1, {'player': {'health': {}}})[0] == 'match'
    # generic null (claimed) against a tool value is a mismatch; both absent is a match
    assert oracle.evaluate(FakeLive({(1, 'Pcon'): None}), ctx, e, 1, docs)[0] == 'mismatch'
    assert oracle.evaluate(FakeLive({(1, 'Pcon'): None}), ctx, e, 1, {'player': {'health': {}}})[0] == 'match'


def test_evaluate_negative_native_code(oracle):
    e = om.Entry('player.value', 'asking_price', 'player', 'transfer_prices.asking_price_property.amount', 'play',
                 ('Papr',), 'exact', (('none_if_negative', True),))
    docs = {'player': {'transfer_prices': {'asking_price_property': {'amount': None}}}}
    assert oracle.evaluate(FakeLive({(1, 'Papr'): -1}), FakeContext(), e, 1, docs)[0] == 'match'
    assert oracle.evaluate(FakeLive({(1, 'Papr'): 500}), FakeContext(), e, 1, docs)[0] == 'tool_unavailable'


def test_evaluate_via_reference(oracle):
    e = om.Entry('nation.identity', 'short_name', 'competition', 'context.nation.short_name', 'nati', ('Nsnm',),
                 'string', sample='competition', via='cnti')

    class Live(FakeLive):
        def uid_index(self, table):
            return {765: (139, 0x999)}

        def prop(self, address, code):
            if (address, code) == (7, 'cnti'):
                from fm_live_mcp.fmdb.vm import PropertyResult, CallStats
                return PropertyResult(code, RecordRef('Nnat', 765, 765), 'record_ref', True, CallStats())
            return super().prop(address, code)

    live = Live({(0x999, 'Nsnm'): 'England'})
    docs = {'competition': {'context': {'nation': {'short_name': 'England'}}}}
    assert oracle.evaluate(live, FakeContext(), e, 7, docs)[0] == 'match'
    assert oracle.evaluate(live, FakeContext(), e, 7, {'competition': {'context': {'nation': {'short_name': 'Eng'}}}})[0] == 'mismatch'


def test_tally_and_report(oracle):
    e = om.Entry('player.health', 'fatigue', 'player', 'health.fatigue', 'play', ('Pjad',), 'exact')
    tally = oracle.Tally()
    for i in range(7):
        tally.add(e, 'mismatch', f'player[{i}]', 5, 6, None)
    tally.add(e, 'match', 'player[9]', 6, 6, None)
    row = tally.fields[e.key]
    assert row['mismatch'] == 7 and len(row['examples']) == oracle.MAX_EXAMPLES
    meta = {'seed': 1, 'game_date_start': '2030-12-10', 'game_date_end': '2030-12-10', 'sizes': {'player': 8},
            'elapsed_seconds': 1.0, 'vm_calls': 8}
    report = oracle.build_report(tally, meta)
    assert report['families']['player.health']['mismatch'] == 7
    text = oracle.render_markdown(report)
    assert 'player.health.fatigue' in text and 'Not yet analysed' in text
    assert '| field | mismatches / compared | examples (record: tool value, generic value) |' in text
    assert '`player.health.fatigue` | 7 / 8 |' in text


def test_findings_apply_to_reports_and_wildcards(oracle):
    row = {'family': 'currency.identity', 'field': 'name'}
    report = {'fields': {'currency.identity.name': dict(row), 'staff.attributes.goalkeeping': {'family': 'staff.attributes'},
                         'player.health.fatigue': {'family': 'player.health'}}}
    oracle.refresh_findings(report)
    assert report['fields']['currency.identity.name']['finding']['class'] == om.DIFFERENT
    assert report['fields']['staff.attributes.goalkeeping']['finding']['class'] == om.DIFFERENT
    assert report['fields']['player.health.fatigue']['finding'] is None


def test_live_pins_are_consistent_with_the_map_and_findings():
    import importlib.util
    spec = importlib.util.spec_from_file_location('oracle_live_pins', ROOT / 'tests/test_fmdb_oracle_live.py')
    live = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live)
    keys = {e.key for e in om.ENTRIES}
    families = {e.family for e in om.ENTRIES}
    assert live.PINNED_FAMILIES and live.PINNED_FIELDS
    assert set(live.PINNED_FAMILIES) <= families
    assert set(live.PINNED_FIELDS) <= keys
    assert not set(live.PINNED_FIELDS) & set(live.PINNED_FAMILIES)
    for key in live.PINNED_FIELDS:
        assert key not in om.FINDINGS and key.rsplit('.', 1)[0] + '.*' not in om.FINDINGS, key
    for family in live.PINNED_FAMILIES:
        assert family + '.*' not in om.FINDINGS
        assert not any(k.startswith(family + '.') for k in om.FINDINGS), family
    # every classified field is unpinned
    classified = {e.key for e in om.ENTRIES if e.key in om.FINDINGS or e.family + '.*' in om.FINDINGS}
    pinned = set(live.PINNED_FIELDS) | {e.key for e in om.ENTRIES if e.family in live.PINNED_FAMILIES}
    assert not classified & pinned


def test_report_markdown_groups_mismatches_by_reading(oracle):
    e1 = om.Entry('player.personality', 'ambition', 'player', 'profile.personality.ambition', 'pers', ('Pamb',), 'exact')
    e2 = om.Entry('player.personality', 'loyalty', 'player', 'profile.personality.loyalty', 'pers', ('Ploy',), 'exact')
    tally = oracle.Tally()
    tally.add(e1, 'mismatch', 'player[1]', 16, None, None)
    tally.add(e2, 'mismatch', 'player[1]', 12, None, None)
    tally.add(e2, 'generic_unavailable', 'player[2]', None, None, 'Ttea 2000778919 not found in clubs')
    tally.add(e2, 'generic_unavailable', 'player[3]', None, None, 'Ttea 2000778648 not found in clubs')
    meta = {'seed': 1, 'game_date_start': '2030-12-10', 'game_date_end': '2030-12-10', 'sizes': {'player': 1},
            'elapsed_seconds': 1.0, 'vm_calls': 2}
    text = oracle.render_markdown(oracle.build_report(tally, meta))
    assert text.count('### M1.') == 1 and '### M2.' not in text      # one shared reading, two fields
    assert 'Ttea N not found in clubs (2)' in text
