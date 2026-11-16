"""Wire row from 15739B8. Reader versions 0/1 omit the final three bytes."""
import struct

def parse(data, start, *, current_writer=True):
    if type(start) is not int or not 0 <= start < len(data):
        raise ValueError('Missing 15739B8 version')
    version = data[start]
    if current_writer and version != 2:
        raise ValueError('Unsupported 1573858 current writer version')
    end = start + (8 if version >= 2 else 5)
    if end > len(data):
        raise ValueError('Truncated 15739B8 row')
    return {'start': start, 'end': end, 'version': version, 'raw_u16': struct.unpack_from('<H', data, start + 1)[0], 'raw_fields_2_3': list(data[start + 3:start + 5]), 'raw_fields_4_6': list(data[start + 5:end])}
