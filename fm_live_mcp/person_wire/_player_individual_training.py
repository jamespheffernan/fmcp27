"""Pure bounded1326EC4 individual-training transport; writer13272B4.

No native calls, references or nested records. Preserve raw bytes and separately
show native legacy-code conversion/clamp, without assigning enum labels/units.
The native buffered reader flushes this entire child before returning.
"""
LEGACY_CODES = bytes.fromhex('feff000102030405060708090a0b0c131416171518191c1d1e1e1f2020fe')

def convert_code(raw, version):
    if type(raw) is not int or not 0 <= raw <= 255 or type(version) is not int or (not 0 <= version <= 255):
        raise ValueError('Invalid1327168 raw code/version')
    if version > 2:
        return raw
    index = raw + 2 & 255
    return LEGACY_CODES[index] if index <= 29 else 254

def parse(data, start, *, source_major=3754, minor=9):
    if type(start) is not int or not 0 <= start <= len(data):
        raise ValueError('Invalid1326EC4 cursor')
    if type(source_major) is not int or type(minor) is not int or (source_major, minor) != (3754, 9):
        raise ValueError('Unsupported1326EC4 source profile')
    if start == len(data):
        raise ValueError(f'Truncated1326EC4 version at{start}')
    version = data[start]
    size = 11 if version >= 2 else 9
    end = start + size
    if end > len(data):
        raise ValueError(f'Truncated1326EC4 at{start}: need{size}')
    field6 = data[start + 1]
    field9 = data[start + 8]
    converted6 = convert_code(field6, version)
    effective6 = 255 if 33 <= converted6 <= 127 else converted6
    effective9 = convert_code(field9, version)
    return {'start': start, 'end': end, 'consumed_bytes': size, 'version': version, 'raw_hex': bytes(data[start:end]).hex(), 'native_06_raw': field6, 'native_06_after_legacy_conversion': converted6, 'native_06_effective': effective6, 'native_06_effective_signed': effective6 if effective6 < 128 else effective6 - 256, 'native_07_08_raw_hex': bytes(data[start + 2:start + 4]).hex(), 'native_00_03_raw_hex': bytes(data[start + 4:start + 8]).hex(), 'native_09_raw': field9, 'native_09_effective': effective9, 'native_04_05_raw_hex': bytes(data[start + 9:end]).hex() if version >= 2 else None, 'native_04_05_state': 'serialized' if version >= 2 else 'unserialized_destination_unchanged', 'native_reader': '0x1326ec4', 'native_code_converter': '0x1327168', 'native_writer': '0x13272b4', 'native_pending_bytes_at_return': 0, 'complete_child_wire': True, 'semantic_fields_resolved': False, 'source_major': source_major, 'minor': minor}

def rebuild(result):
    out = bytes((result['version'], result['native_06_raw']))
    out += bytes.fromhex(result['native_07_08_raw_hex']) + bytes.fromhex(result['native_00_03_raw_hex'])
    out += bytes((result['native_09_raw'],))
    if result['version'] >= 2:
        out += bytes.fromhex(result['native_04_05_raw_hex'])
    return out
