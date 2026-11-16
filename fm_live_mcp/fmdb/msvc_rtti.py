"""C++ classes of a Windows image, from the run-time type information MSVC-compatible compilers emit.

The Windows build of the game keeps the same information the macOS build keeps in Itanium
``typeinfo`` records, in Microsoft's layout. For every polymorphic class there is

* a type descriptor: two pointers, then the decorated name (``.?AVPERSON@@``);
* one complete object locator per virtual table: signature 1, the offset of that table's
  sub-object in the complete object, and image-relative addresses of the type descriptor, the
  class hierarchy descriptor and the locator itself;
* a class hierarchy descriptor: the class's bases, itself first, each as a base class
  descriptor naming a type descriptor;
* the virtual table: a pointer to the locator, then the method pointers. An object's first
  word points at the first method pointer.

``read_classes`` works on a :class:`~fm_live_mcp.fmdb.pe.PEImage` of the file or of a loaded
image. It is a reading of data the compiler wrote, with one estimate: a virtual table has no
length field, so its methods are counted up to the first slot that is not a relocated pointer
into code. A table followed directly by another table of code pointers is over-counted. A class
with no virtual table in the image (one that is only thrown or caught there) is listed with no
tables and no bases, because the base list is reached through a table's locator.
"""

from __future__ import annotations

import bisect
import re
import struct
from array import array
from dataclasses import dataclass

from .pe import PEImage

_NAME = re.compile(rb"\.\?A[A-Z][\x21-\x7e]{1,2000}\0")
_SIMPLE = re.compile(r"\.\?A[UVW]((?:[A-Za-z_][A-Za-z0-9_]*@)+)@")
_U64 = struct.Struct("<Q")
_COL = struct.Struct("<IIIiii")            # signature, offset, cdOffset, type, hierarchy, self
_SIGNATURE_X64 = 1                         # image-relative fields; 0 is the 32-bit layout
_MAX_BASES = 4096
_MAX_METHODS = 8192


@dataclass(frozen=True)
class VTable:
    """One virtual table. ``rva`` is its first method slot, the value objects hold."""

    rva: int
    offset: int                            # of this table's sub-object in the complete object
    methods: tuple[int, ...]               # RVAs of the methods, in slot order

    def __len__(self) -> int:
        return len(self.methods)


@dataclass(frozen=True)
class RttiClass:
    decorated: str                         # ".?AVPERSON@@"
    name: str                              # "PERSON", "std::exception"; the decorated name if not simple
    descriptor: int                        # RVA of the type descriptor
    bases: tuple[str, ...]                 # decorated names, nearest first, the class itself excluded;
                                           # empty too when the image has no table for the class
    vtables: tuple[VTable, ...]            # ascending by offset; empty when no table names the class

    @property
    def primary(self) -> VTable | None:
        """The table an object of exactly this class points at with its first word."""
        return next((table for table in self.vtables if table.offset == 0), None)


def plain_name(decorated: str) -> str:
    """``.?AVexception@std@@`` as ``std::exception``. Templates and other forms are returned as given."""
    match = _SIMPLE.fullmatch(decorated)
    if not match:
        return decorated
    return "::".join(reversed(match.group(1).rstrip("@").split("@")))


class _Data:
    """The image's non-code bytes by RVA, read once per section."""

    def __init__(self, image: PEImage):
        self.image = image
        sections = sorted((s for s in image.sections if not s.executable and s.virtual_size), key=lambda s: s.rva)
        self.starts = [s.rva for s in sections]
        self.sections = sections
        self.blobs = [image.read(s.rva, s.virtual_size) for s in sections]

    def locate(self, rva: int) -> tuple[bytes, int] | None:
        index = bisect.bisect_right(self.starts, rva) - 1
        if index < 0 or rva >= self.starts[index] + len(self.blobs[index]):
            return None
        return self.blobs[index], rva - self.starts[index]

    def unpack(self, layout: struct.Struct, rva: int):
        found = self.locate(rva)
        if found is None or found[1] + layout.size > len(found[0]):
            return None
        return layout.unpack_from(found[0], found[1])


def read_classes(image: PEImage) -> dict[str, RttiClass]:
    """Every class with run-time type information in ``image``, by decorated name."""
    base = getattr(image, "loaded_at", image.image_base)
    data = _Data(image)
    relocated = set(image.relocations())
    code = sorted((s.rva, s.end) for s in image.sections if s.executable)
    code_starts = [lo for lo, _ in code]

    def in_code(rva: int) -> bool:
        index = bisect.bisect_right(code_starts, rva) - 1
        return index >= 0 and rva < code[index][1]

    # Type descriptors: a relocated pointer (type_info's own table), a spare word, the name.
    names: dict[int, str] = {}
    for start, blob in zip(data.starts, data.blobs):
        for match in _NAME.finditer(blob):
            descriptor = start + match.start() - 16
            if match.start() >= 16 and descriptor % 8 == 0 and descriptor in relocated:
                names[descriptor] = match.group()[:-1].decode("latin-1")

    # Complete object locators: found by their own address in the last field.
    locators: dict[int, tuple[int, int, int]] = {}             # rva -> (offset, descriptor, hierarchy)
    for start, blob in zip(data.starts, data.blobs):
        words = array("I")
        words.frombytes(blob[:len(blob) - len(blob) % 4])
        for index in range(max(0, len(words) - 5)):
            if words[index] != _SIGNATURE_X64 or words[index + 5] != start + 4 * index:
                continue
            _, offset, _, descriptor, hierarchy, _ = _COL.unpack_from(blob, 4 * index)
            if descriptor in names:
                locators[start + 4 * index] = (offset, descriptor, hierarchy)

    # Virtual tables: a relocated pointer to a locator, then relocated pointers into code.
    tables: dict[int, list[VTable]] = {}
    for slot in image.relocations():
        found = data.locate(slot)
        if found is None or found[1] + 8 > len(found[0]):
            continue
        locator = locators.get(_U64.unpack_from(found[0], found[1])[0] - base)
        if locator is None:
            continue
        blob, at = found[0], found[1] + 8
        methods = []
        while len(methods) < _MAX_METHODS and at + 8 <= len(blob) and slot + 8 + 8 * len(methods) in relocated:
            target = _U64.unpack_from(blob, at)[0] - base
            if not in_code(target):
                break
            methods.append(target)
            at += 8
        tables.setdefault(locator[1], []).append(VTable(slot + 8, locator[0], tuple(methods)))

    # Bases, from the hierarchy descriptor of any locator of the class.
    hierarchy_of = {descriptor: hierarchy for _, descriptor, hierarchy in locators.values()}
    classes: dict[str, RttiClass] = {}
    for descriptor, decorated in names.items():
        bases: list[str] = []
        head = data.unpack(struct.Struct("<IIIi"), hierarchy_of[descriptor]) if descriptor in hierarchy_of else None
        if head is not None and 0 < head[2] <= _MAX_BASES:
            for index in range(head[2]):
                entry = data.unpack(struct.Struct("<i"), head[3] + 4 * index)
                target = data.unpack(struct.Struct("<i"), entry[0]) if entry else None
                if target and target[0] in names and target[0] != descriptor:
                    bases.append(names[target[0]])
        classes[decorated] = RttiClass(decorated, plain_name(decorated), descriptor, tuple(bases),
                                       tuple(sorted(tables.get(descriptor, ()), key=lambda t: (t.offset, t.rva))))
    return classes
