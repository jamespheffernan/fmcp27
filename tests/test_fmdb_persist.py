"""Offline tests of the save-code reader (docs/fmdb/PERSIST.md): decoding, keys, routes, tables."""
import json
import struct

from fm_live_mcp.fmdb import persist, persist_stream
from fm_live_mcp.fmdb.sources import native_state


class _Image:
    def __init__(self, words):
        self.words = words

    def file_bytes(self, rva, n):
        return struct.pack('<I', self.words[rva])


def test_load_forms():
    words = {
        0: 0xF9400A60,      # ldr x0, [x19, #0x10]
        4: 0xB85FC261,      # ldur w1, [x19, #-4]
        8: 0xF8408E62,      # ldr x2, [x19, #8]!
        12: 0xF8408662,     # ldr x2, [x19], #8
        16: 0xF8737A83,     # ldr x3, [x20, x19, lsl #3]
        20: 0xA9410A61,     # ldp x1, x2, [x19, #0x10]
        24: 0x39402263,     # ldrb w3, [x19, #8]
        28: 0xD503201F,     # nop: not a load
    }
    im = _Image(words)
    assert persist_stream._load_form(im, 0) == ('imm', 19, 0, 0x10, 0)
    assert persist_stream._load_form(im, 4) == ('imm', 19, 0, -4, 0)
    assert persist_stream._load_form(im, 8) == ('imm', 19, 0, 8, 0)
    assert persist_stream._load_form(im, 12) == ('post', 19, 0, 8, 0)
    assert persist_stream._load_form(im, 16) == ('reg', 20, 19, 0, 3)
    assert persist_stream._load_form(im, 20) == ('imm', 19, 0, 0x10, 0)
    assert persist_stream._load_form(im, 24) == ('imm', 19, 0, 8, 0)
    assert persist_stream._load_form(im, 28) == ()


def test_key_text_round_trip():
    for key in (('w', 0x11043AC, (), 4), ('w', 0x4AC4798, (0x4383554, 0x43F239C), 8), ('c', 0x1104334, 0x26BBD88)):
        assert persist.key_of(persist.key_text(key)) == key
    assert persist.key_of({'key': None}) is None


def test_demangle():
    assert persist.demangle('11GAME_PLAYER') == 'GAME_PLAYER'
    assert persist.demangle('N2db6PERSONE') == 'db::PERSON'
    assert persist.demangle('N6sicore10PERSISTENTE') == 'sicore::PERSISTENT'
    assert persist.demangle(None) is None
    weird = 'N2db15DATABASE_TABLEINS_6PERSONEEE'
    assert persist.demangle(weird) == weird or '::' in persist.demangle(weird)


def test_routes_file():
    doc = json.loads(persist.ROUTES_FILE.read_text())
    assert doc['walker'] == '0x256d728'
    keys = [r['key'] for r in doc['routes']]
    assert len(keys) == len(set(keys)) >= 40
    for r in doc['routes']:
        assert r['function'].startswith('0x') and r['site'].startswith('0x') and r['root_rva'].startswith('0x')
    assert persist.find_route('AGENT_MANAGER')['function'] == '0x259e31c'
    assert persist.find_route('TRANSFER_MANAGER+0x18')['path'] == '+0x18'


def test_verify_route_rejects_other_call():
    class Engine:
        class image:
            @staticmethod
            def file_bytes(rva, n):
                return struct.pack('<I', 0x94000000 | 4)     # bl +16
    route = {'site': '0x1000', 'function': '0x1010'}
    persist._verify_route(Engine, route)
    try:
        persist._verify_route(Engine, {'site': '0x1000', 'function': '0x2000'})
    except persist.PersistError:
        pass
    else:
        raise AssertionError('a call to another function must be refused')


def test_native_state_plan_from_schema(monkeypatch):
    schema = {'roots': [{'root': 'X_MANAGER', 'functions': [
        {'function': '0x10', 'class': 'INJURY_RECORD', 'instances': 25, 'fields': [
            {'n': 0, 'key': 'w:0x14::4', 'kind': 'value', 'per_instance': [1, 1], 'type': 'u32', 'site': '0x14',
             'offset': '0x8', 'offset_source': 'load', 'name': 'field_0', 'label_source': None},
            {'n': 1, 'key': 'w:0x18::1', 'kind': 'value', 'per_instance': [0, 3], 'type': 'u8', 'site': '0x18',
             'offset': None, 'offset_source': None, 'name': 'field_1', 'label_source': None},
            {'n': 2, 'key': 'w:0x1c::2', 'kind': 'value', 'per_instance': [1, 1], 'type': 'u16', 'site': '0x1c',
             'offset': '0xc', 'offset_source': 'buffer', 'name': 'duni', 'label_source': 'getter:INJURY.duni'}]},
        {'function': '0x20', 'class': 'RARE', 'instances': 2, 'fields': []}]}]}
    monkeypatch.setattr(persist, '_SCHEMA', schema)
    plan = native_state.plan()
    assert [p['table'] for p in plan] == ['native_injury_record']
    assert [f['n'] for f in plan[0]['fields']] == [0, 2]
    tables = native_state.tables(engine=None)
    cols = [c.name for c in tables[0].columns]
    assert cols[:8] == ['idx', 'object', 'parent_object', 'parent_class', 'position', 'class', 'ref_table', 'ref_idx']
    assert cols[8] == 'f0_u32' and 'offset 0x8 (load)' in tables[0].columns[8].meaning
    assert cols[9] == 'duni' and 'getter:INJURY.duni' in tables[0].columns[9].meaning
    assert tables[0].manager == {'scope': 'never'}


def test_offset_text():
    assert persist._fmt_offset(None) is None
    assert persist._fmt_offset((0, 0x10)) == '0x10'
    assert persist._fmt_offset((1, 0x18)) == 'caller1+0x18'
    assert persist._fmt_offset((0, 'vec', 0x38)) == '+0x38[]'
    assert persist._fmt_offset((2, 'ptr', 0x40, 8)) == 'caller2[+0x40]+0x8'


def test_ledger_apply_persist():
    from fm_live_mcp.fmdb import ledger
    schema = {'roots': [
        {'root': 'AGENT_MANAGER', 'status': 'ok', 'writes': 88, 'bytes': 352, 'fast_seconds': 0.01,
         'functions': [{'function': '0x259e31c', 'class': 'AGENT_MANAGER', 'instances': 1, 'fields': []},
                       {'function': '0x1865704', 'class': 'db::AGENT', 'instances': 3,
                        'fields': [{'kind': 'value'}]}]},
        {'root': 'NEWS_MANAGER', 'status': 'refused', 'refusal': 'VM heap exhausted', 'fast_seconds': 50,
         'functions': [{'function': '0x28f274c', 'class': 'ACCEPT_REJECT_TRADE_OFFER_RESPONSE_OBJECT',
                        'instances': 2, 'fields': []}]}]}
    row = lambda denom, key, status='unreached': ledger._row(denom, key, 'x', key, status=status)  # noqa: E731
    rows = [row('native', 'AGENT_MANAGER'), row('persisted', 'AGENT_MANAGER'), row('native', 'db::AGENT'),
            row('persisted', 'ACCEPT_REJECT_TRADE_OFFER_RESPONSE_OBJECT'), row('persisted', 'NEWS_MANAGER'),
            row('native', 'TRANSFER_MANAGER'), row('editor', 'AGENT_MANAGER'),
            row('native', 'FOG_OF_WAR_MANAGER', 'reads')]
    assert ledger.apply_persist(rows, schema) == 5
    by = {(r[0], r[1]): r for r in rows}
    assert by[('native', 'AGENT_MANAGER')][7] == 'reads' and by[('native', 'AGENT_MANAGER')][6] == 'persist'
    assert by[('native', 'db::AGENT')][7] == 'reads'
    assert by[('persisted', 'ACCEPT_REJECT_TRADE_OFFER_RESPONSE_OBJECT')][7] == 'reads'
    assert by[('persisted', 'NEWS_MANAGER')][7] == 'unavailable'
    assert 'VM heap exhausted' in by[('persisted', 'NEWS_MANAGER')][8]
    assert by[('native', 'TRANSFER_MANAGER')][7] == 'unreached'
    assert by[('editor', 'AGENT_MANAGER')][7] == 'unreached'
    assert by[('native', 'FOG_OF_WAR_MANAGER')][6] == 'none'
