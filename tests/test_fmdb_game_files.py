"""The VM's read-only models of the game's stdio files (ui_vm): a FILE that holds write data libc
has not flushed is read as the game would read it, the disk file with those bytes laid over it at
the kernel file offset, and refused where that cannot be established. No game needed; the libc
tests run this machine's own fopen/fwrite/fseeko/fread and compare."""
import ctypes
import os
import struct
import sys

import pytest

from fm_live_mcp.fmdb import ui_vm
from fm_live_mcp.fmdb.memory import MemoryReadError
from fm_live_mcp.fmdb.vm import _Stop

STREAM, BUFFER, OUT = 0x10000, 0x20000, 0x5000
RD, WR, RW, MBF, APP, OPT, OFF = 0x4, 0x8, 0x10, 0x80, 0x100, 0x400, 0x1000


def file_head(flags, used, *, fd=7, offset=0, bufsize=4096, r=0):
    head = bytearray(ui_vm.FILE_SIZE)
    struct.pack_into('<QiiHh', head, 0, BUFFER + used, r, bufsize - used if flags & WR else 0, flags, fd)
    struct.pack_into('<Qi', head, ui_vm.FILE_BASE, BUFFER, bufsize)
    struct.pack_into('<q', head, ui_vm.FILE_OFFSET, offset)
    return bytes(head)


class Process:
    """Memory of a 'game': one FILE and its stdio buffer; `now` is what a fresh read returns."""

    def __init__(self, head, buffered=b''):
        self.copy = {STREAM: head, BUFFER: buffered.ljust(4096, b'\0')}
        self.now = dict(self.copy)

    @staticmethod
    def _read(space, address, length):
        for start, data in space.items():
            if start <= address and address + length <= start + len(data):
                return data[address - start:address - start + length]
        raise MemoryReadError(f'{address:#x} is not mapped')

    def read(self, address, length):            # the VM's copy of the pages
        return self._read(self.copy, address, length)

    def fresh(self, address, length):           # the process now
        return self._read(self.now, address, length)


class StdioVM:
    def __init__(self, read, resolver):
        self.read, self.file_resolver, self.reader = read, resolver, None
        self._open_files, self._fpos, self.files_read, self.bytes_from_files = {}, {}, set(), 0
        self.regs, self.result, self.stored = [0] * 8, None, b''

    def _x(self, i):
        return self.regs[i]

    def _ret(self, value=0):
        self.result = value

    def write(self, address, data):
        assert address == OUT
        self.stored = bytes(data)

    def seek(self, stream, offset, whence=0):
        self.regs[:3] = [stream, offset & (2**64 - 1), whence]
        ui_vm._fseeko(self)
        return self.result

    def fread(self, stream, total):
        self.regs[:4], self.stored = [OUT, 1, total, stream], b''
        ui_vm._fread(self)
        assert self.result == len(self.stored)
        return self.stored

    def tell(self, stream):
        self.regs[0] = stream
        ui_vm._ftello(self)
        return self.result


def resolver_for(path, positions):
    """fd -> path, with position(fd) answering the next (offset, open flags) of `positions` (the
    last one repeats)."""
    calls = []

    def resolve(fd):
        return str(path)

    def position(fd):
        calls.append(fd)
        return positions[min(len(calls), len(positions)) - 1]
    resolve.position, resolve.calls = position, calls
    return resolve


@pytest.fixture()
def disk(tmp_path):
    path = tmp_path / 'retired_person_hist_archive.obs'
    path.write_bytes(bytes(range(100)))
    return path


def game(monkeypatch, disk, head, buffered=b'', positions=((100, 3),)):
    process = Process(head, buffered)
    monkeypatch.setattr(ui_vm, '_process_read', lambda vm: process.fresh)
    resolver = resolver_for(disk, list(positions))
    return StdioVM(process.read, resolver), process, resolver


def test_a_record_appended_and_not_flushed_is_read_after_the_disk_bytes(monkeypatch, disk):
    """The live case (21 Jan 2031): 68 bytes appended at the end of the file, still in the FILE."""
    record = bytes(range(200, 220))
    vm, _, _ = game(monkeypatch, disk, file_head(WR | RW | MBF | OPT | OFF, 20, offset=100), record)
    assert vm.seek(STREAM, 40) == 0
    assert vm.fread(STREAM, 131075) == bytes(range(40, 100)) + record       # short read ends after the record
    assert vm.tell(STREAM) == 120 and vm.fread(STREAM, 16) == b''             # end of the file as the game sees it
    assert vm.seek(STREAM, -5, 2) == 0 and vm.tell(STREAM) == 115             # SEEK_END counts the record
    assert vm.fread(STREAM, 16) == record[15:]
    assert vm.seek(STREAM, 10) == 0 and vm.fread(STREAM, 30) == bytes(range(10, 40))   # wholly on disk
    assert vm.bytes_from_files == 80 + 5 + 30


def test_bytes_written_inside_the_file_replace_the_disk_bytes_there(monkeypatch, disk):
    """libc holds no offset (__SOFF clear after a partial flush): the kernel's offset places them."""
    vm, _, _ = game(monkeypatch, disk, file_head(WR | RW | MBF | OPT, 10, offset=999), b'ABCDEFGHIJ',
                    positions=[(30, 3)])
    assert vm.seek(STREAM, 0) == 0
    assert vm.fread(STREAM, 500) == bytes(range(30)) + b'ABCDEFGHIJ' + bytes(range(40, 100))
    assert vm.seek(STREAM, 35) == 0 and vm.fread(STREAM, 10) == b'FGHIJ' + bytes(range(40, 45))


def test_a_write_past_the_end_of_the_file_leaves_zeros_between(monkeypatch, disk):
    vm, _, _ = game(monkeypatch, disk, file_head(WR | RW | MBF | OPT | OFF, 4, offset=110), b'WXYZ',
                    positions=[(110, 3)])
    assert vm.seek(STREAM, 95) == 0
    assert vm.fread(STREAM, 500) == bytes(range(95, 100)) + bytes(10) + b'WXYZ'


def test_a_stream_without_unflushed_write_data_reads_the_disk_and_asks_nothing(monkeypatch, disk):
    for head in (file_head(RD | RW | MBF | OPT | OFF, 60, offset=100),        # reading: _p is the read position
                 file_head(WR | RW | MBF | OPT | OFF, 0, offset=100)):         # writing, buffer empty
        vm, _, resolver = game(monkeypatch, disk, head, b'\xff' * 60)
        assert vm.seek(STREAM, 90) == 0 and vm.fread(STREAM, 50) == bytes(range(90, 100))
        assert vm.seek(STREAM, 0, 2) == 0 and vm.tell(STREAM) == 100
        assert resolver.calls == []


@pytest.mark.parametrize('flags, offset, positions, why', [
    (WR | RW | APP | OFF, 100, [(100, 3)], 'an appending or string stream'),
    (WR | RW | OFF, 100, [(100, 3 | ui_vm.O_APPEND)], 'an appending descriptor'),
    (WR | RW | OFF, 90, [(100, 3)], 'stdio and the kernel disagree on the file position'),
    (WR | RW | OFF, 100, [None], 'its file position cannot be read from the process'),
])
def test_unflushed_write_data_that_cannot_be_placed_is_refused(monkeypatch, disk, flags, offset, positions, why):
    vm, _, _ = game(monkeypatch, disk, file_head(flags, 20, offset=offset), bytes(20), positions=positions)
    with pytest.raises(_Stop) as stop:
        vm.seek(STREAM, 0)
    assert stop.value.reason == f'{ui_vm.UNFLUSHED} ({why})' and stop.value.detail == '7'


def test_unflushed_write_data_is_refused_without_a_position_or_a_live_process(monkeypatch, disk):
    head = file_head(WR | RW | OFF, 20, offset=100)
    vm, _, resolver = game(monkeypatch, disk, head, bytes(20))
    del resolver.position                                   # a resolver that only knows paths
    with pytest.raises(_Stop, match='unflushed write data .its file position cannot be read'):
        vm.seek(STREAM, 0)
    vm, _, _ = game(monkeypatch, disk, head, bytes(20))
    monkeypatch.undo()                                      # the real _process_read: this reader is no live process
    with pytest.raises(_Stop, match='unflushed write data .its file position cannot be read'):
        vm.seek(STREAM, 0)
    with pytest.raises(_Stop, match='bounds are not plausible'):
        game(monkeypatch, disk, file_head(WR | RW | OFF, 20, offset=100, bufsize=8), bytes(20))[0].seek(STREAM, 0)


def test_a_stream_that_moved_since_the_pages_were_copied_stops_the_call(monkeypatch, disk):
    head = file_head(WR | RW | MBF | OPT | OFF, 20, offset=100)
    # the game has flushed and appended another record of the same size: same _p, another _offset
    vm, process, _ = game(monkeypatch, disk, head, bytes(20))
    process.now[STREAM] = file_head(WR | RW | MBF | OPT | OFF, 20, offset=120)
    with pytest.raises(_Stop) as stop:
        vm.seek(STREAM, 0)
    assert stop.value.reason == ui_vm.FILE_MOVED
    # the buffer holds other bytes now
    vm, process, _ = game(monkeypatch, disk, head, bytes(20))
    process.now[BUFFER] = b'\x01' * 4096
    with pytest.raises(_Stop, match=ui_vm.FILE_MOVED):
        vm.seek(STREAM, 0)
    # the pages of the process cannot be read again
    vm, process, _ = game(monkeypatch, disk, head, bytes(20))
    del process.now[BUFFER]
    with pytest.raises(_Stop, match=ui_vm.FILE_MOVED):
        vm.seek(STREAM, 0)
    # the kernel offset moves while the disk is read (positions: seek twice, read once, then after the read)
    vm, _, _ = game(monkeypatch, disk, head, bytes(20), positions=[(100, 3)] * 4 + [(120, 3)])
    assert vm.seek(STREAM, 0) == 0
    with pytest.raises(_Stop, match=ui_vm.FILE_MOVED):
        vm.fread(STREAM, 500)
    assert vm._fpos[STREAM] == 0 and vm.bytes_from_files == 0


def test_inherited_position_follows_libc_on_a_stream_in_write_mode():
    from fm_live_mcp.fmdb.sources import _archive_vm as AV

    class Copy:
        def __init__(self, head):
            self.head = head

        def read(self, address, n):
            return self.head[:n]

    assert AV.inherited_position(Copy(file_head(WR | RW | OFF, 68, offset=4561)), 0) == 4629   # _offset + buffered
    assert AV.inherited_position(Copy(file_head(WR | RW | OFF, 0, offset=4561)), 0) == 4561
    assert AV.inherited_position(Copy(file_head(RD | RW | OFF, 60, offset=4096, r=96)), 0) == 4000   # _offset - _r
    assert AV.inherited_position(Copy(file_head(WR | RW, 68, offset=4561)), 0) is None        # no valid _offset


darwin = pytest.mark.skipif(sys.platform != 'darwin', reason='Darwin libc FILE layout and proc_pidfdinfo')


@darwin
def test_the_kernel_reports_this_process_file_offsets(tmp_path):
    path = tmp_path / 'f.bin'
    path.write_bytes(bytes(64))
    fd = os.open(path, os.O_RDWR)
    appending = os.open(path, os.O_WRONLY | os.O_APPEND)
    try:
        os.lseek(fd, 7, os.SEEK_SET)
        info = ui_vm._proc_fd_info(os.getpid(), fd)
        if info is False:
            pytest.skip('proc_pidfdinfo is not available here')
        assert os.path.samefile(info[0], path) and info[1] == 7 and not info[2] & ui_vm.O_APPEND
        resolver = ui_vm.lsof_resolver(os.getpid())
        assert os.path.samefile(resolver(fd), path) and resolver.position(fd)[0] == 7
        os.lseek(fd, 20, os.SEEK_SET)
        assert resolver.position(fd)[0] == 20                    # never cached
        assert resolver.position(appending)[1] & ui_vm.O_APPEND
    finally:
        os.close(fd)
        os.close(appending)


def _libc():
    libc = ctypes.CDLL(None, use_errno=True)
    libc.fopen.restype = ctypes.c_void_p
    libc.fopen.argtypes = [ctypes.c_char_p, ctypes.c_char_p]
    libc.fwrite.restype = libc.fread.restype = ctypes.c_size_t
    libc.fwrite.argtypes = libc.fread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_size_t, ctypes.c_void_p]
    libc.fseeko.argtypes = [ctypes.c_void_p, ctypes.c_longlong, ctypes.c_int]
    libc.fclose.argtypes = [ctypes.c_void_p]
    return libc


@darwin
@pytest.mark.parametrize('case, start, written, expect_soff', [
    ('a record appended at the end', 5000, 68, True),
    ('bytes written inside the file', 1000, 300, True),
    ('a write larger than the buffer, part flushed', 100, None, False),          # the buffer's size + 2508
    ('a write past the end of the file', 5200, 40, True),
])
def test_the_model_reads_what_libc_then_reads(tmp_path, monkeypatch, case, start, written, expect_soff):
    """This machine's libc as the game: fopen r+, fseeko, fwrite, no flush. The model reads this
    process's FILE and buffer as it reads the game's; libc's own fseeko + fread on the same FILE
    (which flushes first) must then return the same bytes."""
    resolver = ui_vm.lsof_resolver(os.getpid())
    path = tmp_path / 'archive.obs'
    path.write_bytes(bytes(i * 7 % 251 for i in range(5000)) * (1 if written else 40))
    libc = _libc()
    stream = libc.fopen(str(path).encode(), b'r+')
    assert stream
    try:
        assert libc.fseeko(stream, start, 0) == 0
        if written is None:                   # libc writes whole buffers through and keeps the rest
            written = struct.unpack_from('<i', ctypes.string_at(stream, ui_vm.FILE_SIZE), ui_vm.FILE_BASE + 8)[0] + 2508
        payload = bytes((i * 13 + 5) % 256 for i in range(written))
        assert libc.fwrite(payload, 1, written, stream) == written
        head = ctypes.string_at(stream, ui_vm.FILE_SIZE)
        flags, fd = struct.unpack_from('<Hh', head, ui_vm.FILE_FLAGS)
        if resolver.position(fd) is None:
            pytest.skip('proc_pidfdinfo is not available here')
        pending = struct.unpack_from('<Q', head, 0)[0] - struct.unpack_from('<Q', head, ui_vm.FILE_BASE)[0]
        assert flags & ui_vm.SWR and 0 < pending <= written and bool(flags & ui_vm.SOFF) == expect_soff, case
        before = path.read_bytes()
        assert before[start + written - pending:start + written] != payload[-pending:]   # not on disk yet
        monkeypatch.setattr(ui_vm, '_process_read', lambda vm: ctypes.string_at)
        vm = StdioVM(ctypes.string_at, resolver)
        assert vm.seek(stream, 0, 2) == 0
        size = vm.tell(stream)
        assert vm.seek(stream, 0) == 0
        modelled = vm.fread(stream, 1 << 20)
        assert vm.seek(stream, max(start - 10, 0)) == 0
        part = vm.fread(stream, 50)
        # now libc itself, on the same FILE: the seek flushes, the read returns the file
        assert libc.fseeko(stream, 0, 0) == 0
        buffer = ctypes.create_string_buffer(1 << 20)
        count = libc.fread(buffer, 1, 1 << 20, stream)
        got = buffer.raw[:count]
    finally:
        libc.fclose(stream)
    assert got == path.read_bytes() and len(got) == max(len(before), start + written)
    assert modelled == got and size == len(got), case
    assert part == got[max(start - 10, 0):max(start - 10, 0) + 50]


# ---------------------------------------------------------------------- readers with their own descriptor
def test_bytes_laid_over_a_pread(monkeypatch):
    """match_archive and live_match_backing pread the disk file themselves; stdio_file.lay_over
    gives what the game would read there."""
    from fm_live_mcp.fmdb import stdio_file as sf
    disk = bytes(range(100))
    inside = (30, b'ABCDEFGHIJ')
    assert sf.lay_over(disk[20:50], 20, 30, 100, inside) == disk[20:30] + b'ABCDEFGHIJ' + disk[40:50]
    assert sf.lay_over(disk[0:20], 0, 20, 100, inside) == disk[0:20]                # no overlap
    assert sf.lay_over(disk[35:100], 35, 500, 100, inside) == b'FGHIJ' + disk[40:]   # short read at the end
    appended = (100, b'WXYZ')
    assert sf.size_with(100, appended) == 104 and sf.size_with(100, None) == 100
    assert sf.lay_over(disk[90:], 90, 14, 100, appended) == disk[90:] + b'WXYZ'
    assert sf.lay_over(b'', 100, 4, 100, appended) == b'WXYZ' and sf.lay_over(b'', 104, 4, 100, appended) == b''
    assert sf.lay_over(disk[90:], 90, 50, 100, (104, b'!')) == disk[90:] + bytes(4) + b'!'
    assert sf.lay_over(disk[5:9], 5, 4, 100, None) == disk[5:9]


def test_a_bank_frame_that_is_not_readable_says_why_its_file_was_not_placed():
    from fm_live_mcp.fmdb import match_archive as ma
    assert ma._unreadable({}) == 'frame bounds or header invalid'
    assert ma._unreadable({'unflushed_refused': 'game file has unflushed write data (an appending descriptor)'}) == \
        'frame bounds or header invalid (game file has unflushed write data (an appending descriptor))'
    assert ma._unflushed(object(), STREAM) == (None, None)             # no process: nothing to lay over


@darwin
def test_the_newest_frame_of_a_match_bank_reads_while_part_of_it_is_in_the_buffer(tmp_path):
    """The live case of 21 Jan 2031 (pks_3.obs): the game rewrote its newest statistics frame inside
    the bank file; libc passed whole buffers through (__SOFF clear) and kept the last 2,508 bytes,
    with older bytes still on disk in their place. match_archive reads the disk file from its own
    descriptor. With this machine's libc as the game: the frame is unreadable from the disk alone,
    reads with the buffered bytes laid over at the kernel's offset of the writer's descriptor, and
    is the same frame once libc has flushed."""
    import compression.zstd as zstd
    from types import SimpleNamespace
    from fm_live_mcp.fmdb import match_archive as ma, stdio_file as sf

    raws = [bytes((i * k) % 251 for i in range(3000)) for k in (3, 5)] + [os.urandom(9000)]
    # the game's frames carry zstd's content checksum (frame header descriptor 0x04), so bytes that
    # are not the frame's fail to decompress instead of giving other statistics
    frames = [zstd.compress(raw, options={zstd.CompressionParameter.checksum_flag: 1}) for raw in raws]
    assert all(frame[4] & 0x04 for frame in frames)
    header = bytes.fromhex('030173626f2e0100')
    older = os.urandom(30000)                              # what the file held there before the rewrite
    path = tmp_path / 'pks_3.obs'
    path.write_bytes(header + frames[0] + frames[1] + older)
    start = len(header) + len(frames[0]) + len(frames[1])
    entries, at = [], 0
    for key, frame in enumerate(frames, 1):
        entries.append((key, at, len(frame)))
        at += len(frame)
    libc = _libc()
    stream = libc.fopen(str(path).encode(), b'r+')
    assert stream
    try:
        assert libc.fseeko(stream, start, 0) == 0 and libc.fwrite(frames[2], 1, len(frames[2]), stream) == len(frames[2])
        head = ctypes.string_at(stream, sf.FILE_SIZE)
        flags, fd = struct.unpack_from('<Hh', head, sf.FILE_FLAGS)
        if sf.fd_info(os.getpid(), fd) is False:
            pytest.skip('proc_pidfdinfo is not available here')
        engine = SimpleNamespace(pid=os.getpid(), read=ctypes.string_at)
        unflushed, refused = ma._unflushed(engine, stream)
        buffered = struct.unpack_from('<Q', head, 0)[0] - struct.unpack_from('<Q', head, sf.FILE_BASE)[0]
        assert refused is None and flags & sf.SWR and not flags & sf.SOFF        # part passed through
        assert unflushed == (start + len(frames[2]) - buffered, frames[2][-buffered:]) and 0 < buffered < len(frames[2])
        bank = {'ordinal': 3, 'path': str(path), 'origin': len(header), 'entries': entries}
        assert list(ma.read_frames(bank)) == [(1, raws[0]), (2, raws[1]), (3, None)]          # the disk alone
        assert list(ma.read_frames({**bank, 'unflushed': unflushed})) == [(1, raws[0]), (2, raws[1]), (3, raws[2])]
        assert libc.fseeko(stream, 0, 0) == 0                                      # libc flushes
        assert ma._unflushed(engine, stream) == (None, None)
        assert list(ma.read_frames(bank)) == [(1, raws[0]), (2, raws[1]), (3, raws[2])]
        # the overlay taken before the flush lays the same bytes over the same place: nothing changes
        assert list(ma.read_frames({**bank, 'unflushed': unflushed})) == [(1, raws[0]), (2, raws[1]), (3, raws[2])]
    finally:
        libc.fclose(stream)


@darwin
def test_a_frame_appended_past_the_end_of_the_bank_reads_from_the_buffer(tmp_path):
    import compression.zstd as zstd
    from types import SimpleNamespace
    from fm_live_mcp.fmdb import match_archive as ma, stdio_file as sf

    raws = [b'first frame ' * 40, b'newest frame ' * 60]
    frames = [zstd.compress(raw, options={zstd.CompressionParameter.checksum_flag: 1}) for raw in raws]
    path = tmp_path / 'pks_0.obs'
    path.write_bytes(bytes(8) + frames[0])
    bank = {'ordinal': 0, 'path': str(path), 'origin': 8,
            'entries': [(1, 0, len(frames[0])), (2, len(frames[0]), len(frames[1]))]}
    libc = _libc()
    stream = libc.fopen(str(path).encode(), b'r+')
    assert stream
    try:
        assert libc.fseeko(stream, 0, 2) == 0 and libc.fwrite(frames[1], 1, len(frames[1]), stream) == len(frames[1])
        if sf.fd_info(os.getpid(), struct.unpack_from('<h', ctypes.string_at(stream, sf.FILE_SIZE), sf.FILE_FD)[0]) is False:
            pytest.skip('proc_pidfdinfo is not available here')
        unflushed, refused = ma._unflushed(SimpleNamespace(pid=os.getpid(), read=ctypes.string_at), stream)
        assert refused is None and unflushed == (8 + len(frames[0]), frames[1])
        assert list(ma.read_frames(bank)) == [(1, raws[0]), (2, None)]             # past the end of the disk file
        assert list(ma.read_frames({**bank, 'unflushed': unflushed})) == [(1, raws[0]), (2, raws[1])]
    finally:
        libc.fclose(stream)
