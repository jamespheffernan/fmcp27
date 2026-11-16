"""Offline tests of the UI round 2 (docs/fmdb/UI_ROUND2.md): screen parameters, the second sweep's
helpers, the compiled-out scan, the ledger's use of nested fields and the round-2 screen specs."""
import struct
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'scripts'))

from fm_live_mcp.fmdb import ledger, ui_params, ui_registry  # noqa: E402
from fm_live_mcp.fmdb import ui_recipes_round2 as R  # noqa: E402
from fm_live_mcp.fmdb.ui_tools import UiToolError, normalize_params  # noqa: E402
import fmdb_ui_sweep as S  # noqa: E402

BINDINGS = {'player': 0x1000001, 'human': 0x1000002, 'scouted_player': 0x1000003, 'scout': 0x1000004,
            'team': 0x18000221, 'club': 0x3000010, 'league': 0x19000007, 'ucl': 0x1900027D,
            'today_si': 266164992, 'game_date': '2030-12-13', 'news_unid': 5}


def test_parameter_table_names_the_sweep_globals():
    t = ui_params.table()
    assert len(t) == 231
    assert ui_params.name_of(0x56D1248) == 'number'
    assert ui_params.name_of(0x56D1688) == 'human'
    assert ui_params.name_of(0x56D18E8) == 'rolemask'
    assert ui_params.rva_of('VisionObjectiveYear') == 0x56D1A28


def test_candidates_by_kind():
    assert ui_params.kind_of('person') == 'object'
    assert ui_params.candidates('person', BINDINGS)[:2] == [0x1000001, 0x1000002]
    assert ui_params.candidates('date', BINDINGS)[0] == 266164992
    assert ui_params.candidates('ishometeam', BINDINGS)[:2] == [1, 0]
    assert ui_params.candidates('number', BINDINGS)[0] == 10
    assert ui_params.candidates('monthindex', BINDINGS)[:2] == [11, 12]
    assert ui_params.candidates('year', BINDINGS)[0] == 2030


def test_assignments_vary_one_parameter_at_a_time():
    sets = ui_params.assignments([0x56D1688, 0x56D16C8], BINDINGS, limit=5)
    assert sets[0] == {0x56D1688: 0x1000002, 0x56D16C8: 0x1000001}
    assert all(set(s) == {0x56D1688, 0x56D16C8} for s in sets)
    assert len(sets) <= 5
    assert ui_params.assignments([0x1234], BINDINGS) == []          # unknown global: nothing to try


def test_normalize_params():
    assert normalize_params({'Number': 3, 'ishometeam': True}) == {'number': 3, 'ishometeam': 1}
    assert normalize_params(None) == {}
    with pytest.raises(UiToolError):
        normalize_params({'nosuch': 1})
    with pytest.raises(UiToolError):
        normalize_params({'number': 'x'})


def test_note_nested_records_registry_fields():
    reg = ui_registry.default()
    found = {}
    value = [{'1xM8': 12, 'XQO4': {}, 'zzzz': 1}, {'XQO4': {'AJuK': {'name': 'Technical Average'}}}]
    S.note_nested(found, value, 'aJJp', reg)
    assert found['1xM8'] == ['aJJp', 'value']
    assert found['XQO4'][1] == 'value'            # unset in the first record, data in the second
    assert found['AJuK'][1] == 'value'
    assert 'zzzz' not in found and 'qvJ6' not in found


def _fake_image(words, start):
    class Image:
        text_range = (start, start + 4 * len(words))

        def file_bytes(self, rva, length):
            data = struct.pack(f'<{len(words)}I', *words)
            return data[rva - start: rva - start + length]
    return Image()


def _b(pc, target):
    return 0x14000000 | (((target - pc) // 4) & 0x3FFFFFF)


def test_compiled_out_scan_finds_return_true_cases():
    start = S.RETURN_TRUE_STUB - 0x100
    key_stub, key_code = 'adJf', 'Pref'
    words = []

    def case(code, target_words):
        v = int.from_bytes(code.encode(), 'big')
        words.extend([0x52800008 | ((v & 0xFFFF) << 5), 0x72A00008 | ((v >> 16) << 5), 0x6B08001F])
        pc = start + 4 * len(words)
        words.append(0x54000000 | ((2 & 0x7FFFF) << 5))      # b.eq +8
        words.append(0xD503201F)                             # nop (fall through)
        target = start + 4 * len(words)
        for w in target_words(target):
            words.append(w)
    case(key_stub, lambda pc: [_b(pc, S.RETURN_TRUE_STUB)])
    case(key_code, lambda pc: [0x94000000, 0xD65F03C0])      # bl ...; ret
    while start + 4 * len(words) < S.RETURN_TRUE_STUB:
        words.append(0xD503201F)
    words += [0x52800020, 0xD65F03C0]                        # the stub: mov w0, #1; ret
    out = S.compiled_out_scan(_fake_image(words, start), [key_stub, key_code])
    assert list(out) == [key_stub]


def test_ledger_counts_nested_fields_and_compiled_out(monkeypatch):
    reg = ui_registry.default()
    person_keys = list(reg.classes['PERSON_UI_HANDLER'].keys(4))
    unset_code = person_keys[0]
    nested_code = '1xM8'
    sweep = [{'job': '28:PERSON_UI_HANDLER', 'class': 'PERSON_UI_HANDLER', 'counts': {'unset': 1},
              'keys': {unset_code: {'status': 'unset', 'label': reg.label(unset_code)}},
              'nested': {nested_code: ['aJJp', 'value']}}]
    monkeypatch.setattr(ledger, '_ui_round2_data', lambda: {'compiled_out': {unset_code: ['0x37f290']}})
    rows, _ = ledger.build_ui(reg, sweep)
    by = {r[1]: r for r in rows}
    assert by[nested_code][7] == 'reads' and 'field of the records' in by[nested_code][8]
    assert by[unset_code][7] == 'unavailable' and 'compiled out' in by[unset_code][8]


def test_unclaimed_keys_are_assigned_to_hosts():
    reg = ui_registry.default()
    hosts = S.unclaimed_keys_by_host(reg)
    fallback = set(hosts.pop('_fallback'))
    every = set().union(*map(set, hosts.values()))
    claimed = set()
    for hc in reg.classes.values():
        claimed.update(hc.keys(4))
    assert every == set(reg.labels) - claimed
    assert fallback <= set(hosts['PERSON_UI_HANDLER'])
    assert S.keep_extra_row('x', {'status': 'unset'}, {'x'}) is False
    assert S.keep_extra_row('x', {'status': 'value'}, {'x'}) is True


def test_round2_screen_specs_resolve_to_registry_keys():
    reg = ui_registry.default()
    assert set(R.SCREENS) == {'player_comparison', 'staff_comparison', 'tactics', 'squad_registration',
                              'training', 'contract_negotiation', 'transfer_negotiation', 'competition_rules'}
    for name, parts in R.SCREENS.items():
        for part, htype, kind, labels, params in parts:
            cls = reg.types[htype]['client'] if htype != R.DATABASE_RECORD else {
                'person': 'PERSON_UI_HANDLER', 'other': 'PERSON_UI_HANDLER', 'team': 'TEAM_UI_HANDLER',
                'competition': 'COMPETITION_UI_HANDLER'}[kind]
            keys = R.labels_to_codes(reg, cls, labels)
            assert keys, (name, part)
            for label in params:
                for pname in params[label]:
                    ui_params.rva_of(pname)
    keys = R.labels_to_codes(reg, 'TEAM_TRAINING_UI_HANDLER', ['TrainingBestRatings'])
    assert keys == {'TrainingBestRatings': 'eXrB'}
