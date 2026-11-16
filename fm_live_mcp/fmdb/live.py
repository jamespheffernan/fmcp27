"""Live-process adapter for the property VM: a long-lived, read-only `read(address, length)`.

`open_live()` attaches through the existing Bridge, runs its build/identity check
(`Bridge._player_layout`: pinned FM27 version, plugin SHA256 and loaded Mach-O UUID)
and returns the plugin base, the verified on-disk plugin path and a `StreamReader`.

`StreamReader` wraps the helper's persistent `read-stream` (<= 16 KiB per read,
100,000 reads / 64 MiB per stream). It splits long reads, rotates to a fresh
stream before either cap, and reopens after a rejected read (the helper closes
its stream on any failure). It never writes. A faster reader exposing the same
`read(address, length) -> bytes` method can replace it.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .. import players
from ..reader import ReadStream, ReaderError

CHUNK = 16384
READ_CAP = 95_000
BYTE_CAP = 60 << 20


class StreamReader:
    def __init__(self, helper, pid):
        self.helper, self.pid = Path(helper), pid
        self._stream = None
        self._reads = self._bytes = 0
        self.total_reads = self.total_bytes = self.rotations = 0

    def _ensure(self, length):
        if (self._stream is None or self._stream.closed or self._reads + 1 > READ_CAP
                or self._bytes + length > BYTE_CAP):
            if self._stream is not None:
                self._stream.close()
                self.rotations += 1
            self._stream = ReadStream(self.helper, self.pid)
            self._reads = self._bytes = 0
        return self._stream

    def read(self, address: int, length: int) -> bytes:
        out = bytearray()
        while length > 0:
            n = min(length, CHUNK)
            stream = self._ensure(n)
            try:
                data = stream.read(address, n)
            except ReaderError:
                self._stream = None  # ReadStream closed itself; reopen on the next read
                raise
            self._reads += 1
            self._bytes += n
            self.total_reads += 1
            self.total_bytes += n
            out += data
            address += n
            length -= n
        return bytes(out)

    def close(self):
        if self._stream is not None:
            self._stream.close()
            self._stream = None


@dataclass
class LiveSession:
    bridge: object
    reader: StreamReader
    base: int
    plugin_path: Path
    pid: int

    def file_resolver(self):
        """fd -> path for the game's open files (read-only `lsof`), for PropertyVM(file_resolver=...)."""
        from .ui_vm import lsof_resolver
        return lsof_resolver(self.pid)

    def close(self):
        self.reader.close()
        self.bridge.detach()


def open_live(pid: int | None = None, helper: Path | None = None) -> LiveSession:
    """Attach, run the existing pinned-build check, and return a long-lived reader."""
    from ..bridge import Bridge
    bridge = Bridge(helper) if helper else Bridge()
    session = bridge.attach(pid)['session_id']
    with bridge._read_scope(session):
        tables = bridge._player_layout(bridge.process)
    base = tables[0] - players.RVA[0]
    plugin_path = Path(bridge.plugin_identity[0][0])
    reader = StreamReader(bridge.helper, bridge.process.pid)
    return LiveSession(bridge, reader, base, plugin_path, bridge.process.pid)
