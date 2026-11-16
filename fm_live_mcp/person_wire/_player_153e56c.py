"""Traverse the current PLAYER+F0+58 form rows without retaining child payloads."""
import struct


class UnsupportedChild(ValueError):
    def __init__(self, native, offset, reason):
        self.native = hex(native)
        self.offset = offset
        super().__init__(f'Unsupported {native:#x} at {offset}: {reason}')


def parse(data, start, *, child_readers):
    cursor = start

    def take(length):
        nonlocal cursor
        if length > len(data) - cursor:
            raise ValueError('Truncated153E56C source')
        position = cursor
        cursor += length
        return position

    def byte():
        return data[take(1)]

    groups = byte()
    for _ in range(groups):
        head = take(10)
        kind, version, _, count = struct.unpack_from('<BBII', data, head)
        if kind not in (20, 60):
            raise UnsupportedChild(0x153e56c, head, 'unsupported polymorphic kind')
        if version != 1:
            raise UnsupportedChild(0x153e56c, head + 1, 'unsupported currentwriter group version')
        if count > 4096:
            raise UnsupportedChild(0x153e56c, head + 6, 'offline per-group row budget exceeded')
        for _ in range(count):
            row = take(15)
            if data[row] != 1:
                raise UnsupportedChild(0x153aa34, row, 'unsupported currentwriter row version')
            present = data[row + 14]
            if present == 1:
                extra_version = byte()
                if extra_version != 3:
                    raise UnsupportedChild(0x153c870, cursor - 1, 'unsupported currentwriter extra version')
                # Discard byte, u32, u16 and 31 raw bytes.
                take(38)
            elif present != 0:
                raise ValueError('Invalid currentwriter153AA34 presence')

    for native in (0x151f710, 0x155007c):
        present = byte()
        if present == 0:
            continue
        if present != 1:
            raise ValueError('Invalid currentwriter153E56C presence')
        reader = child_readers.get(native)
        if reader is None:
            raise UnsupportedChild(native, cursor, 'missing optional child codec')
        child = reader(data, cursor)
        if not isinstance(child, dict) or type(child.get('end')) is not int or not cursor < child['end'] <= len(data):
            raise ValueError('Invalid153E56C child cursor')
        cursor = child['end']
    return {'start': start, 'end': cursor}
