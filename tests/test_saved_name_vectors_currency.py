"""Currency context follows the existing sequential source traversal once."""
import struct

import pytest

from fm_live_mcp import saved_name_vectors as names, saved_squad_tables
from test_saved_club_search import database
from test_saved_currency_records import currency
from test_saved_name_vectors import metadata, overlay, fixture
from test_saved_world_search import framed


def source(currencies):
    prefix = database([]) + framed([]) * 2 + framed(currencies) + framed([]) * 5
    return (prefix + metadata(1) * 3 + b'opaque supplement'
            + overlay(['First']) + overlay(['Second']) + overlay(['Common'])
            + struct.pack('<IB', 1, 1) + b'\xff')


def pound(index=0, **kwargs):
    return currency(index=index, native=86, name='United Kingdom Pound',
                    rate_raw=struct.pack('<f', 1.0), **kwargs)


def test_single_pass_currency_context_and_names(monkeypatch):
    calls = []
    original = saved_squad_tables.saved_currency_records.read_currency

    def counted(reader, ordinal, kind):
        calls.append(ordinal)
        return original(reader, ordinal, kind)

    monkeypatch.setattr(saved_squad_tables.saved_currency_records, 'read_currency', counted)
    layout = names.locate(source([pound()]))
    assert calls == [0]
    assert layout.base_currency_code == 'GBP'
    assert layout.lookup('first', 0) == 'First'
    assert layout.name_counts == {'first': 1, 'second': 1, 'common': 1}
    assert 'base_currency_code' not in layout.provenance


@pytest.mark.parametrize('rows', [
    [],
    [currency(native=85, name='United Kingdom Pound')],
    [currency(native=86, name='Other')],
    [currency(native=86, name='United Kingdom Pound', rate_raw=struct.pack('<f', 2.0))],
    [currency(native=86, name='United Kingdom Pound', rate_raw=struct.pack('<f', float('nan')))],
    [pound(), pound(index=1)],
    [pound(), currency(index=1, native=86, name='Other', rate_raw=struct.pack('<f', 2.0))],
])
def test_missing_malformed_or_duplicate_context_is_unavailable(rows):
    layout = names.locate(source(rows))
    assert layout.base_currency_code is None
    assert layout.lookup('second', 0) == 'Second'


def test_empty_original_tables_have_no_currency_context():
    assert names.locate(fixture()).base_currency_code is None
