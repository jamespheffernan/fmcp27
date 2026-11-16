import struct
import pytest
from fm_live_mcp import frame_world_basis as basis


def memory():
    base = 0x10000000
    values = {base + at: raw for at, raw in basis.SPANS}
    for table, offset, target in basis.ROUTES:
        values[base + table + offset] = struct.pack("<Q", base + target)

    def read(address, size):
        assert address in values and len(values[address]) == size
        return values[address]

    return base, values, read


def test_all_nine_official_spans_and_three_virtual_routes_are_required():
    base, values, read = memory()
    assert len(basis.SPANS) == 9 and len(basis.ROUTES) == 3
    basis.verify_native(read, base)


@pytest.mark.parametrize("span", range(9))
def test_each_changed_world_span_fails_closed(span):
    base, values, read = memory()
    at, _ = basis.SPANS[span]
    old = values[base + at]
    values[base + at] = bytes([old[0] ^ 1]) + old[1:]
    with pytest.raises(ValueError, match="basis changed"):
        basis.verify_native(read, base)


@pytest.mark.parametrize("route", range(3))
def test_each_changed_named_virtual_route_fails_closed(route):
    base, values, read = memory()
    table, offset, target = basis.ROUTES[route]
    values[base + table + offset] = struct.pack("<Q", base + target + 4)
    with pytest.raises(ValueError, match="route changed"):
        basis.verify_native(read, base)
