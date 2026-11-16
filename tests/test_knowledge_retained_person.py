"""knowledge_retained_person: the 27.0.1 resolver's hidden-PERSON predicate (virtual +0x510)."""
import struct

import pytest

from fm_live_mcp import address_book, knowledge_retained_person as retained

BASE = 0x1_0000_0000
PERSON, TABLE, METHOD = 0x2_0000_0000, 0x2_0000_1000, BASE + 0x100


def _read(code):
    memory = {PERSON: struct.pack('<Q', TABLE), TABLE + 0x510: struct.pack('<Q', METHOD), METHOD: code}

    def read(address, size):
        for start, data in memory.items():
            if start <= address and address + size <= start + len(data):
                return data[address - start:address - start + size]
        raise AssertionError(f'unexpected read {address:#x}')
    return read


@pytest.mark.parametrize('code, hidden', [
    (bytes.fromhex('00008052c0035fd6'), False),      # mov w0, #0; ret
    (bytes.fromhex('000080d2c0035fd6'), False),      # mov x0, #0; ret
    (bytes.fromhex('20008052c0035fd6'), True),       # mov w0, #1; ret
])
def test_constant_predicates_on_27_0_1(monkeypatch, code, hidden):
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', next(iter(retained.HIDDEN_PERSON_PREDICATE_BUILDS)))
    assert retained._native_hidden(_read(code), BASE, PERSON) is hidden


def test_other_predicates_refuse_on_27_0_1(monkeypatch):
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', next(iter(retained.HIDDEN_PERSON_PREDICATE_BUILDS)))
    with pytest.raises(ValueError, match='not a constant return'):
        retained._native_hidden(_read(bytes.fromhex('080040f9c0035fd6')), BASE, PERSON)


def test_pinned_build_has_no_predicate(monkeypatch):
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', address_book.PINNED_SHA256)
    assert retained._native_hidden(lambda *_: pytest.fail('no read on the pinned build'), BASE, PERSON) is False
