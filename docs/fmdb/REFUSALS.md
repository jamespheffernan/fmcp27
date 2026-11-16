# Emulator refusals: what the VM no longer declines, and why the rest remain

Branch `p1/virtual`, 11 November 2026, build 27.0.0.2493426, Newcastle career (10 Dec 2030).
Code: `fm_live_mcp/fmdb/vm.py` (models, RNG policies, long-walk retry), `ui_vm.py` (UI VM RNG
copy and sensitivity salt), `fm_live_mcp/fmdb/sources/virtual_players.py`,
`scripts/fmdb_rng_classify.py`, tests in `tests/test_fmdb_refusals.py`.

`FMDB_VM_REFUSALS=legacy` restores the behaviour before this branch (RNG refused, none of the new
models, no long-walk retry, no automatic file resolver). The before/after runs below use it.

## Random numbers (RNG)

The game keeps one pcg32 generator per thread (XSH-RR, multiplier 0x5851F42D4C957F2D):
thread-local 0x56C44F8 is `{u32 seed, u64 state @+8, u64 increment @+0x10}`, 0x56C4510 its
"seeded" flag. 2,190 call sites draw from it inline. The first draw on a thread seeds it from
`std::random_device` (0x4360CC8: state = seed x 0xA4E7735A4C957F2D + 0x5851F42D4C957F2E,
increment 1). Two other functions (0x4360638, 0x4360A48) seed a fresh mt19937 from
`std::random_device` on every use. A reader thread's draws are therefore unknowable, and so is
fresh `random_device` entropy.

Policies (`vm.RNG_POLICIES`, `PropertyVM(rng=...)`):

| policy | what the code gets | result |
|---|---|---|
| `refuse` | stop at the first draw | `Unavailable('thread-local RNG state')` (the behaviour before) |
| `private` | a VM-private generator seeded the way 0x4360CC8 seeds the game's, fixed seed | value, `PropertyResult.rng == 'private'` (not what the game shows) |
| `isolate` (default) | as `private`, then the call is repeated with a second seed | the value when both runs agree (`rng == 'independent'`), else `Unavailable('value depends on random draws')` |
| `copy` (UiHandlerVM, owner thread) | a VM-private copy of the game thread's own generator | what the game would compute from its current state; `rng_uses` counts draws |

`std::random_device` follows the same policy (refused under `refuse`; a VM-private sequence
otherwise, every draw counted and the result marked). `UiHandlerVM.rng_salt` replaces the copied
pcg32 state (and salts the private `random_device` sequence) for sensitivity runs.

Classification of consumers: (a) the output does not depend on the draws, (b) the output is a
function of the generator state the game would also use next, (c) the game drew it earlier and
stored it (read the stored value instead).

Evidence: `scripts/fmdb_rng_classify.py` reads each `ui_recipes_more` screen twice on fresh
UiHandlerVMs with `rng='copy'`, the second time with the copied pcg32 state replaced by a salted
one (`rng_salt`). Equal answers mean class (a). The same salt drives a second UI sweep
(`FMDB_RNG_SALT`, `FMDB_UI_SWEEP_OUT`) for the handler jobs that drew. The table is also
`ui_vm.RNG_CONSUMERS`.

| consumer | draws | class | evidence |
|---|---|---|---|
| medical (`exhausted_and_recurring`) | 136 | a | identical with a salted state |
| youth intake (`youth_intake_level`; `std::random_device`, was refused) | 2 | a | identical with a salted device sequence; level and feedback now read |
| manager profile, board (`job_security_from_contract`) | 72 | a | identical |
| season expectations (`competitions`) | 4 | a | identical |
| scouting, transfers, squad dynamics, training, finances, league table | 0 | - | no draws |
| HIRE_INTERMEDIARY (56) | 440 | a | 1 key drew; same value with a salted state |
| TEAM_CONFIDENCE (114, board confidence) | 16 | a | same |
| RECRUITMENT_FOCUS (85) | 8 | a | same |
| MATCH (61) | 0 on this binding | - | no draws |
| CLUB_VISION_MEETING_EDIT_SESSION (14) | 1,266-1,268 | not classified | the plain run stopped on an input ("write to shipped code") and skipped 9 keys; the salted run read 8 |
| PERSON, TEAM, COMPETITION, CLUB handlers | 8-248 | not classified | the 120 s per-type budget ran out at load average 80-200 (PERSON skipped 101 keys, TEAM 356) |

`ui_vm.two_seed(read, salt)` applies the rule to any handler answer: it runs the read with the
game's copied state and with a salted one and replaces every leaf that differs by
`{'unavailable': GENERATED_AT_READ}`. The screen recipes can wrap their reads in it; on the
consumers classified above it would withhold nothing.

Property getters (PropertyVM/FastVM, reader thread) use `isolate`: each call that drew is
repeated with a second seed, so its class is decided per value. Coverage counts are below.

## Virtual players

12,739 `player` rows are VIRTUAL_PLAYER: a 0x40-byte compact record (people-table entry =
compact + 0x20) holding the team index (+8), a profile cache index (+0x14, i16), a few template
bytes (+0x10..+0x1F) and the ids (+0x28 people index, +0x2C id). The getter (thunk 0x18A83C8 ->
0x18A7778) asks VIRTUAL_MANAGER (global 0x56A68A8) for a full ACTUAL_PLAYER profile through
0x18A0ED0(manager, compact, create=1):

* The manager keeps a ring of 520 generated profiles (vector manager+8, next slot manager+0x20,
  capacity manager+0x28).
* When compact+0x14 indexes a slot whose profile carries the player's id (profile + virtual base
  + 0xC == compact+0x2C, the test at 0x18A0F24), that profile is used.
* Otherwise the next ring slot is overwritten with a newly generated profile and compact+0x14 is
  pointed at it. The previous occupant loses its profile.

How stable is a profile? Three experiments on the reference save:

1. Forced regeneration (VM-private cache index -1) of 408 materialised profiles, 7 codes each:
   2,796 of 2,856 cells reproduced; the 60 that differed were the first and second names of the 30
   profiles that carry a name.
2. The same for those 30 named profiles over 1,099 person and player codes: 28,650 of 28,980
   cells reproduced. The 330 differences were 9 name codes (`Pfna Psna PAfn PAna PnRV Pfln dbnm
   dbnD Pnam`; 30 each: empty after generation) and the height (`Phei Phes`).
3. RNG access during generation comes from one site: 0x18A384C -> 0x154B5F0, an inlined pcg32
   draw on the thread generator that jitters the height between template bounds. 378 of the 408
   materialised profiles have no name at all.

So generation is a deterministic function of the stored compact data, except the height (a draw
from the thread generator) and the name (attached to a profile by some path other than
0x18A0ED0; only 30 materialised profiles have one).

State on 10 Dec 2030: 408 `cached` (the ring slot holds the player's own profile), 12,331 to be
generated (9,118 never materialised, cache index -1; 3,213 evicted: their slot now holds another
player).

What reads now:

* Getter path (`Engine.get_property`, any PropertyVM/FastVM with the default `rng='isolate'`):
  for a cached player every field is the stored profile value (no draws). For an uncached one the
  getter generates the profile inside the VM exactly as the game would on its next request; the
  height comes back `Unavailable('value depends on random draws')` and every other field is a
  value. The names come back empty, which is what the shipped getter returns for a generated
  profile right now.
* On demand (`fm_live_mcp/fmdb/sources/virtual_players.py`): `read_virtual(engine, records,
  codes)` reads the requested columns of the given players, `team_virtual(engine, team_index)`
  lists a squad's virtual members, `rows_for` turns rows into SQL tuples. Nothing is materialised
  save-wide: the `virtual_player` source table is declared `mode='lazy'` with an invalidation key
  (`row_key`: the 64 compact bytes, the ring slot and its owner, plus the game date for a generated
  row). Rows carry every `player` getter column plus the `person` columns the player table does not
  have (1,099 codes), `profile_state` (`cached` / `generated`), `draw_dependent` and
  `unavailable`. For a generated row the profile is generated twice (two private seeds), the
  committed VM states are compared byte by byte, and a column is kept when its getter read none of
  the differing bytes or gives the same value from both states; otherwise it is NULL ("generated
  at read") and listed in `draw_dependent`. Name columns of generated rows are NULL with the reason
  (the game may attach a name later). Costs are in "Costs" below.

Validation: every VIRTUAL_PLAYER of the managed club's teams (70: 61 + 5 + 4 across three teams)
was read; the 4 with a cached profile agree with the hand-built reader (`virtual.decode`) on name,
birth date and the 36 outfield attributes, 152 of 152 comparisons. The hand-built reader reports
the other 66 as identity-only (56 negative cache index, 10 cache identity mismatch), the same split
as `profile_state` here. Names to check on screen (Newcastle youth squad): Neil Millar (born 22 Dec
2012, height 189 cm), Lewis Wilson (3 Jan 2012, 178 cm), Mark Maiello (29 Aug 2011, 178 cm),
Macaulay Wing (13 Sep 2010, 175 cm).

### Costs (CPU, load average 100-200, single process)

| route | CPU per field | per player |
|---|---|---|
| `Engine.get_property` (FastVM), materialised profile | 0.84 ms | - |
| `Engine.get_property` (FastVM), generated profile: the getter generates the profile on every call, twice when it draws (two-seed rule) | 2.49 ms | - |
| `read_virtual` (UiHandlerVM: generate twice, commit, then one getter call per column), any profile | 0.9-1.1 ms | 56 ms for the two generations; 0.9-1.1 s for all 964 columns |

So a squad's 61 virtual members at 10 columns cost about 1.5 CPU s through the getter path; the
whole save at every column would cost 3-4 CPU hours, which is why nothing is eager. A row depends
on the compact record (64 bytes), the ring slot it indexes and that slot's owner; a generated row
also on the template data the generator reads (team, nation, date), hence the game date in
`row_key`. Between 20:20 and 22:55 the materialised count moved from 408 to 390 while
the game ran: the ring changes as the game shows other players.

## Other externals

Every model lives in `vm.EXTERNALS` (`EXTERNALS_2026_11_11`), so PropertyVM, FastVM (which enters
Python for any model that is not a constant) and UiHandlerVM (after its own `UI_EXTERNALS`) share
it. Static call-site census from the plugin's `bl` instructions in brackets.

| external | model | marked |
|---|---|---|
| `_strtoll`, `_strtoull`, `_strtoul`, `_atoi`, `_strchr`, `_strrchr`, `_strstr`, `_strcpy`, `_strncpy`, `_strcat` [strtoll 80 sites] | C semantics on VM memory | no |
| `std::__next_prime` [86 sites, hash-table bucket counts] | smallest prime >= n (deterministic Miller-Rabin); libc++'s overflow_error above 0xFFFFFFFFFFFFFFC5 stops the call | no |
| `_asinf` [89 sites], `_asin`, `_acos(f)`, `_atan`, `_atan2f`, `_tan`, `_exp2(f)`, `_log2f`, `_log10f` | libm | no |
| `_pthread_mutexattr_init/settype/destroy` [63 sites, COMPETITION stage lists], `_pthread_mutex_init/destroy`, `_pthread_cond_init/destroy`, `_sched_yield` | no-ops (the VM is single-threaded; the lock models are already no-ops); constant, so FastVM runs them in C | no |
| `_pthread_condattr_init/destroy` (14 November 2026) [constructor 0x43A6BF4 of the mutex and condition variable inside a memory pool; reached when a read builds a pool the game process has not built yet, e.g. `PAST_TRADE`, HISTORIES.md] | no-ops: the attribute object only feeds `pthread_cond_init`, a no-op; `pthread_cond_wait` stays refused | no |
| `_getpid` [3 sites] | the game's process id (known to the reader) | no |
| `_gettimeofday` [18 sites], `_time` [43 sites] | this machine's current wall clock: these are host-clock reads (log records, timers), not the game date, which is a database field | `host clock` |
| `_SteamInternal_ContextInit` [75 sites] | a VM-private context with every Steam interface NULL (the Steam client library lies outside the plugin and can never run here); the code's own "no Steam" branches run | `Steam offline` |
| `_CFStringCreateWithCString(NoCopy)`, `_CFStringGetMaximumSizeOfFileSystemRepresentation`, `_CFStringGetFileSystemRepresentation`, `_CFRelease` [0x44293AC: path string -> file-system path, 24 callers] | a VM-private string object | no |
| `_stat` | read-only `stat` of the path on this machine, only under the user's home folder (the game's own data folders); other paths stop the call | `host file system` |
| `std::random_device` | see RNG | `random_device` |
| `__tlv_atexit` | no-op (the VM's thread block lives for one call) | no |
| `_access`, `_opendir`/`_readdir`/`_closedir`, `_mkdir` of an existing folder, `_getenv`, `_gethostname` | host file system and environment, read-only, under the home folder only; `getenv` reads the game's own environment (sysctl `KERN_PROCARGS2`); `mkdir` of a missing folder stops the call ("the game would create a folder") | `host file system`, `host name` |
| `_fopen` (r, r+), `_open` (no `O_TRUNC`, no creation), `_read`, `_pread`, `_lseek`, `_fileno`, `_fstat`, `_fclose`/`_close` | files the game reopens to read (e.g. `Temporary/tc_league_history_dt.cmt` for the season expectations screen): VM descriptors from 30,000, served by the read-only stdio models; any write stops the call | `host file system: read` |
| `___error`, `_pthread_cond_signal/broadcast`, `_nanosleep`, `_NSBeep`, `std::__shared_weak_count::__release_weak` | an errno cell per call; no-ops in a single-threaded VM | no |
| `_localtime_r`, `_backtrace`, `_printf`, `_fprintf`, `_vfprintf`, `_fputs`, `_fputc`, `_putchar`, `_fwrite`, `_fflush`, `_write` | the diagnostic log record 0x43F24EC (host time, local time, call stack, console line); only stdout/stderr (fd 1/2) are accepted, the text is formatted and discarded, other streams stop the call | `host clock`, `console output discarded` |
| `_fseeko`/`_fread`/`_ftello`/`_ferror` | the read-only `.fmf` file models now apply wherever the reader knows the game's pid (`live.StreamReader`, `LiveMemory`, `engine._VMReader`): the resolver is made automatically | no |
| the same, on a FILE with unflushed write data (14 November 2026) | what the game would read: the disk file with the FILE's buffered bytes at the kernel's file offset (libc flushes there before any seek or read). Refused, cause in brackets, for an appending stream or descriptor, a string stream, a position the process does not give, or stdio and the kernel disagreeing; `game file changed while it was read` when the stream moved (HISTORIES.md) | no |

Marks: `CallStats.marked` / `PropertyResult.marks` list the stand-ins that reached a call;
`vm.marked` counts them per VM. UiHandlerVM keeps its fixed 1970 wall clock (committed handler
state stays reproducible) and marks it.

Thread model: `FILE_LLIST::get_list` (0x14A0FB0) pages history lists (playing history `Plhs`,
non-playing history `Pnph`, `Pnhs` ...) in from `Temporary/*_dt.cmt` on the owning thread only;
on a reader thread it logs "outside of main thread" and loads nothing. The console model stops
the call on that line, and `get_property` repeats it as the owning thread: the owner's TLV block
(dyld's lookup, moved from the UI VM) and read-only access to the game's `Temporary/*_dt.cmt`
files. Checked on 6 players on both VMs: 18 of 18 history cells read (they were 144 refusals).

Unreadable live memory: two causes. (1) A transient failed read while the game remaps a page:
`RetryReader` reads once more after 5 ms (`retried`, `recovered`). (2) Pages copied at different
times: a long-lived VM holds a page with a pointer the game has since replaced, and the getter
follows it to a garbage address (observed: `0x41610A3EC21D0000`, `0x4E554C4C...` = "NULL" text,
`0x1800000000`). The same `PRSS` call that failed in one VM read a value in a fresh one. On an
unreadable-memory stop `get_property` drops the VM's and the reader's page caches once per
(record, key) and repeats the call (`stale_retries`, `stale_recovered`). UiHandlerVM keeps this
off, because a refresh would discard committed handler state.

Long list walks: a call stopped by the instruction budget or the timeout is repeated once with 25
times the budget and 12 times the timeout (FastVM's timeout ticks included); the result is cached
per (record, key) until the next snapshot (`_session_setup`).

## Before and after

### Property coverage (`scripts/fmdb_coverage.py`, 30 record types, 2,245 (type, field) pairs, 71,898 calls)

Before: the run of 11 November in `COVERAGE.md` (same save and game date). After: this branch at
commit 840ac33 (PropertyVM, 3,582 s wall at load average 60-250); the rows marked † were fixed
after that run and re-checked on samples, not by a second full run.

| reason (calls) | before | after |
|---|---|---|
| thread-local RNG state | 1,266 | 0 |
| generated at read (two-seed rule: the value changes with the draws) | - | 5 (height of generated virtual players `Phei`, `Phes`) |
| external call `_fseeko` | 809 | 0 (automatic file resolver) |
| external call `_gettimeofday` | 169 | 0 |
| external call `_localtime_r` | - | 144 † (then `_backtrace`, `_printf`, `_fopen` of a log file; now the owner-thread retry reads the history lists) |
| emulation stopped early (timeout) | 90 | 30 (list walks: `ctms`, `rgts`, `Lcit`; 60 s retry at load average 250) |
| instruction budget exceeded | 51 | 0 |
| unreadable live memory | 52 | 170 † (138 position/role-score lists `PRSS PRLS ORLS` and 18 `player_types` cells read through stale page copies; fresh VMs read them; now retried on fresh pages) |
| external call `_asinf` | 7 | 0 |
| total | 2,444 | 349 |
| (type, field) pairs with no value in any sampled record | 12 | 0 |
| pairs with a value | 1,251 | 1,285 |

### FastVM against PropertyVM (`scripts/fmdb_vm_check.py`)

`--records 6 --tables player,person,club,team --seed 11`: 39,564 cells, 2 different, 0
instruction-count differences, 739 s wall, 789 CPU s. Player and person (30,780 cells): 0
different. The 2 (`club` 1714 `Tko1`, `team` 23692 `hier`) were stale-page stops on the
long-lived classic VM; on fresh VMs both read the same value. An earlier run before the
stale-symptom retry found 20 different cells, all on one generated virtual player in the
long-lived FastVM (non-plugin calls, stores to code); fresh VMs agreed on all 12 checked codes.

### Oracle (`scripts/fmdb_oracle.py --seed 1`, same sample sizes as `ORACLE.md`)

| | match | mismatch | generic-unavailable | tool-unavailable |
|---|---|---|---|---|
| `ORACLE.md` (before) | 31,385 | 134 | 82 | 100 |
| this branch | 31,385 | 110 | 95 | 111 |

1,592 s wall, 815 CPU s, load average 80-200. Families that moved: staff attributes 1,106/44 ->
1,128/22 (match/mismatch); player club 535/30/80 -> 523/34/88 and staff contract 270/0/2 ->
262/1/5, where the extra generic-unavailable cells are the harness's "Ttea ... not found in
clubs" (a reference to a reserve or youth team, resolved by the harness, not a VM stop); currency
664/26/2 (2 stale-page stops under load); staff job and player contract moved between match and
tool-unavailable (the tool side). The game ran between the two runs (the virtual-player ring
changed), so part of the movement is live data. A same-time run with `FMDB_VM_REFUSALS=legacy` would separate the two; it was not run.

### UI sweep (`scripts/fmdb_ui_sweep.py`, the 18 jobs that had unavailable keys)

Before (`UI_SWEEP.md`): 122 unavailable keys in these jobs, 63 of them unmodelled externals
(`CFStringCreateWithCStringNoCopy` 20, `SteamInternal_ContextInit` 10, `getpid` 10,
`pthread_mutexattr_init` 9, `asinf` 8, `std::random_device` 4, `std::__next_prime` 2). After
(this branch, load average 80-250, 120 s per type): 97 unavailable keys, of which unmodelled
externals: `objc_msgSend` 3 (DATABASE_VERSION: an Objective-C call, outside the plugin) and
`access` 2 (from a run before the model). The others name real limits: unreadable live memory 60
(42 in GAME, job 54, where the binding passes text, `0x3631313000` = "0116", where the handler
expects an object), null dereferences 11 (inputs and screen parameters the sweep does not supply),
"the game would create a folder" 9 (STORE: `mkdir` of a missing folder; the VM never writes the
file system), `fwrite` to a file 3 (MULTIPLAYER), "game file has unflushed write data" 4, timeouts 2,
store to code 1. PERSON_SEARCH (73) went from 44 values / 12 unavailable to 56 / 0, COMPETITION from
11 unavailable to 6. The PERSON, TEAM and CLUB handlers ran out of the 120 s budget under load
(skipped keys), so their counts are not comparable.

## Remaining refusals

None of the remaining property-getter refusals is an unmodelled external. Each names missing data
or a limit:

| refusal | where | why, and the next route |
|---|---|---|
| generated at read (two-seed rule) | `Phei`/`Phes` of virtual players without a materialised profile | the game draws the height (0x154B5F0) when it materialises the profile, and draws again after the ring evicts it. Nothing stores it before then |
| virtual player names | name codes of generated virtual profiles | 0x18A0ED0 does not name a profile; 30 of 408 materialised profiles carry a name from another path. Next: watch the profile's name handles while emulating the two other callers of 0x18A0ED0 (0x189FAE0 from 0x2D8068C, 0x1899E6C from 0x189ABDC), and read the PERSON UI handler's name key `2K31` for an unmaterialised player on the owner thread |
| emulation stopped early (timeout) | competition `ctms`/`rgts`, local region `Lcit` | whole-table walks; at load average 250 even 60 s of wall clock is not enough on the classic VM. FastVM checks the same budget in C; a quiet machine or a larger `LONG_TIMEOUT_FACTOR` reads them |
| unreadable live memory after the fresh-page retry | rare | a page the game really does not map (a pointer field that is garbage in live memory too) |
| `variant kind 14 (symbol)` | 1 cell in the FastVM check | a value decoder gap in `variant.py`, not an emulator refusal |
| virtual players have no stored value for this slot | `x:` derived player columns | by design in `extras.py` |
