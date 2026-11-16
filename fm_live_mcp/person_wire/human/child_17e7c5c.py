"""Exact bounded current-writer 17E7C5C component. No presumed input cursor."""
import struct

class Unsupported(ValueError):

    def __init__(self, native, offset, version):
        self.native = hex(native)
        self.offset = offset
        super().__init__(f'Unsupported {native:#x} version {version} at {offset}')

class Reader:

    def __init__(self, data, start, limit):
        if not isinstance(data, (bytes, bytearray, memoryview)) or type(start) is not int or type(limit) is not int or (not 0 <= start <= limit <= len(data)):
            raise ValueError('invalid bounded source')
        self.data = data
        self.offset = start
        self.limit = limit

    def num(self, code):
        size = struct.calcsize('<' + code)
        p = self.offset
        if size > self.limit - p:
            raise ValueError(f'truncated17E7C5C source at {p}')
        self.offset += size
        return struct.unpack_from('<' + code, self.data, p)[0]

    def fields(self, spec):
        return {key: self.num(code) for key, code in spec}

    def version(self, code, expected, native):
        p = self.offset
        v = self.num(code)
        if v != expected:
            raise Unsupported(native, p, v)
        return v

def small(r):
    start = r.offset
    v = r.version('B', 4, 25777356)
    fields = r.fields([(hex(i), 'B') for i in range(9)])
    return {'start': start, 'end': r.offset, 'version': v, 'fields': fields, 'native_reader': '0x18954cc'}

def detail(r):
    start = r.offset
    v = r.version('h', 13, 25775792)
    fields = r.fields([('0x2c', 'I'), ('0x62', 'B'), ('0x50', 'I'), ('0x54', 'I'), ('0x30', 'I'), ('0x34', 'I'), ('0x58', 'I'), ('0x63', 'B'), ('0x64', 'B'), ('0x65', 'B'), ('0x5c', 'H')])
    child = small(r)
    fields.update(r.fields([('0x38', 'I'), ('0x66', 'B'), ('0x67', 'B'), ('0x44', 'I'), ('0x48', 'I'), ('0x28', 'I'), ('0x20', 'Q'), ('0x5e', 'H'), ('0x3c', 'I'), ('0x40', 'I'), ('0x60', 'H'), ('0x4c', 'I'), ('0x18', 'Q')]))
    return {'start': start, 'end': r.offset, 'version': v, 'fields': fields, 'child': child, 'native_reader': '0x1894eb0'}

def subrecord(r):
    start = r.offset
    v = r.version('B', 7, 20049804)
    fields = r.fields([('0x68', 'I'), ('0x6c', 'B'), ('0x73', 'B'), ('0x6d', 'B'), ('0x72', 'B'), ('0x6e', 'B'), ('0x71', 'B'), ('0x6f', 'B')])
    child = detail(r)
    fields['0x70'] = r.num('B')
    return {'start': start, 'end': r.offset, 'version': v, 'fields': fields, 'child': child, 'native_reader': '0x131ef8c'}

def parse(data, start, *, source_major=3754, minor=9, limit=None):
    if (type(source_major), type(minor)) != (int, int) or (source_major, minor) != (3754, 9):
        raise ValueError('unsupported explicit source profile')
    r = Reader(data, start, len(data) if limit is None else limit)
    v = r.version('B', 8, 25066588)
    fields = r.fields([('0x2d5', 'B'), ('0x2d6', 'B'), ('0x2d7', 'B'), ('0x2d0', 'H'), ('0x2d2', 'B'), ('0x2d3', 'B'), ('0x2d4', 'B')])
    children = [subrecord(r) for _ in range(6)]
    return {'start': start, 'end': r.offset, 'version': v, 'fields': fields, 'children': children, 'native_reader': '0x17e7c5c', 'native_writer': '0x17e7ef8', 'source_profile': {'major': source_major, 'minor': minor}, 'state': 'complete_current_writer_component', 'complete_person': False}
