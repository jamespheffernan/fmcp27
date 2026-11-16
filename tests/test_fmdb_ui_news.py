"""Offline tests for the inbox / calendar / fixture recipes (fm_live_mcp.fmdb.ui_recipes_news)."""
import base64
from datetime import date
import struct

import pytest

from fm_live_mcp.fmdb import ui_recipes_news as N
from fm_live_mcp.fmdb.ui_handlers import HandlerReading, Reading
from fm_live_mcp.fmdb.ui_vm import fourcc
from fm_live_mcp.fmdb.variant import si_date as decode_si_date
from fm_live_mcp.fmdb.vm import Unavailable


def test_si_date_encoding_round_trip():
    payload = N.si_date(date(2030, 12, 10), 57)
    assert payload == 2030 << 17 | 344 << 8 | 57
    assert N.si_date_parts(payload) == (date(2030, 12, 10), 57)
    assert N.si_date_parts(1900 << 17 | 1 << 8) is None
    # the variant decoder (the game's own SI_DATE traits) reads the same layout
    decoded = decode_si_date(payload)
    assert decoded.iso == '2030-12-10' and decoded.low == 57
    with pytest.raises(ValueError):
        N.si_date(date(2030, 1, 1), 128)


def test_packed_date_and_kickoff_match_fixture_reader():
    payload = N.si_date(date(2030, 12, 10), 57)
    packed = N.packed_from_si(payload)
    assert packed == 2030 << 16 | 57 << 9 | 344
    assert N.kickoff(payload)['time'] == '20:00'
    assert N.kickoff(N.si_date(date(2031, 1, 1), 31))['time'] == '13:30'
    assert N.kickoff(N.si_date(date(2031, 2, 3), 0))['state'] == 'no_time_code'


def test_bag_bytes_layout():
    blob = N.bag_bytes(0x1000, [('nMzT', 0x2000), (fourcc('stDT'), 0x3000)])
    begin, end, cap = struct.unpack_from('<QQQ', blob)
    assert (begin, end, cap) == (0x1018, 0x1038, 0x1038)
    entries = [struct.unpack_from('<IIQ', blob, 24 + 16 * i) for i in range(2)]
    assert entries == [(fourcc('nMzT'), 0, 0x2000), (fourcc('stDT'), 0, 0x3000)]
    assert N.bag_bytes(0x1000, [])[:24] == struct.pack('<QQQ', 0x1018, 0x1018, 0x1018)


def test_parse_declarations():
    memory = {}

    def put(address, data):
        for i, b in enumerate(data):
            memory[address + i] = b

    def read(address, length):
        return bytes(memory.get(address + i, 0) for i in range(length))
    groups = 0x5000
    put(0x100, struct.pack('<QQQ', groups, groups + 2 * N.DECLARATION_SIZE, groups + 2 * N.DECLARATION_SIZE))
    put(groups + 0x30, struct.pack('<QQ', 0x6000, 0x6008))
    put(0x6000, struct.pack('<II', fourcc('Viiw'), fourcc('UIQa')))
    put(groups + N.DECLARATION_SIZE + 0x30, struct.pack('<QQ', 0x7000, 0x7004))
    put(0x7000, struct.pack('<I', fourcc('MPML')))
    out = N.parse_declarations(read, 0x100)
    assert out == [(groups, groups + 0x18, ['Viiw', 'UIQa']),
                   (groups + N.DECLARATION_SIZE, groups + N.DECLARATION_SIZE + 0x18, ['MPML'])]


def test_links_and_ui_ids():
    record = base64.b64encode(struct.pack('<IIII', fourcc('110 '), 28, fourcc('dref'), 0x18000221)).decode()
    text = f'Draw: \x01{record}\x02Newcastle United\x01 v Wolves'
    assert N.links(text) == [{'text': 'Newcastle United', 'record': {'110 ': 28, 'dref': 0x18000221}}]
    assert N.links(None) == []
    assert N.ui_id_parts(0x18000221) == (0x18, 0x221)
    assert N.ui_id_parts(-8388609) is None            # 0xFF7FFFFF: 'no object'
    assert N.dref({'dref': 402653729}) == 0x18000221


FIXTURE_EVENT = {
    'FRfr': {'dref': 0x35000551, 'dcnt': decode_si_date(N.si_date(date(2030, 12, 10), 57))},
    'FxNm': {'dref': 0x39000B82}, 'date': decode_si_date(N.si_date(date(2030, 12, 10), 57)),
    'comp': {'dref': 0x1900027D}, 'Topp': {'dref': 0x18000551}, 'Ttea': {'dref': 0x18000221},
    'iSHo': False, 'HUCD': True, 'TpoN': 13, 'FxVn': 2, 'clEv': 0}
NAMES = {0x1900027D: 'UEFA Champions League', 0x18000551: 'Villarreal C.F.',
         0x18000221: 'Newcastle United', 0x39000B82: 'UEFA Champions League League Phase',
         0x19000295: 'Emirates FA Cup', 0x17000107: 'Third Round'}


def fake_names(ui_id):
    return {'id': ui_id, 'type': None, 'name': NAMES.get(ui_id)}


def test_shape_fixture_event():
    row = N.shape_event(FIXTURE_EVENT, fake_names,
                        lambda ref: {'stadium': 'Estadio de La Cerámica', 'home_team': 'Villarreal C.F.'})
    assert row['kind'] == 'fixture' and row['date'] == '2030-12-10'
    assert row['kickoff']['time'] == '20:00'
    assert row['competition']['name'] == 'UEFA Champions League'
    assert row['opponent']['name'] == 'Villarreal C.F.'
    assert row['venue'] == 'away' and row['is_home'] is False
    assert row['stadium'] == 'Estadio de La Cerámica'
    assert N.calendar_fixture_key(row) == ('2030-12-10', 0x551, 0x221)


def test_shape_training_and_competition_events():
    day = decode_si_date(N.si_date(date(2030, 12, 11), 57))
    training = N.shape_event({'clEv': 17, 'date': day, 'Szio': [301, 301, 400], 'type': 0})
    assert training['kind'] == 'training' and training['sessions'] == [301, 301, 400]
    comp = N.shape_event({'comp': {'dref': 0x19000295}, 'Ttea': {'dref': 0x18000221}, 'crep': 157,
                          'CoII': False, 'date': decode_si_date(N.si_date(date(2031, 1, 11), 37)),
                          'Fmtd': -1, 'sbsn': {'dref': 0x17000107}, 'type': 23, 'clEv': 1}, fake_names)
    assert comp['kind'] == 'competition' and comp['type'] == 23
    assert comp['type_inferred'] == 'round_scheduled_date'
    assert comp['competition']['name'] == 'Emirates FA Cup' and comp['stage']['name'] == 'Third Round'
    assert N.event_key(comp) != N.event_key(training)


def test_cross_check_fixtures():
    row = N.shape_event(FIXTURE_EVENT, fake_names,
                        lambda ref: {'stadium': 'Estadio de La Cerámica'})
    bridge = {'date': '2030-12-10', 'kickoff_time': {'time': '20:00'},
              'home_team': {'database_index': 0x551}, 'away_team': {'database_index': 0x221},
              'competition': {'name': 'UEFA Champions League'},
              'stadium': {'name': 'Estadio de La Cerámica'}}
    out = N.cross_check_fixtures([row], [bridge])
    assert len(out['matched']) == 1 and not out['mismatched'] and not out['calendar_only']
    late = dict(bridge, kickoff_time={'time': '21:00'})
    other = dict(bridge, date='2030-12-13')
    out = N.cross_check_fixtures([row], [late, other])
    assert out['mismatched'][0]['differs'] == {'kickoff': ('20:00', '21:00')}
    assert out['bridge_only'] == [('2030-12-13', 0x551, 0x221)]


def _reading(values):
    return HandlerReading(70, 'NEWS_ITEM_UI_HANDLER', 'NEWS_ITEM_UI_HANDLER_SERVER', {}, {},
                          readings=[Reading(k, None, None, v, 0.0) for k, v in values.items()])


def test_shape_news():
    record = base64.b64encode(struct.pack('<IIII', fourcc('110 '), 28, fourcc('dref'), 0x18000254)).decode()
    reading = _reading({
        'titl': 'FA Cup draws Newcastle against Wolves',
        'body': f'Newcastle United will play \x01{record}\x02Wolverhampton Wanderers\x01.',
        'CqMA': decode_si_date(N.si_date(date(2030, 12, 10), 53)), '77MG': '19:00', 'G0xt': False,
        'nips': {'110 ': 28, 'dref': 0x0101AC66},
        '8C2l': {'3Sd ': [{'kEd5': 0, '0JJ4': {'110 ': 28, 'dref': 0x19000295}}]},
        'QdrY': Unavailable('external call _strtod')})
    entry = N.InboxEntry(0x1000, 1342304, 'CUP_ROUND_DRAW_NEWS', 0xC032)
    row = N.shape_news(entry, reading, fake_names)
    assert row['subject'] == 'FA Cup draws Newcastle against Wolves'
    assert row['body'] == 'Newcastle United will play Wolverhampton Wanderers.'
    assert row['body_links'][0]['record']['dref'] == 0x18000254
    assert row['date'] == '2030-12-10' and row['time_sent'] == '19:00'
    assert row['read'] is False and row['read_flag'] is False
    assert row['sender']['id'] == 0x0101AC66
    assert row['references'][0]['name'] == 'Emirates FA Cup'
    assert row['unavailable'] == {'QdrY': 'external call _strtod'}
    assert N.InboxEntry(0, 1, None, 0xC033).read is True


class _FakeUc:
    def __init__(self):
        self.regs = {}

    def reg_read(self, reg):
        return self.regs.get(reg, 0)

    def reg_write(self, reg, value):
        self.regs[reg] = value


class _FakeVm:
    """Just enough of PropertyVM for the libc models: registers, a byte map, _x and _ret."""

    def __init__(self):
        self.uc, self.mem, self.returned = _FakeUc(), {}, None

    def _x(self, i):
        import unicorn.arm64_const as A
        return self.uc.reg_read(getattr(A, f'UC_ARM64_REG_X{i}'))

    def set_x(self, i, value):
        import unicorn.arm64_const as A
        self.uc.reg_write(getattr(A, f'UC_ARM64_REG_X{i}'), value)

    def read(self, address, length):
        return bytes(self.mem.get(address + i, 0) for i in range(length))

    def write(self, address, data):
        for i, b in enumerate(data):
            self.mem[address + i] = b

    def _ret(self, value):
        self.returned = value


def test_libc_models_memchr_modff_strtod():
    import unicorn.arm64_const as A
    from fm_live_mcp.fmdb import ui_vm
    vm = _FakeVm()
    vm.write(0x1000, b'abc,def\0')
    for i, v in enumerate((0x1000, ord(','), 8)):
        vm.set_x(i, v)
    ui_vm._memchr(vm)
    assert vm.returned == 0x1003
    vm.set_x(2, 3)
    ui_vm._memchr(vm)
    assert vm.returned == 0
    vm.uc.reg_write(A.UC_ARM64_REG_D0, struct.unpack('<I', struct.pack('<f', 2.75))[0])
    vm.set_x(0, 0x2000)
    ui_vm._modff(vm)
    assert struct.unpack('<f', vm.read(0x2000, 4))[0] == 2.0
    assert struct.unpack('<f', struct.pack('<I', vm.uc.reg_read(A.UC_ARM64_REG_D0) & 0xFFFFFFFF))[0] == 0.75
    vm.write(0x3000, b'  -12.5e1xyz\0')
    vm.set_x(0, 0x3000)
    vm.set_x(1, 0x4000)
    ui_vm._strtod(vm)
    assert struct.unpack('<d', struct.pack('<Q', vm.uc.reg_read(A.UC_ARM64_REG_D0)))[0] == -125.0
    assert struct.unpack('<Q', vm.read(0x4000, 8))[0] == 0x3000 + 9
    vm.write(0x5000, b'0x1p3\0')
    vm.set_x(0, 0x5000)
    from fm_live_mcp.fmdb.vm import _Stop
    with pytest.raises(_Stop):
        ui_vm._strtod(vm)
