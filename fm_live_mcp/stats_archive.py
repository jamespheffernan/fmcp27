"""Bind a player's indexed archive to the game's active read-only data file."""
from contextlib import contextmanager
from ._os_compat import change_time_ns, open_fd, pread, O_CLOEXEC, O_NOFOLLOW, O_NONBLOCK
import os
from pathlib import Path
import stat
import struct
import subprocess

from . import players, world

MANAGER_ROOT = 0x56A83C8
MANAGER_TYPE = (0x55DE5E8, b'20PLAYER_STATS_MANAGER')
STREAM_TABLE = 0x5698178
FILE_STREAM_TABLE = 0x569E380
RECORD_WIDTH = 168
VERSION = 7
HEADER = bytes.fromhex('0301746d632e0700')
MAX_PLAYERS = 2_000_000
MAX_ENTRIES = 4096
SOURCE_COVERAGE = 'indexed_disk_stats_archive_only_no_current_or_starting_history'
NATIVE_SPANS = {
    0xF2037C: '080340f9085941f9e00318aa00013fd6e81240f9080100b4e20300aa010540f9e10000b4420040b9e00301912322009408000014ff1f00f947010014010140f9a11600b4e003019103008052e9260094e82340f9',
    0xF26C84: '8403003400158052a81eef94f80300aaa30240f9e10317aae20316aae40314aa2500805206158052f1150b94780200f9c83c02f008a1199108c1bf3848040036c03c02f000c01891010e80524dbbd094f80300aae10317aae20316aae30315aae40314aa4d000094780a00f910000014c83c02f008a1199108c1bf3888040036c03c02f000c01891010e80523dbbd094f80300aae10317aae20316aae30315aae40314aa3d000094780600f9',
    0xCA4794: '080040f908010bd1080140f90800088b00f10291c0035fd6',
    0x11EE748: '280040b95f040031600000541f01026b8c010054087d40931f050031400b0054099c80b90a9442395f010071ea179f1a29492a8b0a09c99a48a1099b480a00b4',
    0x11EE8C4: '08008012280000b9',
    0xF2A214: 'c80280b9e820f83789aa47a94a0109cb4afd4393ebf301b26b5595f24a7d0b9b5f0108ebe91f00540a03805218252a9b082740a91f0109eb401f0054',
    0xF2A2D8: '280340b9e80f00b9829a40b9e1330091e00314aa13110b94e10f40b9e114f837a00240f9080040f9081140f900013fd640140035',
    0xF2A028: 'c80240b91f05003120300054',
    0x437F014: 'e80300aa001440f91f0400b140000054c0035fd6000d40f9e00100b4f44fbea9fd7b01a9fd430091f30308aa080040f9080940f900013fd6',
    0x437F114: '081440f9f60302aa1f0500b140010054691a40f9080109cb09fd7f930a01098a0801298a',
}


def verify_native(read, base):
    for rva, hex_bytes in NATIVE_SPANS.items():
        expected = bytes.fromhex(hex_bytes)
        if read(base+rva, len(expected)) != expected:
            raise ValueError('Player statistics archive native route changed')


def _pointer(read, address, *, nullable=False):
    value = players.u64(read(address, 8))
    if value == 0 and nullable:
        return value
    if value < 4096 or value % 8:
        raise ValueError('Invalid statistics archive pointer')
    return value


def _manager_type(read, base, address):
    rva, name = MANAGER_TYPE
    if _pointer(read, address) != base+rva:
        raise ValueError('Unexpected player statistics manager type')
    displacement, info = struct.unpack('<qQ', read(base+rva-16, 16))
    if displacement != 0:
        raise ValueError('Unexpected player statistics manager displacement')
    text = players.u64(read(info+8, 8))
    if read(text, len(name)+1) != name+b'\0':
        raise ValueError('Unexpected player statistics manager RTTI')


def _header(read, address, stride, limit):
    start, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if start == end == capacity == 0:
        return start, 0
    if (start < 4096 or start % 8 or not start <= end <= capacity
            or (end-start) % stride or (capacity-start) % stride
            or capacity-start > stride*limit):
        raise ValueError('Invalid statistics archive index vector bounds')
    return start, (end-start)//stride


def _active_file(pid, descriptor):
    """Resolve just the game's one fd; include inode/device to detect path swaps."""
    try:
        result = subprocess.run(
            ['lsof', '-a', '-p', str(pid), '-d', str(descriptor), '-FpfDin'],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=3, text=True, encoding='utf-8')
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        raise ValueError('Cannot resolve the active statistics archive descriptor') from exc
    if len(result.stdout) > 16384:
        raise ValueError('Statistics archive descriptor listing exceeds bound')
    fields = {}
    for line in result.stdout.splitlines():
        if not line or line[0] not in 'pfDin':
            raise ValueError('Unexpected statistics archive descriptor listing')
        if line[0] in fields:
            raise ValueError('Ambiguous statistics archive descriptor binding')
        fields[line[0]] = line[1:]
    try:
        if int(fields['p']) != pid or int(fields['f']) != descriptor:
            raise ValueError('Statistics archive descriptor identity disagrees')
        path = Path(fields['n'])
        device, inode = int(fields['D'], 16), int(fields['i'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('Invalid statistics archive descriptor binding') from exc
    if not path.is_absolute() or path.name != 'player_stats_hist_dt.cmt':
        raise ValueError('Unexpected active statistics archive filename')
    return path, device, inode


def _file_identity(value):
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, change_time_ns(value))


def _result(state, reason=None, *, width=None, version=None, encoding=None, count=None):
    return {'state': state, 'reason': reason, 'records': [], 'native_entry_count': count,
            'skipped_entries': [], 'record_width': width, 'version': version,
            'encoding': encoding, 'source_coverage': SOURCE_COVERAGE}


def _source(read, base, address, tables):
    expected = tuple(base+rva for rva in players.RVA)
    if (address < 4096 or address % 8 or tuple(tables) != expected
            or players.u64(read(address, 8)) != expected[0]):
        raise ValueError('Statistics archive supports actual players only')
    person = address+0x388
    if (players.u64(read(address+0x140, 8)) != expected[1]
            or players.u64(read(person, 8)) != expected[2]
            or int.from_bytes(read(person+8, 4), 'little') == 0xFFFFFFFF):
        raise ValueError('Statistics archive player owner type or identity changed')
    if players.u64(read(expected[2]+0x2B0, 8)) != base+0xCA4794:
        raise ValueError('Person statistics archive index getter changed')
    common_delta = struct.unpack('<q', read(expected[2]-0x2C0, 8))[0]
    if common_delta != -0x110:
        raise ValueError('Person statistics archive common-owner displacement changed')
    index = struct.unpack('<i', read(person+common_delta+0xBC, 4))[0]
    verify_native(read, base)
    if index == -1:
        return _result('no_history_index', 'native_index_minus_one', count=0), None
    if index < -1:
        return _result('no_history_index', 'native_negative_index', count=0), None
    manager = _pointer(read, base+MANAGER_ROOT, nullable=True)
    if not manager:
        return _result('unavailable', 'no_player_statistics_manager'), None
    _manager_type(read, base, manager)
    pair = _pointer(read, manager+0x20, nullable=True)
    if not pair:
        return _result('unavailable', 'no_archive_source_pair'), None
    disk, resident, supplementary = struct.unpack('<QQQ', read(pair, 24))
    for pointer in (disk, resident, supplementary):
        if pointer and (pointer < 4096 or pointer % 8):
            raise ValueError('Invalid statistics archive source selection')
    if resident:
        return _result('unavailable', 'native_resident_source_not_decoded'), None
    if not disk:
        return _result('unavailable', 'no_disk_archive_source'), None
    data = read(disk, 0xA8)
    tags = [world.string(read, players.u64(data, offset)) for offset in (8, 16, 24)]
    if tags != ['player_stats_hist_id', 'player_stats_hist_dt', 'player_stats_hist_ls']:
        raise ValueError('Player statistics archive source tags disagree')
    width = struct.unpack_from('<i', data, 0x9C)[0]
    version = struct.unpack_from('<H', data, 0xA0)[0]
    stream = _pointer(read, disk+0x50, nullable=True)
    if not stream:
        return _result('unavailable', 'disk_stream_not_resident', width=width, version=version), None
    if _pointer(read, stream) != base+STREAM_TABLE:
        raise ValueError('Unexpected statistics archive segment stream type')
    if (players.u64(read(base+STREAM_TABLE+0x10, 8)) != base+0x437F014
            or players.u64(read(base+STREAM_TABLE+0x20, 8)) != base+0x437F078):
        raise ValueError('Statistics archive segment bounds getter changed')
    flags = read(stream+12, 1)[0]
    mode = read(base+0x56D2C98, 1)[0]
    switches = list(read(base+0x56D3522, 2))
    encoding = {'stream_flags': flags, 'global_reference_mode': mode,
                'global_reference_switches': switches, 'fixed_width_mode': data[0xA5],
                'supplementary_cache_present': bool(supplementary)}
    if width != RECORD_WIDTH or version != VERSION:
        return _result('unavailable', 'unsupported_archive_width_or_version',
                       width=width, version=version, encoding=encoding), None
    if (flags, mode, switches, data[0xA5]) != (2, 0, [0, 0], 1):
        return _result('unavailable', 'unsupported_archive_reference_or_stride_encoding',
                       width=width, version=version, encoding=encoding), None
    native_size = struct.unpack_from('<i', data, 0x98)[0]
    if native_size == 0:
        return _result('unavailable', 'native_stream_size_not_materialized',
                       width=width, version=version, encoding=encoding), None
    if native_size < -1:
        raise ValueError('Invalid statistics archive native stream size')
    origin = players.u64(read(stream+0x20, 8))
    if origin != len(HEADER):
        raise ValueError('Unexpected statistics archive data origin')
    segment_length = struct.unpack('<q', read(stream+0x28, 8))[0]
    if segment_length < -1:
        raise ValueError('Invalid statistics archive segment length')
    underlying = _pointer(read, stream+0x18)
    if _pointer(read, underlying) != base+FILE_STREAM_TABLE:
        raise ValueError('Unexpected statistics archive file stream type')
    owner = _pointer(read, underlying+0x18)
    file_pointer = _pointer(read, owner+8)
    descriptor = struct.unpack('<h', read(file_pointer+0x12, 2))[0]
    if descriptor < 0:
        raise ValueError('Statistics archive descriptor is closed')
    start, count = _header(read, disk+0x78, 24, MAX_PLAYERS)
    if index >= count:
        raise ValueError('Player statistics archive index is outside its owner table')
    offsets, entry_count = _header(read, start+index*24, 4, MAX_ENTRIES)
    values = struct.unpack(f'<{entry_count}i', read(offsets, entry_count*4)) if entry_count else ()
    result = _result('decoded', width=width, version=version, encoding=encoding, count=entry_count)
    return result, (descriptor, origin, values, native_size, segment_length)


@contextmanager
def open_player_archive(read, base: int, address: int, tables: tuple, pid: int):
    """Yield private raw rows; accept them only after this context exits cleanly."""
    if type(pid) is not int or pid <= 0:
        raise ValueError('Invalid statistics archive process ID')
    observed = world.ReadSet(read)
    result, source = _source(observed, base, address, tables)
    if source is None:
        yield result
        observed.verify()
        return
    descriptor, origin, offsets, native_size, segment_length = source
    binding = _active_file(pid, descriptor)
    path, device, inode = binding
    descriptor_owned = None
    yielding = False
    try:
        try:
            descriptor_owned = open_fd(path, os.O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOFOLLOW)
            initial = os.fstat(descriptor_owned)
            if not stat.S_ISREG(initial.st_mode) or (initial.st_dev, initial.st_ino) != (device, inode):
                raise ValueError('Active statistics archive file identity disagrees')
            header = pread(descriptor_owned, len(HEADER), 0)
            if header != HEADER:
                raise ValueError('Unsupported statistics archive magic or header version')
            consumed = [(0, header)]
            for index, offset in enumerate(offsets):
                if offset < 0:
                    result['skipped_entries'].append({'entry_index': index, 'native_offset': offset,
                                                     'reason': 'native_negative_offset_skipped'})
                    continue
                if (offset % RECORD_WIDTH or origin+offset+RECORD_WIDTH > initial.st_size
                        or (native_size != -1 and offset > native_size)
                        or (segment_length != -1 and offset+RECORD_WIDTH > segment_length)):
                    raise ValueError('Statistics archive offset is misaligned or truncated')
                raw = pread(descriptor_owned, RECORD_WIDTH, origin+offset)
                if len(raw) != RECORD_WIDTH:
                    raise ValueError('Incomplete statistics archive record read')
                if raw[0] != 0 or struct.unpack_from('<h', raw, 5)[0] == -2:
                    raise ValueError('Unsupported variable-width statistics archive reference transport')
                result['records'].append({'native_offset': offset, 'raw': raw})
                consumed.append((origin+offset, raw))
            yielding = True
            yield result
            yielding = False
            observed.verify()
            if _active_file(pid, descriptor) != binding:
                raise ValueError('Active statistics archive descriptor binding changed')
            if _file_identity(os.fstat(descriptor_owned)) != _file_identity(initial):
                raise ValueError('Statistics archive file changed during read')
            if _file_identity(path.stat(follow_symlinks=False)) != _file_identity(initial):
                raise ValueError('Statistics archive path binding changed')
            for offset, raw in consumed:
                if pread(descriptor_owned, len(raw), offset) != raw:
                    raise ValueError('Consumed statistics archive bytes changed')
            if _file_identity(os.fstat(descriptor_owned)) != _file_identity(initial):
                raise ValueError('Statistics archive file changed during verification')
        except OSError as exc:
            if yielding:
                raise
            raise ValueError('Statistics archive file could not be read or verified') from exc
    finally:
        if descriptor_owned is not None:
            try:
                os.close(descriptor_owned)
            except OSError:
                pass
