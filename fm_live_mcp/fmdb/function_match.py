"""Function matching across two builds of the plugin, including functions the patch changed.

`address_map` finds an unchanged function by its masked fingerprint. A point release changes a
few thousand functions (10,389 of 118,168 between 27.0.0.2493426 and 27.0.1.2503222), and an
address inside one of them needs the same function found on the new build by other evidence.
`match(reference, target)` does that the way binary differs do: it starts from the functions
whose exported name is the same on both builds, then those whose fingerprint is unique on both
builds, and propagates from them, round by round, until nothing more is found:

  call graph   the same matched callers (as a set) and the same matched callees and imports in
               the same order
  callees      the same ordered matched callees and imports, when the callers do not decide
  callers      the same set of at least two matched callers
  call order   the k-th unmatched call of a matched caller, when the caller's calls align
               (matched callees and imports equal around it)
  vtable slot  slot i of a class vtable on both builds, when the slots around it agree
  data         the same referenced strings (by content) and matched globals
  imports      the same sequence of at least three imported calls
  neighbour    the only function between two matched neighbours on both builds (the linker
               keeps an object file's functions together and in order)
  similarity   inside such a gap, the pair whose masked instructions are most alike, when each
               is the other's best by a clear margin

A match is accepted only when it is unique and mutual: the evidence names one new function for
the old one and that old function for the new one (a signature held by exactly one unmatched
function on each side), and the two functions' masked instructions are not unrelated
(`similarity` at least FLOOR). Each match records its method and a confidence: the similarity of
the masked instruction multisets (1.0 for an unchanged function).

`align(reference, start, target, start2)` aligns the instructions of a matched pair (registers
and address fields masked, then a second pass with immediates masked inside unequal stretches)
and `carry(...)` takes an address inside the old function to its aligned instruction and
classifies the change at that instruction:

  same         the instruction is the same up to address fields
  registers    only register allocation differs
  offset       an immediate that is a structure offset or a size differs (ldr/str offsets,
               add immediates, mov sizes): the address resolves, and the change is recorded
  logic        anything else, or no aligned instruction: unresolved, with both windows
"""
from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import zlib

from .platform_macos_arm64 import _sx, adrp_page, is_adrp, page_use

LC_SYMTAB = 0x2
_EXPORTS: dict = {}     # {binary sha256: {exported name: function start}}


def exported_functions(binary) -> dict:
    """{symbol name: function start} of the external symbols the binary defines in its code
    (LC_SYMTAB, `nm -gU`). An exported name is stronger evidence than the masked fingerprint,
    which cannot tell apart accessors that differ only in the in-page offset of the global they
    load after the first use: 27.0.1 has `_i_characters_get_instance` with the fingerprint that
    `_i_translator_get_instance` had on 27.0.0, so the fingerprint alone paired those two."""
    import struct
    key = getattr(binary, 'sha256', None) or id(binary)
    if key in _EXPORTS:
        return _EXPORTS[key]
    image = binary.image
    mm, base = image._map, image.slice_offset
    ncmds = struct.unpack_from('<I', mm, base + 16)[0]
    p, out = base + 32, {}
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<II', mm, p)
        if cmd == LC_SYMTAB:
            symoff, nsyms, stroff, _strsize = struct.unpack_from('<IIII', mm, p + 8)
            for k in range(nsyms):
                strx, ntype, _sect, _desc, value = struct.unpack_from('<IBBHQ', mm, base + symoff + 16 * k)
                if ntype & 0xF0 or ntype & 0x0F != 0x0F:      # external, defined in a section, no stabs
                    continue
                if not binary.is_code(value):
                    continue
                bounds = binary.function_of(value)
                if bounds is None or bounds[0] != value:
                    continue
                start = base + stroff + strx
                out[mm[start:mm.find(b'\0', start)].decode('latin1')] = value
        p += size
    _EXPORTS[key] = out
    return out


FLOOR = 0.25            # minimum instruction similarity for a match from context
SIM_ACCEPT = 0.6        # minimum similarity for a match found by similarity alone
SIM_MARGIN = 0.1        # the best candidate must beat the second by this much
GAP_LIMIT = 24          # the largest gap of unmatched functions compared pairwise
ROUNDS = 12


# --------------------------------------------------------------------------- instruction tokens
def tokens(binary, start, end=None):
    """Masked instruction words of one function, as in `Binary.fingerprint`: ADRP pages, the page
    offsets paired with them, adr and literal-load offsets and branch targets leaving the
    function are hidden; a call or tail call to an import keeps the import's name (as a hash)."""
    cache = binary.__dict__.setdefault('_token_cache', {})
    key = (start, end)
    if key in cache:
        return cache[key]
    if end is None:
        end = binary.function_of(start)[1]
    words = binary.function_words(start, end)
    stubs = binary.image.stubs
    out = []
    pages = set()                   # registers holding an ADRP page (straight-line tracking)
    # registers that only ever hold an ADRP page in this function (hoisted into a callee-saved
    # register; restoring it from the frame in the epilogue does not count as a write)
    adrp_regs = {w & 31 for w in words if is_adrp(w)}
    if adrp_regs:
        other = set()
        for w in words:
            if not is_adrp(w) and not ((w >> 5) & 31 == 31 and (w & 0x3B000000) in (0x29000000, 0x28000000,
                                                                                     0x39000000, 0x38000000)):
                other.update(_gpr_written(w))
        fixed = adrp_regs - other
    else:
        fixed = set()
    for i, w in enumerate(words):
        pc = start + 4 * i
        if is_adrp(w):
            pages.add(w & 31)
            out.append(w & 0x9F00001F)
            continue
        masked = w
        for rd in pages | fixed:
            if page_use(w, rd) is not None:          # the page offset of a global: an address field
                masked = w & ~(0xFFF << 10)
                break
        written = _gpr_written(w)
        if written:
            pages.difference_update(written)
        top = w & 0xFC000000
        if top in (0x94000000, 0x14000000):
            target = pc + _sx(w & 0x3FFFFFF, 26) * 4
            name = stubs.get(target) if not start <= target < end else None
            masked = top | (zlib.crc32(name.encode()) & 0x3FFFFFF if name else 0)
        elif (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000:   # b.cond, cbz/cbnz
            masked = w & ~(0x7FFFF << 5)
        elif (w & 0x7E000000) == 0x36000000:                 # tbz/tbnz
            masked = w & ~(0x3FFF << 5)
        elif (w & 0x9F000000) == 0x10000000:                 # adr
            masked = w & 0x9F00001F
        elif (w & 0x3B000000) == 0x18000000:                 # ldr literal
            masked = w & 0xFF00001F
        out.append(masked)
    cache[key] = out
    return out


def _gpr_written(w):
    """General registers an instruction overwrites (approximate; calls clobber x0-x18 and lr)."""
    op0 = (w >> 25) & 0xF
    if op0 & 0b0101 == 0b0100:                               # loads and stores
        if (w >> 26) & 1:
            return ()                                        # SIMD/FP register
        if (w >> 27) & 7 == 0b101:                           # pairs: L bit
            return (w & 31, (w >> 10) & 31) if (w >> 22) & 1 else ()
        return (w & 31,) if (w >> 22) & 3 else ()
    if op0 in (0b1000, 0b1001) or op0 & 0b0111 == 0b0101:    # data processing
        return (w & 31,)
    if (w & 0xFC000000) == 0x94000000 or (w & 0xFFFFFC1F) == 0xD63F0000:
        return tuple(range(19)) + (30,)
    return ()


def reg_mask(w):
    """Bits of `w` that name registers (AArch64 encoding groups), to compare two instructions
    up to register allocation."""
    op0 = (w >> 25) & 0xF
    if op0 in (0b1000, 0b1001):                              # data processing, immediate
        op1 = (w >> 23) & 7
        if op1 in (0b000, 0b001, 0b101):                     # adr/adrp, move wide: Rd only
            return 0x1F
        if op1 == 0b111:                                     # extract: Rd, Rn, Rm
            return 0x3FF | (0x1F << 16)
        return 0x3FF                                         # add/sub, logical, bitfield
    if op0 & 0b0101 == 0b0100:                               # loads and stores
        m = 0x3FF
        if (w >> 27) & 7 == 0b101:                           # pairs: Rt2
            m |= 0x1F << 10
        if (w >> 27) & 7 == 0b111 and not (w >> 24) & 1 and (w >> 21) & 1:
            m |= 0x1F << 16                                  # register offset, atomics: Rm/Rs
        if (w >> 24) & 0x3F == 0b001000:                     # exclusive: Rs, Rt2
            m |= (0x1F << 16) | (0x1F << 10)
        return m
    if op0 & 0b0111 == 0b0101:                               # data processing, register
        m = 0x3FF | (0x1F << 16)
        if (w >> 24) & 0x1F == 0b11011:                      # 3-source: Ra
            m |= 0x1F << 10
        return m
    if op0 & 0b0111 == 0b0111:                               # SIMD and FP
        return 0x3FF | (0x1F << 16)
    if op0 in (0b1010, 0b1011):                              # branches, system
        if (w >> 25) & 0x3F in (0b011010, 0b011011):         # cbz/cbnz, tbz/tbnz
            return 0x1F
        if (w >> 25) & 0x7F == 0b1101011:                    # br/blr/ret
            return 0x1F << 5
    return 0


def frame_mask(w):
    """Immediate bits of `w` that name a stack-frame slot: a load or store based on sp or x29,
    an add/sub of sp. A patch that changes a function's frame moves every such offset; that is
    stack allocation, not a structure change."""
    rn = (w >> 5) & 31
    if rn not in (29, 31) and not ((w & 0x1F000000) == 0x11000000 and (w & 31) == 31):
        return 0
    if (w & 0x3B000000) == 0x39000000:                       # ldr/str unsigned offset
        return 0xFFF << 10
    if (w & 0x3B200000) == 0x38000000:                       # ldur/stur, pre/post index
        return 0x1FF << 12
    if (w & 0x3A000000) == 0x28000000:                       # ldp/stp
        return 0x7F << 15
    if (w & 0x1F000000) == 0x11000000:                       # add/sub immediate on sp
        return 0x1FFF << 10
    return 0


def _key(t, w):
    """Alignment token: masked instruction with registers and stack-frame offsets hidden."""
    return t & ~reg_mask(w) & ~frame_mask(w)


def shape(w):
    """`w` with registers and every immediate an offset or size could sit in masked: the
    instruction class only (used to align stretches whose immediates changed)."""
    w &= ~reg_mask(w)
    op0 = (w >> 25) & 0xF
    if op0 in (0b1000, 0b1001):
        return w & ~(0x3FFFF << 5) if (w >> 23) & 7 == 0b101 else w & ~(0xFFF << 10)
    if op0 & 0b0101 == 0b0100:
        return w & ~(0x7FFF << 10)                           # imm12 / imm9 / imm7 fields
    return w


# --------------------------------------------------------------------------- the graph
class _Side:
    """Call graph and references of one binary, by function start."""

    def __init__(self, binary):
        self.b = binary
        self.starts = binary.starts
        self.index = {s: i for i, s in enumerate(self.starts)}
        end = binary.text_start + binary.text_size
        self.ends = self.starts[1:] + [end]
        callers = defaultdict(set)
        callees = defaultdict(list)
        starts = self.starts
        for target, sites in binary.calls.items():
            for site in sites:
                i = bisect_right(starts, site) - 1
                if i < 0:
                    continue
                f = starts[i]
                callees[f].append((site, target))
                callers[target].add(f)
        for v in callees.values():
            v.sort()
        self.callers = callers
        self.callees = callees
        self.uses = {}                        # use pc -> data target
        for target, uses in binary.refs.items():
            for _adrp, use, _kind in uses:
                self.uses[use] = target
        self.use_pcs = sorted(self.uses)
        cs = None
        for seg in binary.image.segments:
            if seg.name == '__TEXT' and '__cstring' in seg.sections:
                cs = seg.sections['__cstring'][:2]
        self.cstring = cs
        self.fp = {s: binary.fingerprint(s) for s in self.starts}   # the cache key find_fingerprint uses

    def end(self, start):
        return self.ends[self.index[start]]

    def size(self, start):
        return (self.end(start) - start) // 4

    def refs(self, start):
        lo = bisect_left(self.use_pcs, start)
        hi = bisect_left(self.use_pcs, self.end(start))
        return [(pc, self.uses[pc]) for pc in self.use_pcs[lo:hi]]

    def string(self, target):
        if self.cstring and self.cstring[0] <= target < self.cstring[0] + self.cstring[1]:
            data = self.b.image.file_bytes(target, 256)
            return data.split(b'\0', 1)[0]
        return None


def similarity(r, a, t, b):
    """Multiset similarity of the register-masked instruction tokens of two functions (0..1)."""
    x = Counter(w & ~reg_mask(w) for w in tokens(r, a))
    y = Counter(w & ~reg_mask(w) for w in tokens(t, b))
    n = sum(x.values()) + sum(y.values())
    return 2 * sum((x & y).values()) / n if n else 1.0


class Match:
    """The function correspondence of two builds: `fwd` {old start: new start}, `bwd` the
    inverse, `how` {old start: (method, confidence, detail)}."""

    def __init__(self, reference, target):
        self.r, self.t = reference, target
        self.R, self.T = _Side(reference), _Side(target)
        self.fwd, self.bwd, self.how = {}, {}, {}
        self.dmap = {}
        self.stats = Counter()

    # ---------------------------------------------------------------- bookkeeping
    def _accept(self, a, b, method, detail='', confidence=None):
        if a in self.fwd or b in self.bwd:
            return False
        if confidence is None:
            confidence = similarity(self.r, a, self.t, b)
            if confidence < FLOOR:
                self.stats[f'{method}: refused below floor'] += 1
                return False
        self.fwd[a], self.bwd[b] = b, a
        self.how[a] = (method, round(confidence, 3), detail)
        self.stats[method] += 1
        return True

    def unmatched(self):
        return ([s for s in self.R.starts if s not in self.fwd], [s for s in self.T.starts if s not in self.bwd])

    # ---------------------------------------------------------------- exported names
    def exports(self, hide=()):
        """Functions exported under the same name on both builds (`exported_functions`), before
        any fingerprint pairing: the name decides even where the fingerprint is ambiguous."""
        mine, theirs = exported_functions(self.r), exported_functions(self.t)
        n = 0
        for name, a in mine.items():
            b = theirs.get(name)
            if b is None or a in hide or a not in self.R.fp or b not in self.T.fp:
                continue
            conf = 1.0 if self.R.fp[a] == self.T.fp[b] else similarity(self.r, a, self.t, b)
            n += self._accept(a, b, 'export', name, conf)
        return n

    # ---------------------------------------------------------------- exact
    def exact(self, hide=()):
        """Functions whose fingerprint is unique on both builds (`hide`: old starts held out, to
        measure how well the propagation finds them; see tests)."""
        mine, theirs = defaultdict(list), defaultdict(list)
        for s, fp in self.R.fp.items():
            mine[fp].append(s)
        for s, fp in self.T.fp.items():
            theirs[fp].append(s)
        for fp, a in mine.items():
            b = theirs.get(fp)
            if b and len(a) == 1 and len(b) == 1 and a[0] not in hide:
                self._accept(a[0], b[0], 'exact', 'unique fingerprint', 1.0)
        self._mine, self._theirs = mine, theirs

    def ranked(self):
        """Identical functions still unmatched after propagation: the same rank in address
        order, when both builds have equally many and they are long enough to matter."""
        from .platform_macos_arm64 import MIN_RANKED
        n = 0
        for fp, a in self._mine.items():
            b = self._theirs.get(fp, [])
            if len(a) == len(b) > 1 and fp[0] >= MIN_RANKED:
                left = [x for x in a if x not in self.fwd]
                right = [y for y in b if y not in self.bwd]
                if len(left) == len(right) == len(a):
                    for k, (x, y) in enumerate(zip(left, right)):
                        n += self._accept(x, y, 'rank', f'rank {k} of {len(a)} identical', 1.0)
        return n

    # ---------------------------------------------------------------- data correspondence
    def data_map(self):
        """{old global: new global} from the ADRP references of matched pairs whose
        instructions are equal under masking (same offsets inside the function)."""
        votes = defaultdict(set)
        R, T = self.R, self.T
        for a, b in self.fwd.items():
            if R.fp[a] != T.fp[b]:
                continue
            for pc, target in R.refs(a):
                other = T.uses.get(b + (pc - a))
                if other is not None:
                    votes[target].add(other)
        dmap = {k: next(iter(v)) for k, v in votes.items() if len(v) == 1}
        inverse = defaultdict(set)
        for k, v in dmap.items():
            inverse[v].add(k)
        self.dmap = {k: v for k, v in dmap.items() if len(inverse[v]) == 1}
        self.dmap_inv = {v: k for k, v in self.dmap.items()}

    # ---------------------------------------------------------------- signatures
    def _callees_sig(self, side, f, old):
        out = []
        stubs = side.b.image.stubs
        for _site, target in side.callees.get(f, ()):
            name = stubs.get(target)
            if name:
                out.append(('S', name))
                continue
            if old:
                m = self.fwd.get(target)
            else:
                m = target if target in self.bwd else None
            if m is not None:
                out.append(('F', m))
        return tuple(out)

    def _callers_sig(self, side, f, old):
        if old:
            return frozenset(self.fwd[c] for c in side.callers.get(f, ()) if c in self.fwd)
        return frozenset(c for c in side.callers.get(f, ()) if c in self.bwd)

    def _data_sig(self, side, f, old):
        out = []
        for _pc, target in side.refs(f):
            s = side.string(target)
            if s is not None and len(s) >= 4:
                out.append(('s', s))
            elif old and target in self.dmap:
                out.append(('d', self.dmap[target]))
            elif not old and target in self.dmap_inv:
                out.append(('d', target))
        return tuple(sorted(set(out)))

    def _join(self, method, sig_old, sig_new, ok=lambda s: True):
        left, right = self.unmatched()
        a_by, b_by = defaultdict(list), defaultdict(list)
        for a in left:
            s = sig_old(a)
            if s is not None and ok(s):
                a_by[s].append(a)
        for b in right:
            s = sig_new(b)
            if s is not None and ok(s):
                b_by[s].append(b)
        n = 0
        for s, a in a_by.items():
            b = b_by.get(s)
            if b and len(a) == 1 and len(b) == 1:
                n += self._accept(a[0], b[0], method, _describe(s))
        return n

    def by_call_graph(self):
        R, T = self.R, self.T

        def weight(s):
            callers, callees = s
            return len(callers) + sum(1 for k, _ in callees if k == 'F') + sum(1 for k, _ in callees if k == 'S') / 2 >= 2
        n = self._join('call graph', lambda a: (self._callers_sig(R, a, True), self._callees_sig(R, a, True)),
                       lambda b: (self._callers_sig(T, b, False), self._callees_sig(T, b, False)), weight)
        n += self._join('callees', lambda a: self._callees_sig(R, a, True), lambda b: self._callees_sig(T, b, False),
                        lambda s: sum(1 for k, _ in s if k == 'F') + sum(1 for k, _ in s if k == 'S') / 2 >= 2)
        n += self._join('callers', lambda a: self._callers_sig(R, a, True), lambda b: self._callers_sig(T, b, False),
                        lambda s: len(s) >= 2)
        return n

    def by_call_order(self):
        """Pairs the unmatched callees of each matched caller whose call sequences align."""
        R, T = self.R, self.T
        stubs_r, stubs_t = self.r.image.stubs, self.t.image.stubs
        votes = defaultdict(set)
        rvotes = defaultdict(set)
        for a, b in list(self.fwd.items()):
            ca, cb = R.callees.get(a, ()), T.callees.get(b, ())
            if not ca or not cb:
                continue
            ua = [t for _s, t in ca if t not in self.fwd and t not in stubs_r and t in R.index]
            if not ua:
                continue
            ta = [(('S', stubs_r[t]) if t in stubs_r else ('F', self.fwd[t]) if t in self.fwd else ('U',))
                  for _s, t in ca]
            tb = [(('S', stubs_t[t]) if t in stubs_t else ('F', t) if t in self.bwd else ('U',)) for _s, t in cb]
            sm = SequenceMatcher(None, ta, tb, autojunk=False)
            for op, i1, i2, j1, j2 in sm.get_opcodes():
                if op != 'equal':
                    continue
                for k in range(i2 - i1):
                    if ta[i1 + k] == ('U',):
                        x, y = ca[i1 + k][1], cb[j1 + k][1]
                        if x in R.index and y in T.index and y not in self.bwd:
                            votes[x].add((y, a))
                            rvotes[y].add(x)
        n = 0
        for x, ys in votes.items():
            cands = {y for y, _ in ys}
            if len(cands) == 1:
                y = cands.pop()
                if rvotes[y] == {x}:
                    callers = sorted({c for _, c in ys})
                    if len(callers) == 1 and similarity(self.r, x, self.t, y) < 2 * FLOOR:
                        self.stats['call order: one caller, refused below twice the floor'] += 1
                        continue
                    n += self._accept(x, y, 'call order', f'aligned call in {len(callers)} matched caller(s), '
                                                          f'e.g. {callers[0]:#x}')
        return n

    def by_vtable(self):
        r, t = self.r, self.t
        n = 0
        for name, entries in r.vtables.items():
            theirs = dict((off, ap) for ap, off in t.vtables.get(name, ()))
            for ap, off in entries:
                bp = theirs.get(off)
                if bp is None or len([1 for _a, o in entries if o == off]) != 1:
                    continue
                ra = _slots(r, ap)
                tb = _slots(t, bp)
                if len(ra) != len(tb):
                    continue
                for i, (x, y) in enumerate(zip(ra, tb)):
                    if x is None or y is None or x in self.fwd or y in self.bwd:
                        continue
                    if x not in self.R.index or y not in self.T.index:
                        continue
                    # neighbours in the vtable agree where they are matched
                    if any(ra[j] in self.fwd and self.fwd[ra[j]] != tb[j]
                           for j in (i - 1, i + 1) if 0 <= j < len(ra) and ra[j] is not None and tb[j] is not None):
                        continue
                    n += self._accept(x, y, 'vtable slot', f'{name} +{off:#x} slot {i}')
        return n

    def by_data(self):
        self.data_map()
        R, T = self.R, self.T
        return self._join('data', lambda a: self._data_sig(R, a, True), lambda b: self._data_sig(T, b, False),
                          lambda s: sum(1 for k, _ in s if k == 's') >= 1 or len(s) >= 2)

    def by_imports(self):
        R, T = self.R, self.T

        def sig(side, f):
            stubs = side.b.image.stubs
            s = tuple(stubs[t] for _site, t in side.callees.get(f, ()) if t in stubs)
            return s if len(s) >= 3 else None
        return self._join('imports', lambda a: sig(R, a), lambda b: sig(T, b))

    def gaps(self):
        """[(old functions, new functions, lower matched pair)] between consecutive matched
        functions that keep their order on both builds."""
        R, T = self.R, self.T
        anchors = [(a, self.fwd[a]) for a in R.starts if a in self.fwd]
        out = []
        prev = None
        for a, b in anchors:
            if prev is not None and prev[1] < b:
                i0, i1 = R.index[prev[0]] + 1, R.index[a]
                j0, j1 = T.index[prev[1]] + 1, T.index[b]
                if i1 > i0 and j1 > j0:
                    out.append((R.starts[i0:i1], T.starts[j0:j1], prev))
            prev = (a, b)
        return out

    def by_neighbours(self):
        n = 0
        for left, right, (pa, _pb) in self.gaps():
            left = [x for x in left if x not in self.fwd]
            right = [y for y in right if y not in self.bwd]
            if len(left) == 1 and len(right) == 1:
                n += self._accept(left[0], right[0], 'neighbour', f'only unmatched function after {pa:#x} on both builds')
        return n

    def by_similarity(self):
        n = 0
        for left, right, (pa, _pb) in self.gaps():
            left = [x for x in left if x not in self.fwd]
            right = [y for y in right if y not in self.bwd]
            if not left or not right or len(left) * len(right) > GAP_LIMIT * GAP_LIMIT:
                continue
            score = {(x, y): similarity(self.r, x, self.t, y) for x in left for y in right}
            for x in left:
                row = sorted(((score[x, y], y) for y in right), reverse=True)
                best, y = row[0]
                second = row[1][0] if len(row) > 1 else 0.0
                col = sorted((score[z, y] for z in left if z != x), reverse=True)
                other = col[0] if col else 0.0
                if best >= SIM_ACCEPT and best - second >= SIM_MARGIN and best - other >= SIM_MARGIN:
                    n += self._accept(x, y, 'similarity', f'best of {len(right)} in the gap after {pa:#x}', best)
        return n

    def run(self, log=None, hide=()):
        self.exports(hide)
        self.exact(hide)
        for rnd in range(ROUNDS):
            got = Counter()
            for name, step in (('call graph', self.by_call_graph), ('call order', self.by_call_order),
                               ('vtable', self.by_vtable), ('data', self.by_data), ('imports', self.by_imports),
                               ('neighbour', self.by_neighbours)):
                got[name] = step()
            if not sum(got.values()):
                got['similarity'] = self.by_similarity()
                if not got['similarity']:
                    got['rank'] = self.ranked()
                    if not got['rank']:
                        break
            if log:
                log(f'    round {rnd}: {dict(+got)}; matched {len(self.fwd)} of {len(self.R.starts)}')
        self.data_map()
        return self


def _slots(binary, ap, limit=600):
    out = []
    for i in range(limit):
        s = binary.slot(ap, i)
        if s is None:
            if (ap + 8 * i) in binary.image.binds:
                out.append(None)
                continue
            break
        if not binary.is_code(s):
            break
        out.append(s)
    return out


def _describe(sig):
    text = repr(sig)
    return text if len(text) < 120 else text[:117] + '...'


# --------------------------------------------------------------------------- alignment
CONTEXTS = ((4, 4), (8, 0), (0, 8), (3, 3), (6, 0), (0, 6), (2, 2))
POSITIONAL = 8          # an unequal stretch is paired position by position only up to this length
CONTEXT_ALIGNED = {}    # {(old function, index): context length} of sites aligned by unique context


def identities(match, old, start):
    """{instruction index: identity} of the calls and data references of one function whose
    counterpart is known: a call to a matched function, a reference to a mapped global or to a
    string (by content). Old and new functions get equal identities for corresponding targets."""
    memo = match.__dict__.setdefault('_identities', {})
    if (old, start) in memo:
        return memo[old, start]
    side = match.R if old else match.T
    if not match.dmap:
        match.data_map()
    out = memo[old, start] = {}
    for site, target in side.callees.get(start, ()):
        if target in side.b.image.stubs:
            continue
        ident = match.fwd.get(target) if old else (target if target in match.bwd else None)
        if ident is not None:
            out[(site - start) // 4] = ('call', ident)
    for pc, target in side.refs(start):
        s = side.string(target)
        if s is not None and len(s) >= 4:
            out[(pc - start) // 4] = ('str', s)
            continue
        ident = match.dmap.get(target) if old else (target if target in match.dmap_inv else None)
        if ident is not None:
            out[(pc - start) // 4] = ('data', ident)
    return out


def align(reference, a, target, b, *, sites=None, match=None, blind=()):
    """{i: j} aligned instruction indexes of two matched functions (old index i has no
    counterpart when it is absent).

    1. Sequence alignment (difflib) of the tokens with registers and stack-frame offsets
       masked; inside an unequal stretch of equal length up to POSITIONAL instructions,
       position by position; otherwise a second alignment on the instruction class
       (immediates masked too).
    2. For the old instructions in `sites` (all when None) that step 1 leaves out, typically
       because the compiler moved a basic block: the instruction whose context is unique in the
       new function, with the instruction itself compared by class only. Contexts tried, as
       (instructions before, after): (4, 4), (8, 0), (0, 8), (3, 3), (6, 0), (0, 6), (2, 2); the
       first whose key occurs exactly once on both sides wins.
    With `match`, a call to a matched function and a reference to a mapped global or a string
    align only with the call or reference to its counterpart (`identities`)."""
    cache = getattr(reference, '_align_cache', None)
    if cache is None or blind:
        cache = {} if blind else reference.__dict__.setdefault('_align_cache', {})
    ck = (a, b, match is not None)
    if ck in cache:
        out, ka, kb, sa, sb = cache[ck]
    else:
        ta, tb = tokens(reference, a), tokens(target, b)
        wa = reference.function_words(a, a + 4 * len(ta))
        wb = target.function_words(b, b + 4 * len(tb))
        ka = [_key(t, w) for t, w in zip(ta, wa)]
        kb = [_key(t, w) for t, w in zip(tb, wb)]
        if match is not None:                          # calls and references by what they name
            for i, ident in identities(match, True, a).items():
                if i not in blind:                     # (blind: held out, to measure the alignment)
                    ka[i] = ident
            for j, ident in identities(match, False, b).items():
                kb[j] = ident
        sa = [shape(w) & ~frame_mask(w) for w in wa]
        sb = [shape(w) & ~frame_mask(w) for w in wb]
        out = {}
        sm = SequenceMatcher(None, ka, kb, autojunk=False)
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == 'equal':
                for k in range(i2 - i1):
                    out[i1 + k] = j1 + k
            elif op == 'replace':
                if i2 - i1 == j2 - j1 <= POSITIONAL:
                    for k in range(i2 - i1):
                        out[i1 + k] = j1 + k
                else:                                  # second pass on the instruction class only
                    inner = SequenceMatcher(None, sa[i1:i2], sb[j1:j2], autojunk=False)
                    for op2, x1, x2, y1, y2 in inner.get_opcodes():
                        if op2 == 'equal' or (op2 == 'replace' and x2 - x1 == y2 - y1 <= POSITIONAL):
                            for k in range(x2 - x1):
                                out[i1 + x1 + k] = j1 + y1 + k
        cache[ck] = (out, ka, kb, sa, sb)
    missing = [i for i in (range(len(ka)) if sites is None else sites) if 0 <= i < len(ka) and i not in out]
    if not missing:
        return out
    out = dict(out)
    taken = set(out.values())
    contexts = {} if blind else reference.__dict__.setdefault('_context_cache', {})
    ck = (a, b, match is not None)
    for before, after in CONTEXTS:
        if not missing:
            break

        def key(k, s, i):
            if i - before < 0 or i + after >= len(k):
                return None
            return (tuple(k[i - before:i]), s[i], tuple(k[i + 1:i + 1 + after]))
        if (*ck, before, after) not in contexts:
            mine, theirs = Counter(), {}
            for i in range(len(ka)):
                x = key(ka, sa, i)
                if x is not None:
                    mine[x] += 1
            for j in range(len(kb)):
                y = key(kb, sb, j)
                if y is not None:
                    theirs[y] = -1 if y in theirs else j
            contexts[*ck, before, after] = (mine, theirs)
        mine, theirs = contexts[*ck, before, after]
        left = []
        for i in missing:
            x = key(ka, sa, i)
            j = theirs.get(x, -1) if x is not None and mine[x] == 1 else -1
            if j >= 0 and j not in taken:
                out[i] = j
                taken.add(j)
                CONTEXT_ALIGNED[a, i] = before + after
            else:
                left.append(i)
        missing = left
    return out


def bracketed(match, a, b, pairs, i, j):
    """Whether the aligned pair (i, j) sits between the nearest calls or references around i
    whose counterparts align with the same identity: the one before i at an index below j, the
    one after above it (one side suffices at the start or end of a function). Returns
    (ok, detail)."""
    mine, theirs = identities(match, True, a), identities(match, False, b)
    below = [k for k in mine if k < i]
    above = [k for k in mine if k > i]
    lo = max(below) if below else None
    hi = min(above) if above else None
    checks = []
    for k in (lo, hi):
        if k is None:
            continue
        jk = pairs.get(k)
        ok = jk is not None and theirs.get(jk) == mine[k] and ((jk < j) if k < i else (jk > j))
        checks.append(ok)
    if not checks:
        return True, 'no call or reference in the function to confirm the alignment'
    if all(checks):
        return True, f'between anchors at {lo} and {hi}'
    return False, f'the calls or references around instruction {i} do not align around {j}'


def _predecessors(binary, start, end):
    """{instruction address: [predecessor addresses]} of one function (straight-line flow and
    branch targets inside the function; returns and indirect branches end a path)."""
    cache = binary.__dict__.setdefault('_pred_cache', {})
    if (start, end) in cache:
        return cache[start, end]
    preds = defaultdict(list)
    for pc in range(start, end, 4):
        w = binary.word(pc)
        targets, falls = [], True
        if (w & 0xFC000000) == 0x14000000:                       # b
            targets, falls = [pc + _sx(w & 0x3FFFFFF, 26) * 4], False
        elif (w & 0xFF000010) == 0x54000000 or (w & 0x7E000000) == 0x34000000:   # b.cond, cbz/cbnz
            targets = [pc + _sx((w >> 5) & 0x7FFFF, 19) * 4]
        elif (w & 0x7E000000) == 0x36000000:                     # tbz/tbnz
            targets = [pc + _sx((w >> 5) & 0x3FFF, 14) * 4]
        elif (w & 0xFE1FFC1F) == 0xD61F0000 and (w >> 21) & 3 in (0, 2):   # br, ret
            falls = False
        for target in targets:
            if start <= target < end:
                preds[target].append(pc)
        if falls and pc + 4 < end:
            preds[pc + 4].append(pc)
    cache[start, end] = preds
    return preds


def page_base(binary, start, at, reg, limit=4000, depth=0):
    """True when every definition of `reg` that reaches the instruction at `at` (searching the
    function's flow backwards) is an ADRP, or a copy (`mov`) or an `add #imm` of a register
    whose reaching definitions are: the instruction's offset is then part of a global's address
    (an address field), not a structure offset."""
    if depth > 4:
        return False
    end = binary.function_of(start)[1]
    preds = _predecessors(binary, start, end)
    seen, todo, defs = set(), list(preds.get(at, ())), 0
    while todo and len(seen) < limit:
        q = todo.pop()
        if q in seen:
            continue
        seen.add(q)
        w = binary.word(q)
        if is_adrp(w) and (w & 31) == reg:
            defs += 1
            continue
        if reg in _gpr_written(w):
            if (w >> 5) & 31 == 31 and (w & 0x3A000000) == 0x28000000:            # ldp from the frame
                continue
            if (w & 0xFFE0FFE0) == 0xAA0003E0 and (w & 31) == reg:               # mov reg, xm
                src = (w >> 16) & 31
            elif (w & 0xFF800000) == 0x91000000 and (w & 31) == reg:             # add reg, xn, #imm
                src = (w >> 5) & 31
            else:
                return False
            if src == 31 or not page_base(binary, start, q, src, limit, depth + 1):
                return False
            defs += 1
            continue
        if q == start:
            return False                                         # an argument reaches the site
        todo.extend(preds.get(q, ()))
    return defs > 0 and not todo

def section_shifts(match):
    """{(segment, section): shift} of data sections whose mapped globals (the data map) almost
    all moved by one amount (at least 90 percent of them)."""
    cached = getattr(match, '_section_shifts', None)
    if cached is not None:
        return cached
    if not match.dmap:
        match.data_map()
    by = defaultdict(Counter)
    r = match.r
    bounds = []
    for seg in r.image.segments:
        for name, (start, size, *_x) in seg.sections.items():
            bounds.append((start, start + size, seg.name, name))
    for old, new in match.dmap.items():
        for lo, hi, seg, name in bounds:
            if lo <= old < hi:
                by[seg, name][new - old] += 1
                break
    out = {}
    for key, c in by.items():
        shift, n = c.most_common(1)[0]
        if n >= 0.9 * sum(c.values()) and n >= 5:
            out[key] = (shift, bounds_of(bounds, key))
    match._section_shifts = out
    return out


def bounds_of(bounds, key):
    return next((lo, hi) for lo, hi, seg, name in bounds if (seg, name) == key)


def global_offset(match, a, b, old, new):
    """True when `old` and `new` are the page offsets of one global on the two builds: some ADRP
    page P of the old function and P' of the new one give P + old and P' + new that the data
    map (or the shift of the section holding P + old) relates."""
    r, t = match.r, match.t
    pages_a = {adrp_page(w, a + 4 * i) for i, w in enumerate(r.function_words(a)) if is_adrp(w)}
    if not pages_a:
        return False
    pages_b = {adrp_page(w, b + 4 * i) for i, w in enumerate(t.function_words(b)) if is_adrp(w)}
    shifts = section_shifts(match)
    for p in pages_a:
        x = p + old
        y = match.dmap.get(x)
        if y is None:
            for _key, (shift, (lo, hi)) in shifts.items():
                if lo <= x < hi:
                    y = x + shift
                    break
        if y is not None and (y - new) in pages_b and (y - new) % 0x1000 == 0:
            return True
    return False


def _imm_change(wa, wb):
    """(kind, old, new, base register) when two instructions of the same class differ only in an
    offset or size immediate (registers may differ too), else None."""
    ra, rb = wa & ~reg_mask(wa), wb & ~reg_mask(wb)
    if (wa & 0x3B000000) == 0x39000000 and (wa ^ wb) & ~0x3FFFFF & ~reg_mask(wa) == 0 and \
            (wb & 0x3B000000) == 0x39000000 and (wa >> 22) & 3 == (wb >> 22) & 3:
        size, simd, opc = wa >> 30, (wa >> 26) & 1, (wa >> 22) & 3
        if simd and opc & 2:
            size = 4
        return 'ldst', ((wa >> 10) & 0xFFF) << size, ((wb >> 10) & 0xFFF) << size, (wa >> 5) & 31, (wb >> 5) & 31
    if (wa & 0x3B200C00) == 0x38000000 and (rb & ~(0x1FF << 12)) == (ra & ~(0x1FF << 12)):   # ldur/stur
        return 'ldst', _sx((wa >> 12) & 0x1FF, 9), _sx((wb >> 12) & 0x1FF, 9), (wa >> 5) & 31, (wb >> 5) & 31
    if (wa & 0x3A000000) == 0x28000000 and (rb & ~(0x7F << 15)) == (ra & ~(0x7F << 15)):     # ldp/stp
        scale = 2 + (wa >> 31) if not (wa >> 26) & 1 else 2 + (wa >> 30)
        return 'pair', _sx((wa >> 15) & 0x7F, 7) << scale, _sx((wb >> 15) & 0x7F, 7) << scale, \
            (wa >> 5) & 31, (wb >> 5) & 31
    if (wa & 0x1F000000) == 0x11000000 and (rb & ~(0x1FFF << 10)) == (ra & ~(0x1FFF << 10)):  # add/sub imm
        sh = 12 if (wa >> 22) & 1 else 0
        shb = 12 if (wb >> 22) & 1 else 0
        return 'add', ((wa >> 10) & 0xFFF) << sh, ((wb >> 10) & 0xFFF) << shb, (wa >> 5) & 31, (wb >> 5) & 31
    if (wa & 0x1F800000) == 0x12800000 and (rb & ~(0x3FFFFF << 5)) == (ra & ~(0x3FFFFF << 5)):  # mov wide
        hw = (wa >> 21) & 3
        return 'mov', ((wa >> 5) & 0xFFFF) << (16 * hw), ((wb >> 5) & 0xFFFF) << (16 * ((wb >> 21) & 3)), None, None
    return None


def classify(reference, a, va, target, b, vb, match=None):
    """How the instruction at old address `va` (in function `a`) and its aligned instruction at
    `vb` (in `b`) differ: ('same' | 'registers' | 'stack' | 'offset' | 'logic', detail dict).
    'stack': only a stack-frame slot (and registers) differs."""
    wa, wb = reference.word(va), target.word(vb)
    ta = tokens(reference, a)[(va - a) // 4]
    tb = tokens(target, b)[(vb - b) // 4]
    if match is not None:
        x = identities(match, True, a).get((va - a) // 4)
        y = identities(match, False, b).get((vb - b) // 4)
        if x is not None and y is not None and x != y:
            return 'logic', {'why': f'names a different {x[0]} on this build'}
    if ta == tb:
        return 'same', {}
    if ta & ~reg_mask(wa) == tb & ~reg_mask(wb):
        return 'registers', {}
    if frame_mask(wa) and _key(ta, wa) == _key(tb, wb):
        return 'stack', {}
    imm = _imm_change(wa, wb)
    if imm is not None:
        kind, old, new, base_a, base_b = imm
        if kind in ('ldst', 'add') and (page_base(reference, a, va, base_a) and page_base(target, b, vb, base_b)
                                        or match is not None and global_offset(match, a, b, old, new)):
            return 'same', {'page_offset': [old, new]}               # a global's page offset: an address field
        return 'offset', {'kind': kind, 'old': old, 'new': new, 'base': base_a, 'base_new': base_b}
    return 'logic', {}


def window(binary, at, before=4, after=4):
    """Hex words around `at` (the site marked with '>')."""
    lo = binary.function_of(at)
    out = []
    for k in range(-before, after + 1):
        pc = at + 4 * k
        if lo and lo[0] <= pc < lo[1]:
            out.append(f'{">" if k == 0 else " "}{pc:#x}: {binary.word(pc):08x}')
    return out


def carry_data(match: Match, v):
    """Carry the old data address `v` through the references of matched functions: (new address,
    method, confidence, detail) or None. `data` when the ADRP references of matched functions
    whose instructions are unchanged agree on one counterpart (the same correspondence the
    `data` signature uses); `aligned xref` when the references of matched changed functions,
    taken at their aligned instructions, all name one global."""
    if not match.dmap:
        match.data_map()
    if v in match.dmap:
        return match.dmap[v], 'data-match', 1.0, 'ADRP references of matched functions with equal instructions agree'
    r = match.r
    found, seen = [], 0
    for _adrp, use, _kind in r.refs.get(v, ()):
        bounds = r.function_of(use)
        if bounds is None or bounds[0] not in match.fwd:
            continue
        a, b = bounds[0], match.fwd[bounds[0]]
        i = (use - a) // 4
        pairs = align(r, a, match.t, b, sites=[i], match=match)
        j = pairs.get(i)
        seen += 1
        if j is None or not bracketed(match, a, b, pairs, i, j)[0]:
            continue
        cls, _info = classify(r, a, use, match.t, b, b + 4 * j, match)
        if cls not in ('same', 'registers', 'stack'):
            continue
        new = match.T.uses.get(b + 4 * j)
        if new is not None:
            found.append((new, match.how[a][1]))
    values = {n for n, _c in found}
    if len(values) == 1:
        conf = min(c for _n, c in found)
        return values.pop(), 'aligned-xref', conf, f'aligned ADRP reference in {len(found)} of {seen} matched function(s)'
    return None


def carry(match: Match, v):
    """Carry the old code address `v` to the new build: (new address | None, method, confidence,
    detail, change) where change is None or {'class': ..., ...} for a site that differs."""
    r, t = match.r, match.t
    bounds = r.function_of(v)
    if bounds is None:
        return None, 'unresolved', 0.0, 'outside every function', None
    a = bounds[0]
    b = match.fwd.get(a)
    if b is None:
        return None, 'unresolved', 0.0, f'function {a:#x} has no unique, mutual match on this build', None
    method, conf, detail = match.how[a]
    i = (v - a) // 4
    if v % 4:
        return None, 'unresolved', conf, 'not an instruction boundary', None
    if match.R.fp[a] == match.T.fp[b]:                 # the same code: the same offset
        return b + 4 * i, method, conf, f'{detail}; function {a:#x} -> {b:#x} unchanged, +{v - a:#x}', None
    pairs = align(r, a, t, b, sites=[i], match=match)
    j = pairs.get(i)
    if j is None:
        change = {'class': 'logic', 'old_window': window(r, v), 'new_window': [],
                  'why': 'the instruction has no aligned counterpart (deleted or rewritten)'}
        return None, 'unresolved', conf, f'{method} match of {a:#x} -> {b:#x}; no aligned instruction', change
    ok, why = bracketed(match, a, b, pairs, i, j)
    if not ok and CONTEXT_ALIGNED.get((a, i), 0) >= 8:
        ok, why = True, f'{why}, but its {CONTEXT_ALIGNED[a, i]} neighbouring instructions are unique in both functions'
    if not ok and i == 0:
        ok, why = True, 'the start of the matched function'
    if not ok:
        change = {'class': 'unconfirmed', 'old_window': window(r, v), 'new_window': window(t, b + 4 * j), 'why': why}
        return None, 'unresolved', conf, f'{method} match of {a:#x} -> {b:#x}; {why}', change
    vb = b + 4 * j
    cls, info = classify(r, a, v, t, b, vb, match)
    change = None
    if cls != 'same':
        change = {'class': cls, **info}
    if cls == 'logic':
        change.update(old_window=window(r, v), new_window=window(t, vb))
        return None, 'unresolved', conf, f'{method} match of {a:#x} -> {b:#x}; the instruction changed', change
    return vb, method, conf, f'{detail}; function {a:#x} -> {b:#x}, instruction {i} -> {j} ({cls}; {why})', change


# --------------------------------------------------------------------------- structure changes
def this_registers(binary, start, upto):
    """Registers that hold the function's first argument (`this` for a method) at `upto`, by a
    straight-line scan from the start: x0, plus every register copied from one that holds it
    (`mov xd, xn`), minus registers written otherwise and the caller-saved ones after a call.
    Control flow is ignored, so this answers only for code before the first join; callers use
    it as "the base is `this`" evidence, never as proof."""
    held = {0}
    for pc in range(start, upto, 4):
        w = binary.word(pc)
        if (w & 0xFFE0FFE0) == 0xAA0003E0:                       # mov xd, xm (orr xd, xzr, xm)
            rd, rm = w & 31, (w >> 16) & 31
            if rm in held:
                held.add(rd)
            else:
                held.discard(rd)
            continue
        if (w & 0xFC000000) == 0x94000000 or (w & 0xFFFFFC1F) == 0xD63F0000:   # bl / blr
            held -= set(range(0, 19))
            continue
        if (w & 0x3B000000) == 0x39000000 or (w & 0x3B200000) == 0x38000000:   # ldr/str (imm)
            if (w >> 22) & 1:                                    # a load writes Rt
                held.discard(w & 31)
            continue
        if (w & 0x3A000000) == 0x28000000:                       # ldp/stp
            if (w >> 22) & 1:
                held.discard(w & 31)
                held.discard((w >> 10) & 31)
            continue
        if (w >> 26) & 0b111 == 0b101 and (w >> 29) & 3 != 0b11 or (w & 0x1F) == 31:
            continue                                             # branches; writes to xzr/sp
        held.discard(w & 31)
    return held


def owners(match, a):
    """Classes whose vtable holds the pinned function `a` (any slot), by mangled name."""
    index = getattr(match, '_owner_index', None)
    if index is None:
        index = defaultdict(set)
        r = match.r
        for name, entries in r.vtables.items():
            for ap, off in entries:
                for s in _slots(r, ap, 400):
                    if s is not None:
                        index[s].add(name)
        match._owner_index = index
    return sorted(index.get(a, ()))


def offset_changes(match, max_size=6000):
    """Every load, store or add-immediate whose offset differs between the aligned instructions
    of matched changed functions (stack-frame offsets left out): [{function, new_function, at,
    new_at, kind, old, new, base, this, owners}] for code where the base register's type can
    be told from the function (`this` of a method) and where it cannot."""
    r, t = match.r, match.t
    out = []
    for a, b in match.fwd.items():
        if match.R.fp[a] == match.T.fp[b]:
            continue
        na, nb = match.R.size(a), match.T.size(b)
        if na > max_size or nb > max_size:
            continue
        if na == nb:
            pairs = {i: i for i in range(na)}
        else:
            pairs = align(r, a, t, b, match=match)
        for i, j in pairs.items():
            va, vb = a + 4 * i, b + 4 * j
            wa, wb = r.word(va), t.word(vb)
            if wa == wb or frame_mask(wa) or frame_mask(wb):
                continue
            cls, info = classify(r, a, va, t, b, vb, match)
            if cls != 'offset':
                continue
            kind, old, new, base = info['kind'], info['old'], info['new'], info['base']
            if old == new or kind == 'mov':
                continue
            if ta_tb_differ_beyond(r, a, va, t, b, vb, kind):
                continue
            out.append({'function': a, 'new_function': b, 'at': va, 'new_at': vb, 'kind': kind, 'old': old,
                        'new': new, 'base': base, 'this': base in this_registers(r, a, va)})
    return out


def ta_tb_differ_beyond(reference, a, va, target, b, vb, kind):
    """True when the two instructions differ in more than the offset and registers (a different
    opcode, size or sign extension): then it is not the same access with a moved field."""
    wa, wb = reference.word(va), target.word(vb)
    keep = {'ldst': 0xFFC00000, 'pair': 0xFFC00000, 'add': 0xFF800000}[kind]
    return (wa & keep) != (wb & keep)
