"""Current48936D4 wire for one4893974 subobject; no own version or refs.

Ordered wire entry extents are consumed without retaining payloads. Native tree insertion may collapse duplicate
keys; this source projection does not emulate that in-memory transformation.
"""
import struct

def parse(data, start, *, container_version=18, limit=None, source_major=3754, minor=9, max_entries=100000):
    if type(container_version) is not int or container_version != 18:
        raise ValueError('Explicit current container18 scope required')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Explicit3754/9 source profile required')
    if type(max_entries) is not int or not 0 <= max_entries <= 1000000:
        raise ValueError('Invalid offline entry budget')
    bound = len(data) if limit is None else limit
    if type(start) is not int or type(bound) is not int or (not 0 <= start <= bound <= len(data)):
        raise ValueError('Invalid bounded4893974 cursor')
    at = start

    def take(n):
        nonlocal at
        if n > bound - at:
            raise ValueError(f'Truncated4893974 at{at}')
        raw = bytes(data[at:at + n])
        at += n
        return raw

    def count(width):
        n = struct.unpack('<I', take(4))[0]
        if n > max_entries:
            raise ValueError('Offline4893974 entry budget exceeded')
        if n * width > bound - at:
            raise ValueError('Truncated4893974 entries')
        return n
    first_count = count(4)
    # Both vectors have fixed unconstrained wire entries; preserve extents and
    # validate the following fixed-count guard without allocating row objects.
    at += first_count * 4
    first = None
    second_count = count(11)
    at += second_count * 11
    second = None
    fixed_count = struct.unpack('<I', take(4))[0]
    if fixed_count != 3:
        raise ValueError('Current paired48936D4 writer emits fixed count3')
    fixed = [take(4).hex() for _ in range(3)]
    return {'start': start, 'end': at, 'native_reader': '0x4893974', 'paired_writer': '0x48936d4', 'container_version': container_version, 'own_version_consumed': False, 'first_count': first_count, 'first_entries': first, 'second_count': second_count, 'second_entries': second, 'fixed_count': fixed_count, 'fixed_entries_raw': fixed, 'complete_owned_child': True, 'native_tree_duplicate_collapse_not_applied': True, 'reference_context_consumed': False, 'field_semantics_resolved': False}
