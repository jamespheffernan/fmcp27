"""Source3754/9 member stream v521. Both directions call 3BDF670."""
WIDTHS = (4, 2, 2, 4, 4, 4, 4, 4, 4, 1, 1, 1)
def parse(data, start):
    if type(start) is not int or not 0 <= start <= len(data)-sum(WIDTHS):
        raise ValueError('Truncated +5B0 payload')
    cursor = start
    chunks = []
    for size in WIDTHS:
        chunks.append(bytes(data[cursor:cursor+size]).hex())
        cursor += size
    return dict(start=start,end=cursor,fields_in_native_order_hex=chunks)
