"""Offline checks: UI registry data file and handler input encoding (no game needed)."""
import struct

import pytest

from fm_live_mcp.fmdb import ui_registry
from fm_live_mcp.fmdb.ui_vm import fourcc, fourcc_text, object_id


@pytest.fixture(scope='module')
def registry():
    return ui_registry.default()


def test_registry_is_pinned_and_complete(registry):
    from fm_live_mcp import players
    assert registry.build == players.SHA256
    assert len(registry.labels) > 7000
    assert len(registry.classes) > 600
    assert registry.label('4zmg') == 'BoardConfidenceOverallGrade'
    assert '4zmg' in registry.codes('BoardConfidenceOverallGrade')


def test_team_confidence_class(registry):
    client = registry.handler_class('TEAM_CONFIDENCE')
    assert client.vtable == 0x54E2E58
    assert client.fn(4) == 0x54F454 and client.fn(17) == 0x551A9C
    assert len(client.keys(4)) >= 70
    assert client.declares() == ('Tcnf',)
    server = registry.server_of('TEAM_CONFIDENCE_UI_HANDLER')
    assert server.fn(2) == 0x551D60
    assert {'Tcnf', 'Ttea', 'CdTc'} <= set(server.slots['2']['fourccs'])


def test_types_when_present(registry):
    if not registry.types:
        pytest.skip('type table not generated (needs --live)')
    assert registry.types[114]['client'] == 'TEAM_CONFIDENCE_UI_HANDLER'
    assert registry.types[114]['server'] == 'TEAM_CONFIDENCE_UI_HANDLER_SERVER'
    assert registry.type_of('TEAM_CONFIDENCE_UI_HANDLER') == 114


def test_fourcc_round_trip():
    assert fourcc('Tcnf') == 0x54636E66
    assert fourcc('110 ') == 0x31313020
    assert fourcc_text(0x347A6D67) == '4zmg'


def test_object_id_matches_shipped_packer():
    # 0x11B8B0C: w = (w2 & 0x7FFFFF) | w1 << 24 (team 545 of table type 0x18).
    assert object_id(0x18, 545) == 0x18000221
    assert object_id(3, 414) == 0x0300019E


def test_ui_record_layout():
    """UI_RECORD = {begin, end, cap, u32}: sorted 8-byte (key, value) pairs (0x77E714)."""
    from fm_live_mcp.fmdb.ui_vm import UiHandlerVM

    class Fake(UiHandlerVM):
        def __init__(self):  # no Unicorn session: exercise the encoder on a byte heap
            self.memory, self.top = {}, 0x1000

        def heap_bytes(self, data, align=16):
            self.top = (self.top + align - 1) & ~(align - 1)
            address, self.top = self.top, self.top + len(data)
            self.memory[address] = bytes(data)
            return address

    vm = Fake()
    header = vm.ui_record({'Ttea': 0x18000221, '110 ': 114})
    begin, end, cap, flags = struct.unpack('<QQQI', vm.memory[header][:28])
    pairs = vm.memory[begin]
    assert end - begin == 16 and cap == end and flags == 0
    assert struct.unpack('<IIII', pairs) == (fourcc('110 '), 114, fourcc('Ttea'), 0x18000221)
