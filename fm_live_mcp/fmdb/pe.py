"""A Windows PE32+ (x86-64) image, read from its file or from a process that has it loaded.

This is the image half of the Windows platform model (part 1 of ``platform_model.py``): headers,
sections, bytes by RVA, base relocations (the pointer slots), imports, exports, the function
table from the exception directory, and the CodeView record that identifies the build.

Two layouts are read with the same code:

* file layout (``PEImage.from_file``): section bytes sit at their file offsets;
* mapped layout (``PEImage.from_memory``): the image as the loader placed it, where an RVA is an
  offset from the load address. This is the layout to use when the file on disk is protected
  and only the loaded image holds the real code.

``compare_with_memory`` checks a file against a loaded image section by section, after applying
the file's relocations for the load address; it is how the two layouts are reconciled.
"""

from __future__ import annotations

import hashlib
import mmap
import struct
from array import array
from dataclasses import dataclass
from pathlib import Path

MACHINE_AMD64 = 0x8664
PE32_PLUS = 0x20B

DIR_EXPORT, DIR_IMPORT, DIR_RESOURCE, DIR_EXCEPTION = 0, 1, 2, 3
DIR_BASERELOC, DIR_DEBUG, DIR_TLS, DIR_LOAD_CONFIG, DIR_IAT, DIR_DELAY_IMPORT = 5, 6, 9, 10, 12, 13

SCN_CODE = 0x00000020
SCN_EXECUTE, SCN_READ, SCN_WRITE = 0x20000000, 0x40000000, 0x80000000

RELOC_ABSOLUTE, RELOC_DIR64 = 0, 10
DEBUG_CODEVIEW = 2

_U16, _U32, _U64 = struct.Struct("<H"), struct.Struct("<I"), struct.Struct("<Q")
_RUNTIME_FUNCTION = struct.Struct("<III")


class PEError(ValueError):
    """The bytes are not a PE32+ x86-64 image, or a table in it is malformed."""


@dataclass(frozen=True)
class Section:
    name: str
    rva: int
    virtual_size: int
    file_offset: int
    file_size: int
    characteristics: int

    @property
    def end(self) -> int:
        return self.rva + self.virtual_size

    @property
    def executable(self) -> bool:
        return bool(self.characteristics & SCN_EXECUTE)

    @property
    def writable(self) -> bool:
        return bool(self.characteristics & SCN_WRITE)

    def contains(self, rva: int) -> bool:
        return self.rva <= rva < self.end


@dataclass(frozen=True)
class Import:
    """One imported function: the slot at `slot` holds its address once the image is loaded."""

    library: str
    name: str | None
    ordinal: int | None
    slot: int


@dataclass(frozen=True)
class CodeView:
    """The debug record that names a build: the PDB's GUID and age, and its path."""

    guid: str
    age: int
    pdb: str

    @property
    def key(self) -> str:
        return f"{self.guid}{self.age:x}"


@dataclass(frozen=True)
class SectionMatch:
    """How one section of a file compares with the loaded image."""

    name: str
    size: int
    same_bytes: int
    pages: int
    same_pages: int
    unreadable_pages: int
    executable: bool
    writable: bool

    @property
    def identical(self) -> bool:
        return self.same_bytes == self.size and not self.unreadable_pages


class PEImage:
    """One PE32+ image. `data` is the whole file (file layout) or the whole mapped image."""

    def __init__(self, data, *, mapped: bool = False, path: Path | None = None):
        self.data = data
        self.mapped = mapped
        self.path = path
        self._sha256: str | None = None
        self._relocations: array | None = None
        self._functions: list[tuple[int, int]] | None = None
        self._exports: dict[str, int] | None = None
        self._imports: list[Import] | None = None
        if len(data) < 0x40 or bytes(data[:2]) != b"MZ":
            raise PEError("not a PE image: no MZ header")
        pe = _U32.unpack_from(data, 0x3C)[0]
        if pe + 24 > len(data) or bytes(data[pe:pe + 4]) != b"PE\0\0":
            raise PEError("not a PE image: no PE signature")
        self.machine, count, self.timestamp, _, _, optional_size, self.characteristics = \
            struct.unpack_from("<HHIIIHH", data, pe + 4)
        optional = pe + 24
        if self.machine != MACHINE_AMD64 or _U16.unpack_from(data, optional)[0] != PE32_PLUS:
            raise PEError(f"not an x86-64 PE32+ image (machine {self.machine:#x})")
        self.entry_point = _U32.unpack_from(data, optional + 16)[0]
        self.image_base = _U64.unpack_from(data, optional + 24)[0]
        self.section_alignment, self.file_alignment = struct.unpack_from("<II", data, optional + 32)
        self.size_of_image, self.size_of_headers, self.checksum = struct.unpack_from("<III", data, optional + 56)
        directories = min(_U32.unpack_from(data, optional + 108)[0], 16)
        self.directories = [struct.unpack_from("<II", data, optional + 112 + 8 * i) for i in range(directories)]
        table = optional + optional_size
        self.sections: list[Section] = []
        for i in range(count):
            raw = bytes(data[table + 40 * i:table + 40 * i + 40])
            if len(raw) < 40:
                raise PEError("section table runs past the end of the image")
            virtual_size, rva, file_size, file_offset = struct.unpack_from("<IIII", raw, 8)
            self.sections.append(Section(raw[:8].rstrip(b"\0").decode("latin-1"), rva,
                                         virtual_size or file_size, file_offset, file_size,
                                         _U32.unpack_from(raw, 36)[0]))

    # -- construction ------------------------------------------------------------

    @classmethod
    def from_file(cls, path) -> "PEImage":
        path = Path(path)
        with path.open("rb") as stream:
            data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        return cls(data, path=path)

    @classmethod
    def from_memory(cls, memory, base: int, *, path: Path | None = None) -> "PEImage":
        """The image loaded at `base` in a process. Pages that cannot be read are zero."""
        head = memory.read(base, 0x1000)
        size = cls(head, mapped=True).size_of_image
        page = 0x1000
        chunks = memory.read_many([(base + offset, min(page, size - offset)) for offset in range(0, size, page)])
        data = bytearray(size)
        unreadable = []
        for index, chunk in enumerate(chunks):
            if chunk is None:
                unreadable.append(index * page)
            else:
                data[index * page:index * page + len(chunk)] = chunk
        image = cls(bytes(data), mapped=True, path=path)
        image.loaded_at = base
        image.unreadable_pages = unreadable
        return image

    # -- bytes by RVA ------------------------------------------------------------

    @property
    def sha256(self) -> str:
        if self._sha256 is None:
            self._sha256 = hashlib.sha256(self.data).hexdigest()
        return self._sha256

    def section_of(self, rva: int) -> Section | None:
        return next((s for s in self.sections if s.contains(rva)), None)

    def section(self, name: str) -> Section | None:
        return next((s for s in self.sections if s.name == name), None)

    def read(self, rva: int, length: int) -> bytes:
        """`length` bytes at `rva`. Bytes a section has in memory but not in the file are zero."""
        if rva < 0 or length < 0 or rva + length > self.size_of_image:
            raise PEError(f"read of {length} bytes at RVA {rva:#x} is outside the image")
        if self.mapped:
            return bytes(self.data[rva:rva + length])
        if rva + length <= self.size_of_headers:
            return bytes(self.data[rva:rva + length])
        out = bytearray(length)
        for section in self.sections:
            lo, hi = max(rva, section.rva), min(rva + length, section.rva + section.file_size)
            if lo < hi:
                start = section.file_offset + lo - section.rva
                out[lo - rva:hi - rva] = self.data[start:start + hi - lo]
        return bytes(out)

    def u32(self, rva: int) -> int:
        return _U32.unpack(self.read(rva, 4))[0]

    def u64(self, rva: int) -> int:
        return _U64.unpack(self.read(rva, 8))[0]

    def cstr(self, rva: int, limit: int = 512) -> str:
        raw = self.read(rva, min(limit, self.size_of_image - rva))
        return raw.split(b"\0", 1)[0].decode("latin-1")

    def directory(self, index: int) -> tuple[int, int]:
        return self.directories[index] if index < len(self.directories) else (0, 0)

    # -- tables ------------------------------------------------------------------

    def relocations(self) -> array:
        """RVAs of the 8-byte slots the loader adds the load delta to, ascending."""
        if self._relocations is None:
            slots = array("I")
            rva, size = self.directory(DIR_BASERELOC)
            table = self.read(rva, size) if size else b""
            offset = 0
            while offset + 8 <= len(table):
                page, block = struct.unpack_from("<II", table, offset)
                if block < 8 or offset + block > len(table):
                    break
                for (entry,) in _U16.iter_unpack(table[offset + 8:offset + block]):
                    kind = entry >> 12
                    if kind == RELOC_DIR64:
                        slots.append(page + (entry & 0xFFF))
                    elif kind != RELOC_ABSOLUTE:
                        raise PEError(f"relocation type {kind} is not expected in an x86-64 image")
                offset += block
            self._relocations = slots
        return self._relocations

    def functions(self) -> list[tuple[int, int]]:
        """(begin, end) RVAs from the exception directory, ascending. An entry is a function or,
        for a function the compiler split, one fragment of it. Leaf functions (no calls and no
        stack frame) have no entry, so this is not every function start in the image."""
        if self._functions is None:
            rva, size = self.directory(DIR_EXCEPTION)
            table = self.read(rva, size - size % 12) if size else b""
            self._functions = sorted((begin, end) for begin, end, _ in _RUNTIME_FUNCTION.iter_unpack(table)
                                     if begin and end > begin)
        return self._functions

    def function_of(self, rva: int) -> tuple[int, int] | None:
        functions = self.functions()
        lo, hi = 0, len(functions)
        while lo < hi:
            mid = (lo + hi) // 2
            if functions[mid][0] <= rva:
                lo = mid + 1
            else:
                hi = mid
        if lo and functions[lo - 1][1] > rva:
            return functions[lo - 1]
        return None

    def exports(self) -> dict[str, int]:
        """Exported name -> RVA (forwarded exports included, pointing at their forwarder string)."""
        if self._exports is None:
            found: dict[str, int] = {}
            rva, size = self.directory(DIR_EXPORT)
            if size:
                names, functions_rva, names_rva, ordinals_rva = struct.unpack_from("<IIII", self.read(rva + 24, 16))
                functions_count = self.u32(rva + 20)
                name_table = self.read(names_rva, 4 * names) if names else b""
                ordinal_table = self.read(ordinals_rva, 2 * names) if names else b""
                function_table = self.read(functions_rva, 4 * functions_count) if functions_count else b""
                for i in range(names):
                    ordinal = _U16.unpack_from(ordinal_table, 2 * i)[0]
                    if ordinal < functions_count:
                        found[self.cstr(_U32.unpack_from(name_table, 4 * i)[0])] = \
                            _U32.unpack_from(function_table, 4 * ordinal)[0]
            self._exports = found
        return self._exports

    def imports(self) -> list[Import]:
        """Every imported function with the RVA of its address slot."""
        if self._imports is None:
            found: list[Import] = []
            rva, size = self.directory(DIR_IMPORT)
            while size:
                lookup, _, _, name, thunks = struct.unpack("<IIIII", self.read(rva, 20))
                if not name and not thunks:
                    break
                library = self.cstr(name)
                # In a loaded image the address table is overwritten; the lookup table keeps the names.
                source = lookup or thunks
                index = 0
                while True:
                    value = self.u64(source + 8 * index)
                    if not value:
                        break
                    if value >> 63:
                        found.append(Import(library, None, value & 0xFFFF, thunks + 8 * index))
                    else:
                        found.append(Import(library, self.cstr((value & 0x7FFFFFFF) + 2), None, thunks + 8 * index))
                    index += 1
                rva += 20
            self._imports = found
        return self._imports

    def codeview(self) -> CodeView | None:
        rva, size = self.directory(DIR_DEBUG)
        for offset in range(0, size - size % 28, 28):
            kind, length, data_rva, data_offset = struct.unpack_from("<IIII", self.read(rva + offset, 28), 12)
            if kind != DEBUG_CODEVIEW or length < 24:
                continue
            raw = self.read(data_rva, length) if (self.mapped or not data_offset) else bytes(
                self.data[data_offset:data_offset + length])
            if raw[:4] != b"RSDS":
                continue
            a, b, c = struct.unpack_from("<IHH", raw, 4)
            guid = f"{a:08X}{b:04X}{c:04X}{raw[12:20].hex().upper()}"
            return CodeView(guid, _U32.unpack_from(raw, 20)[0], raw[24:].split(b"\0", 1)[0].decode("utf-8", "replace"))
        return None


def compare_with_memory(image: PEImage, memory, base: int, *, page: int = 0x1000) -> list[SectionMatch]:
    """Compare each section of a file-layout image with the image loaded at `base`.

    The file's bytes are relocated for `base` first, so a section that the loader left alone
    compares equal byte for byte. Sections the loader or the program writes to (import address
    tables, data) differ by design; a code section that differs was changed after loading."""
    delta = (base - image.image_base) & 0xFFFFFFFFFFFFFFFF
    slots = image.relocations()
    results = []
    cursor = 0
    for section in image.sections:
        size = section.virtual_size
        expected = bytearray(image.read(section.rva, size))
        if delta:
            while cursor < len(slots) and slots[cursor] < section.rva:
                cursor += 1
            while cursor < len(slots) and slots[cursor] + 8 <= section.rva + size:
                at = slots[cursor] - section.rva
                _U64.pack_into(expected, at, (_U64.unpack_from(expected, at)[0] + delta) & 0xFFFFFFFFFFFFFFFF)
                cursor += 1
        offsets = range(0, size, page)
        loaded = memory.read_many([(base + section.rva + o, min(page, size - o)) for o in offsets])
        same_bytes = same_pages = unreadable = 0
        for offset, chunk in zip(offsets, loaded):
            want = expected[offset:offset + page]
            if chunk is None:
                unreadable += 1
            elif chunk == want:
                same_pages += 1
                same_bytes += len(want)
            else:
                same_bytes += sum(x == y for x, y in zip(chunk, want))
        results.append(SectionMatch(section.name, size, same_bytes, len(offsets), same_pages, unreadable,
                                    section.executable, section.writable))
    return results
