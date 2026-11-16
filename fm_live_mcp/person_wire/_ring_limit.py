"""Non-destructive source-wire geometry; not a configured native loader emulator."""
import struct

def parse_ring_wire(data, start=0, *, end=None):
    """Read encoded u32 count, 0..12 serialized bytes and following raw+230u32.

    Caller must establish the exact preceding source3754/9 PLAYER cursor. An
    accepted physical span does not assert native global56C1628 or prior object
    state. This function consumes no game state and assigns no ring slot/head.
    """
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ValueError('Invalid source wire bytes')
    end = len(data) if end is None else end
    if type(start) is not int or type(end) is not int or (not 0 <= start <= end <= len(data)):
        raise ValueError('Invalid checked source span')
    if end - start < 4:
        raise ValueError('Truncated ring count')
    count = struct.unpack_from('<I', data, start)[0]
    if count > 12:
        raise ValueError('Ring count exceeds proved physical capacity12')
    stop = start + 8 + count
    if stop > end:
        raise ValueError('Truncated ring and following scalar span')
    return {'start': start, 'end': stop, 'count': count, 'ring_source_offset': start + 4, 'serialized_order': list(data[start + 4:start + 4 + count]), 'native_0x230_raw_u32': struct.unpack_from('<I', data, start + 4 + count)[0], 'geometry': 'paired_native_writer_physical_span', 'native_runtime_acceptance': 'not_asserted', 'native_slot_projection': None}

def native_positive_guard(count, collection_limit):
    """Predicate after count flush; assumes earlier initial+218==0 guard passed."""
    if type(count) is not int or not 0 <= count <= 4294967295:
        raise ValueError('Invalid native u32 count')
    if collection_limit is not None and (type(collection_limit) is not int or not 0 <= collection_limit <= 18446744073709551615):
        raise ValueError('Invalid native u64 collection limit')
    if count == 0:
        return 'continue_without_collection_limit_test'
    if count > 12:
        return 'return_false_without_consuming_ring'
    if collection_limit is None:
        return 'unknown_runtime_limit'
    if count >= collection_limit:
        return 'return_false_without_consuming_ring'
    return 'continue'
