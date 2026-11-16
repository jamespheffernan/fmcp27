"""macOS ARM64 implementation of the platform model (see platform_model.py).

Mach-O images (fat or thin; chained fixups or the older LC_DYLD_INFO opcodes), Itanium C++ RTTI
and vtable layout, AArch64 instruction shapes, and the live process found by its Mach-O UUID.
Everything here is specific to this platform; anchors.py uses it only through the methods
listed in platform_model.BinaryModel.
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass, field
import hashlib
import re
import struct
from pathlib import Path

from .image import ImageError, PluginImage

NAME = 'macos-arm64'
LC_FUNCTION_STARTS = 0x26
MIN_UNIQUE = 6          # instructions: shorter functions match by fingerprint only at the same address
MIN_RANKED = 16         # instructions: identical functions are told apart by rank only above this size
TI_CLASS = '__ZTVN10__cxxabiv117__class_type_infoE'
TI_SI = '__ZTVN10__cxxabiv120__si_class_type_infoE'
TI_VMI = '__ZTVN10__cxxabiv121__vmi_class_type_infoE'
RET = 0xD65F03C0
MOV_W0_0 = 0x52800000
MOV_W0_1 = 0x52800020


# --------------------------------------------------------------------------- decoding helpers
def _sx(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def is_adrp(w):
    return (w & 0x9F000000) == 0x90000000


def adrp_page(w, pc):
    imm = ((w >> 29) & 3) | (((w >> 5) & 0x7FFFF) << 2)
    return (pc & ~0xFFF) + (_sx(imm, 21) << 12)


def page_use(w, rd):
    """(kind, page offset) when `w` consumes the ADRP register `rd` as a page base, else None.
    Kinds: 'add', 'ldr<bits>', 'str<bits>' (unsigned-offset integer or SIMD loads/stores)."""
    if ((w >> 5) & 31) != rd:
        return None
    if (w & 0xFF800000) == 0x91000000:                      # add xd, xn, #imm (no shift)
        return 'add', (w >> 10) & 0xFFF
    if (w & 0x3B000000) == 0x39000000:                      # ldr/str unsigned offset
        size, simd, opc = w >> 30, (w >> 26) & 1, (w >> 22) & 3
        if simd and opc & 2:
            size = 4
        scale = 1 << size
        load = bool(opc & 1) or (not simd and opc == 2) or (not simd and opc == 3 and size < 3)
        return ('ldr' if load else 'str') + str(8 * scale), ((w >> 10) & 0xFFF) * scale
    return None


def bl_target(w, pc):
    if (w & 0xFC000000) in (0x94000000, 0x14000000):
        return pc + _sx(w & 0x3FFFFFF, 26) * 4
    return None


def movz_movk_value(words):
    """FourCC-sized constants built by `movz wN,#lo` + `movk wN,#hi,lsl #16` pairs."""
    out = []
    for i in range(len(words) - 1):
        a, b = words[i], words[i + 1]
        if (a & 0xFFE00000) == 0x52800000 and (b & 0xFFE00000) == 0x72A00000 and (a & 31) == (b & 31):
            out.append(((b >> 5) & 0xFFFF) << 16 | ((a >> 5) & 0xFFFF))
    return out


def is_fourcc(value):
    data = value.to_bytes(4, 'big')
    return all(48 <= c <= 57 or 65 <= c <= 90 or 97 <= c <= 122 or c == 32 for c in data) \
        and any(65 <= c <= 90 or 97 <= c <= 122 for c in data)


# --------------------------------------------------------------------------- the binary
@dataclass
class TypeInfo:
    address: int
    name: str
    kind: str                       # class | si | vmi
    bases: list = field(default_factory=list)   # [(base type_info or bind name, offset, virtual)]


class Binary:
    """Static view of one plugin ARM64 slice: fixups, RTTI, vtables, functions, references."""

    def __init__(self, path):
        self.path = Path(path)
        with self.path.open('rb') as stream:
            self.sha256 = hashlib.file_digest(stream, 'sha256').hexdigest()
        self.rebases = {}
        try:
            self.image = PluginImage.load(self.path, verify=False)
            self._parse_rebases()
        except ImageError as exc:
            if 'CHAINED_FIXUPS' not in str(exc):
                raise
            self.image = _load_dyld_info_image(self.path, self.rebases)   # older builds (FM26)
        code = self.image.segment('__TEXT').sections['__text']
        self.text_start, self.text_size = code[0], code[1]
        self.text = self.image.file_bytes(self.text_start, self.text_size)
        self.words = memoryview(self.text).cast('I')
        self.starts = self._function_starts()
        self._rtti = None
        self._vtables = None
        self._refs = None
        self._calls = None
        self._fp_cache = {}

    # ---------------------------------------------------------------- raw access
    def u64(self, rva):
        return struct.unpack('<Q', self.image.file_bytes(rva, 8))[0]

    def u32(self, rva):
        return struct.unpack('<I', self.image.file_bytes(rva, 4))[0]

    def word(self, rva):
        if self.text_start <= rva < self.text_start + self.text_size:
            return self.words[(rva - self.text_start) // 4]
        return self.u32(rva)

    def cstr(self, rva, limit=512):
        data = self.image.file_bytes(rva, limit)
        return data.split(b'\0', 1)[0].decode('latin-1')

    def pointer(self, slot):
        """Rebase target of a pointer slot (None when the slot is not a rebased pointer)."""
        return self.rebases.get(slot)

    def is_code(self, rva):
        return self.text_start <= rva < self.text_start + self.text_size

    def version(self):
        """CFBundleShortVersionString of the app containing the plugin, when it can be found."""
        for parent in self.path.parents:
            plist = parent / 'Info.plist'
            if parent.name == 'Contents' and plist.exists() and parent.parent.suffix == '.app':
                import plistlib
                try:
                    return plistlib.loads(plist.read_bytes()).get('CFBundleShortVersionString')
                except Exception:  # noqa: BLE001
                    return None
        return None

    def _parse_rebases(self):
        image, d = self.image, self.image._map
        offset = image.slice_offset
        ncmds = struct.unpack_from('<I', d, offset + 16)[0]
        cursor, fixups = offset + 32, None
        self._lc = []
        for _ in range(ncmds):
            cmd, size = struct.unpack_from('<II', d, cursor)
            self._lc.append((cmd, cursor))
            if cmd == 0x80000034:
                fixups = struct.unpack_from('<II', d, cursor + 8)
            cursor += size
        h = offset + fixups[0]
        starts_off = struct.unpack_from('<I', d, h + 4)[0]
        seg_count = struct.unpack_from('<I', d, h + starts_off)[0]
        for s in range(seg_count):
            info = struct.unpack_from('<I', d, h + starts_off + 4 + 4 * s)[0]
            if not info:
                continue
            base = h + starts_off + info
            _size, page_size, fmt, seg_offset, _maxp, page_count = struct.unpack_from('<IHHQIH', d, base)
            seg = image.segment_for(seg_offset)
            for p in range(page_count):
                start = struct.unpack_from('<H', d, base + 22 + 2 * p)[0]
                if start == 0xFFFF:
                    continue
                rva = seg_offset + p * page_size + start
                while True:
                    value = struct.unpack_from('<Q', d, offset + seg.fileoff + (rva - seg.vmaddr))[0]
                    if not value >> 63:
                        self.rebases[rva] = value & 0xFFFFFFFFF
                    nxt = (value >> 51) & 0xFFF
                    if not nxt:
                        break
                    rva += nxt * 4

    def _load_commands(self):
        d = self.image._map
        offset = self.image.slice_offset
        ncmds = struct.unpack_from('<I', d, offset + 16)[0]
        cursor, out = offset + 32, []
        for _ in range(ncmds):
            cmd, size = struct.unpack_from('<II', d, cursor)
            out.append((cmd, cursor))
            cursor += size
        return out

    def _function_starts(self):
        if not hasattr(self, '_lc'):
            self._lc = self._load_commands()
        d = self.image._map
        for cmd, cursor in self._lc:
            if cmd == LC_FUNCTION_STARTS:
                off, size = struct.unpack_from('<II', d, cursor + 8)
                data = d[self.image.slice_offset + off:self.image.slice_offset + off + size]
                out, addr, i = [], 0, 0
                while i < len(data):
                    r = s = 0
                    while True:
                        c = data[i]
                        i += 1
                        r |= (c & 0x7F) << s
                        s += 7
                        if c < 0x80:
                            break
                    if r == 0:
                        break
                    addr += r
                    out.append(addr)
                return out
        return []

    # ---------------------------------------------------------------- functions
    def function_of(self, rva):
        """(start, end) of the function containing `rva` (LC_FUNCTION_STARTS bounds)."""
        i = bisect_right(self.starts, rva) - 1
        if i < 0:
            return None
        end = self.starts[i + 1] if i + 1 < len(self.starts) else self.text_start + self.text_size
        return self.starts[i], end

    def function_words(self, start, end=None):
        if end is None:
            end = self.function_of(start)[1]
        lo, hi = (start - self.text_start) // 4, (end - self.text_start) // 4
        return self.words[lo:hi]

    # ---------------------------------------------------------------- RTTI
    @property
    def rtti(self) -> dict:
        """{mangled name: TypeInfo} for every type_info object in the slice."""
        if self._rtti is None:
            kinds = {TI_CLASS: 'class', TI_SI: 'si', TI_VMI: 'vmi'}
            out, by_addr = {}, {}
            for slot, name in self.image.binds.items():
                kind = kinds.get(name)
                if kind is None:
                    continue
                name_ptr = self.pointer(slot + 8)
                if name_ptr is None:
                    continue
                mangled = self.cstr(name_ptr, 400)
                if not mangled:
                    continue
                info = TypeInfo(slot, mangled, kind)
                if kind == 'si':
                    info.bases = [(self.pointer(slot + 16) or self.image.binds.get(slot + 16), 0, False)]
                elif kind == 'vmi':
                    count = self.u32(slot + 20)
                    for b in range(min(count, 64)):
                        at = slot + 24 + 16 * b
                        base = self.pointer(at) or self.image.binds.get(at)
                        flags = struct.unpack('<q', self.image.file_bytes(at + 8, 8))[0]
                        info.bases.append((base, flags >> 8, bool(flags & 1)))
                out.setdefault(mangled, info)
                by_addr[slot] = info
            self._rtti = out
            self._ti_by_addr = by_addr
        return self._rtti

    def typeinfo_at(self, address):
        self.rtti
        return self._ti_by_addr.get(address)

    @property
    def vtables(self) -> dict:
        """{mangled name: [(address point, offset_to_top)]}, primary first, then by address."""
        if self._vtables is None:
            self.rtti
            ti_extent = set()
            for info in self._ti_by_addr.values():
                n = {'class': 2, 'si': 3, 'vmi': 3 + 2 * len(info.bases)}[info.kind]
                ti_extent.update(info.address + 8 * k for k in range(n))
            out = defaultdict(list)
            for slot, target in self.rebases.items():
                info = self._ti_by_addr.get(target)
                if info is None or slot in ti_extent:
                    continue
                if (slot - 8) in self.rebases or (slot - 8) in self.image.binds:
                    continue
                top = struct.unpack('<q', self.image.file_bytes(slot - 8, 8))[0]
                if top > 0 or top % 8 or top < -0x100000:
                    continue
                first = slot + 8
                f = self.rebases.get(first)
                if f is None and first not in self.image.binds:
                    continue
                if f is not None and not self.is_code(f):
                    continue
                out[info.name].append((first, -top))
            self._vtables = {k: sorted(v, key=lambda e: (e[1] != 0, e[0])) for k, v in out.items()}
        return self._vtables

    def vtable(self, mangled, offset=0):
        """Address point of the vtable of `mangled` whose subobject offset is `offset`."""
        hits = [a for a, off in self.vtables.get(mangled, ()) if off == offset]
        return hits[0] if len(hits) == 1 else (min(hits) if hits else None)

    def slot(self, vtable, index):
        """Function a vtable slot points at (None for a bind, e.g. __cxa_pure_virtual)."""
        return self.rebases.get(vtable + 8 * index)

    def class_name(self, vtable):
        """Mangled class name of a vtable address point (vtable[-1] -> type_info)."""
        self.rtti
        info = self._ti_by_addr.get(self.rebases.get(vtable - 8))
        return info.name if info else None

    def base_offset(self, mangled, base_mangled):
        """Offset of the `base_mangled` subobject inside a complete `mangled` object (first path
        found). Virtual bases are resolved through the vbase offsets of the subobject vtables."""
        def walk(name, cur, depth):
            if name == base_mangled:
                return cur
            info = self.rtti.get(name)
            if info is None or depth > 12:
                return None
            vt = self.vtable(mangled, cur)
            for base, offset, virtual in info.bases:
                base_info = self._ti_by_addr.get(base) if isinstance(base, int) else None
                if base_info is None:
                    continue
                if virtual:
                    if vt is None:
                        continue
                    sub = cur + struct.unpack('<q', self.image.file_bytes(vt + offset, 8))[0]
                else:
                    sub = cur + offset
                found = walk(base_info.name, sub, depth + 1)
                if found is not None:
                    return found
            return None
        return walk(mangled, 0, 0)

    # ---------------------------------------------------------------- references
    @property
    def refs(self) -> dict:
        """{target: [(adrp pc, use pc, kind)]} for ADRP + add/ldr/str pairs in __text."""
        if self._refs is None:
            out = defaultdict(list)
            words, start = self.words, self.text_start
            n = len(words)
            for m in re.finditer(rb'[\x90\xb0\xd0\xf0]', self.text):
                j = m.start()
                if j % 4 != 3:
                    continue
                i = j // 4
                w = words[i]
                pc = start + 4 * i
                page = adrp_page(w, pc)
                rd = w & 31
                for k in range(i + 1, min(i + 9, n)):
                    use = page_use(words[k], rd)
                    if use is not None:
                        out[page + use[1]].append((pc, start + 4 * k, use[0]))
                        break
            self._refs = dict(out)
        return self._refs

    def refs_in(self, start, end):
        """Ordered [(use pc, target, kind)] of ADRP-pair references inside [start, end)."""
        words = self.function_words(start, end)
        out = []
        for i, w in enumerate(words):
            if not is_adrp(w):
                continue
            pc = start + 4 * i
            page, rd = adrp_page(w, pc), w & 31
            for k in range(i + 1, min(i + 9, len(words))):
                use = page_use(words[k], rd)
                if use is not None:
                    out.append((start + 4 * k, page + use[1], use[0]))
                    break
        return out

    @property
    def calls(self) -> dict:
        """{target: [call site]} for every BL in __text."""
        if self._calls is None:
            out = defaultdict(list)
            words, start = self.words, self.text_start
            for m in re.finditer(rb'[\x94\x95\x96\x97]', self.text):
                j = m.start()
                if j % 4 != 3:
                    continue
                i = j // 4
                pc = start + 4 * i
                out[pc + _sx(words[i] & 0x3FFFFFF, 26) * 4].append(pc)
            self._calls = dict(out)
        return self._calls

    def callees(self, start, end=None):
        """Ordered BL targets of one function."""
        words = self.function_words(start, end)
        return [start + 4 * i + _sx(w & 0x3FFFFFF, 26) * 4 for i, w in enumerate(words)
                if (w & 0xFC000000) == 0x94000000]

    def stub_name(self, rva):
        return self.image.stubs.get(rva)

    def stub_for(self, name):
        for rva, n in self.image.stubs.items():
            if n == name:
                return rva
        return None

    # ---------------------------------------------------------------- fingerprints
    def fingerprint(self, start, end=None):
        """Address-independent hash of one function (see module docstring)."""
        key = (start, end)
        if key in self._fp_cache:
            return self._fp_cache[key]
        if end is None:
            end = self.function_of(start)[1]
        words = self.function_words(start, end)
        h = hashlib.blake2b(digest_size=12)
        pending = {}
        out = bytearray()
        for i, w in enumerate(words):
            pc = start + 4 * i
            if is_adrp(w):
                pending[w & 31] = 3
                out += struct.pack('<I', w & 0x9F00001F)
                continue
            masked = w
            for rd in list(pending):
                if page_use(w, rd) is not None:
                    masked = w & ~(0xFFF << 10)
                    del pending[rd]
                    break
                pending[rd] -= 1
                if pending[rd] <= 0:
                    del pending[rd]
            top = w & 0xFC000000
            if top in (0x94000000, 0x14000000):
                target = pc + _sx(w & 0x3FFFFFF, 26) * 4
                if not start <= target < end:
                    name = self.image.stubs.get(target)
                    out += struct.pack('<I', top)
                    if name:
                        out += name.encode() + b'\0'
                    continue
            elif (w & 0x9F000000) == 0x10000000:            # adr
                masked = w & 0x9F00001F
            elif (w & 0x3B000000) == 0x18000000:            # ldr literal
                masked = w & 0xFF00001F
            out += struct.pack('<I', masked)
        h.update(out)
        result = (len(words), h.hexdigest())
        self._fp_cache[key] = result
        return result

    def functions_by_length(self):
        if not hasattr(self, '_by_len'):
            by = defaultdict(list)
            ends = self.starts[1:] + [self.text_start + self.text_size]
            for s, e in zip(self.starts, ends):
                by[(e - s) // 4].append(s)
            self._by_len = by
        return self._by_len

    def find_fingerprint(self, fp):
        """Every function start whose fingerprint equals `fp`."""
        n, _ = fp
        return [s for s in self.functions_by_length().get(n, ()) if self.fingerprint(s) == fp]


def _uleb(data, i):
    result = shift = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            return result, i


def _sleb(data, i):
    result = shift = 0
    while True:
        b = data[i]
        i += 1
        result |= (b & 0x7F) << shift
        shift += 7
        if b < 0x80:
            if b & 0x40:
                result -= 1 << shift
            return result, i


def _load_dyld_info_image(path, rebases: dict) -> PluginImage:
    """PluginImage for a slice that uses LC_DYLD_INFO(_ONLY) rebase/bind opcodes instead of
    chained fixups (FM26 and older builds). Fills `rebases` {slot: target}."""
    import mmap
    stream = Path(path).open('rb')
    d = mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ)
    stream.close()
    offset, size = 0, len(d)
    if struct.unpack_from('>I', d, 0)[0] == 0xCAFEBABE:
        for i in range(struct.unpack_from('>I', d, 4)[0]):
            cpu, _, off, sz, _ = struct.unpack_from('>IIIII', d, 8 + 20 * i)
            if cpu == 0x0100000C:
                offset, size = off, sz
    ncmds = struct.unpack_from('<I', d, offset + 16)[0]
    cursor, segments, info = offset + 32, [], None
    from .image import Segment
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', d, cursor)
        if cmd == 0x19:
            name = d[cursor + 8:cursor + 24].rstrip(b'\0').decode()
            vmaddr, vmsize, fileoff, filesize, _maxp, initprot, nsects, _ = struct.unpack_from('<QQQQiiII', d, cursor + 24)
            seg = Segment(name, vmaddr, vmsize, fileoff, filesize, initprot)
            for k in range(nsects):
                b = cursor + 72 + 80 * k
                addr, ssize, soff = struct.unpack_from('<QQI', d, b + 32)
                seg.sections[d[b:b + 16].rstrip(b'\0').decode()] = (addr, ssize, soff)
            segments.append(seg)
        elif cmd in (0x22, 0x80000022):
            info = struct.unpack_from('<10I', d, cursor + 8)
        cursor += cmdsize
    if info is None:
        raise ImageError('Neither chained fixups nor LC_DYLD_INFO')
    image = PluginImage(Path(path), offset, size, segments, {}, {}, (0, 0), (0, 0), d)
    text = image.segment('__TEXT')
    code, stubs = text.sections['__text'], text.sections['__stubs']
    image.text_range = (code[0], stubs[0] + stubs[1])
    image.stub_range = (stubs[0], stubs[0] + stubs[1])

    def slot_value(rva):
        seg = image.segment_for(rva)
        return struct.unpack_from('<Q', d, offset + seg.fileoff + rva - seg.vmaddr)[0] & ((1 << 63) - 1)

    rebase_off, rebase_size = info[0], info[1]
    data = d[offset + rebase_off:offset + rebase_off + rebase_size]
    i, seg_i, addr = 0, 0, 0
    def rebase(a):
        rebases[a] = slot_value(a)
    while i < len(data):
        op, imm = data[i] & 0xF0, data[i] & 0x0F
        i += 1
        if op == 0x00:
            break
        if op == 0x20:
            seg_i = imm
            addr, i = _uleb(data, i)
            addr += segments[seg_i].vmaddr
        elif op == 0x30:
            v, i = _uleb(data, i)
            addr += v
        elif op == 0x40:
            addr += imm * 8
        elif op == 0x50:
            for _ in range(imm):
                rebase(addr)
                addr += 8
        elif op == 0x60:
            n, i = _uleb(data, i)
            for _ in range(n):
                rebase(addr)
                addr += 8
        elif op == 0x70:
            rebase(addr)
            v, i = _uleb(data, i)
            addr += v + 8
        elif op == 0x80:
            n, i = _uleb(data, i)
            skip, i = _uleb(data, i)
            for _ in range(n):
                rebase(addr)
                addr += skip + 8
    for b_off, b_size, lazy in ((info[2], info[3], False), (info[4], info[5], False), (info[6], info[7], True)):
        data = d[offset + b_off:offset + b_off + b_size]
        i, addr, name = 0, 0, None
        while i < len(data):
            op, imm = data[i] & 0xF0, data[i] & 0x0F
            i += 1
            if op == 0x00:
                if lazy:
                    continue
                break
            elif op in (0x10, 0x30):
                pass
            elif op == 0x20:
                _, i = _uleb(data, i)
            elif op == 0x40:
                end = data.index(b'\0', i)
                name = data[i:end].decode('latin-1')
                i = end + 1
            elif op == 0x50:
                pass
            elif op == 0x60:
                _, i = _sleb(data, i)
            elif op == 0x70:
                addr, i = _uleb(data, i)
                addr += segments[imm].vmaddr
            elif op == 0x80:
                v, i = _uleb(data, i)
                addr = (addr + v) & 0xFFFFFFFFFFFFFFFF
            elif op == 0x90:
                image.binds[addr] = name
                addr += 8
            elif op == 0xA0:
                image.binds[addr] = name
                v, i = _uleb(data, i)
                addr = (addr + v + 8) & 0xFFFFFFFFFFFFFFFF
            elif op == 0xB0:
                image.binds[addr] = name
                addr += imm * 8 + 8
            elif op == 0xC0:
                n, i = _uleb(data, i)
                skip, i = _uleb(data, i)
                for _ in range(n):
                    image.binds[addr] = name
                    addr += skip + 8
            else:
                break
    for a in image.binds:
        rebases.pop(a, None)
    image._parse_stubs()
    return image




# --------------------------------------------------------------------------- shape queries
# The instruction-level questions anchors.py asks (platform_model.BinaryModel). A Windows x86-64
# model answers the same questions with x86 patterns.
def _type_key(self, itanium):
    """The platform's type name for a canonical (Itanium-mangled) type key: identity here."""
    return itanium


def _fourcc_constants(self, start, limit=4096):
    """Distinct FourCC constants a function builds (`movz`+`movk` pairs): a getter's key tree."""
    end = min(self.function_of(start)[1], start + 4 * limit)
    words = list(self.function_words(start, end))
    return {v for v in movz_movk_value(words) if is_fourcc(v)}


def _first_branch_target(self, start, window=4):
    """Target of the first B/BL in the first `window` instructions (thunks)."""
    words = list(self.function_words(start))[:window]
    return next((t for t in (bl_target(w, start + 4 * i) for i, w in enumerate(words)) if t), None)


def _constant_return_functions(self, value):
    """Function starts whose whole body is `mov w0,#value; ret`."""
    want = 0x52800000 | (value << 5)
    words, start = self.words, self.text_start
    return [s for s in self.starts
            if 0 <= (s - start) // 4 < len(words) - 1 and words[(s - start) // 4] == want
            and words[(s - start) // 4 + 1] == RET]


def _virtual_bool_check_globals(self, slot):
    """{global: uses} for `ldr x0,[G]; ldr x8,[x0]; ldr x8,[x8,#slot*8]; blr x8; tbz/tbnz w0`:
    a global object asked a yes/no virtual question (the game-layer interceptors, slot 7)."""
    words, start = self.words, self.text_start
    want = 0xF9400108 | (slot << 10)              # ldr x8, [x8, #slot*8]
    hits = Counter()
    for target, uses in self.refs.items():
        for _adrp, use, kind in uses:
            if kind != 'ldr64':
                continue
            i = (use - start) // 4
            if (words[i] & 31) != 0 or i + 4 >= len(words):
                continue
            if words[i + 1] != 0xF9400008 or words[i + 2] != want or words[i + 3] != 0xD63F0100:
                continue
            if (words[i + 4] & 0x7E00001F) != 0x36000000:
                continue
            hits[target] += 1
    return dict(hits)


def _call_result_stores(self, import_name):
    """[(call site, global, flag)] where the result of a call to `import_name` is stored to a
    global right after the call; `flag` is a byte global set by `strb` in the next instructions."""
    words, start = self.words, self.text_start
    stub = self.stub_for(import_name)
    out = []
    for site in self.calls.get(stub, ()) if stub else ():
        i = (site - start) // 4
        for k in range(i + 1, min(i + 3, len(words) - 1)):
            if is_adrp(words[k]):
                use = page_use(words[k + 1], words[k] & 31)
                if use and use[0] == 'str64' and (words[k + 1] & 31) == 0:
                    glob = adrp_page(words[k], start + 4 * k) + use[1]
                    flag = None
                    tail = [words[j] for j in range(k + 2, min(k + 6, len(words)))]
                    for j in range(len(tail) - 1):
                        if is_adrp(tail[j]):
                            u = page_use(tail[j + 1], tail[j] & 31)
                            if u and u[0] == 'str8':
                                flag = adrp_page(tail[j], start + 4 * (k + 2 + j)) + u[1]
                            break
                    out.append((site, glob, flag))
                break
    return out


def _loads_by_width(self, bits):
    """Counter {global: loads of that width} over all ADRP-paired loads."""
    out = Counter()
    kind = f'ldr{bits}'
    for target, uses in self.refs.items():
        n = sum(1 for _, _, k in uses if k == kind)
        if n:
            out[target] = n
    return out


def _data_range(self):
    seg = self.image.segment('__DATA')
    return seg.vmaddr, seg.vmaddr + seg.vmsize


def _image_end(self):
    return max(s.vmaddr + s.vmsize for s in self.image.segments)


Binary.pointer_size = 8
Binary.type_key = _type_key
Binary.fourcc_constants = _fourcc_constants
Binary.first_branch_target = _first_branch_target
Binary.constant_return_functions = _constant_return_functions
Binary.virtual_bool_check_globals = _virtual_bool_check_globals
Binary.call_result_stores = _call_result_stores
Binary.loads_by_width = _loads_by_width
Binary.data_range = _data_range
Binary.image_end = _image_end


# --------------------------------------------------------------------------- process access
def slice_uuid(binary: Binary) -> bytes:
    from .. import players
    return players.macho_uuid(binary.image._map[binary.image.slice_offset:binary.image.slice_offset + 16384])


def find_plugin_base(memory, binary: Binary) -> int | None:
    """Load address of `binary` in a live process: the executable region whose Mach-O header
    carries the same LC_UUID (no build pin involved). Reads only."""
    from .. import players
    want = slice_uuid(binary)
    for region in memory.regions():
        if not region.protection & 4:
            continue
        try:
            head = memory.read(region.start, 16384)
            if players.macho_uuid(head) == want:
                return region.start
        except Exception:  # noqa: BLE001 - not a Mach-O header / unreadable
            continue
    return None


def open_live(binary: Binary, pid: int | None = None):
    """(LiveMemory, base) of a running FM process that has `binary` loaded, else (None, reason)."""
    from .memory import LiveMemory, find_fm_process
    if pid is None:
        process = find_fm_process()
        if process is None:
            return None, 'no running Football Manager process'
        pid, executable = process.pid, process.executable
    else:
        executable = None
    memory = LiveMemory(pid, expected_executable=executable)
    base = find_plugin_base(memory, binary)
    if base is None:
        memory.close()
        return None, 'the running game has a different plugin build loaded'
    return memory, base


