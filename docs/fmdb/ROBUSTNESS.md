# Robustness: another game build, plans from code, a game that moves during a build

Three pieces keep the generic database reader working when the game changes under it:

1. `fmdb/anchors.py`, `fmdb/build.py`, `scripts/fmdb_rebase.py`: find every pinned plugin
   address again on another build and switch the fmdb modules to it.
2. `fmdb/plancompile.py`, `scripts/fmdb_plancompile.py`: derive a field's direct plan from the
   getter's code on a synthetic record, with no record sampled.
3. `fmdb/consistency.py`: stamp every table read with the game date and re-read only the
   tables that went stale during a build. (Removed when the on-demand lane merged: the content
   check of `fmdb/freshness.py` runs once on the finished build and re-reads, per page, the rows
   whose bytes moved during it; see SNAPSHOT.md "Freshness by content".)
4. `fmdb/platform_model.py`: the boundary between the reader and the platform (binary format,
   C++ ABI, instruction set, process access, calling convention).

Sections 5 and 6 record two things that are not built: how a direct plan becomes a write plan,
and what the reader needs from the Mac it runs on.

Speed (fill, first build, shipped plans, refresh time) is the performance lane's work; see
`PERFORMANCE.md`.

## 1. Anchors

### What is pinned

The fmdb modules carry 237 named anchors for build 27.0.0.2493426 (`anchors.pinned()`): the 36
record classes (table vtable, slot-3 getter, primary offset), the 24 `DATABASE_TABLE<T>` roots
and vtables, `players.RVA`/`STAFF_RVA`, the world roots, the current date and 32 world types,
the VM constants (typed-traits registry, return-true helper, 15 interceptor tuples, owning-thread
globals, thread-local RNG descriptors), the UI handler factory and base vtables and three pool
allocators, the UI recipe helpers and globals, and the native extras slots.

### How each kind is found

| Method | What it finds |
|---|---|
| RTTI | type_info objects through the binds to the three `__cxxabiv1` type_info vtables; vtables as the rebased words pointing at a type_info, with offset-to-top before them; primary and secondary vtables per class; subobject offsets from `__vmi_class_type_info` base lists, virtual bases through the vbase offsets of the subobject vtables (ACTUAL_PLAYER's PERSON at +0x388 comes out this way); getters and native slots as vtable slots |
| Code shape | the 15 interceptor globals (`ldr x0,[G]; ldr x8,[x0]; ldr x8,[x8,#0x38]; blr x8; tbz w0`), the owning-thread word and its flag (`pthread_self()` stored next to a `strb #1`), the fallback thread word (the other `pthread_self()` global read with the flag), the current date (`{u16 day, u16 year}`: the two most halfword-loaded globals are adjacent), `mov w0,#1; ret`, the UI key/label registration function (the largest GameAssembly function by a factor of two) |
| Live type scan | with the game of that build running: every word of the plugin's `__DATA` that points at an object is followed once and the object's vtable named; 469 typed globals in 0.1 s. Gives the 24 table roots, SAVE_SYSTEM, NEWS_MANAGER, the typed-traits registry, and the class behind each interceptor global |
| Fingerprint | a function hashed with every address-dependent field masked (ADRP pages, their paired page offsets, calls and branches leaving the function, literal loads) and with calls to imports replaced by the import name. An anchor inside an unchanged function keeps its offset. Functions shorter than 6 instructions match only at the same address; identical functions are told apart by rank only above 16 instructions |
| Xref | a global or data address as the n-th ADRP reference of an unchanged, uniquely fingerprinted referencing function (up to five, which must agree) |

The fingerprints of the pinned build ship as
`fmdb/data/anchors-reference-<sha256>.json.gz` (2,799 entries, 75 KB), so a patched install
does not need the old binary. Where two methods find different values the anchor is withheld.

### Results on 27.0.0.2493426 (derived from scratch, compared with the pinned values)

| Methods allowed | Match | Equivalent | Missing | Mismatch |
|---|---|---|---|---|
| RTTI + code shape | 174 | 1 | 62 | 0 |
| + live type scan | 218 | 1 | 18 | 0 |
| + fingerprint index | 236 | 1 | 0 | 0 |
| all | 236 | 1 | 0 | 0 |

"Equivalent": `vm.RETURN_TRUE_RVA` is another shipped `mov w0,#1; ret` (the VM checks only the
two instructions). Without the fingerprint index the 18 missing are the three pool allocators,
the two thread-local RNG descriptors, `world.GAME_ROOT` (two globals hold a GAME_UI) and the 12
UI recipe helpers (`BAG_INSERT`, `PARAM_LOOKUP/HOOK/FOUND`, `INT32_VARIANT`, `RESOLVE`,
`SI_DATE_TRAITS`, the three VISION globals).

UI handler layer: all 614 handler classes of the shipped registry resolve by RTTI; 12,868 of
their 12,938 slot functions equal the registry's (the rest are pure-virtual binds).

### Another build on this machine: FM26 26.3.2.2329565

Found in `/Volumes/External SSD/SteamLibrary/steamapps/common/Football Manager 26`. No other FM27
build exists on this machine (Steam `downloading`, `temp` and `depotcache` hold no FM27 depot;
the FM2024 folder holds 1.2 MB of data only). FM26 uses the older LC_DYLD_INFO rebase/bind
opcodes instead of chained fixups; `anchors.Binary` now reads both.

FM26 is a year of development away from FM27, so it is a lower bound for what a patch does.
Statically (no FM26 game running, so no live scan): 185 of 237 anchors found (RTTI 168, code
shape 5, xref 7, fingerprint 5); 2 withheld on conflict (`world.TYPES.game_club_finance`,
`extras.PLAYER_SLOTS.21.regular`: RTTI and fingerprint disagree, so the slot numbering moved
between the years). The 7 table roots found by xref sit in FM26 exactly as the FM27 roots do
relative to each other (continents, nations +8, media sources +0x20, player types +0x28,
removed records +0x38, derbies +8, agreements +8). 16 interceptor globals match the bypass
pattern (FM27 has 15); naming them needs the live scan. 590 of 614 UI handler classes exist in
FM26; the registration function is again the largest GameAssembly function (0x7F6048, 165,625
instructions).

### Switching builds

`scripts/fmdb_rebase.py <plugin> --live` (game of that build running) writes
`$FMCP_CACHE_DIR/fmdb/anchors/<sha256>.json`. `Engine.open_build()` attaches to the running
game without the Bridge, finds the plugin by its Mach-O UUID, and `build.activate()` rebinds
the module constants from the anchor file. A file that lacks a required anchor (classes,
tables, players, world, VM) is refused as a whole; missing optional anchors (UI recipe helpers,
extras slots) become None, which makes exactly those features refuse. Plans are keyed by plugin
sha256, so a new build derives and verifies its own (section 2).

### The rest of the reader: the address book (12 November)

Every plugin address the reader uses outside the named anchors now goes through the address
book (`fm_live_mcp/address_book.py`); docs/GAME_UPDATE.md has the procedure. The old census
counted every literal inside the image range; about a third of those were coincidences (row
budgets, engine offsets, bit masks, template ids, labels in the offline save parsers). The
address census (`fmdb/address_census.py`) decides each one, and `fmdb/address_map.py` resolves
the addresses on another build from the preserved pinned plugin.

| Group | In-range values | Addresses | Resolved from scratch, RTTI + fingerprint + xref | With the added methods |
|---|---|---|---|---|
| fmdb | 363 | 328 | 294 | 328 |
| knowledge engine | 442 | 414 | 296 | 414 |
| hand-built tools | 2,753 | 1,900 | 1,690 | 1,900 |

"From scratch": `scripts/fm_update_build.py` run on the pinned plugin as if it were a new build,
with the same-address shortcut for short functions refused; no value differs from the pinned
one. On a patch, addresses in changed functions drop out and make exactly the code that uses
them refuse; `fm_status` names the tools. The knowledge engine still reimplements game logic
(relation masks, transfer predicates, stars), which a patch can change without moving any
address. Struct offsets: direct plans are re-derived per build; hand-built fields are checked
against the generic getter by the live part of the update (withheld when they disagree); the
manager walkers are disabled when their class's allocation size changes. Independently of any
patch, attaching at all depends on this Mac's SIP configuration (section 6).

## 2. Static plan compilation

`plancompile.Compiler` runs the shipped getter on a SYNTHETIC record of the class: its vtable
group from RTTI (primary and secondary vtables at their offsets), zeros elsewhere, in an address
range the game never uses (`0x6F00_0000_0000`). Globals, interceptor objects, language tables
and the typed-traits registry come from live memory as in every VM call; no game record is read.

1. Pointer skeleton: an 8-byte load from synthetic memory that reads 0 is tried as a pointer
   (a fresh zeroed synthetic object is linked in) and kept when the getter then loads from that
   object. This follows the key's arm through thunks, helpers and virtual calls on the record.
2. Probes: every other loaded field is set to test values (0, 1, sign boundaries, all ones, a
   float 1.0, an SI_DATE, a year/day date, single bits) and the getter re-run. With exactly one
   field that changes the result, the plan is the first `bulkplans` form that reproduces every
   probe (int signed/unsigned, bool nonzero or bit k, float, double, tenths, SI_DATE, year/day,
   colour, with or without zero-is-null). A pointer slot whose object answers `{u32 length,
   bytes}` gives a string plan; one whose object's +0xC/+0x10 become the result gives a
   record-reference plan.
3. Null links: every pointer on the plan's chain is set to null and the getter must give None,
   as the plan does.

### Branch paths

Every run records the set of executed basic blocks of shipped code (`PathTracer`); the path
hash is blake2b-8 over the sorted block RVAs, so loop counts do not change it and any branch
that runs different code does. A compiled plan carries `paths`: {path hash: the run that first
reached it}, e.g. for COMP `Pat0` (int at chain [0xC8, 4]):

    {'<hash A>': 'baseline: every field the arm reads is 0, every pointer it follows is set',
     '<hash B>': 'u64@[0xc8] = null'}

These are the branches the plan was derived on and what selects each. Verification
(`plancompile.verify`) runs the getter on 50 real records with the same tracer and returns
`uncovered path` when a record took a path the compile did not see, even if the value agreed,
so such a plan is not stored. Traced plans (`bulkplans.PlanTracer`) now record the paths of
their sampled records too (`plan['paths']`: {hash: records}); `plancompile.audit_paths` measures
the paths of existing plans over many records. A C block hook in FastVM can compute the same
hash during the fill (the definition is the sorted set of block RVAs).

The first COMP run without the null-link probes showed why this matters: 17 of 21 compiled
plans had 45 of 50 verification records on a path the compile had not seen (their pointer at
+0xC8 is null, the synthetic record's was set), with agreeing values. Adding the null-link runs
brought the compiled paths to the paths real records take: 19 of 24 verified with every record
on a compiled path. `WpBn` was demoted: 14 of 50 records disagreed, all on paths outside the
compiled two (the records took 12 different paths).

Audit of shipped traced plans (`audit_paths`, 200 random records each, 27 CPU s): of 169
ACTUAL_PLAYER direct plans, 158 see one path and 11 see two to five; of 82 CLUB plans, 50 see
one path and 32 see two or three. No plan disagreed with the getter on these 200 records. The
plans with several paths are the ones to audit continuously (the review's "right on samples,
wrong on a rare path" case); the shipped plans predate path recording, so they carry no
`paths` until re-derived.

### Results on 27.0.0.2493426 (all classes, 11 November)

Fields emulated today that a direct plan could serve (scalar, handled by the getter): 2,216
(class, field) pairs. One process, `nice -n 10`, load average 75-80: 3,190 s wall, 3,374 CPU s,
95,382 getter runs on the Python VM with the path tracer, verification included.

| | Pairs |
|---|---|
| Compiled | 237 (10.7%) |
| Verified on 50 records, every record on a compiled path | 191 (8.6%); 113 of them saw one value only in the check |
| Demoted (a value disagreed) | 40 |
| Values agreed, a record on an uncovered path | 6 |

Per snapshot table (the table's own columns, summed over its classes): injury 20 of 27,
weather 8 of 13, language 7 of 10, team 5 of 20, stadium 3 of 15, competition 19 of 163,
person 69 of 825, player 28 of 336, non-player 8 of 108, club 20 of 552, national team 0 of 131.

Why the rest is not compiled (pairs): the result does not depend on any record field the arm
reads (771: values from game state, other tables or lists, such as a club's second team);
the getter fails on the synthetic record (406: virtual calls through pointers held in the
record, whose class the record does not fix, and instruction budgets); several fields feed the
result (about 510: arithmetic, ratings, combined flags); no plan form reproduces the probes
(184); a null pointer on the chain gives a value other than None (91). The 40 demotions are
mostly booleans that depend on a second field the synthetic record left at zero (`PCDB`,
`PMbp`, `PMce`: plan True, getter False) and chains that land on unreadable memory on real
records (`FNin`, `Pcbi`); verification caught every one.

Cost: about 1.5 CPU s per field on average, dominated by the player and staff classes
(ACTUAL_PLAYER_AND_NON_PLAYER 1,329 s for 218 fields). This is not cheaper than tracing; what
it buys is a plan that needs no records with differing values, and its branch paths.

In the snapshot plan phase the compiler runs before the tracer: unbudgeted for a class with
missing plans (a new build), else at most 15 s per build for fields emulated today
(`snapshot.COMPILE_BUDGET_S`); verified plans are stored as `origin: compiled`, and a field the
compiler tried is marked `compile: 1` so it is not tried again.

## 3. Consistency under play

Scope note (orchestrator, 11 November): freshness is moving to the performance lane as
content-based change detection (hashes of the record-arena pages decide what is re-read; the
game date stops being the staleness key). This lane keeps only the small per-table stamp below,
which that design can reuse: a page-hash refresh can write the same `read_at` entry per table.

`Build.run` reads every table through `consistency.read_table`, which stamps the game date
before and after and checks the table's vector header (root, header, start, end, capacity).
After the eager emulation, `consistency.settle` re-checks the date and every header and
re-reads only the stale tables: read on another day, read while the day changed, or whose vector
moved (moved vectors are re-enumerated first), up to two passes. The stamps go to `_build`
(key `read_at`: `{table: {game_date, stable, rereads, reason}}`), and when every table was
re-read on a new date the snapshot's game date becomes that date. Before, the build checked
once at the end and noted "the snapshot mixes both days". On a quiet game the cost is two
4-byte date reads and one header read per table.

## 4. Platform boundary

`fmdb/platform_model.py` names the five things the reader needs from a platform and puts the
macOS ARM64 implementation (`fmdb/platform_macos_arm64.py`) behind them. A Windows x86-64
port adds a second implementation; the anchor recipes, the pinned anchor names, plans,
verification and the snapshot stay as they are.

| Part | Interface | macOS ARM64 today | Windows x86-64 would need |
|---|---|---|---|
| Image model | `load_binary(path)`; bytes by RVA, `function_of`, `starts`, `is_code`, `pointer(slot)`, `data_range`, `stub_for`, sha256, version | Mach-O fat/thin, chained fixups or LC_DYLD_INFO, LC_FUNCTION_STARTS | PE/COFF, base relocations, `.pdata` for function bounds, the IAT for imports |
| Type model | `type_key(canonical)`, `vtables`, `vtable(type, offset)`, `slot`, `class_name`, `base_offset` | Itanium RTTI (`__class_type_info`, `__si_`, `__vmi_`), offset-to-top, vbase offsets | MSVC RTTI (complete object locator at vtable[-1], class hierarchy descriptor, base class array with mdisp/pdisp/vdisp), `.?AV...@@` names |
| Code model | `refs`, `refs_in`, `calls`, `fingerprint`, `find_fingerprint`, and the shape questions `fourcc_constants`, `first_branch_target`, `constant_return_functions`, `virtual_bool_check_globals`, `call_result_stores`, `loads_by_width` | AArch64: ADRP pairs, BL, MOVZ/MOVK | x86-64: RIP-relative operands, `call rel32`, `mov r32, imm32`, `call [rax+slot*8]` |
| Process access | `open_process(binary)`: regions, read, read_many, the image's load address | `fm_fast_reader` (task port), image found by Mach-O UUID | ReadProcessMemory / a module snapshot, image found by PE timestamp and size |
| Calling convention | `CallingConvention` (this, arguments, result, link, stack) and the external-function models | AAPCS64; models of libc, libc++, pthread, libm (25 functions) | Microsoft x64 (`WIN64` is listed for reference); models of the MSVC runtime |

The emulator (`vm.py`, `fastvm.py`, `ui_vm.py`) and the 25 external models still use AAPCS64
and Unicorn's ARM64 mode directly; they are the largest part of a port. `anchors.py` asks the
platform model questions and never decodes an instruction itself. `anchors.Binary` remains as
an alias of the macOS model for existing callers.

## 5. Write readiness (phase 3; not built)

A direct plan is an address expression: start at the record, follow `chain[:-1]` as pointers,
read `width` bytes at `chain[-1]`, decode by `type`/`transform`. 755 of the 1,224 shipped direct
plans are plain integers (`int`, `identity`); the rest are bit flags, dates, tenths, colours,
strings, record references and 127 rating blobs. A write plan is the same expression with an
encoder:

- Encoder per terminal type: `int` (width, sign, range check), `bool nonzero` (write 0/1 into
  the stored width), `bool bit:k` (read-modify-write of one bit), `float div10` (round to
  tenths), `sidate`/`date_yd` (pack), `colour`. Strings and record references are not plain
  stores (they allocate or must point at an existing record) and stay out of the first set.
  Rating blobs write the 0-100 raw byte, never the 1-20 rating.
- Validation schema: `editor.fmf` as parsed by `catalog.py` (minimum, maximum, enum values,
  dependencies, `read_only_dependencies`). A value outside the editor's own range is refused.
- Oracle: the setter, as the getter is the read oracle. In every `db::` class checked, vtable
  slot 2 is a FourCC comparison tree of the same size as the slot-3 getter (CLUB 394 vs 398
  keys, COMP 267 vs 313, PERSON 88 vs 386 at the base level, STADIUM 81 vs 96), which makes slot
  2 the property setter; this is a static observation, not yet confirmed by emulation. Accept a
  write plan only when the emulated setter, given the new value on a copy, writes exactly the
  bytes the plan's encoder would write (VM dirty pages diffed against the copy) and nothing
  else. A setter that allocates, notifies or touches shared pools needs code in the game
  process and is out of scope for direct writes.
- How static compilation extends to setters: the compiler already runs shipped code on a
  synthetic record with a pointer skeleton and probes. For a setter it would call slot 2 with
  a probe value in the variant argument instead of probing record bytes, and trace writes
  (a UC_HOOK_MEM_WRITE on the synthetic range) instead of loads: one written location whose
  bytes follow the probe value under one encoder is a compiled write plan, and the path hash
  states which branch (validation, clamping, side effects) the write takes. The read plan and
  the write plan of a field must then agree on the chain and width.

## 6. Deployment prerequisite: attaching to the game

Checked on this Mac with `codesign` and `csrutil` (11 November):

- The game's main executable (`com.SportsInteractive.FootballManager27`, team 3JJX9QL35J) is
  signed with the hardened runtime (`flags=0x10000(runtime)`) and has no
  `com.apple.security.get-task-allow` entitlement. Its entitlements include
  `com.apple.security.cs.allow-dyld-environment-variables` and
  `com.apple.security.cs.disable-library-validation` (and camera and photo-library access).
- The reader's helpers (`fm_fast_reader`, `fm_live_helper`) are ad-hoc signed with
  `com.apple.security.cs.debugger`.
- This Mac runs a custom System Integrity Protection configuration: `csrutil status` reports
  "Custom Configuration" with "Debugging Restrictions: disabled" (also Filesystem Protections and
  Kernel Integrity Protections disabled).

On a Mac with default SIP, `task_for_pid` from an ad-hoc-signed helper on a hardened-runtime
process without `get-task-allow` is expected to fail, so the reader is expected not to attach
there. This has not been tested on a stock Mac. Every live feature, including the anchor live
scan and `Engine.open_build`, depends on that attach. The two dyld entitlements mean a library
named in `DYLD_INSERT_LIBRARIES` would load into the game without changing its signature; that
route, and whether to take it, is the owner's decision and nothing here acts on it.
