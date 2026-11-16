"""A private PropertyVM that may also read the game's own history archives.

The game keeps history it does not hold in memory (archived fixture groups, competition
history, player/staff/injury histories, award history) in files it writes to its
`Temporary` directory (`fixture_group_archive.obs`, `competition_archive.obs`, `*_hist_dt.cmt`,
...) and reads back on demand through stdio (`fseeko`/`fread` on a FILE* it keeps open).
The shared VM only lets the game's code read `.fmf` data files; this VM additionally lets the
game's own loaders read those archive files, read-only, through the same stdio models
(`ui_vm`: the FILE* descriptor is mapped to its path with lsof and opened read-only here; a
stream with unflushed write data is read with those bytes laid over the disk file, or refused
where their place is not established). Nothing is written to the game or to the files.
"""
from __future__ import annotations

from pathlib import Path
import struct

from .. import ui_vm
from ..vm import FILE_EXTERNALS, PropertyVM, _Stop

TEMPORARY = Path.home() / 'Library/Application Support/Sports Interactive/Football Manager 27/Temporary'
ARCHIVE_SUFFIXES = ('.obs', '.cmt')
_MODELS = {'_fseeko': ui_vm._fseeko, '_fseek': ui_vm._fseeko, '_ftello': ui_vm._ftello, '_ftell': ui_vm._ftello,
           '_fread': ui_vm._fread, '_ferror': ui_vm._ferror}


def allowed(path) -> bool:
    if not path:
        return False
    p = Path(path)
    return p.suffix == '.fmf' or (p.suffix in ARCHIVE_SUFFIXES and p.parent == TEMPORARY)


# libc FILE (Darwin arm64): _p +0x00, _r +0x08, _flags +0x10, _bf._base +0x18, _ur +0x70, _offset +0x90
FILE_R, FILE_FLAGS_AT, FILE_UR, FILE_OFFSET, SOFF = 0x08, 0x10, 0x70, 0x90, 0x1000
FILE_P, FILE_BASE, SWR = 0x00, 0x18, 0x0008


def inherited_position(vm, stream):
    """The logical position of a game FILE that the VM has not seeked: libc's own rule (ftello:
    _offset while __SOFF says it is valid, less _r on a stream that is reading, plus the bytes
    buffered and not flushed on a stream that is writing), or None. The game's FILE_INPUT_STREAM
    seek (0x4429B9C) skips fseeko when its cached position already equals the target, so a load
    can start with an fread on a stream the VM never positioned; the game's fread continues from
    exactly this position."""
    head = vm.read(stream, 0x98)
    flags = struct.unpack_from('<H', head, FILE_FLAGS_AT)[0]
    if not flags & SOFF or struct.unpack_from('<i', head, FILE_UR)[0]:
        return None
    offset = struct.unpack_from('<q', head, FILE_OFFSET)[0]
    if flags & SWR:
        p, base = struct.unpack_from('<Q', head, FILE_P)[0], struct.unpack_from('<Q', head, FILE_BASE)[0]
        offset += p - base if p else 0
    else:
        offset -= struct.unpack_from('<i', head, FILE_R)[0]
    return offset if offset >= 0 else None


class _ArchiveFiles:
    def call(self, address, args=(), *, fargs=()):
        """One retry on fresh pages after an unreadable-memory stop. 12 Nov 2026: 1 of 40 loads of the
        two largest archived groups stopped on unreadable live memory after 0.2 s while the other 39
        agreed byte for byte; the game had remapped a page between the copies (REFUSALS.md, stale
        pages). The retry starts from the same VM state (`call` restores it) on current pages."""
        try:
            return super().call(address, args, fargs=fargs)
        except _Stop as stop:
            refresh = getattr(self, 'refresh_pages', None)
            if 'unreadable live memory' not in str(stop.reason) or refresh is None:
                raise
            refresh()
            self.unreadable_retries = getattr(self, 'unreadable_retries', 0) + 1
            return super().call(address, args, fargs=fargs)

    def _external(self, name):
        if name in FILE_EXTERNALS and self.file_resolver is not None:
            drain = getattr(self, '_drain_externals', None)
            if drain is not None:
                drain()
            stream = self._x(3) if name == '_fread' else self._x(0)
            fd = struct.unpack('<h', self.read(stream + 0x12, 2))[0]
            path = self.file_resolver(fd)
            if not allowed(path):
                raise _Stop('game file outside the allowed data and archive files', str(path))
            if name == '_fread' and stream not in self._fpos:
                position = inherited_position(self, stream)
                if position is not None:
                    self._fpos[stream] = position
                    self.inherited_positions = getattr(self, 'inherited_positions', 0) + 1
            self.stubbed[name] += 1
            if self._call is not None:
                self._call.externals.append(name)
            _MODELS[name](self)
            return
        super()._external(name)


class ArchiveVM(_ArchiveFiles, PropertyVM):
    pass


def archive_vm(engine, *, fast=False, **kwargs):
    """An archive-reading VM over the engine's memory. Classic PropertyVM by default: on 11 Nov 2026
    the FastVM variant loaded some archived groups short (2026: 1,001 records from 54 groups
    where the classic VM read 33,852 from 66) once the game had swapped its resident archived
    years, so it is used only when asked for."""
    from ..engine import _VMReader
    kwargs.setdefault('file_resolver', engine.file_resolver())
    cls = ArchiveVM
    if fast:
        from .. import fastvm
        if fastvm.available():
            cls = type('ArchiveFastVM', (_ArchiveFiles, fastvm.FastVM), {})
    return cls(_VMReader(engine.memory), engine.base, engine.image, **kwargs)
