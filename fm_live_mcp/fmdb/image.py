"""On-disk ARM64 slice of the game plugin: segments, stubs and chained-fixup binds.

The property VM executes code bytes from this file only (never from live memory),
so emulated code is exactly the shipped code. `PluginImage.load` fails closed
unless the file matches the build the existing reader pins (`players.SHA256`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import mmap
from pathlib import Path
import struct

FAT_MAGIC = 0xCAFEBABE
MH_MAGIC_64 = 0xFEEDFACF
CPU_ARM64 = 0x0100000C
LC_SEGMENT_64 = 0x19
LC_DYLD_CHAINED_FIXUPS = 0x80000034


class ImageError(ValueError):
    pass


@dataclass
class Segment:
    name: str
    vmaddr: int
    vmsize: int
    fileoff: int
    filesize: int
    initprot: int
    sections: dict = field(default_factory=dict)  # name -> (addr, size, offset)


@dataclass
class PluginImage:
    path: Path
    slice_offset: int
    slice_size: int
    segments: list
    binds: dict          # rva of pointer slot -> imported symbol name
    stubs: dict          # rva of stub -> imported symbol name
    stub_range: tuple    # (start rva, end rva)
    text_range: tuple    # (start rva, end rva) of executable __TEXT
    _map: mmap.mmap
    tlv_vars: tuple = (0, 0)          # __thread_vars (start rva, end rva)
    tlv_template: tuple = (0, 0, 0)   # (__thread_data rva, its size, __thread_bss size)

    @classmethod
    def load(cls, path, *, verify=True) -> 'PluginImage':
        path = Path(path)
        if verify:
            from .. import players
            with path.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != players.SHA256:
                    raise ImageError('Plugin binary differs from the pinned build; refusing to emulate it')
        stream = path.open('rb')
        data = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
        stream.close()
        offset, size = 0, len(data)
        if struct.unpack_from('>I', data, 0)[0] == FAT_MAGIC:
            count = struct.unpack_from('>I', data, 4)[0]
            for i in range(count):
                cpu, _, off, sz, _ = struct.unpack_from('>IIIII', data, 8 + 20 * i)
                if cpu == CPU_ARM64:
                    offset, size = off, sz
                    break
            else:
                raise ImageError('No ARM64 slice')
        if struct.unpack_from('<I', data, offset)[0] != MH_MAGIC_64:
            raise ImageError('ARM64 slice is not a 64-bit Mach-O')
        ncmds, sizeofcmds = struct.unpack_from('<II', data, offset + 16)
        cursor = offset + 32
        segments, fixups = [], None
        for _ in range(ncmds):
            cmd, cmdsize = struct.unpack_from('<II', data, cursor)
            if cmd == LC_SEGMENT_64:
                name = data[cursor + 8:cursor + 24].rstrip(b'\0').decode()
                vmaddr, vmsize, fileoff, filesize, _maxprot, initprot, nsects, _ = struct.unpack_from(
                    '<QQQQiiII', data, cursor + 24)
                seg = Segment(name, vmaddr, vmsize, fileoff, filesize, initprot)
                for s in range(nsects):
                    base = cursor + 72 + 80 * s
                    sect = data[base:base + 16].rstrip(b'\0').decode()
                    addr, ssize, soff = struct.unpack_from('<QQI', data, base + 32)
                    seg.sections[sect] = (addr, ssize, soff)
                segments.append(seg)
            elif cmd == LC_DYLD_CHAINED_FIXUPS:
                fixups = struct.unpack_from('<II', data, cursor + 8)
            cursor += cmdsize
        image = cls(path, offset, size, segments, {}, {}, (0, 0), (0, 0), data)
        text = image.segment('__TEXT')
        if text.vmaddr != 0:
            raise ImageError('Unexpected __TEXT vmaddr')
        code = text.sections['__text']
        stubs = text.sections['__stubs']
        image.text_range = (code[0], stubs[0] + stubs[1])
        image.stub_range = (stubs[0], stubs[0] + stubs[1])
        for seg in segments:
            if '__thread_vars' in seg.sections:
                addr, size, _ = seg.sections['__thread_vars']
                image.tlv_vars = (addr, addr + size)
            if '__thread_data' in seg.sections:
                data = seg.sections['__thread_data']
                bss = seg.sections.get('__thread_bss', (data[0] + data[1], 0, 0))
                if bss[0] != data[0] + data[1]:
                    raise ImageError('TLV template is not contiguous')
                image.tlv_template = (data[0], data[1], bss[1])
        if fixups is None:
            raise ImageError('Missing LC_DYLD_CHAINED_FIXUPS')
        image._parse_fixups(*fixups)
        image._parse_stubs()
        return image

    def segment(self, name) -> Segment:
        for seg in self.segments:
            if seg.name == name:
                return seg
        raise ImageError(f'Missing segment {name}')

    def segment_for(self, rva):
        for seg in self.segments:
            if seg.vmaddr <= rva < seg.vmaddr + seg.vmsize:
                return seg
        return None

    def file_bytes(self, rva: int, length: int) -> bytes:
        """Bytes of the on-disk slice at an RVA; zero fill past a segment's file size."""
        seg = self.segment_for(rva)
        if seg is None or rva + length > seg.vmaddr + seg.vmsize:
            raise ImageError(f'RVA {rva:#x}+{length:#x} is outside the image')
        rel = rva - seg.vmaddr
        start = self.slice_offset + seg.fileoff + rel
        avail = max(0, min(length, seg.filesize - rel))
        return bytes(self._map[start:start + avail]) + b'\0' * (length - avail)

    def is_code(self, rva: int) -> bool:
        return self.text_range[0] <= rva < self.text_range[1]

    def in_text_segment(self, rva: int) -> bool:
        seg = self.segments and self.segment('__TEXT')
        return 0 <= rva < seg.vmsize

    def _parse_fixups(self, dataoff, datasize):
        d = self._map
        h = self.slice_offset + dataoff
        (_version, starts_off, imports_off, symbols_off, imports_count, imports_format,
         _symbols_format) = struct.unpack_from('<IIIIIII', d, h)
        names = []
        for i in range(imports_count):
            if imports_format == 1:
                raw = struct.unpack_from('<I', d, h + imports_off + 4 * i)[0]
                name_off = raw >> 9
            elif imports_format == 2:
                raw = struct.unpack_from('<I', d, h + imports_off + 8 * i)[0]
                name_off = raw >> 9
            elif imports_format == 3:
                raw = struct.unpack_from('<Q', d, h + imports_off + 16 * i)[0]
                name_off = raw >> 32
            else:
                raise ImageError(f'Unsupported chained import format {imports_format}')
            start = h + symbols_off + name_off
            end = d.find(b'\0', start)
            names.append(d[start:end].decode('latin-1'))
        seg_count = struct.unpack_from('<I', d, h + starts_off)[0]
        for s in range(seg_count):
            info = struct.unpack_from('<I', d, h + starts_off + 4 + 4 * s)[0]
            if not info:
                continue
            base = h + starts_off + info
            _size, page_size, fmt, seg_offset, _maxp, page_count = struct.unpack_from('<IHHQIH', d, base)
            if fmt not in (2, 6):  # DYLD_CHAINED_PTR_64, DYLD_CHAINED_PTR_64_OFFSET
                raise ImageError(f'Unsupported chained pointer format {fmt}')
            seg = self.segment_for(seg_offset)
            for p in range(page_count):
                start = struct.unpack_from('<H', d, base + 22 + 2 * p)[0]
                if start == 0xFFFF:
                    continue
                rva = seg_offset + p * page_size + start
                while True:
                    off = self.slice_offset + seg.fileoff + (rva - seg.vmaddr)
                    value = struct.unpack_from('<Q', d, off)[0]
                    if value >> 63:
                        self.binds[rva] = names[value & 0xFFFFFF]
                    nxt = (value >> 51) & 0xFFF
                    if not nxt:
                        break
                    rva += nxt * 4

    def _parse_stubs(self):
        start, end = self.stub_range
        for rva in range(start, end - 11, 12):
            adrp, ldr, br = struct.unpack('<III', self.file_bytes(rva, 12))
            if adrp & 0x9F00001F != 0x90000010 or ldr & 0xFFC003FF != 0xF9400210 or br != 0xD61F0200:
                continue
            immlo, immhi = (adrp >> 29) & 3, (adrp >> 5) & 0x7FFFF
            imm = ((immhi << 2) | immlo)
            if imm & (1 << 20):
                imm -= 1 << 21
            slot = (rva & ~0xFFF) + (imm << 12) + ((ldr >> 10) & 0xFFF) * 8
            name = self.binds.get(slot)
            if name:
                self.stubs[rva] = name
