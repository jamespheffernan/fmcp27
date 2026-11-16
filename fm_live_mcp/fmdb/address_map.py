"""The per-build address map: every plugin address the reader uses, found again on another build.

`derive(target, reference, census)` takes the plugin of the new build (`target`), the plugin of
the pinned build (`reference`, preserved under fmdb-runtime-research/builds/<version>/) and the
address census of the source tree (address_census.py), and returns
{pinned value: Resolution} for every literal the census marks as an address. Nothing is read
from a running game. A value is resolved only by a method that identifies the same thing on
both builds; anything else is left unresolved with the reason, and the address book makes the
code that uses it refuse.

Methods, in the order tried (`Resolution.method`):

  named        the fmdb core's named anchor for the same pinned value (anchors.resolve: RTTI,
               code shape, fingerprints, live type scan when given)
  rtti         a vtable address point by class name and subobject offset; a type_info by name
  stub         an import stub by the imported symbol
  section      a section start or end by segment and section name
  export       the containing function by its exported symbol name, when its masked code is
               unchanged (before the fingerprint: a fingerprint twin is never taken for an
               exported function)
  export-xref  a data address as the same reference of the functions exported under the same
               names, when their masked code is unchanged (before `xref`)
  fingerprint  the containing function by its masked fingerprint (unique on both builds, or the
               same rank among identical functions above MIN_RANKED instructions), plus the
               offset inside it
  vtable-slot  a function that sits in slot i of a class vtable: slot i of that class on the
               new build, accepted when the fingerprints agree
  callee       a function called from a uniquely fingerprinted function as its k-th call: the
               k-th call of that function on the new build, accepted when the fingerprints agree
  neighbour    a function next to (up to 3 functions away from) a uniquely fingerprinted one,
               at the same distance on the new build, accepted when the fingerprints agree
  xref         a data address as the n-th ADRP reference of an unchanged, uniquely fingerprinted
               function (up to five referencing functions, which must agree)
  content      a constant in __TEXT (a string, a jump table) by its bytes, unique in the same
               section of the new build
  vtable+off   an address inside a vtable (a slot) or a type_info: the resolved object plus the
               same offset
  page         the 4 KiB page of another address of the same file that resolved
  range        a range bound: the same offset inside the same section, when the section is at
               least that large on the new build (sanity bounds, never dereferenced)

Methods for code the patch changed, through the whole-binary function match
(function_match.py; `Resolution.confidence` is the similarity of the matched functions):

  match:<how>        an address in a function matched by call graph, callees, callers, call
                     order, vtable slot, data, imports, neighbour, similarity or rank: the aligned
                     instruction, accepted when the calls and references around it align too
                     (or its 8 neighbouring instructions are unique in both functions, or it is
                     the function's start); `Resolution.change` records how the instruction
                     differs (registers, stack, offset) and, for an unresolved site, both
                     instruction windows
  match:data-match   a global named by matched functions whose instructions are equal
  match:aligned-xref a global named by the aligned reference of matched changed functions
  match:bracketed    `bracketed` with neighbours resolved through the match
  match:local-shift  a constant in __TEXT between two that moved by the same amount, with the
                     same bytes at the moved place

`strict=True` (used to prove the procedure on the pinned build itself) refuses the one
shortcut that relies on the pinned number: a short function matched "at the same address".

Reviewed by hand, per build (`builds.<plugin sha256>` in data/address_overrides.json):

  reviewed     `values`: an address the methods left unresolved or carried to the wrong
               instruction, read by hand from both builds' code, with the evidence. It replaces
               whatever the methods found.
  guards       `guards`: a native guard whose code changed but whose meaning for the decoder was
               established by comparing both builds' code (`registers`: the same computation with
               another register allocation or instruction order; `shape`: the same fields read
               through different code; `ported`: the logic changed and the reader's port follows
               the new build). The guard is re-derived from the new build's bytes at
               the reviewed address, only when the address map puts the span exactly there.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
import hashlib

from . import anchors
from .address_census import section_bounds

NEIGHBOURS = 3


@dataclass
class Resolution:
    value: int | None
    method: str
    detail: str = ''
    confidence: float | None = None     # matched-function methods: similarity of the two functions
    change: dict | None = None          # the instruction at the site differs (function_match.classify)

    def public(self):
        out = {'value': self.value, 'method': self.method, 'detail': self.detail}
        if self.confidence is not None:
            out['confidence'] = self.confidence
        if self.change is not None:
            out['change'] = self.change
        return out


class _Functions:
    """Fingerprint lookups shared by the code methods (cached per binary pair)."""

    def __init__(self, target, reference, strict, log=None):
        self.t, self.r, self.strict = target, reference, strict
        self._located = {}
        self._match = None
        self.log = log

    def match(self):
        """The whole-binary function correspondence (function_match.Match), built on first use."""
        if self._match is None:
            from . import function_match
            import time
            t = time.time()
            self._match = function_match.Match(self.r, self.t).run(log=self.log)
            if self.log:
                self.log(f'  function match: {len(self._match.fwd)} of {len(self._match.R.starts)} pinned functions '
                         f'matched ({time.time() - t:.0f}s)')
        return self._match

    def bounds(self, binary, rva):
        b = binary.function_of(rva)
        return b if b and binary.is_code(rva) else None

    def unique_map(self, start):
        """Start of the same function on the target by fingerprint alone, or None (with why)."""
        if start in self._located:
            return self._located[start]
        fp = self.r.fingerprint(start)
        mine = self.r.find_fingerprint(fp)
        theirs = self.t.find_fingerprint(fp)
        out = None
        if not theirs:
            out = (None, 'function changed (no function with its fingerprint on this build)')
        elif len(mine) == 1 and len(theirs) == 1:
            if fp[0] >= anchors.MIN_UNIQUE or (not self.strict and theirs[0] == start):
                out = (theirs[0], f'unique fingerprint ({fp[0]} instructions)')
            else:
                out = (None, f'fingerprint unique but the function is too short to trust ({fp[0]} instructions)')
        elif len(mine) == len(theirs) and fp[0] >= anchors.MIN_RANKED:
            rank = mine.index(start)
            out = (theirs[rank], f'rank {rank} of {len(mine)} identical functions')
        else:
            out = (None, f'no unique fingerprint ({len(mine)} identical on the pinned build, {len(theirs)} here, '
                         f'{fp[0]} instructions)')
        self._located[start] = out
        return out

    def same(self, ref_start, tgt_start):
        return tgt_start is not None and self.t.function_of(tgt_start) and \
            self.t.function_of(tgt_start)[0] == tgt_start and \
            self.r.fingerprint(ref_start) == self.t.fingerprint(tgt_start)

    def slot_index(self):
        """{function: [(class, subobject offset, slot)]} of the pinned build's vtables."""
        if getattr(self, '_slots', None) is None:
            r, index = self.r, defaultdict(list)
            for name, entries in r.vtables.items():
                for ap, off in entries:
                    for i in range(0, 600):
                        slot = r.slot(ap, i)
                        if slot is None:
                            if (ap + 8 * i) in r.image.binds:
                                continue
                            break
                        if not r.is_code(slot):
                            break
                        index[slot].append((name, off, i))
            self._slots = index
        return self._slots

    def by_vtable_slot(self, start):
        t = self.t
        for name, off, i in self.slot_index().get(start, ())[:16]:
            tv = t.vtable(name, off)
            cand = t.slot(tv, i) if tv is not None else None
            if self.same(start, cand):
                return cand, f'{name} +{off:#x} vtable slot {i}'
        return None

    def by_callee(self, start):
        r, t = self.r, self.t
        for site in r.calls.get(start, ())[:24]:
            caller = r.function_of(site)
            if caller is None:
                continue
            mapped, _why = self.unique_map(caller[0])
            if mapped is None:
                continue
            mine = r.callees(*caller)
            where = t.function_of(mapped)
            if where is None:
                continue
            theirs = t.callees(*where)
            if len(mine) != len(theirs):
                continue
            k = mine.index(start)
            if self.same(start, theirs[k]):
                return theirs[k], f'call {k} of the function at {caller[0]:#x} (unique fingerprint)'
        return None

    def by_neighbour(self, start):
        r, t = self.r, self.t
        i = bisect_left(r.starts, start)
        if i >= len(r.starts) or r.starts[i] != start:
            return None
        for d in range(1, NEIGHBOURS + 1):
            for j in (i - d, i + d):
                if not 0 <= j < len(r.starts):
                    continue
                mapped, _ = self.unique_map(r.starts[j])
                m = bisect_left(t.starts, mapped) if mapped is not None else len(t.starts)
                if m >= len(t.starts) or t.starts[m] != mapped:
                    continue
                k = m + (i - j)
                if 0 <= k < len(t.starts) and self.same(start, t.starts[k]):
                    return t.starts[k], f'{i - j:+d} functions from {r.starts[j]:#x} (unique fingerprint)'
        return None


def _section_of(binary, rva):
    for seg in binary.image.segments:
        if seg.name == '__LINKEDIT':
            continue
        for name, (start, size, *_r) in seg.sections.items():
            if start <= rva < start + size:
                return seg.name, name, start, size
    return None


def _section_in(binary, seg_name, sect_name):
    for seg in binary.image.segments:
        if seg.name == seg_name and sect_name in seg.sections:
            start, size, *_r = seg.sections[sect_name]
            return start, size
    return None


def _typed_slots(binary):
    """{type name: [address]} of every word after a rebased pointer to a type_info (vtable
    address points, including construction and secondary vtables), sorted."""
    cached = getattr(binary, '_typed_slots', None)
    if cached is None:
        binary.rtti
        cached = defaultdict(list)
        for slot, target in binary.rebases.items():
            info = binary.typeinfo_at(target)
            if info is not None:
                cached[info.name].append(slot + 8)
        for v in cached.values():
            v.sort()
        binary._typed_slots = cached
    return cached


def _vtable_like(reference, target, v, name):
    offs = [o for a, o in reference.vtables.get(name, ()) if a == v]
    if offs:
        mine = [a for a, o in reference.vtables.get(name, ()) if o == offs[0]]
        hits = [a for a, o in target.vtables.get(name, ()) if o == offs[0]]
        if len(hits) == 1 and len(mine) == 1:
            return Resolution(hits[0], 'rtti', f'{name} vtable +{offs[0]:#x}')
        if len(hits) == len(mine) > 1:
            k = mine.index(v)
            return Resolution(hits[k], 'rtti', f'{name} vtable +{offs[0]:#x}, {k} of {len(mine)} by address')
    # an address point the vtable filter left out (construction vtables, odd offset-to-top):
    # the k-th word after a pointer to this type_info, when both builds have as many
    mine = _typed_slots(reference).get(name, [])
    theirs = _typed_slots(target).get(name, [])
    if v in mine and len(mine) == len(theirs):
        k = mine.index(v)
        return Resolution(theirs[k], 'rtti', f'{k} of {len(mine)} words after a pointer to type_info {name}')
    return None


def _content_key(reference, rva):
    """Bytes that identify a __TEXT constant: the C string from rva, else up to 256 bytes."""
    data = reference.image.file_bytes(rva, 256)
    nul = data.find(b'\0')
    if 4 <= nul:
        return data[:nul + 1]
    return data


def _find_content(target, seg_name, sect_name, key):
    where = _section_in(target, seg_name, sect_name)
    if where is None:
        return []
    start, size = where
    blob = target.image.file_bytes(start, size)
    hits, i = [], blob.find(key)
    while i >= 0 and len(hits) < 3:
        hits.append(start + i)
        i = blob.find(key, i + 1)
    return hits


def named_values(found: dict, pinned: dict) -> dict:
    """{pinned scalar value: (new value, method)} from a named-anchor resolution."""
    out = {}
    for name, value in pinned.items():
        anchor = found.get(name)
        if isinstance(value, tuple):
            if anchor is not None:
                for i in (0, 3):
                    if isinstance(value[i], int):
                        out.setdefault(value[i], (anchor.value[i], anchor.method))
            continue
        if isinstance(value, int) and anchor is not None and isinstance(anchor.value, int):
            out.setdefault(value, (anchor.value, anchor.method))
    return out


# The methods the census already had before the address book (RTTI for vtables, the function
# fingerprint, the xref chain); `derive(extra=False)` measures what the added methods bring.
BASIC = ('rtti', 'export', 'export-xref', 'fingerprint', 'xref')


def derive(target, reference, census: dict, *, named: dict | None = None, strict: bool = False,
           extra: bool = True, matched: bool = True, log=None, functions=None) -> dict:
    """{pinned value: Resolution} for every address literal of `census` on `target`.
    `matched=False` leaves out the methods that rely on the whole-binary function match
    (function_match.py: changed functions). `functions` reuses the lookups (and the function
    match) of an earlier derive on the same pair of builds.

    A 'page' override resolves to the page of the other addresses of the same file in that page
    (they must agree on one page), or, when the override names one address (`of`), to the page of
    that address: for a page whose addresses move to different pages on the new build, the
    review says which of them the page is for."""
    if functions is not None and (functions.t is not target or functions.r is not reference
                                  or functions.strict != strict):
        functions = None
    fns = functions or _Functions(target, reference, strict, log)
    fns.matched = matched and extra
    derive.functions = fns
    anchors.STRICT = strict
    ref_bounds = section_bounds(reference)
    tgt_bounds = {v: k for k, v in section_bounds(target).items()}
    overrides, overrides_by_file = {}, {}
    page_of = {}
    files_of = defaultdict(set)
    for rel, entry in census['files'].items():
        for key, row in entry.items():
            if row['d'] == 'A':
                v = int(key, 16)
                files_of[v].add(rel)
                if row['rule'].startswith('override:'):
                    overrides_by_file[(rel, v)] = row['rule'].split(':', 1)[1]
                    if row.get('of'):
                        page_of[(rel, v)] = int(row['of'], 16)
    for v, rels in files_of.items():
        hows = {overrides_by_file.get((rel, v)) for rel in rels}
        if hows == {'page'}:
            overrides[v] = 'page'
        elif 'manual' in hows:
            overrides[v] = 'manual'
        elif 'range' in hows:
            overrides[v] = 'range'
    out = {}
    pages = sorted({v for (_rel, v), how in overrides_by_file.items() if how == 'page'})
    for v in sorted(files_of):
        how = overrides.get(v)
        if how == 'page':
            continue
        res = _resolve_one(v, how, target, reference, fns, ref_bounds, tgt_bounds, named or {})
        if not extra and res.value is not None and res.method not in BASIC:
            res = Resolution(None, 'unresolved', f'needs method {res.method}')
        out[v] = res
    for v, (new, evidence) in reviewed_values(target.sha256).items():
        if v in out:
            out[v] = Resolution(new, 'reviewed', evidence)
    anchors.STRICT = False
    for v in pages if not extra else ():
        out[v] = Resolution(None, 'unresolved', 'needs method page')
    per_file = {}
    for v in pages if extra else ():
        for rel in files_of[v]:
            if overrides_by_file.get((rel, v)) != 'page':
                continue
            if (rel, v) in page_of:
                of = page_of[(rel, v)]
                got = out.get(of)
                if got is None or of in pages:
                    got = _resolve_one(of, None, target, reference, fns, ref_bounds, tgt_bounds, named or {})
                res = (Resolution(got.value & ~0xFFF, 'page', f'page of {of:#x} ({got.method}: {got.detail})')
                       if got.value is not None else
                       Resolution(None, 'unresolved', f'page of {of:#x}, which does not resolve: {got.detail}'))
                per_file.setdefault(rel, {})[v] = res
                continue
            siblings = {c for c in address_census_values(census, rel) if c & ~0xFFF == v and c != v}
            mapped = {out[c].value & ~0xFFF for c in siblings if c in out and out[c].value is not None}
            if len(mapped) == 1:
                res = Resolution(mapped.pop(), 'page', f'page of {len(siblings)} address(es) of {rel}')
            else:
                res = Resolution(None, 'unresolved', f'page of addresses of {rel} that resolve to {len(mapped)} pages')
            per_file.setdefault(rel, {})[v] = res
        if v not in out:
            first = next((per_file[rel][v] for rel in sorted(files_of[v]) if v in per_file.get(rel, {})), None)
            out[v] = first or Resolution(None, 'unresolved', 'page')
    derive.per_file = per_file
    return out


def reviews(sha256: str) -> dict:
    """The hand review of one build (`builds.<sha256>` of data/address_overrides.json): {'values':
    {hex pinned: {'value': hex, 'evidence': str}}, 'guards': {file: {hex pinned: {'new': hex,
    'length': int (optional), 'verdict': str, 'evidence': str}}}}."""
    import json
    from .address_census import OVERRIDES_PATH
    if not OVERRIDES_PATH.exists():
        return {}
    return json.loads(OVERRIDES_PATH.read_text()).get('builds', {}).get(sha256) or {}


def reviewed_values(sha256: str) -> dict:
    """{pinned int: (new int, evidence)} reviewed by hand for this build."""
    return {int(k, 16): (int(e['value'], 16), e['evidence']) for k, e in (reviews(sha256).get('values') or {}).items()}


def address_census_values(census, rel):
    return [int(k, 16) for k, row in census['files'].get(rel, {}).items() if row['d'] == 'A']


def _resolve_one(v, how, target, reference, fns, ref_bounds, tgt_bounds, named):
    if how == 'manual':
        return Resolution(None, 'unresolved', 'listed as manual in address_overrides.json')
    if v in named and named[v][0] is not None:
        return Resolution(named[v][0], 'named', f'fmdb anchor ({named[v][1]})')
    if how == 'range':
        where = _section_of(reference, v)
        if where is None:
            return Resolution(None, 'unresolved', 'range bound outside every section')
        seg, sect, start, _size = where
        theirs = _section_in(target, seg, sect)
        if theirs is None or v - start >= theirs[1]:
            return Resolution(None, 'unresolved', f'range bound in {seg},{sect}: section smaller on this build')
        return Resolution(theirs[0] + (v - start), 'range', f'{seg},{sect} +{v - start:#x}')
    name = reference.class_name(v)
    if name:
        hit = _vtable_like(reference, target, v, name)
        if hit is not None:
            return hit
        return Resolution(None, 'unresolved', f'vtable of {name}: no unique counterpart on this build')
    info = reference.typeinfo_at(v)
    if info is not None:
        theirs = target.rtti.get(info.name)
        if theirs is not None:
            return Resolution(theirs.address, 'rtti', f'type_info {info.name}')
        return Resolution(None, 'unresolved', f'type_info {info.name} absent on this build')
    if v in reference.image.stubs:
        sym = reference.image.stubs[v]
        t = target.stub_for(sym)
        return Resolution(t, 'stub', sym) if t is not None else \
            Resolution(None, 'unresolved', f'import {sym} no longer called')
    if v in ref_bounds and not (reference.is_code(v) and reference.function_of(v)[0] == v):
        label = ref_bounds[v]
        t = tgt_bounds.get(label)
        return Resolution(t, 'section', label) if t is not None else \
            Resolution(None, 'unresolved', f'section bound {label} absent')
    if reference.is_code(v):
        start, _end = reference.function_of(v)
        off = v - start
        name, exported = _export_of(fns, start)
        if exported is not None and fns.same(start, exported):
            return Resolution(exported + off, 'export', f'exported function {name}; +{off:#x}')
        # an exported function whose code changed is found by the match (which pairs exported
        # names first), never by a fingerprint twin
        mapped, why = fns.unique_map(start) if exported is None else (None, f'exported function {name} changed')
        if mapped is not None:
            return Resolution(mapped + off, 'fingerprint', f'{why}; +{off:#x}')
        for method, fn in (('vtable-slot', fns.by_vtable_slot), ('callee', fns.by_callee),
                           ('neighbour', fns.by_neighbour)):
            hit = fn(start)
            if hit is not None:
                return Resolution(hit[0] + off, method, f'{hit[1]}; +{off:#x}')
        if getattr(fns, 'matched', False):
            from .function_match import carry
            new, method, conf, detail, change = carry(fns.match(), v)
            return Resolution(new, f'match:{method}' if new is not None else 'unresolved',
                              detail if new is not None else f'in function {start:#x} (+{off:#x}): {why}; {detail}',
                              conf, change)
        return Resolution(None, 'unresolved', f'in function {start:#x} (+{off:#x}): {why}')
    # data
    hit = _export_xref(reference, target, v, fns)
    if hit is not None:
        return hit
    entry = anchors.reference_entry(reference, v)
    hit = anchors.locate_entry(target, entry) if entry else None
    if hit is not None:
        return Resolution(hit[0], 'xref', hit[2])
    where = _section_of(reference, v)
    if where and where[0] == '__TEXT':
        key = _content_key(reference, v)
        for n in sorted({min(len(key), k) for k in (16, 32, 64, 128, 256)}):
            if len(_find_content(reference, where[0], where[1], key[:n])) != 1:
                continue
            hits = _find_content(target, where[0], where[1], key[:n])
            if len(hits) == 1:
                return Resolution(hits[0], 'content', f'{n} bytes unique in {where[0]},{where[1]}')
            break
    # inside a vtable or type_info object: the object plus the same offset
    for back in range(8, 0x800, 8):
        base = v - back
        name = reference.class_name(base)
        if name:
            hit = _vtable_like(reference, target, base, name)
            if hit is not None:
                return Resolution(hit.value + back, 'vtable+off', f'{hit.detail}; +{back:#x}')
            break
        info = reference.typeinfo_at(base)
        if info is not None and back <= 0x40:
            theirs = target.rtti.get(info.name)
            if theirs is not None:
                return Resolution(theirs.address + back, 'vtable+off', f'type_info {info.name} +{back:#x}')
            break
    hit = _global_plus_offset(reference, target, v)
    if hit is not None:
        return hit
    hit = _field_reference(reference, target, v, fns)
    if hit is not None:
        return hit
    hit = _bracketed(reference, target, v)
    if hit is not None:
        return hit
    if getattr(fns, 'matched', False) and reference.refs.get(v):
        from .function_match import carry_data
        got = carry_data(fns.match(), v)
        if got is not None:
            return Resolution(got[0], f'match:{got[1]}', got[3], got[2])
    if getattr(fns, 'matched', False):
        hit = _bracketed_matched(reference, v, fns.match()) or _local_shift(reference, target, v, fns.match())
        if hit is not None:
            return hit
    if entry is None:
        return Resolution(None, 'unresolved', 'data address with no referencing code')
    return Resolution(None, 'unresolved', 'data address whose referencing functions all changed or are not unique')


def _export_of(fns, start):
    """(name, start on the target) of the function exported under the name the pinned function
    `start` has (function_match.exported_functions), or (name or None, None)."""
    from .function_match import exported_functions
    names = getattr(fns, '_export_names', None)
    if names is None:
        names = fns._export_names = {s: n for n, s in exported_functions(fns.r).items()}
    name = names.get(start)
    if name is None:
        return None, None
    return name, exported_functions(fns.t).get(name)


def _export_xref(reference, target, v, fns):
    """A global referenced by exported functions: the reference at the same index in the
    function exported under the same name on the target, when that function's masked code is
    unchanged; all such references must agree. Checked before the fingerprint xref, which can
    take a fingerprint twin (27.0.1: the translator global 0x5721E70 went to the characters
    global by `_i_characters_get_instance`, whose fingerprint `_i_translator_get_instance` had)."""
    found, names = set(), []
    for _adrp, use, _kind in reference.refs.get(v, ()):
        bounds = reference.function_of(use)
        if bounds is None:
            continue
        name, exported = _export_of(fns, bounds[0])
        if exported is None:
            continue
        theirs_bounds = target.function_of(exported)
        mine = reference.refs_in(*bounds)
        index = [i for i, (u, t, _k) in enumerate(mine) if u == use and t == v]
        theirs = target.refs_in(*theirs_bounds)
        # the same code, or the same length with the same references in the same places (the
        # fingerprint keeps the page offsets of a hoisted ADRP register, which move with the data)
        if not index or len(theirs) != len(mine):
            continue
        if not fns.same(bounds[0], exported) and not (
                bounds[1] - bounds[0] == theirs_bounds[1] - theirs_bounds[0]
                and all(u - bounds[0] == u2 - exported and k == k2
                        for (u, _t, k), (u2, _t2, k2) in zip(mine, theirs))):
            continue
        found.add(theirs[index[0]][1])
        names.append(name)
    if len(found) == 1:
        return Resolution(found.pop(), 'export-xref', f'reference in exported function(s) {", ".join(sorted(set(names)))}')
    return None


def _global_plus_offset(reference, target, v, reach=0x80):
    """A field of a referenced global: the nearest referenced address below `v` (within `reach`)
    resolved by xref, plus the same offset, accepted only when every 8-byte word from that
    global to v+8 is a rebased pointer on both builds or on neither, and the pointers that name a
    class (vtables) name the same class."""
    where = _section_of(reference, v)
    if where is None or where[1] in ZERO_FILL:
        return None                     # nothing to compare: left to the live type scan
    for back in range(1, reach + 1):
        base = v - back
        if not reference.refs.get(base):
            continue
        hit = anchors.locate_entry(target, anchors.reference_entry(reference, base))
        if hit is None:
            return None
        new = hit[0] + back
        for off in range(-(back % 8), back + 8, 8):
            a, b = base + off, hit[0] + off
            pa, pb = reference.pointer(a), target.pointer(b)
            if (pa is None) != (pb is None):
                return None
            if pa is not None and reference.class_name(pa) != target.class_name(pb):
                return None
            if pa is None and reference.image.file_bytes(a, 8) != target.image.file_bytes(b, 8):
                return None
        return Resolution(new, 'global+off', f'{hit[2]} at {base:#x}, +{back:#x}; bytes and pointers equal')
    return None


ZERO_FILL = ('__bss', '__common', '__thread_bss')


def _bracketed(reference, target, v, reach=0x200):
    """An address no code names directly, between the nearest referenced addresses below and
    above it (each within `reach`): when both resolve by xref and stand the same distance apart
    on the new build, v keeps its offset from the lower one (the linker kept that stretch of
    the section together)."""
    lo = next((v - d for d in range(1, reach) if reference.refs.get(v - d)), None)
    hi = next((v + d for d in range(1, reach) if reference.refs.get(v + d)), None)
    if lo is None or hi is None:
        return None
    a = anchors.locate_entry(target, anchors.reference_entry(reference, lo))
    b = anchors.locate_entry(target, anchors.reference_entry(reference, hi))
    if a is None or b is None or b[0] - a[0] != hi - lo:
        return None
    return Resolution(a[0] + (v - lo), 'bracketed',
                      f'between {lo:#x} and {hi:#x} (both by xref, {hi - lo:#x} apart on both builds)')


def _bracketed_matched(reference, v, match, reach=0x200):
    """`_bracketed` with the neighbours resolved through the function match (the data map of
    matched functions, or their aligned references): for addresses no code names, such as one
    table root among its neighbours or a constant inside a table."""
    from .function_match import carry_data
    lo = next((v - d for d in range(1, reach) if reference.refs.get(v - d)), None)
    hi = next((v + d for d in range(1, reach) if reference.refs.get(v + d)), None)
    if lo is None or hi is None:
        return None
    a, b = carry_data(match, lo), carry_data(match, hi)
    if a is None or b is None or b[0] - a[0] != hi - lo:
        return None
    return Resolution(a[0] + (v - lo), 'match:bracketed',
                      f'between {lo:#x} ({a[1]}) and {hi:#x} ({b[1]}), {hi - lo:#x} apart on both builds',
                      min(a[2], b[2]))


def _local_shift(reference, target, v, match, reach=0x1000, length=16):
    """A constant in __TEXT no code names (inside a table): the nearest referenced constants
    below and above it (within `reach`) resolve through the function match and moved by the
    same amount, and the `length` bytes at v are the same at v plus that amount."""
    from .function_match import carry_data
    where = _section_of(reference, v)
    if where is None or where[0] != '__TEXT':
        return None
    shifts = []
    for direction in (-1, 1):
        for d in range(1, reach):
            u = v + direction * d
            if reference.refs.get(u):              # the nearest one that resolves
                got = carry_data(match, u)
                if got is not None:
                    shifts.append((got[0] - u, u, got[1]))
                    break
    if len(shifts) != 2 or shifts[0][0] != shifts[1][0]:
        return None
    new = v + shifts[0][0]
    if reference.image.file_bytes(v, length) != target.image.file_bytes(new, length):
        return None
    return Resolution(new, 'match:local-shift',
                      f'{shifts[0][1]:#x} and {shifts[1][1]:#x} around it both moved {shifts[0][0]:+#x}; '
                      f'{length} bytes equal', 1.0)


def _ldst_offset(word):
    """(base register, byte offset) of an integer LDR/STR with an unsigned immediate, or None."""
    if word & 0x3F000000 != 0x39000000:
        return None
    size = word >> 30
    return (word >> 5) & 31, ((word >> 10) & 0xFFF) << size


def _field_reference(reference, target, v, fns, reach=0x100, window=12):
    """A global that code reaches as `adrp xN, B@page; add xN, xN, B@off; ldr/str [xN, #d]`
    with B + d == v (a field of a larger global, or the next of several adjacent globals the
    compiler addresses from one base). Found in an unchanged, uniquely fingerprinted function on
    the pinned build; on the new build the same instructions of that function give B' and the
    same d."""
    for back in range(8, reach + 1, 8):
        base = v - back
        for _adrp, use, kind in reference.refs.get(base, ())[:24]:
            if kind != 'add':
                continue
            rd = reference.word(use) & 31
            hit = None
            for k in range(1, window + 1):
                pc = use + 4 * k
                if not reference.is_code(pc):
                    break
                ld = _ldst_offset(reference.word(pc))
                if ld is not None and ld[0] == rd and ld[1] == back:
                    hit = pc
                    break
            if hit is None:
                continue
            start, _end = reference.function_of(use)
            mapped, _why = fns.unique_map(start)
            if mapped is None:
                continue
            new_use = mapped + (use - start)
            new_end = target.function_of(mapped)[1]
            theirs = [t for u, t, k in target.refs_in(mapped, new_end) if u == new_use and k == 'add']
            if len(theirs) == 1:
                return Resolution(theirs[0] + back, 'field-xref',
                                  f'add of {base:#x} then [x{rd}, #{back:#x}] in the function at {start:#x} '
                                  f'(unique fingerprint)')
    return None


def live_partners(res: dict, census: dict, reference, typed: dict) -> int:
    """Resolve unresolved data addresses through the live type scan of the new build: a global
    written in a tuple next to a vtable literal (`(root, vtable, name)`) is the only global of
    the running game that holds an object of that class. Returns how many it resolved."""
    by_type = defaultdict(list)
    for slot, name in typed.items():
        by_type[name].append(slot)
    count = 0
    for rel, entry in census['files'].items():
        for key, row in entry.items():
            v = int(key, 16)
            r = res.get(v)
            if row['d'] != 'A' or r is None or r.value is not None:
                continue
            for partner in row.get('with', ()):
                name = reference.class_name(int(partner, 16))
                slots = by_type.get(name, []) if name else []
                if len(slots) == 1:
                    res[v] = Resolution(slots[0], 'live', f'only global holding a {name} (live type scan)')
                    count += 1
                    break
    return count


# --------------------------------------------------------------------------- code guards
def guard_rewrites(target, reference, census: dict, mapping: dict, root, match=None, lengths_rewritten=False,
                   review_key='guards') -> dict:
    """{file: {old constant (hex of bytes or the sha string): new constant}} for the code-byte
    and sha256 guards next to resolved addresses whose code is unchanged under masking.

    A guard is `(address, bytes)`, `{address: bytes}`, `(address, length, sha256)` or `(start, end, sha256)` (bytes
    as a bytes literal, `bytes.fromhex('..')` or a hex string). The new constant is taken from
    the new build only when the masked instructions (address-dependent fields hidden: ADRP pages
    and offsets, every branch offset, literal loads) are equal; otherwise the guard keeps the
    pinned bytes and fails, so the tool refuses. With `match` (function_match.Match), a span
    whose masked code differs is classified instruction by instruction against its aligned span:
    'same' (every instruction differs only in address fields, including page offsets of globals
    held in hoisted registers: rewritten like an unchanged span), or, listed in `spans` and left
    refusing, 'offset' (only structure offsets or sizes differ: a structure change), 'registers'
    (register or stack-slot allocation differs), 'logic' (anything else, or the span is not
    contiguous on the new build).

    A reviewed `(address, length, sha256)` span may have a new length only when the caller's
    rewrite also replaces the length literal (`lengths_rewritten`, the adviser's rewrite; the
    result's `lengths` lists them); the reader's rewrite does not, so there it refuses. The hand
    reviews are the build's `review_key` entry of data/address_overrides.json ('adviser_guards'
    for the tactic writer)."""
    import ast
    from pathlib import Path
    out = defaultdict(dict)
    lengths = defaultdict(dict)
    stats = {'rewritten': 0, 'unchanged': 0, 'changed_code': 0, 'unresolved': 0}
    spans = []
    reviewed_guards = reviews(target.sha256).get(review_key) or {}
    reviewed = []
    for rel, entry in census['files'].items():
        if not any(r['rule'] == 'guard' for r in entry.values()):
            continue
        tree = ast.parse((Path(root) / rel).read_text())
        groups = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Tuple):
                groups.append(node.elts)
            elif isinstance(node, ast.Dict):          # {address: code bytes} spans
                groups.extend([k, v] for k, v in zip(node.keys, node.values) if k is not None)
        for elts in groups:
            ints = [e.value for e in elts if isinstance(e, ast.Constant) and type(e.value) is int]
            consts = [_guard_const(e) for e in elts]
            consts = [c for c in consts if c is not None]
            if not ints or len(consts) != 1:
                continue
            original, payload = consts[0]
            addr = ints[0]
            if f'{addr:#x}' not in entry or entry[f'{addr:#x}']['d'] != 'A':
                continue
            new = mapping.get(addr)
            if new is None or new.value is None:
                stats['unresolved'] += 1
                continue
            if isinstance(payload, bytes):
                length, kind = len(payload), 'bytes'
            elif len(ints) >= 2 and ints[1] > addr and f'{ints[1]:#x}' in entry:
                end = mapping.get(ints[1])
                length, kind = ints[1] - addr, 'sha'
                if end is None or end.value is None:
                    stats['unresolved'] += 1
                    continue
                review = (reviewed_guards.get(rel) or {}).get(f'{addr:#x}')
                if (end.value - new.value != length and review is not None
                        and int(review['new'], 16) == new.value and review.get('length') == end.value - new.value):
                    # a whole function whose new length was reviewed by hand: re-derived from the new
                    # bytes between the mapped ends, only when both ends are where the review puts them
                    old_bytes = reference.image.file_bytes(addr, length)
                    if hashlib.sha256(old_bytes).hexdigest() == payload:
                        n = review['length']
                        out[rel][original] = hashlib.sha256(target.image.file_bytes(new.value, n)).hexdigest()
                        stats['reviewed'] = stats.get('reviewed', 0) + 1
                        reviewed.append({'file': rel, 'address': addr, 'new': new.value, 'length': n, 'kind': kind,
                                         'verdict': review.get('verdict', 'reviewed'), 'evidence': review['evidence']})
                        continue
                if end.value - new.value != length:
                    # the span's code changed length: the guard keeps the pinned hash and refuses at
                    # run time, so list it with the tools it disables (it was only counted before)
                    stats['changed_code'] += 1
                    stats['changed_code_length'] = stats.get('changed_code_length', 0) + 1
                    spans.append({'file': rel, 'address': addr, 'new': new.value, 'length': length, 'kind': kind,
                                  'verdict': 'logic', 'changes': [{'class': 'logic', 'why': (
                                      f'the span {addr:#x}..{ints[1]:#x} ({length} bytes) is '
                                      f'{end.value - new.value} bytes on this build')}]})
                    continue
            elif len(ints) >= 2:
                length, kind = ints[1], 'sha'
            else:
                continue
            old_bytes = reference.image.file_bytes(addr, length)
            new_bytes = target.image.file_bytes(new.value, length)
            if (payload != old_bytes) if kind == 'bytes' else (hashlib.sha256(old_bytes).hexdigest() != payload):
                stats['not_a_guard'] = stats.get('not_a_guard', 0) + 1     # e.g. (vtable, its RTTI name)
                continue
            review = (reviewed_guards.get(rel) or {}).get(f'{addr:#x}')
            if review is not None and old_bytes != new_bytes:
                # a guard whose changed code was compared by hand on both builds: re-derived from the
                # new bytes at the reviewed place, only when the address map puts the span there
                if int(review['new'], 16) != new.value or (kind == 'sha' and review.get('length', length) != length
                                                            and not lengths_rewritten):
                    stats['changed_code'] += 1
                    stats['changed_code_review_mismatch'] = stats.get('changed_code_review_mismatch', 0) + 1
                    spans.append({'file': rel, 'address': addr, 'new': new.value, 'length': length, 'kind': kind,
                                  'verdict': 'logic', 'changes': [{'class': 'logic', 'why': (
                                      f'reviewed at {review["new"]} (length {review.get("length", length)}), '
                                      f'but the address map puts it at {new.value:#x} (length {length})')}]})
                    continue
                n = review.get('length', length)
                new_bytes = target.image.file_bytes(new.value, n)
                if kind == 'bytes':
                    out[rel][original] = new_bytes.hex() if isinstance(original, str) else new_bytes
                else:
                    out[rel][original] = hashlib.sha256(new_bytes).hexdigest()
                    if n != length:
                        # an (address, length, sha256) span whose reviewed length differs: the
                        # length literal changes with the hash (the adviser's rewrite applies it)
                        lengths[rel][original] = n
                stats['reviewed'] = stats.get('reviewed', 0) + 1
                reviewed.append({'file': rel, 'address': addr, 'new': new.value, 'length': n, 'kind': kind,
                                 'verdict': review.get('verdict', 'reviewed'), 'evidence': review['evidence']})
                continue
            if old_bytes == new_bytes:
                stats['unchanged'] += 1
                continue
            if not _masked_equal(reference, addr, target, new.value, length):
                verdict, changes = _span_change(match, addr, new.value, length) if match else ('logic', [])
                if verdict != 'same':
                    stats['changed_code'] += 1
                    stats[f'changed_code_{verdict}'] = stats.get(f'changed_code_{verdict}', 0) + 1
                    spans.append({'file': rel, 'address': addr, 'new': new.value, 'length': length, 'kind': kind,
                                  'verdict': verdict, 'changes': changes})
                    continue
                stats['same_by_alignment'] = stats.get('same_by_alignment', 0) + 1
            if kind == 'bytes':
                out[rel][original] = new_bytes.hex() if isinstance(original, str) else new_bytes
            else:
                out[rel][original] = hashlib.sha256(new_bytes).hexdigest()
            stats['rewritten'] += 1
    return {'files': {k: {_key(o): _key(n) for o, n in v.items()} for k, v in out.items()}, 'stats': stats,
            'spans': spans, 'reviewed': reviewed, **({'lengths': dict(lengths)} if lengths else {})}


def _span_change(match, a, b, length):
    """('same' | 'offset' | 'registers' | 'logic' | 'data', [per-instruction change]) of a guarded
    span at `a` on the pinned build whose bytes at `b` on the new build differ under masking. Each
    instruction is aligned inside its own matched function (a span may cross function bounds)
    and must land at the same place in the new span."""
    from . import function_match as fm
    r, t = match.r, match.t
    if not (r.is_code(a) and t.is_code(b)) or a % 4 or b % 4 or length % 4:
        old, new = r.image.file_bytes(a, length), t.image.file_bytes(b, length)
        diff = [k for k in range(length) if old[k] != new[k]]
        return 'data', [{'why': f'{len(diff)} of {length} bytes differ, first at +{diff[0]:#x}' if diff else 'bytes equal',
                         'old_bytes': old[:64].hex(), 'new_bytes': new[:64].hex()}]
    changes, worst = [], 'same'
    rank = {'same': 0, 'registers': 1, 'stack': 1, 'offset': 2, 'logic': 3, 'unconfirmed': 3}
    aligned = {}
    for k in range(length // 4):
        va, vb = a + 4 * k, b + 4 * k
        fa = r.function_of(va)
        fb = match.fwd.get(fa[0]) if fa else None
        if fb is None:
            changes.append({'at': va, 'class': 'logic', 'why': 'the function holding it has no match'})
            worst = 'logic'
            continue
        if fa[0] not in aligned:
            sites = [(a - fa[0]) // 4 + x for x in range(length // 4)]
            aligned[fa[0]] = fm.align(r, fa[0], t, fb, sites=[i for i in sites if i >= 0], match=match)
        j = aligned[fa[0]].get((va - fa[0]) // 4)
        if j is None or fb + 4 * j != vb:
            changes.append({'at': va, 'class': 'logic', 'why': 'not aligned within the span',
                            'old_word': f'{r.word(va):08x}', 'new_word': f'{t.word(vb):08x}'})
            worst = 'logic'
            continue
        cls, info = fm.classify(r, fa[0], va, t, fb, vb, match)
        if cls != 'same':
            changes.append({'at': va, 'new_at': vb, 'class': cls, **info,
                            'old_word': f'{r.word(va):08x}', 'new_word': f'{t.word(vb):08x}'})
        if rank[cls] > rank[worst]:
            worst = cls
    verdict = {'stack': 'registers'}.get(worst, worst)    # 'same': only address fields differ
    return verdict, changes

def _key(value):
    return value.hex() if isinstance(value, bytes) else value


def _guard_const(node):
    """(original constant, payload) of a guard element: payload bytes for code bytes, the sha
    string for a sha256; None for anything else."""
    import ast
    if isinstance(node, ast.Constant):
        v = node.value
        if isinstance(v, bytes):
            return v, v
        if isinstance(v, str) and len(v) >= 8 and len(v) % 2 == 0 and all(c in '0123456789abcdefABCDEF' for c in v):
            return (v, v) if len(v) == 64 else (v, bytes.fromhex(v))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == 'fromhex' \
            and node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
        try:
            return node.args[0].value, bytes.fromhex(node.args[0].value)
        except ValueError:
            return None
    return None


def _masked_equal(reference, a, target, b, length):
    if not (reference.is_code(a) and target.is_code(b)) or length % 4 or a % 4 or b % 4:
        return False
    if reference.fingerprint(a, a + length) == target.fingerprint(b, b + length):
        return True
    from .function_match import tokens        # conditional branches leaving the span masked too
    return tokens(reference, a, a + length) == tokens(target, b, b + length)


# --------------------------------------------------------------------------- whole-binary diff
def function_diff(target, reference) -> dict:
    """How many functions of the pinned build exist unchanged on the new one (by fingerprint)."""
    theirs = defaultdict(int)
    for s in target.starts:
        theirs[target.fingerprint(s)] += 1
    mine = defaultdict(int)
    for s in reference.starts:
        mine[reference.fingerprint(s)] += 1
    unchanged = sum(min(n, theirs.get(fp, 0)) for fp, n in mine.items())
    return {'pinned_functions': len(reference.starts), 'functions': len(target.starts),
            'unchanged': unchanged, 'changed_or_removed': len(reference.starts) - unchanged,
            'new_or_changed': len(target.starts) - unchanged}
