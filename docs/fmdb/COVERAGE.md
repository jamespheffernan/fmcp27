# fmdb PropertyVM coverage (FM27 27.0.0.2493426, ARM64)

`fm_live_mcp/fmdb/vm.py` answers an editor field by emulating the record's own property
getter, `record.vtable[3](record, fourcc, out)`, in Unicorn. Code comes from the
SHA256-pinned on-disk ARM64 slice; data pages are copied from the live game on first
touch; stores stay inside the VM and are rolled back before the next call. A value is
reported only when the shipped getter produced it; everything else is `Unavailable(reason)`.

## Getter ABI

* `x0` = record (for PERSON tables, the PERSON subobject pointer held by the table; the
  slot-3 thunk adjusts to the primary), `w1` = FourCC as a big-endian u32 (`'PCAB'` =
  0x50434142), `x2` = 16-byte `sicore` typed value, which must already hold a valid NULL
  value: the getter destroys the old value through `out->traits->vtable[3]` before storing.
* `w0` != 0 when the getter claimed the key. Unclaimed keys fall through class getters to
  the generic database getter 0x11B23E8.
* Typed value = `{traits*, payload:u64}`; traits = `{vtable, kind:u8}`. Registry built by
  0x4403CD4 (pointer at global 0x573BBA0): NULL, bool, int32, uint32, int64, uint64, float,
  double, STRING, SYMBOL, TYPED_LIST, RECORD, DATE_TIME. Other traits live outside the
  registry: `fmdate::SI_DATE`, `sicore::RGBA`, `sicore::DATA`. `variant.py` documents each
  payload layout (strings `{u32 len, utf-8}`; RECORD = vector of `{u32 key, typed*}`;
  TYPED_LIST = vector of `typed*`; DATA = `{u8*, u32 size}`; SI_DATE =
  `year << 17 | day_of_year << 8 | low8`; RGBA = 0xAARRGGBB).
* A database record reference is a RECORD with one entry `{table FourCC: int64 unique_id |
  random_id << 32}` (builder 0x11B404C). `RecordRef` keeps the FourCC and both ids;
  `tables.resolve` maps declared FourCCs to a live table index.
* Player attributes come back as 4-byte DATA blobs produced by GAME_PLAYER slot 10
  (0x20E7154). In every managed-squad sample byte 1 equalled the stored attribute and
  bytes 2-3 equalled byte 1; the blob is returned as bytes without further interpretation.

## Execution context the VM chooses

* `view='database'` (default): GAME_PLAYER (global 0x56D2B50) intercepts PERSON properties.
  The base player getter 0x1503624 asks its slot 7 (0x20F2D34, returns 0) whether to bypass
  the interceptor; slot 9 (0x20BB788) otherwise answers and returns NULL for PCAB/PPAB in a
  running career. The database view gives the VM a private copy of the GAME_PLAYER vtable
  whose slot 7 is the shipped `mov w0,#1; ret` at 0x4406A6C; no code byte is changed.
  `view='game'` keeps the interceptor (PCAB/PPAB then come back NULL).
* The same pattern recurs one game-layer object per record class. A static scan for
  `adrp; ldr x0,[global]; ldr x8,[x0]; ldr x8,[x8,#0x38]; blr x8; tbnz w0,#0` finds 15
  globals (`vm.INTERCEPTORS`: GAME_PLAYER, GAME_PERSON, GAME_ACTUAL_PLAYER,
  GAME_ACTUAL_NON_PLAYER, GAME_HUMAN_NON_PLAYER, GAME_RETIRED_PERSON, GAME_CLUB,
  GAME_NATIONAL_TEAM_CONTAINER, GAME_TEAM_CONTAINER, GAME_COMP, GAME_STADIUM, GAME_AWARD,
  GAME_MEDIA_SOURCE, GAME_DB_RECORD, GAME_CONTINENT), each with slot 7 the shipped
  `mov w0,#0; ret`. The database view bypasses all of them. What they hid: GAME_PERSON
  slot 11 (0x206C8E4) returns NULL for the eight personality ratings (Pada ... Ptem) unless
  game-option flags at 0x56D4987/0x56D498B are set; GAME_ACTUAL_NON_PLAYER slot 17 does the
  same for staff tendencies, board attributes, versatility and the Ncra/Npta/Ncrr/Nhmr/Nwrr
  ratings; GAME_CLUB withheld Csth and several stadium fields. A sample of every record
  type (5 records each, all editor codes) showed only gains apart from two keys the record
  getter does not claim at all (Pibl, Ctfc).
* Game fallback: in the database view a key the record's own getter does not claim (w0 = 0,
  NULL value) is asked again with the interceptors in place. If the game layer claims it,
  that answer is returned with `PropertyResult.view == 'game'` (`get_property(...,
  game_fallback=False)` turns this off). Several hundred non-editor keys per person class
  (season statistics, morale, form) are answered only this way (`extras.py`).
* Language files: with `file_resolver=` (e.g. `LiveSession.file_resolver()`, the UI VM's
  read-only `lsof` mapping) `fseeko/fread/ftello/ferror` on the game's own `FILE*` are
  modelled with the UI VM's stdio models, restricted to `.fmf` data files; the translated
  names come from `Resources/data/game_simulation/languages.fmf`. Without a resolver these
  calls refuse as before (`_fseeko`).
* `thread='reader'` (default): `pthread_self()` returns a VM-private id, so owning-thread
  checks (flag 0x56C10E8, words 0x56C10F0 / 0x56D66B0) fail and getters return stored
  values. With `thread='owner'`, condition/fitness getters bring the record up to the
  current date first (in the VM copy) and drew different values for 4-5 of 25 players.
* Thread-local variables resolve to a fresh per-call block initialised from the live TLV
  template. The PCG random generator descriptors (0x56C44F8, 0x56C4510) are refused:
  virtual-player attributes and some position scores draw random numbers per evaluation.

## Modelled and refused externals

Modelled in Python: allocation (`malloc`, `operator new`, `calloc`, `realloc`; bump heap,
reset per call), `free`/`delete` (no-op), pthread/os_unfair/libc++ mutexes and shared
mutexes (no-op), `__cxa_guard_acquire/release`, `___chkstk_darwin`, mem*/str* helpers,
`memset_pattern16`, `strtol`, libm, `pthread_self/equal` (thread model above), dyld TLV
access and `__tlv_atexit` (no-op: the per-call thread block is never torn down),
`__dynamic_cast` (walks the live Itanium RTTI, public bases only) and the printf
family (`%[flags][width][.prec][len]diouxXcspfFeEgG`, Apple variadic slots; anything else
refuses), and with a `file_resolver` read-only stdio on the game's `.fmf` data files.
Refused (call becomes Unavailable): other file I/O (`fseeko` without a resolver: translated
names are read from language files on demand), clocks (`gettimeofday`), C++ throws, and
every unlisted import.

## Fields that are not editor properties (`extras.py`)

* `EXTRA_FIELDS[record_type]`: keys the getters claim that the editor catalog does not list,
  found by `scripts/fmdb_extras.py` (static scan of every class getter and interceptor
  handler for `movz/movk wN; cmp wK, wN` FourCC constants, minus all catalog codes, each
  remaining key asked of sampled records). Data in `fm_live_mcp/fmdb/data/extras.json.gz`.
* `DERIVED[record_type]`: values no key serves, read through the native getter slot the
  property itself uses: player `condition_stored` (slot 138 with refresh flag 0; Pcon returns
  -1 while slot 23 reports days still out), `injury_days_remaining` (slot 23),
  `has_injury_record` (slot 21), `injuries` (the native injury vector player +0xF0);
  stadium `pitch_type_stored` (+0xAD; Spty maps 0 to 1); currency `name_stored` (+0x18;
  Cnam is translated). `Pijl`/`Phij` read the STARTING_INJURY database table
  (global 0x56D32A8, empty in a running career), so they never list a current injury.
* Census of 2026-11-11 (4 records per type, budget 500,000): 1,896 (record type, key) pairs
  return a value; the getters claimed 2,658 (type, key) pairs in all. Per type (with value /
  claimed / candidates): play 450/651/3220 (228 only from the game layer), nnpl 489/724/3212
  (231), offc 118/165, jour 123/168, agen 125/169, club 114/147/1370 (48), team 106/128,
  awar 79/95, natc 57/64, nati 51/57, comp 43/52, stad 18/26, cont 16, inju 10,
  curr/lang/lcrg/mdso/regi/drbr/agrm/stgn 9 each, dscr 8, weat 8. The game-layer person keys
  are mostly season statistics as `{valu, numb}` records (goals POgl, assists Poas, minutes
  POmi, xG PoxG, passes POpa/POpC, average rating Prat), plus morale `Pmor` and form `Pfrm`.
  Labels other than `Pcjo` and `injr` are inferred (`name_inferred`).
* Staff on job code 46 with contract status -1 get 0 from every display attribute: the
  rating conversion 0xC8B220 reads the main-contract job byte and returns 0 for that job set.
  This is the record's own logic (not an interceptor); the raw `NDxx` keys keep the values.

## Complications seen

* Lazily computed caches and mutation: getters write reference counts, pool free lists
  (sicore pools pop a node and push it back), static-init guards and owner-thread caches.
  All stores go to copy-on-write pages and are rolled back; `CallStats.mutated_pages`
  counts them.
* Pool allocation from live free lists: RECORD/TYPED_LIST/DATA objects are built from
  sicore pools whose free-list heads live in plugin globals; the VM pops live nodes into its
  COW copy, so decoded objects can sit at live addresses.
* Thunks and multiple inheritance: PERSON table pointers are secondary subobjects; the VM
  always enters through the table pointer's own vtable slot 3.
* Translated names: CURRENCY `Cnam` returns the translated name when the translation table
  has one in memory (`U.S. Dollar` vs stored `United States Dollar`) and reads a language
  file otherwise (Unavailable: `_fseeko` unless the VM has a `file_resolver`; then the name
  comes from `languages.fmf`, and `extras` `name_stored` keeps the stored string).
* Long scans: competition team lists (`ctms`, `cntm`, `otms`, `rgts`) and local-region
  city lists walk whole tables; some exceed the instruction budget or the 5 s timeout.

## Validation against hand-proven decoders (25 records per type)

| type | field(s) | match | mismatch | unavailable |
|---|---|---|---|---|
| CITY | Cnam, Clat, Clon | 75 | 0 | 0 |
| CURRENCY | Cexr | 25 | 0 | 0 |
| CURRENCY | Cnam | 17 | 1 (translated name `U.S. Dollar`) | 7 (`_fseeko`) |
| COMP | crep | 25 | 0 | 0 |
| PLAYER (ACTUAL_PLAYER) | PCAB, PPAB, Pfit, Pjad, Pcon | 125 | 0 | 0 |

`scripts/fmdb_validate.py` reproduces this table; `tests/test_fmdb_live.py` runs it when FM
is attached.

## Coverage run (2026-11-11, Newcastle career, game date Dec 2030)

Generated by `scripts/fmdb_coverage.py` (per type 25 sampled records plus the managed club / squad where relevant; view `database`, thread `reader`, budget 2,000,000 instructions). A field counts as **value** when at least one sampled record returned a decoded, non-empty value; **unset** when the getter claimed it but every record was null/empty; **not handled** when the getter returned 0 with a null value for every record; otherwise **unavailable**, grouped by the most common reason.

Totals: 30 record types, 2245 (type, field) pairs: value 1251, not_handled 505, unset 477, unavailable 12.

Calls: 71,898; mean 9.882 ms, median 0.142 ms, p95 6.87 ms per call; instructions mean 10,367.9, median 406.0, max 2,000,018. Wall time 740.4 s; 15,080 live pages and 827 code pages cached; 591,582 reader calls (70.8 MB).

| type | table | records | fields | value | unset | not handled | unavailable | unavailable by reason | mean ms |
|---|---|---|---|---|---|---|---|---|---|
| pers | people | 54 | 286 | 148 | 50 | 88 | 0 | - | 0.591 |
| play | people | 54 | 245 | 230 | 5 | 9 | 1 | external call _fseeko (1) | 4.452 |
| nnpl | people | 25 | 140 | 96 | 5 | 39 | 0 | - | 0.552 |
| offc | people | 25 | 16 | 16 | 0 | 0 | 0 | - | 0.82 |
| jour | people | 25 | 10 | 10 | 0 | 0 | 0 | - | 1.606 |
| agen | people | 25 | 7 | 7 | 0 | 0 | 0 | - | 139.982 |
| CntF | people | 54 | 10 | 0 | 0 | 10 | 0 | - | 0.165 |
| club | clubs | 26 | 443 | 177 | 146 | 119 | 1 | external call _fseeko (1) | 3.261 |
| c2tm | clubs | 26 | 27 | 24 | 3 | 0 | 0 | - | 15.218 |
| c3tm | clubs | 26 | 27 | 24 | 3 | 0 | 0 | - | 1.791 |
| c4tm | clubs | 26 | 27 | 10 | 1 | 16 | 0 | - | 0.179 |
| natc | national_team_containers | 25 | 335 | 84 | 108 | 143 | 0 | - | 2.24 |
| nati | nations | 25 | 36 | 23 | 1 | 12 | 0 | - | 6.784 |
| team | teams | 25 | 25 | 15 | 3 | 6 | 1 | external call _fseeko (1) | 10.538 |
| comp | competitions | 25 | 262 | 114 | 124 | 19 | 5 | emulation stopped early (timeout) (2); external call _fseeko (1); instruction budget exceeded (1); external call _gettimeofday (1) | 53.561 |
| cont | continents | 7 | 16 | 11 | 1 | 4 | 0 | - | 16.311 |
| city | cities | 25 | 15 | 12 | 1 | 2 | 0 | - | 11.671 |
| curr | currencies | 25 | 7 | 4 | 1 | 2 | 0 | - | 21.939 |
| stad | stadiums | 25 | 61 | 46 | 4 | 11 | 0 | - | 5.854 |
| lang | languages | 25 | 12 | 9 | 1 | 2 | 0 | - | 5.391 |
| lcrg | local_regions | 25 | 12 | 7 | 2 | 2 | 1 | emulation stopped early (timeout) (1) | 436.433 |
| weat | weather | 25 | 94 | 91 | 1 | 2 | 0 | - | 1.002 |
| inju | injuries | 25 | 29 | 25 | 2 | 2 | 0 | - | 2.525 |
| awar | awards | 25 | 39 | 32 | 4 | 2 | 1 | external call _fseeko (1) | 7.601 |
| mdso | media_sources | 25 | 20 | 17 | 1 | 2 | 0 | - | 19.144 |
| regi | regions | 25 | 6 | 1 | 1 | 2 | 2 | external call _fseeko (2) | 7.259 |
| drbr | derbies | 25 | 16 | 8 | 3 | 5 | 0 | - | 7.758 |
| agrm | agreements | 6 | 8 | 5 | 1 | 2 | 0 | - | 25.976 |
| stgn | stage_names | 25 | 8 | 3 | 3 | 2 | 0 | - | 1.983 |
| dscr | player_types | 25 | 6 | 2 | 2 | 2 | 0 | - | 32.094 |

### Per call

Every (record, field) call, so a field can count in several columns. Top reasons for unavailable calls:

| type | calls | value | unset | not handled | unavailable | top unavailable reasons (calls) |
|---|---|---|---|---|---|---|
| pers | 15444 | 5040 | 3854 | 6120 | 430 | thread-local RNG state (286); external call _gettimeofday (144) |
| play | 13230 | 11090 | 347 | 194 | 1599 | thread-local RNG state (980); external call _fseeko (542); unreadable live memory (50); instruction budget exceeded (26) |
| nnpl | 3500 | 1200 | 124 | 2140 | 36 | external call _fseeko (36) |
| offc | 400 | 356 | 44 | 0 | 0 | - |
| jour | 250 | 250 | 0 | 0 | 0 | - |
| agen | 175 | 171 | 4 | 0 | 0 | - |
| CntF | 540 | 0 | 0 | 540 | 0 | - |
| club | 11518 | 3237 | 5083 | 3162 | 36 | external call _fseeko (26); external call _asinf (7); unreadable live memory (2); emulation stopped early (timeout) (1) |
| c2tm | 702 | 303 | 220 | 162 | 17 | external call _fseeko (17) |
| c3tm | 702 | 180 | 141 | 378 | 3 | external call _fseeko (3) |
| c4tm | 702 | 10 | 1 | 691 | 0 | - |
| natc | 8375 | 1769 | 3031 | 3575 | 0 | - |
| nati | 900 | 503 | 97 | 300 | 0 | - |
| team | 625 | 306 | 121 | 157 | 41 | external call _fseeko (41) |
| comp | 6550 | 1788 | 4149 | 475 | 138 | emulation stopped early (timeout) (63); external call _fseeko (25); instruction budget exceeded (25); external call _gettimeofday (25) |
| cont | 112 | 75 | 9 | 28 | 0 | - |
| city | 375 | 277 | 48 | 50 | 0 | - |
| curr | 175 | 86 | 25 | 50 | 14 | external call _fseeko (14) |
| stad | 1525 | 1006 | 244 | 275 | 0 | - |
| lang | 300 | 225 | 25 | 50 | 0 | - |
| lcrg | 300 | 143 | 82 | 50 | 25 | emulation stopped early (timeout) (25) |
| weat | 2350 | 2255 | 45 | 50 | 0 | - |
| inju | 725 | 605 | 70 | 50 | 0 | - |
| awar | 975 | 728 | 172 | 50 | 25 | external call _fseeko (25) |
| mdso | 500 | 331 | 107 | 50 | 12 | external call _fseeko (12) |
| regi | 150 | 25 | 25 | 50 | 50 | external call _fseeko (50) |
| drbr | 400 | 186 | 89 | 125 | 0 | - |
| agrm | 48 | 29 | 7 | 12 | 0 | - |
| stgn | 200 | 75 | 75 | 50 | 0 | - |
| dscr | 150 | 31 | 51 | 50 | 18 | external call _fseeko (18) |

All unavailable calls by reason: thread-local RNG state 1,266; external call _fseeko 809; external call _gettimeofday 169; emulation stopped early (timeout) 90; unreadable live memory 52; instruction budget exceeded 51; external call _asinf 7.

Record types with no live table: `prnm` (person-name records (first/common/second names) live in name tables that are not among the 24 DATABASE_TABLE singletons); `ktfl` (kits are embedded lists of club/team records, not table records); `alnm` (alternative names are embedded lists, not table records); `dbch` (editor database-change log; no live table); `lsts` (editor list-of-tables view; no live table); `fmat` (editor file format metadata; no live table).

### External functions

Modelled (calls across the run): `_pthread_mutex_lock` 619,908, `_pthread_mutex_unlock` 619,046, `_memmove` 48,319, `___chkstk_darwin` 46,661, `_memcpy` 31,786, `_bzero` 20,238, `__ZNSt3__119__shared_mutex_base4lockEv` 8,031, `__ZNSt3__119__shared_mutex_base6unlockEv` 8,031, `_strcmp` 7,908, `__Znwm` 6,414, `__tlv_bootstrap` 4,862, `__ZNSt3__119__shared_mutex_base11lock_sharedEv` 4,589, `__ZNSt3__119__shared_mutex_base13unlock_sharedEv` 4,589, `_strlen` 2,985, `_vsnprintf` 2,737, `_pthread_self` 1,044, `__ZdlPv` 534, `_powf` 368, `___dynamic_cast` 141, `___cxa_guard_acquire` 50, `___cxa_guard_release` 50, `_strtol` 18, `_sinf` 14, `_cosf` 14, `_malloc` 10.

Refused (each stops the call with Unavailable): `_fseeko` 809, `_gettimeofday` 169, `_asinf` 7.

### Record reference tables

Table FourCCs seen in record references and the live table whose records carry the referenced unique/random ids:

- `Cclu` -> unresolved (candidates ['clubs', 'teams']) (unique+random id match on 4 examples)
- `MedS` -> media_sources (unique+random id match on 5 examples)
- `Nnat` -> nations (declared)
- `Pers` -> people (unique+random id match on 5 examples)
- `Ttea` -> unresolved (candidates ['clubs', 'teams']) (unique+random id match on 5 examples)
- `city` -> cities (unique+random id match on 5 examples)
- `comp` -> competitions (unique+random id match on 5 examples)
- `cont` -> unresolved (candidates ['regions', 'agreements', 'competitions', 'continents', 'player_types', 'injuries', 'languages', 'weather', 'fixture_names', 'stage_names']) (unique+random id match on 5 examples)
- `curr` -> currencies (unique+random id match on 5 examples)
- `lang` -> languages (declared)
- `lcrg` -> local_regions (declared)
- `regi` -> unresolved (candidates ['regions', 'cities', 'national_team_containers', 'teams', 'player_types', 'nations', 'currencies', 'injuries', 'languages', 'fixture_names', 'stage_names']) (unique+random id match on 5 examples)
- `stad` -> stadiums (unique+random id match on 5 examples)
- `stgn` -> unresolved (candidates ['regions', 'agreements', 'cities', 'national_team_containers', 'teams', 'competitions', 'continents', 'player_types', 'nations', 'currencies', 'injuries', 'languages', 'fixture_names', 'stage_names']) (unique+random id match on 1 examples)
- `wthr` -> weather (declared)

## Direct-access plans (stage 3)

`scripts/fmdb_coverage.py --plans` traces every live load during each call
(`fm_live_mcp/fmdb/plans.py`, which documents the `fmdb-direct-plans/1` format) and keeps a
plan for a (record class, field) only when one load chain explains the value for every
sampled record of that class, the sample has at least two distinct values, and no sampled
record was unavailable or unset (a null pointer may stand for unset in string/record
plans). Run of 2026-11-11 (budget 500,000), written to `out/fmdb-coverage/plans.json`:

* 4,890 (class, field) pairs: 779 direct, 4,111 emulate-only. Main emulate-only reasons:
  unset in every sample 2,237; thread-local RNG 462; value not explained by a traced load
  (computed) 342; list results 204; constant in the sample 213; mixed unset/value 212;
  DATA blobs 94; dates 49; colours 34; no single load across records 32.
* Direct plans by shape: 534 single-offset ints, 66 one-pointer-hop ints, 47 + 18 strings,
  58 record pointers, 35 bools (bit or nonzero), 8 `div10` floats, 7 floats.
* Plans reproduce the hand-proven offsets: ACTUAL_PLAYER PCAB/PPAB/Pfit/Pjad at PERSON
  -300/-298/-312/-310 (primary +0x25C/+0x25E/+0x250/+0x252); CITY name +0x18, nation +0x20,
  weather +0x28, language +0x30, local region +0x38, lat/lon +0x48/+0x4C, altitude int16
  +0x50; CURRENCY rate +0x38; COMP crep int16 +0x188, names +0x40/+0x48/+0x50. Pcon is
  emulate-only: one sampled record's value did not come from a single load.
* Hold-out check (`scripts/fmdb_plan_check.py`, 10 different records per class): 7,584
  agreements and 5 disagreements, one each in RETIRED_PERSON_NAME_POINTERS Pfna/PAfn,
  ACTUAL_PLAYER Pdfn, COMP dbty and STADIUM Spty. Plans are sample observations; a
  consumer should keep the VM as the oracle for spot checks.
