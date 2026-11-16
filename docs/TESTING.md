# Testing

The public checkout excludes private `evidence/` directories and installed game resources. The historical timings below came from the development machine with those inputs available. They are not a claim that the entire research suite passes on a fresh public checkout. Website checks run independently with `node --test site/tests/*.test.cjs`.

The Python suite lives in `tests/` (about 520 files, 20,392 tests). `tests/conftest.py` applies
markers, enforces isolation and serialises tests that read the running game. `pyproject.toml`
holds the default selection. Install the test extra once: `uv pip install -e '.[test]'` (pytest and
pytest-xdist).

## Commands

| Run | Command | What it selects |
|---|---|---|
| Fast default | `pytest` | Everything except `slow`, `live` and `mapped_build`, on one worker per core (`-n auto`) |
| Complete | `pytest --complete` | Every test, including slow and live ones (pinned build; see "Game builds") |
| Live only | `pytest -m live` | Tests that read the running Football Manager 27, through the installed build's map |
| Installed build, static | `pytest -m mapped_build` | The installed build through its address map, without the game |
| One file | `pytest tests/test_x.py` | The whole file; naming files or ids clears the default selection |
| One test, one process | `pytest -n0 tests/test_x.py::test_y` | For a debugger or `print` output |
| Without evidence | `pytest -m "not evidence"` | Skips the tests that need git-ignored `evidence/` files |
| Shuffled order | `pytest --complete --suite-shuffle SEED` | Test files in a seeded random order |

Pass `-n 3` (or any count) to cap the workers on a shared machine. An explicit `-m` always wins over
the default selection and over `--complete`.

Set `FMCP_CACHE_DIR` to a private directory for live tests; they build snapshots there.

## Markers

Test files carry no markers. `tests/conftest.py` applies them as each test is collected, from two
sources:

- **Rules.** A file named `*_live.py` is `live`.
- **Measurements**, in `tests/suite_profile.json`, which `scripts/test_suite_profile.py` regenerates
  from a sequential `--durations=0` log and a `--suite-probe` run:
  - `live`: the test started a reader (`fm_live_helper`, `fm_fast_reader`, `lsof`, `ps -p`) on
    the game's pid. Eight tests outside `*_live.py` files do.
  - `slow`: setup, call and teardown together took at least 1 s in a sequential run (68 ids).
  - `evidence`: the test, or its module at import, opened a git-ignored file under `evidence/`.
    The audit hook sees files the test process opens, not files a subprocess opens.

A profile entry without parameters (`tests/test_x.py::test_y`) covers every parametrised case.

Two more rules:

- `pinned_build`: the module imports `tests/_pinned_build.py` at module level, directly or through
  another test module (a static scan of the imports). Such tests compare with the pinned build's
  code, data or hashes.
- `mapped_build`: a file named `*_mapped.py` (`tests/test_installed_build_mapped.py`).

## Game builds

The reader's source, the fixtures, the frozen native sources and the static proofs belong to one
game build, the pinned one (27.0.0.2493426). A game update replaces the installed build; the reader
addresses it through an address map (`fm_live_mcp/address_book.py`, `docs/GAME_UPDATE.md`). So
the suite never takes the pinned build's files from the Steam install.

**Where the pinned build is.** `fm_live_mcp/build_paths.py` answers it, for tests, fixtures and
research scripts: `FMCP_PINNED_APP=<an fm.app of that build>`; else the preserved bundle tree
`/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds/27.0.0.2493426/fm.app`;
else the Steam install when its plugin is the pinned one (by sha256). Tests use
`tests/_pinned_build.py` (`PLUGIN`, `EDITOR_FMF`, `GAME_ASSEMBLY`, `METADATA`, ...). Without a pinned
build every `pinned_build` test skips and names the directory to provide; the other tests run.

The preserved tree is hard links to the files `scripts/fm_update_build.py` preserved in that build's
directory, laid out as the app bundle (so code that derives sibling paths from the plugin works):

| In `fm.app/` | Preserved file |
|---|---|
| `Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin` | `game_plugin` |
| `Contents/PlugIns/game_plugin.bundle/Contents/Info.plist` | `plugin-Info.plist` |
| `Contents/Info.plist` | `Info.plist` |
| `Contents/Frameworks/GameAssembly.dylib` | `GameAssembly.dylib` |
| `Contents/Resources/Data/il2cpp_data/Metadata/global-metadata.dat` | `global-metadata.dat` |
| `.../game_plugin.bundle/Contents/Resources/shared/data/` | `fmf/editor.fmf`, `simatch.fmf`, `simatchshared.fmf` |
| `.../game_plugin.bundle/Contents/Resources/data/game_simulation/` | the other nine `fmf/*.fmf` |

Not preserved for the pinned build: `languages.fmf` (209 MB), the English language template
`templates/user_folder/languages/example.ltf` (155 MB; changed by 27.0.1), `shared/tables.fmf` and the
`database/` resources. Tests that need the language template skip, saying so
(`_pinned_build.language_template()`).

**Which build a session addresses** (`tests/conftest.py`, decided before any test imports the
package; the header line `fmcp27 game build:` shows it):

| Session | When | What it does |
|---|---|---|
| pinned | the default | `FMCP_ADDRESS_BOOK=off` (nothing is translated) and `FMCP_PLUGIN_PATH` = the pinned plugin, so the package's run-time defaults (`editor.fmf`, `filters.fmf`, ...) read the pinned files too. `mapped_build` tests skip; live tests skip unless the installed game is the pinned build |
| installed | `-m` can select only `live` or `mapped_build` tests (`pytest -m live`, `-m mapped_build`, `-m "live or mapped_build"`); every named file is `*_live.py` or `*_mapped.py`; or `FMCP_TEST_BUILD=installed` | the address book loads the installed build's map, as the MCP server does. Other tests skip; live tests that are also `pinned_build` skip as build-specific |
| map | `FMCP_ADDRESS_MAP=<file>` | that map on every module (the proof in `docs/GAME_UPDATE.md`) |

`FMCP_TEST_BUILD=pinned|installed|map` forces the choice. A complete check after a game update is
two runs: `pytest --complete` and `pytest -m "live or mapped_build"`.

**The mapped-build selection** (`tests/test_installed_build_mapped.py`, no game needed): the session
loaded the installed plugin's verified map and the build identity follows it; the map resolves
exactly the census addresses and every unresolved one says why; every module of the package imports
through the map; the server registers its tools and `address_book.report` names each unavailable one
with reasons; the update report (`<sha256>.update-report.json`) has its shape; the screen tools
read the installed build's own front-end table (its parameter globals, its collections) and the
UI registry carries the keys that front end added; the translator global is the one
`_i_translator_get_instance` returns on that build; the compiled English concern and promise
texts are bound to the installed `example.ltf` when the update verified them. It needs the map in
`$FMCP_CACHE_DIR/fmdb/anchors/` (`scripts/fm_update_build.py --installed`); when the installed game
is the pinned build it skips. In a checkout without `evidence/`, `-m mapped_build` stops on the
evidence modules that fail at import; add `--continue-on-collection-errors` or name the file.

## How isolation is enforced

Every rule below runs for every test; a violation fails the test that caused it.

- **Process state.** An autouse fixture snapshots the environment, `sys.path`, the working
  directory, `sys.dont_write_bytecode` and `sys.modules` before each test and restores them after
  it. A module-scoped fixture does the same around each file, so a module fixture may change state
  for its own tests only. Importing a test module may add to `sys.path` and nothing else: the
  environment, working directory, bytecode flags and modules are restored after each import.
- **Modules.** The restore puts back any `sys.modules` entry a test replaced or removed and drops
  any `fm_live_mcp.*` entry not loaded from the package directory (frozen fixture sources, stubs,
  copies from other checkouts) and any hand-made stub without a spec or file. This replaces the
  earlier fixture that dropped only `fm_live_mcp.*` entries loaded from `tests/fixtures`, and that
  resolved the path of every loaded `fm_live_mcp` module after every test (23 ms of CPU per test,
  about 470 CPU-seconds per full run).
- **Repository writes.** An audit hook watches `open`, `os.remove`, `os.rename`, `os.mkdir`,
  `shutil.rmtree` and the like. A test that writes anywhere inside the checkout fails; use
  `tmp_path`.
- **The game.** The same hook watches `subprocess.Popen`. A test not marked `live` that passes the
  game's pid to `--pid` or `-p` fails with a message naming the command.
- **Child processes.** After the last test of each file, any child process still running is
  stopped (with its process group) and the file's last test fails. The session repeats the check
  at exit. `FMCP_NO_BACKGROUND_FILL=1`, set by the suite and inherited by subprocesses, stops
  `fmdb.fill.start` and `knowledge_store.start_background_fill` from spawning the detached fills
  that once outlived a test by 22 minutes.
- **Live tests.** Under `-n`, a custom xdist scheduler sends every live test to one worker as one
  unit, so live tests never run concurrently and never wait behind offline ones. A file lock in
  the system temporary directory also serialises them across separate pytest processes. (xdist's
  own `loadgroup` cannot do this under pytest 9: it reads an `@group` suffix that `item.nodeid` no
  longer shows.)
- **Bytecode.** With `PYTHONDONTWRITEBYTECODE=1` (agent shells), pytest would rewrite the asserts
  of every test module in every process, 16 of the 23 seconds of collection. The conftest keeps
  those compiled files under `$TMPDIR/fmcp27-pycache` instead.

## What a new test must do

- Write only under `tmp_path` (or `tmp_path_factory`); never under the checkout.
- Change process state through `monkeypatch`, or accept that the fixture restores it.
- Read the game only from a file named `*_live.py`, or add the test id to `live_tests` in
  `tests/suite_profile.json`. The guard fails it otherwise.
- Take the pinned build's files from `tests/_pinned_build.py`, never from the Steam install. Code
  that reads the running game's files takes them from `build_paths.installed_app()`.
- Stop every process it starts. Do not call `fill.start` or `start_background_fill` with
  `FMCP_NO_BACKGROUND_FILL=0`.
- Load a frozen copy of a module under its own name, not over a real `fm_live_mcp` name, unless the
  test needs exactly that; the restore removes it afterwards either way.
- For a parametrised test over an emulated native function, build immutable inputs (code images,
  parsed evidence, page images) once per module and reset only what a case changes.
  `tests/_unicorn_pages.py` gives exact page images of a `{address: byte}` dict and reuses unchanged
  pages between calls.
- Pass alone: `pytest -n0 tests/test_new.py`.

## Timings

Measured on 11 November 2026 on a 10-core (4P + 6E) Mac with 24 GB, Football Manager 27 running,
with ten other agents on the machine: load averages ran from 10 to over 300, so wall times vary
by a factor of two between identical runs. CPU seconds (user + system, all processes) are the
comparable figure. Runs other than the baseline were `nice -n 10`; parallel runs used `-n 2` or
`-n 3`, never `-n auto`, at the request of the other lanes.

### Where the time went before (trunk 741300f)

From a sequential baseline interrupted at 39% (46 minutes, 7,978 tests), a sequential run of every
test outside `*_live.py` (31 min 27 s wall, 1,593 CPU-s, load 11 to 80) and per-function runs:

| Cost | Seconds | Change |
|---|---|---|
| Live tests (reading the game) | 2,034 s in one complete run; `test_knowledge_bulk_live` alone 1,359 s | Serialised on one worker, excluded by default |
| The hygiene fixture in `tests/conftest.py`: `Path.resolve()` on all ~512 loaded `fm_live_mcp` modules after every test | 23 ms CPU, 45 ms wall per test: ~470 CPU-s per run; 326 s of teardown in the 39% baseline | Replaced by identity checks: 0.3 ms per test |
| Knowledge-lane emulation: rebuilding all ~124 Unicorn pages byte by byte and hashing the 192 MB game plugin for every case | 442 s for the 14 heaviest functions (4,503 cases) | Exact page reuse and one digest per file: 94 s |
| Collection with `PYTHONDONTWRITEBYTECODE=1` | 23 s per process, 16 s of it assertion rewriting; once per xdist worker | Compiled tests cached outside the checkout: 6 s |
| Subprocesses (MCP stdio servers, helpers on fake targets, git) | 163 s over 157 tests | Unchanged |
| The other 17,903 tests (each under 50 ms) | 138 s | Unchanged |

Eleven functions have 256 to 768 cases. Four of them (the knowledge thresholds, UI caller,
operand closure and passing-state functions) spent 0.2 to 0.7 s per case building Unicorn memory;
the other seven cost 0 to 70 ms per case, most of it the hygiene fixture.

### Heaviest parametrised functions, sequential, one process

| Function | Cases | Before | After |
|---|---:|---:|---:|
| `test_knowledge_attribute_thresholds::test_all_field_pairs_…` | 658 | 129.9 s | 15.6 s |
| `test_knowledge_attribute_ui_caller::test_every_field_…` | 141 | 99.4 s | 17.6 s |
| `test_knowledge_attribute_operand_closure::test_all_original_…` | 141 | 87.9 s | 16.7 s |
| `test_knowledge_passing_state::test_zero_threshold_…` | 256 | 58.0 s | 7.3 s |
| `test_knowledge_context_score_source::test_complete_collector_…` | 98 | 27.6 s | 7.5 s |
| `test_committed_wage_spending_core::test_loan_wage_branch_…` | 256 | 18.2 s | 14.1 s |
| `test_committed_wage_offer_selection::test_all_unsigned_state_…` | 768 | 14.7 s | 11.5 s |
| Seven more with 256 to 512 cases | 2,185 | 5.8 s | 3.2 s |
| All 14 | 4,503 | 442 s (286 CPU-s) | 94 s (86 CPU-s) |

Both runs used the new conftest, so the figures isolate the test-body change; load was about 200
before and 100 after. The spending-core cost is in product code (`relocated` reads 8 bytes per
`pread`) and was left alone.

### Runs after

| Run | Command | Wall | CPU | Load | Result |
|---|---|---:|---:|---|---|
| Default, 3 times | `pytest -n 3` | 178 s, 170 s, 170 s (median 170 s) | 401 to 477 s | 10 to 30 | 20,199 passed, 21 skipped each time |
| Everything outside `*_live.py`, sequential | `pytest -n0 --complete --ignore-glob='*_live.py'` | 30 min 4 s, mostly waiting on the live lock held by another run; tests themselves 806 s | 508 s | 25 to 80 | 20,269 passed, 21 skipped |
| Complete minus live, shuffled seed 11 | `--complete -m "not live" -n 3 --suite-shuffle 11` | 293 s | 544 s | 27 to 268 | 8 failures from the machine, not the order (below) |
| Complete minus live, shuffled seed 22 | `… -n 2 --suite-shuffle 22` | 293 s | 501 s | 79 to 268 | 20,261 passed, 21 skipped |
| Complete minus live, shuffled seed 33 | `… -n 3 --suite-shuffle 33` | 178 s | 483 s | 38 to 119 | 20,261 passed, 21 skipped |
| Live only, after the session fix | `pytest -n0 -m live` | 44 min 46 s | 1,622 s | 39 to 180 | 101 passed, 12 skipped, 9 failed (below); no guard failures |
| Complete | `pytest --complete -n 3` | 33 min 49 s, of which the live group about 30 min | 2,198 s | 38 to 81 | 20,371 passed, 25 skipped, 2 failed and 1 error in live files (below) |

Before, the same selection as the sequential row took 31 min 27 s and 1,593 CPU-s; the full
sequential suite took 31 minutes unloaded and 55 minutes loaded on 10 November.

The seed-11 failures: six `test_fmdb_fill` setups refused to build because the system volume had
148 MiB free at that moment (another agent's temporary files), and two MCP stdio tests failed when
`ps` timed out after 5 s at load 268. All eight passed when rerun. In the complete run,
`test_fmdb_ui_news_live` failed twice because the career date moved on during the run (the tests
pin 10 December 2030 and skip on other dates when they notice), and `test_fmdb_ui_tools_live`
failed the child-process guard, which led to closing the tools' cached sessions after each module.
In the later live-only run the game had moved to 13 December 2030: nine
`test_fmdb_ui_more_live::test_screen_reads_and_is_json` cases failed because the screens reported
unavailable fields, and they fail the same way with `--noconftest`, so the save, not the suite,
decides them.

### Remaining cost

The complete run is bounded by the live group, which runs on one worker by design: two tests in
`test_knowledge_bulk_live.py` read every field of the squad through the existing per-player tools
(962 s and 397 s), and the snapshot, oracle and UI-stability checks take 100 to 150 s each. They
read the game and cannot share work with offline tests.
