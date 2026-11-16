"""NON_PLAYER+70 BASE_INTERNATIONAL_PERSON_DATA wire, reader D8A570.

No date/statistic meanings or reference identities are inferred. The current
writer emits version2; native signed versions below2 omit the vector. Nonempty
vectors require an independently established NATIONAL_TEAM_CONTAINER transport.
"""
import struct

class UnsupportedReference(ValueError):

    def __init__(self, offset):
        self.native = 17930380
        self.offset = offset
        super().__init__(f'Unproved NATIONAL_TEAM_CONTAINER transport at {offset}:111988C required')

def parse(data, start, *, source_major=3754, minor=9, reference_reader=None, max_rows=4096):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported NON_PLAYER+70 source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid NON_PLAYER+70 cursor')
    if type(max_rows) is not int or max_rows < 0:
        raise ValueError('Invalid NON_PLAYER+70 work budget')
    at = start

    def take(n):
        nonlocal at
        if n > len(data) - at:
            raise ValueError(f'Truncated NON_PLAYER+70 at {at}:need{n}')
        raw = bytes(data[at:at + n])
        at += n
        return raw

    def u(n):
        return int.from_bytes(take(n), 'little')
    version = int.from_bytes(take(2), 'little', signed=True)
    count = None
    rows = []
    if version >= 2:
        count = u(4)
        if count > max_rows:
            raise ValueError('NON_PLAYER+70 vector work budget exceeded')
        for index in range(count):
            first = at
            marker = u(1)
            if reference_reader is None:
                raise UnsupportedReference(at)
            reference = reference_reader(data, at, 'NATIONAL_TEAM_CONTAINER', '0')
            if not isinstance(reference, dict) or type(reference.get('end')) is not int or (not at < reference['end'] <= len(data)):
                raise ValueError('Invalid111988C reference progress')
            at = reference['end']
            field8 = u(2)
            fielda = u(2)
            fieldc = u(1)
            rows.append({'native_index': index, 'start': first, 'end': at, 'marker': marker, 'reference': reference, 'field08_raw_u16': field8, 'field0a_raw_u16': fielda, 'field0c_raw_u8': fieldc})
    tail_start = at
    field28 = u(4)
    field34 = u(1)
    field2c = u(4)
    field08 = u(4)
    date30 = take(4).hex()
    field0c = u(4)
    return {'start': start, 'end': at, 'native_reader': '0xd8a570', 'native_writer': '0xd8a8c8', 'native_type': 'db::BASE_INTERNATIONAL_PERSON_DATA', 'native_owner_field': 'NON_PLAYER+0x70', 'version': version, 'vector_present_by_version': version >= 2, 'vector_count': count, 'rows': rows, 'tail_start': tail_start, 'fields': {'28_raw_u32': field28, '34_raw_u8': field34, '2c_raw_u32': field2c, '08_raw_u32': field08, '30_raw_date_hex': date30, '0c_raw_u32': field0c}, 'pending_bytes': 0, 'complete_child_wire': True, 'references_resolved': False, 'semantic_fields_resolved': False}

def validate_current_writer(result):
    if result['version'] != 2:
        raise ValueError('NON_PLAYER+70 current writer version differs from2')
    if any((row['marker'] != 0 for row in result['rows'])):
        raise ValueError('NON_PLAYER+70 current writer row marker differs from0')
