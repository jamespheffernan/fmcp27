# Game update: making the reader address a new Football Manager 27 build

The reader carries the plugin addresses of build 27.0.0.2493426 (plugin sha256 `774cacde…`)
as integer literals: about 2,500 distinct addresses across the hand-built tools, the knowledge
engine and the fmdb core. A Steam patch moves them. One command finds them again on the new
build; the server applies the result when it starts.

## What the owner sees

1. Steam installs the patch. At the next server start the reader notices the new plugin
   (one hash of the installed plugin, cached by file identity) and, finding no address map
   for it, stays on the pinned numbers. Every tool that reads the game refuses with:

   > Unsupported player layout. The game runs build 27.0.x.y, which this reader has no
   > verified address map for; it is verified for 27.0.0.2493426. Run once, with or without
   > the game running: `PYTHONPATH=. python scripts/fm_update_build.py --installed` then
   > restart the MCP server.

   Tools that read saved files from disk keep working.
2. The owner (or an agent) runs that command. It needs no game and takes one to three
   minutes. It prints how many addresses resolved, which tools and tables are unavailable on
   the new build and why.
3. Restart the MCP server. `fm_status` shows `game_build.state: "mapped"`, the counts, the
   unresolved addresses and `unavailable_tools` (each with the address and the reason).
   `fm_coverage` shows the same plus `unavailable_tables`.
4. With the new build running and a save loaded, run the same command with `--live`. It reads
   the game (read-only), proves the map and withholds any hand-built field that disagrees with
   the game's own getter. Restart the server once more.

## The procedure, as the next agent runs it

All commands from the repository root, with `PYTHONPATH=.`, `FMCP_NO_BACKGROUND_FILL=1` and the
cache the server uses (`FMCP_CACHE_DIR`).

| Step | Command | Game | Duration |
|---|---|---|---|
| Static update | `scripts/fm_update_build.py --installed` | not needed | 45 s on the pinned build; 1 to 3 min on a patch |
| Restart the server | (client) | | |
| Live proof | `scripts/fm_update_build.py --installed --live` | the new build, a save loaded | 10 to 20 min |
| Plans | add `--plans` to the live run | as above | about 40 min more |
| Ship | commit the fingerprint index (`--ship-index`) and the plan cache entry for the new sha256 | | |

The static update, step by step (timings measured on the pinned build, 12 November 2026):

| Part | What it does | Time (pinned build / 27.0.1) |
|---|---|---|
| preserve | copies the plugin, `GameAssembly.dylib`, `global-metadata.dat`, `Info.plist`, the `.fmf` files and the five front-end asset bundles (`bundles/`, 14 MB; from builds after 27.0.1) to `fmdb-runtime-research/builds/<version>/` (once) | 2 s |
| load | parses both plugins (the new one and the preserved pinned one) | 1 to 5 s |
| derive | the 237 named fmdb anchors (`anchors.resolve`), then every address literal (`address_map.derive`; on a patch the whole-binary function match of `function_match.py` first, 46 s), the named anchors the fingerprints missed filled from the address map, and the native code guards next to them | 13 s / 86 s |
| import check | imports every module of the package with the map applied, in a fresh interpreter, and computes the unavailable tools and tables (unresolved addresses and native guards whose code changed) | 3 to 12 s |
| extras | whole-binary function diff, import list against the VM's modelled externals, moved structure offsets (`build_update.structure_changes`, 35 s), the functions the emulator calls by address, `operator new` sizes per class, `editor.fmf` schema diff, the front end of the new build (below, 10 to 17 s), UI handler registry of the new build (the shipped one translated slot by slot through the function match; handler types carried when the factory is unchanged; its key/label list changed by what the new front end added, removed or relabelled), the UI registration function in `GameAssembly.dylib`, the fingerprint index of the new build | 11 s / 54 s |

Outputs, in `$FMCP_CACHE_DIR/fmdb/anchors/`:

* `<sha256>.addresses.json`: the address map the server loads;
* `<sha256>.json`: the fmdb anchor file (`fmdb/build.py`, `Engine.open_build`);
* `<sha256>.update-report.json`: everything the run found: resolved and unresolved per group
  and per module, each unresolved address with what it was on the pinned build (its function
  and offset, or its section), why it did not resolve and where the source uses it, the
  tools and tables it disables, and the per-build diffs;
* `<sha256>.ui_registry.json.gz` and `anchors-reference-<sha256>.json.gz`;
* `<sha256>.ui_frontend.json.gz`: the new build's front end (below).

**The English language template.** Three modules carry English text compiled from the pinned
build's `example.ltf` and bind it to that file's sha256 (and the concern-history query to its
size): `_concern_template_definitions.py`, `promise_kind_definitions.py`,
`live_player_concern_history.py`. The extras step (`build_update.english_template`, under 1 s)
reads the installed file and compares every compiled text with the new file's text for the same
id; when all agree the map records the file under `english_template` and the address book
rewrites the pinned identity in those three files to the new one, so
`fm_get_player_concern_history(include_templates=true)` accepts it. A text that changed leaves
`verified` false with the ids listed, and the query keeps refusing. The other modules that name
the pinned template's sha256 (playing time, injuries, bans, international duty, staff
responsibilities, tactic roles, assessment labels) use it as provenance only and do not read the
file; their compiled texts are not yet checked against a new file.

**The front end per build.** The screen tools turn values into the game's words through the
front end: data collections in the `ui-datacollections` asset bundle map a value to a translation
id (`OverallHappinessDataCollection`, `ClubVisionProgressDataCollection`, ...), the game's own
translator gives the text; the property registry in `GameAssembly.dylib` labels each FourCC; the
record schemas, views and view parameters come from `global-metadata.dat`, `GameAssembly.dylib` and
the UXML bundles; the 231 screen-parameter globals are plugin addresses. None of this is a census
literal, so the address map never translates it. The extras step runs
`scripts/fmdb_ui_frontend.py --app <the installed fm.app>` (capstone and UnityPy, through `uv run`
from its cache when the server's interpreter lacks them) and writes the table next to the map;
`ui_frontend.table()` loads the running build's (`ui_frontend.active_source()`; `fm_ui_frontend`
shows it under `source`). The report's `extras.front_end.diff` lists registry keys added, removed
and relabelled, data collections whose keys or translation ids changed, translation ids added and
removed, record schemas, views and table factories changed, screen parameters added or removed and
UI record ids renumbered. On the pinned build the shipped table is the front end. On a mapped
build without its table (the extractor could not run) the shipped table is used with a
`front_end_note` in the screen tools' results, and only the parameter globals the address map
translates are kept.

The live part, after a live type scan (24 table roots, singletons, interceptor objects) and a
second derivation with it, runs with the map applied: `fmdb_vm_check.py`, `fmdb_oracle.py` on a
sample (the decoder self-check below), `fmdb_snapshot_check.py`, the live tests
`tests/test_fmdb_live.py tests/test_fmdb_snapshot_live.py tests/test_bridge.py`, and with
`--plans` the plan re-derivation `fmdb_snapshot.py`. Each result is recorded in the map's
`verified.checks`.

## How it works

**The census** (`fm_live_mcp/fmdb/address_census.py`, shipped as
`fmdb/data/address_census.json.gz`) decides for each integer literal under `fm_live_mcp/` that
falls inside the plugin image whether it is an address. A value inside the image range is not
always an address: 100000 is a row budget, 0x15370 an offset into the match engine,
0x1001F0 a bit mask, 629884 a template id. The census decides from the pinned build's kind of
the value (vtable, type_info, function start, instruction, referenced data, constant, section
bound) and the site: a literal next to code bytes or a sha256 is an address whatever its
spelling; a literal added to a non-base operand anywhere and never to the image base is an
offset; operands of bit operations and names containing MASK are masks; powers of two and
decimal multiples of 1,000 are sizes; decimal numbers inside functions are ids; the offline
save parsers (`person_wire/`, `_saved_offers/`, `_saved_league/`) use native addresses only as
labels. `fmdb/data/address_overrides.json` lists the 62 values (80 sites) the rules cannot decide, each with
its reason. `tests/test_address_book.py` fails while the tree holds an in-range literal the
census lacks; rebuild it with `scripts/fmdb_rebase.py <pinned plugin> --census --write`.

How the rules were checked on the pinned build: every site the plain value test called an
instruction address written in hex (295 sites) was read by hand; 55 were coincidences (struct
offsets, masks, ids, the Mach-O CPU type, provenance labels) and are now decided as such. All
669 sites decided as decimal ids or out-of-range values were read: none is an address. A random
sample of 50 address sites held no coincidence.

**The address map** (`fm_live_mcp/fmdb/address_map.py`) resolves each address on the new build
from the preserved pinned binary. Methods, strongest first: the fmdb named anchor; RTTI
(vtables by class and subobject offset, ranked when a class has several; type_info by name);
import stubs by symbol; section bounds by name; the exported function of the same name (code in
it, and globals it references at the same place); the containing function's masked fingerprint
plus the offset; a vtable slot; the k-th call of a unique function; a neighbouring unique
function; the n-th ADRP reference of an unchanged function; the bytes of a `__TEXT` constant; an
offset inside a vtable or a type_info; a field of a referenced global with equal bytes and
pointer layout; an `add` then `ldr/str [x, #d]` chain in an unchanged function; a zero-fill
global between two referenced neighbours whose distance is unchanged; the page of another
address of the same file; a range bound kept at the same offset in its section. A value that
none of them finds stays unresolved with the reason.

**Changed functions** (`fm_live_mcp/fmdb/function_match.py`). The methods above need the
function's masked code unchanged. A point release changes thousands of functions (10,389 of
118,168 from 27.0.0 to 27.0.1), so the update first matches every function of the pinned build
to the new one the way a binary differ does: from the functions exported under the same name, then
those whose fingerprint is unique on both builds, it propagates round by round through the call graph (the same matched callers, and
the same matched callees and imports in order), the k-th call of a matched caller whose calls
align, the vtable slot of a class, referenced strings and globals, the sequence of imports,
the only function between two matched neighbours, and inside such a gap the most similar
function by a clear margin. A match must be unique and mutual; each records its method and the
similarity of the two functions as its confidence. Held out, the method finds 6,133 of 6,146
hidden unchanged functions again with 1 wrong (10 percent hidden; 30 percent: 18,358 right, 4
wrong, `tests/test_function_match.py`). An address inside a matched changed function follows
its aligned instruction: a sequence alignment of the instructions with registers, stack slots
and address fields masked, where calls and global references align only with the call or
reference to their counterpart, and, for blocks the compiler moved, the instruction whose eight
neighbours are unique in both functions. The site is accepted only when the nearest calls or
references around it align on both sides of it (or its context is unique, or it is the
function's start); on held-out calls and references that check leaves 18 wrong of 2,699
accepted. The instruction at the site is then classified: `same` (only address fields differ,
including the page offset of a global in a register the compiler hoisted, recognised by its
reaching ADRP definitions or through the data map), `registers`, `stack`, `offset` (a load,
store or add whose offset changed: resolved, and recorded as a structure change) or `logic`
(unresolved, with both instruction windows in the map). Native guards whose span is the same
code up to address fields are re-derived; the others keep refusing and the import check lists
their tools with the verdict.

**The address book** (`fm_live_mcp/address_book.py`) runs at package import. On the pinned build
it does nothing. On a build with a map it installs an import hook that rewrites, in every module
of the package: the literals the census marks as addresses (to the new build's values), the
build identity strings (`players.VERSION`, `players.SHA256` and their copies, so every scattered
build gate accepts exactly the mapped build), and the expected bytes or sha256 of a native guard
whose code is unchanged under masking. An unresolved address becomes an `Unresolved` object:
any arithmetic, comparison, conversion or formatting inside a function raises
`UnresolvedAddress` naming the build and the pinned address, so exactly the code that uses it
refuses; at module level arithmetic yields another `Unresolved`, so modules still import.
`fm_status` and `fm_coverage` list the tools whose code reaches such an address (a static walk
over the live function objects: globals, closure cells such as the captured Bridge, module
attributes and methods named in the code) and the fmdb tables whose root, vtable or getter is
missing.

Why this mechanism and not named anchors everywhere: the 237 fmdb anchors already go through
named constants, and the rest are ~2,250 literals in ~380 files, most of them in tables
(tuples, dicts, guard lists) that tests freeze. Converting them by hand would touch every one of
those files and every test that pins their values. Translating at import leaves the source and
its tests as they are, applies to code written tomorrow (the census test forces the
classification), and on the pinned build changes nothing at all. The fmdb core keeps its named
anchors as the first resolution method, so both agree.

## Struct offsets

An address map cannot see a field that moved inside a record. What catches it:

* **Direct read plans** (fmdb core) are re-derived per build and verified against the getter
  (`--plans`); they are keyed by plugin sha256.
* **Hand-built decoders**: the live part runs `fmdb_oracle.py` on a sample with the map applied.
  A field whose tool value disagrees with the generic getter on the new build, and that has no
  recorded finding in `fmdb/oracle_map.py` (the explained disagreements of the pinned build), is
  written to the map's `withheld`; at the next start the server replaces that field in the tool's
  result by `{"withheld": reason}` instead of its value. `fm_status` lists them.
* **Manager walkers** (`fmdb/mgr_walk_people.py`, `fmdb/sources/managers_market.py`): the static
  update compares, per manager class, the `operator new` size before its vtable store, and the
  `mov w0, #size` at the walker's recorded allocation site. A manager whose size changed is
  disabled (`disabled_managers` in the map); its walker reports the reason instead of reading.
* The static report lists every database record class whose allocation size changed
  (`allocation_sizes.changed_db_records`): the decoders of those classes are the first to check.
* **Moved offsets in code** (`structure_changes` in the report): every load, store or add whose
  offset differs between the aligned instructions of matched changed functions, with global
  page offsets and stack slots left out; those aligned between matching calls and references
  in functions at least 0.9 alike are `confirmed`, and those inside a function the reader's
  source names are listed with the files. They are candidates, not proof.
* **Record getters without the game**: `scripts/fmdb_static_plans.py` compiles the direct read
  plans of every record class from the plugin file alone (plancompile on a synthetic record,
  stand-ins for the game-layer objects, the typed-traits registry built by its own
  constructor), on both builds, and `--compare` diffs them per class and field.
* **Applying a proven move**: a hand-built decoder reads a field through
  `address_book.field(structure, pinned offset)` instead of a bare offset. The pinned offset is
  the default; a map's `offsets` ({structure: {hex pinned offset: new offset or null}}, copied
  from `fmdb/data/structure_offsets.json` for that plugin sha256) changes it, and null refuses.
  Nothing else reads that table: the import rewrite changes only census addresses, so no other
  number can change (`tests/test_function_match.py` checks both). A move enters the file only
  with its proof.

## Proof on the pinned build

`scripts/fm_update_build.py <preserved pinned plugin>` treats the pinned plugin as a new build,
with `strict` set (a short function is never accepted for sitting at the pinned address): every
value comes from a method above, none from the pinned number. Results, 12 November 2026:

| Group | Address values | Resolved by RTTI, fingerprint and xref alone | With the added methods | Wrong |
|---|---|---|---|---|
| fmdb core | 328 | 294 | 328 | 0 |
| hand-built tools | 1,900 | 1,690 | 1,900 | 0 |
| knowledge engine | 414 | 296 | 414 | 0 |

(A value used by two groups counts in each; 2,488 distinct values.) The default test selection
run through that map (`FMCP_ADDRESS_MAP=<map> pytest -q -p no:cacheprovider`, 521 modules
rewritten in every worker): 19,590 passed, 34 failed, 468 errors, the same set as the run without
the map; every failure is a FileNotFoundError on `evidence/`, which this sparse checkout lacks.
An earlier map that left three table roots and one range bound unresolved failed exactly the ten
tests that read them, each with the refusal naming the address; that is how the `bracketed`
method and the range override were added.

A non-identity run, as a stress test: the FM26 plugin installed on this Mac (26.3.2.2329565, a
different game year, so far more than a patch changes) through the same command, 39 s. 49,411 of
the pinned build's 118,168 functions are unchanged there; 739 of 2,488 address values resolve
(named 220, RTTI 344, vtable slots 204, fingerprints 102, string content 97, and the rest), 36
native guards are re-derived and 41 refuse because their code changed. The whole package imports
with the 1,749 unresolved values in place; 151 of 196 tools and 17 fmdb tables are listed as
unavailable with the address and reason, 45 tools (mostly saved-file readers) stay available,
18 manager walkers are disabled. A real patch of FM27 changes far less.

On the server: importing it with a map costs about 2.4 s the first time (every module parsed,
rewritten and compiled) and 0.5 s after, from a bytecode cache under
`$FMCP_CACHE_DIR/fmdb/anchors/code/`, keyed by the map, the census and the address book.

## The first real patch: 27.0.0 to 27.0.1 (12 November 2026)

`docs/builds/27.0.1.md` has the full account. What the update taught:

* The first run of the command (the methods before the function match) resolved 1,892 of the
  2,488 values and 230 of 237 named anchors with 6 required ones missing, and the server did
  not import (0x17DB1D8, a knowledge-engine function, changed). The function match was added
  for this patch.
* With it, the command alone now gives a map the server accepts: 2,323 of 2,488 values, 237 of
  237 named anchors (7 filled from the address map: the stadiums table root, four interceptor
  globals, the typed-traits registry, the news resolver), every module imports, 758 native
  guards re-derived, 47 of 196 tools unavailable (each with the address or guard and the
  reason), no fmdb table unavailable. Static update 132 s (load 1 s, derive 86 s of which the function match
  46 s, import check 3 s, extras 42 s).
* With the game running, every front-end word read null: the map had sent the translator global
  0x5721E70 to the characters singleton, a fingerprint twin (above). Exported names now decide
  first, which corrected that value and two more (0x5721EB0, 0x229DC). The front end itself
  changed little (6 registry keys added, no translation id or collection changed), but the 226
  screen-parameter globals the source does not name were pinned addresses in the shipped table;
  the update now extracts the new build's front end and checks the English template the
  concern-history query binds to (`docs/builds/27.0.1.md`, "Front end and words").
* What stayed manual: reading the unresolved and refusing sites (most are match-engine code
  the patch rewrote; their tools stay unavailable until a decoder is re-derived), the live
  proof (`--live`, the game was closed), and the decision that no structure candidate is proof.
* Tests: the default selection with the 27.0.1 map forced on fails where a test executes
  pinned-build native code from a fixture against the rewritten addresses (5,818 of the 5,834
  results that fail only with the map); those tests prove the pinned build and cannot pass on
  another. The other 16 are pinned-build data checks (shipped plan files, the reference index,
  the keys of a UI handler whose getter changed).

## pi-fm's tactic writer

`adviser/pi/fm-tactic-files.py` (`fm_tactic_file`) and its siblings `fm_tactic_native_core.py`,
`fm_tactic_native_authoring.py`, `fm_tactic_role_catalog.py`, `fm_tactic_team_instructions.py` and
`fm_tactic_position_records.py` run the game's own tactic code under Unicorn: the loader, the
serializer, the role setter, the internal-flag and availability predicates, the team-instruction dispatcher
and the player-instruction setters. They carry the pinned build's addresses, guard hashes and
identity like the reader, and follow a build through the same command.

* **Census.** `fmdb/data/adviser_census.json.gz` classifies every in-range literal of those six
  files on the pinned plugin (238 address values) and records each file's sha256. Rebuild it after
  editing them: `scripts/fm_update_build.py --adviser-census`; `tests/test_adviser_book.py` fails
  while a literal is missing or a file differs. Overrides sit in `address_overrides.json` under
  `adviser/pi/<file>`: role words and position masks next to a record hash are coincidences; the
  pages the emulator premaps are `page` overrides (the page of the file's addresses in it, or with
  `of` the page of one named address); the bound of on-demand code pages is a `range`.
* **Derivation.** `fm_update_build.py` runs `fmdb/adviser_update.py` after the reader's derivation
  and writes the result under `adviser` in the map: the values (the same function match, 2 s more),
  the guards (re-derived when the code is the same under masking, or from a hand review under
  `builds.<sha256>.adviser_guards`, including a new span length, which the adviser's rewrite applies
  to the length literal), the build facts below, and `disabled`: the writer functions whose own code
  uses an address with no counterpart or checks a guard over changed, unreviewed code.
* **Build facts.** The plugin's sha256 and its arm64 slice offset (from the fat header) always;
  the English template's sha256 only when every English text the writer carries is the new file's
  visible text under the same text id (212 role names and internal flag names of the role catalog, of
  `prepared_tactic_roles.py` and the role-matrix labels, the 80 team-instruction names under the
  text ids their native key routes load, and the mentality names); `global-metadata.dat`'s sha256
  only when every enum holding a metadata name of the role catalog is unchanged. A verified English
  template also re-binds `prepared_tactic_roles.ENGLISH_RESOURCE_SHA256` in the reader, which the
  writer imports.
* **Run time.** `fm_live_mcp/adviser_book.py`. The writer's two scripts start by importing it from
  `PI_FM_TACTIC_READER_ROOT`; on a mapped build `fm-tactic-files.py` (and the native-authoring
  subprocess) run again as `__main__`, compiled through the rewrite, and the siblings and the core
  load through the same rewrite. On the pinned build, an unsupported build, or a file whose text
  differs from the census, nothing is rewritten and the writer's own identity checks decide. A
  disabled function refuses at its first line with the build and the reason; `list_templates`
  reports `native_build` (state and `unavailable_functions`).
* **Proof.** `scripts/adviser_two_build.py` loads the writer the way production does on both builds
  and compares everything it consumes from the game's code (loader stages, records, flags,
  serialization, legal role sets (each choice a role word with its internal flag), availability,
  role changes, team commands, player
  instructions, marking targets, an authored request).
  `tests/test_adviser_two_build_mapped.py` runs it on two templates (`pytest -m mapped_build`).

What stays manual for the writer: reviewing changed guarded functions (with the comparison as
evidence), and its `fm-tactic-files.py` donor-based and scalar team edits, whose guards cover whole
pages and serializer helpers that a patch rewrites; they refuse until re-derived.

## What stays manual

* Addresses the update leaves unresolved, and native guards whose code changed (`guards.spans`
  in the map, with the differing instructions): read them in the report; re-derive the decoder
  against the new code, add a resolution method or a census override, or accept that those
  tools stay unavailable.
* Structure candidates (`structure_changes`): a move enters `fmdb/data/structure_offsets.json`
  only with proof; the decoders read such a field through `address_book.field`.
* Fields of hand-built decoders that the oracle map does not cover are not self-checked; the
  allocation-size diff points at the record classes to check first.
* The knowledge engine reimplements game rules (relation masks, transfer predicates, stars); a
  patch can change a rule without moving an address. Re-run `scripts/knowledge_golden.py` live.
* Digests over whole guard tables (a recorded run's policy) must be taken over the source values with
  `address_book.pinned_constant`, or the map's rewrite changes them; the recorder's tactics policy did
  not and refused on 27.0.1.
* Code-range hashes that are not next to their address (`match_rating.UPDATER_SHA1`,
  `match_state.MOMENTUM_SHA1`) are not re-derived; those features refuse until checked by hand.
* The UI handler registry's key/label list is the pinned one (recovered from the pinned
  `GameAssembly.dylib`) changed by the keys the new build's front end added, removed or relabelled
  (the front-end extraction above reads the whole registry of both builds). Handler slots whose
  function changed keep only the function (no keys) until the registry is rebuilt live
  (`scripts/fmdb_ui_registry_build.py --live`).
* The pinned build's asset bundles were not preserved, so the shipped front-end table cannot be
  re-extracted from files any more; it stays the record of 27.0.0's front end.
* The masked fingerprint keeps the page offset of a load through an ADRP register the compiler
  reused (only the first use after the ADRP is masked). Two accessors whose globals swap in-page
  offsets therefore swap fingerprints: 27.0.1's `_i_characters_get_instance` has the fingerprint
  27.0.0's `_i_translator_get_instance` had. Exported names now decide first; a non-exported
  function with such a twin can still be paired wrongly by the fingerprint.
* Integer literals below 0x10000 are not in the census (offsets dominate there); the one plugin
  address in that range, the start of `__text` (0x55F0), is used in three range checks.
* Commit the new fingerprint index (`--ship-index`) and the plan cache entry if the build is to
  ship to other machines.
* Tests run on the pinned build: `tests/conftest.py` sets `FMCP_ADDRESS_BOOK=off` unless
  `FMCP_ADDRESS_MAP` names a map; run the live tests of a new build with that variable set (the
  live part does).
