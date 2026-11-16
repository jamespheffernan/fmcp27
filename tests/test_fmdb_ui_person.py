"""Offline checks for the PERSON / CLUB / PLAYER_REPORT recipes (no game needed)."""
import struct

import pytest

from fm_live_mcp.fmdb import ui_recipes_person as P, ui_registry
from fm_live_mcp.fmdb.ui_vm import fourcc, fourcc_text, REQUEST_KEY_OFFSET, REQUEST_SIZE


@pytest.fixture(scope='module')
def registry():
    return ui_registry.default()


def test_record_and_protocol_constants():
    assert fourcc('dref') == 0x64726566            # 0x1B24A0 reads this record key
    assert fourcc_text(P.NULL_KEY) == 'NULL'        # slot 13 "no direct data key"
    assert P.DATABASE_RECORD == 28 and P.CONTRACT == 19 and P.PLAYER_REPORT == 75
    assert P.PARAM_HOOK_RVA - P.PARAM_LOOKUP_RVA == 0x18 and P.PARAM_FOUND_RVA > P.PARAM_HOOK_RVA


@pytest.mark.parametrize('cls,keys', [
    ('PERSON_UI_HANDLER', P.PLAYER_KEYS), ('CONTRACT_UI_HANDLER', P.CONTRACT_KEYS),
    ('CLUB_UI_HANDLER', P.CLUB_KEYS), ('PLAYER_REPORT_UI_HANDLER', P.SCOUT_KEYS)])
def test_recipe_keys_are_registry_keys_of_their_handler(registry, cls, keys):
    known = set()
    for name in (cls, 'DATABASE_RECORD_UI_HANDLER'):     # base class: Surname, UniqueId, ...
        row = registry.classes[name]
        known |= set(row.keys(4)) | set(row.keys(2)) | set(row.keys(14))
    missing = {name: code for name, code in keys.items() if code not in known}
    assert not missing, missing
    assert all(registry.label(code) for code in keys.values())


def test_vision_parameters_and_filters():
    assert (P.VISION_OWNER, P.VISION_FILTER, P.VISION_FLAG) == (0x56D1A08, 0x56D1A18, 0x56D1A28)
    assert P.OWNERS == {'board': 1, 'supporters': 2}
    assert P.VISION_FILTERS['actionable'] == 6 and P.VISION_FILTERS['culture'] == 4


@pytest.mark.parametrize('value,text', [(10, 'Required'), (7, 'Desired'), (6, 'Preferred'), (5, 'Preferred'),
                                        (4, 'Preferred'), (3, 'Favoured'), (1, 'Favoured'), (0, None),
                                        (None, None), (True, None)])
def test_importance_bands_match_reference_screen(value, text):
    assert P.importance_text(value) == text


def test_objective_shaping():
    entry = {'comp': {'110 ': 0}, 'hint': 'h', 'cvoc': 2, 'cvoi': 44, 'coip': 10,
             'cvon': 'Work within wage budget', 'aZDo': '', 'cvop': 6, 'VOse': 1, 'cvos': 0,
             'VOdt': 2, 'Viys': 'Current Season'}
    row = P._objective(entry)
    assert row['objective'] == 'Work within wage budget' and row['importance'] == 'Required'
    assert row['season'] == 'Current Season' and row['judgement_value'] == 6 and row['id'] == 44


@pytest.mark.parametrize('fields,band', [
    ({'happiness_level': 100}, 'very happy'), ({'happiness_level': 60}, 'very happy'),
    ({'happiness_level': 59}, 'other'), ({'happiness_level': -52}, 'other'),
    ({'happiness_level': 50, 'playing_time_happiness_level': -20,
      'playing_time_happiness': 'Is concerned with the amount of game time he has been getting.'},
     'concerned about playing time'),
    ({'happiness_level': {'unavailable': 'x'}}, None)])
def test_squad_screen_band(fields, band):
    assert P.squad_screen_band(fields) == band


class _FakeUc:
    def __init__(self, heap):
        self.heap = heap

    def mem_write(self, address, data):
        self.heap[address - 0x1000:address - 0x1000 + len(data)] = data


class _FakeVM:
    """Byte heap standing in for the VM: exercises the request encoder only."""
    def __init__(self):
        self.heap = bytearray(0x1000)
        self.top = 0x1000
        self.uc = _FakeUc(self.heap)

    def alloc(self, size, align=16):
        address = self.top
        self.top += (size + align - 1) // align * align
        return address


def test_request_encoding():
    vm = _FakeVM()
    reader = P.DataReader(vm, handler=None)
    request = reader._request('HPPo')
    raw = bytes(vm.heap[request - 0x1000:request - 0x1000 + REQUEST_SIZE])
    assert struct.unpack_from('<I', raw, REQUEST_KEY_OFFSET)[0] == fourcc('HPPo')
    assert raw.count(0) == REQUEST_SIZE - 4 + raw[REQUEST_KEY_OFFSET:REQUEST_KEY_OFFSET + 4].count(0)


def test_value_shaping_keeps_unavailable_reason():
    from fm_live_mcp.fmdb.ui_handlers import Reading
    from fm_live_mcp.fmdb.vm import Unavailable
    assert P._value(Reading('HPPo', None, None, Unavailable('data key PRHP: x'), 0.0)) == \
        {'unavailable': 'data key PRHP: x'}
    assert P._value(Reading('dafe', None, 'string', '\x01QUJD\x02Exceptional\x01', 0.0)) == 'Exceptional'
