"""A stdio FILE of the game, as the game would read the file behind it now.

The game appends to its Temporary files with fwrite and does not flush: the last bytes stay in
the FILE's buffer (__SWR set, [_bf._base, _p)) until the game's next seek, read, flush or close
on that FILE, so the file on disk lacks them or holds older bytes in their place. libc writes
them at the descriptor's current file offset before anything else: fseeko flushes before it
seeks (__sflush, then _sseek) and a read on a stream in write mode flushes before it fills
(__srefill). What the game would read is therefore the disk file with those bytes laid over it
at the kernel's file offset.

`unflushed_write` returns that offset and those bytes only where they are established: the offset
comes from the kernel (proc_pidfdinfo), must equal the FILE's own _offset when libc holds one
(__SOFF), and the FILE, its buffer and the offset are read a second time and must not have moved.
Appending streams (__SAPP, O_APPEND: the bytes would go to the end of the file) and string
streams are not placed. tests/test_fmdb_game_files.py runs this machine's libc as the game and
compares. Used by the VM's stdio models (ui_vm) and by the readers that pread a game file from
their own descriptor (match_archive, live_match_backing). Nothing is written anywhere.
"""
from __future__ import annotations

import struct

# libc FILE (Darwin arm64)
FILE_P, FILE_FLAGS, FILE_FD, FILE_BASE, FILE_OFFSET, FILE_SIZE = 0x00, 0x10, 0x12, 0x18, 0x90, 0x98
SWR, SAPP, SSTR, SOFF = 0x0008, 0x0100, 0x0200, 0x1000
O_APPEND = 0x0008
UNFLUSHED = 'game file has unflushed write data'
FILE_MOVED = 'game file changed while it was read'

PROC_PIDFDVNODEPATHINFO = 2
_VNODE_FDINFO_SIZE, _VNODE_MODE_OFFSET, _VNODE_PATH_OFFSET = 1200, 28, 176   # struct vnode_fdinfowithpath
_libproc = None


class NotPlaced(Exception):
    """The FILE holds unflushed write data whose place in the file is not established."""

    def __init__(self, why, fd):
        super().__init__(f'{UNFLUSHED} ({why})')
        self.reason, self.fd = f'{UNFLUSHED} ({why})', fd


class Moved(Exception):
    """The FILE, its buffer or its file offset changed between the two reads."""

    def __init__(self, fd):
        super().__init__(FILE_MOVED)
        self.reason, self.fd = FILE_MOVED, fd


def fd_info(pid, fd):
    """(path, kernel file offset, open flags) of a regular file open in another process as
    descriptor `fd`, through proc_pidfdinfo (what lsof calls; microseconds instead of a
    subprocess). None: not a regular file; False: the call is not available or was refused."""
    import ctypes
    global _libproc
    try:
        if _libproc is None:
            _libproc = ctypes.CDLL('/usr/lib/libproc.dylib', use_errno=True)
            _libproc.proc_pidfdinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                                ctypes.c_int]
        buf = ctypes.create_string_buffer(_VNODE_FDINFO_SIZE)
        got = _libproc.proc_pidfdinfo(pid, fd, PROC_PIDFDVNODEPATHINFO, buf, _VNODE_FDINFO_SIZE)
    except (OSError, AttributeError):
        return False
    if got != _VNODE_FDINFO_SIZE:
        return False
    openflags, _status, offset = struct.unpack_from('<IIq', buf.raw, 0)          # struct proc_fileinfo
    mode = struct.unpack_from('<H', buf.raw, _VNODE_MODE_OFFSET)[0]
    path = buf.raw[_VNODE_PATH_OFFSET:].split(b'\0', 1)[0].decode('utf-8', 'replace')
    if (mode & 0o170000) != 0o100000 or not path.startswith('/'):
        return None
    return path, offset, openflags


def fd_position(pid):
    """position(fd) -> (kernel file offset, open flags) of the process's descriptor now, or None."""
    def position(fd):
        info = fd_info(pid, fd)
        return (info[1], info[2]) if info else None
    return position


def unflushed_write(read, fresh, position, stream, head=None):
    """(file offset, bytes) of what the game has written to the FILE at `stream` that libc has
    not passed to the kernel yet, or None when the FILE holds none.

    `read(address, length)` is the caller's view of the process (a page copy or the process
    itself), `fresh` reads the process now, `position(fd)` is the kernel's (file offset, open
    flags) now. Raises NotPlaced where the place of the bytes is not established and Moved where
    the two reads differ; `fresh` may raise its own read error, which the caller treats as Moved."""
    if head is None:
        head = read(stream, FILE_SIZE)
    p, = struct.unpack_from('<Q', head, FILE_P)
    flags, fd = struct.unpack_from('<Hh', head, FILE_FLAGS)
    base, size = struct.unpack_from('<Qi', head, FILE_BASE)
    if not flags & SWR or p == base:
        return None
    count = p - base
    if flags & (SAPP | SSTR):
        raise NotPlaced('an appending or string stream', fd)
    if not 0 < count <= size:
        raise NotPlaced('its buffer bounds are not plausible', fd)
    where = position(fd) if position is not None and fresh is not None else None
    if where is None:
        raise NotPlaced('its file position cannot be read from the process', fd)
    offset, openflags = where
    if fresh(stream, FILE_SIZE) != head:        # the caller's copy of the FILE is the FILE now
        raise Moved(fd)
    if openflags & O_APPEND:
        raise NotPlaced('an appending descriptor', fd)
    if flags & SOFF and struct.unpack_from('<q', head, FILE_OFFSET)[0] != offset:
        raise NotPlaced('stdio and the kernel disagree on the file position', fd)
    data = read(base, count)
    if fresh(base, count) != data or fresh(stream, FILE_SIZE) != head or position(fd) != where:
        raise Moved(fd)
    return offset, data


def size_with(disk_size, unflushed):
    """Size of the file as the game would see it: the disk size, or the end of the unflushed write."""
    if unflushed is None:
        return disk_size
    return max(disk_size, unflushed[0] + len(unflushed[1]))


def lay_over(data, at, total, disk_size, unflushed):
    """What the game would read for `total` bytes at file offset `at`: `data` (the bytes the disk
    gave there) with the unflushed write laid over it. A gap between the end of the disk file and
    the write reads as zeros."""
    if unflushed is None:
        return data
    offset, pending = unflushed
    end = min(at + total, size_with(disk_size, unflushed))
    if end <= at:
        return b''
    out = bytearray(end - at)
    out[:len(data)] = data[:len(out)]
    low, high = max(at, offset), min(end, offset + len(pending))
    if low < high:
        out[low - at:high - at] = pending[low - offset:high - offset]
    return bytes(out)
