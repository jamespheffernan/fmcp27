"""Bounded154E184 row. Typed-reference state is explicit, never inferred by fit."""
import struct

class UnsupportedChild(ValueError):

    def __init__(self, native, offset):
        self.native, self.offset = (native, offset)
        super().__init__(f'Unsupported154E184 child {native} at {offset}')

def parse(data, start, *, reference_mode='raw64', source_major=3754, minor=9, native_reference_context=None, reference_reader=None):
    if (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported154E184 source')
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid154E184 cursor')
    at = start
    fields = {}

    def take(n):
        nonlocal at
        if n < 0 or n > len(data) - at:
            raise ValueError('Truncated154E184')
        b = data[at:at + n]
        at += n
        return b

    def u(n):
        return int.from_bytes(take(n), 'little')

    def ref(kind):
        nonlocal at
        begin = at
        if reference_reader:
            r = reference_reader(data, at, kind)
            if not isinstance(r, dict) or type(r.get('end')) is not int or (not at < r['end'] <= len(data)):
                raise ValueError('Invalid154E184 reference callback')
            at = r['end']
            return r
        needed = {'stream_flags': 2, 'root_80a': 0, 'global_3522': 0, 'global_3523': 1, 'global_2c98': 1}
        if native_reference_context != needed:
            raise UnsupportedChild('explicit typed-reference context required for ' + kind, at)
        if kind == 'root40':
            index = struct.unpack('<h', take(2))[0]
            extra = u(4) if index == -2 else None
            return {'start': begin, 'end': at, 'index_i16': index, 'escape_u32': extra, 'resolved': False}
        if kind in ('person', 'person_1104d70'):
            value = u(4)
            return {'start': begin, 'end': at, 'raw_u32': value, 'resolved': False}
        marker = u(1)
        if marker == 2:
            raise UnsupportedChild('0x11073a8 tagged group marker2', at)
        index = u(4)
        secondary = u(4) if marker == 1 and index != 4294967295 else None
        return {'start': begin, 'end': at, 'marker': marker, 'raw_index': index, 'secondary': secondary, 'resolved': False}
    version = u(1)
    fields['root40'] = ref('root40')
    presence = u(1)
    fields['optional_presence'] = presence
    if presence == 1:
        child_start = at
        child = {'version': u(1), 'raw18': take(4).hex(), 'person': ref('person_1104d70'), 'byte23': u(1), 'group08': ref('group'), 'group10': ref('group'), 'byte21': u(1), 'byte20': u(1), 'raw1c': take(4).hex()}
        child.update(start=child_start, end=at)
        fields['optional_3f94fc0'] = child
    fields['raw20'] = take(4).hex()
    for key, size in [('2a', 2), ('28', 2), ('2e', 1), ('30', 1), ('32', 1)]:
        fields[key] = u(size)
    fields['person10'] = ref('person')
    fields['group18'] = ref('group')
    fields['2f'] = u(1)
    fields['24_raw'] = take(4).hex()
    fields['2c'] = u(1)
    fields['2d'] = u(1)
    if version >= 2:
        fields['31'] = u(1)
        fields['33'] = u(1)
    if version == 2:
        fields['legacy_discard'] = u(1)
    return {'start': start, 'end': at, 'version': version, 'fields': fields, 'native_reader': '0x154e184', 'native_writer': '0x154dd68', 'references_resolved': False, 'native_reference_context': native_reference_context}
