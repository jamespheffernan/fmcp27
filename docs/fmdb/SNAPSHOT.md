# fmdb snapshot: columns, on-demand cells and freshness

`fm_live_mcp/fmdb/snapshot.py` writes `<cache>/fmdb/<save key>/snapshot.sqlite`: one SQL table per
editor record type with a live table, metadata tables, and the curated views `player_view`,
`club_view`, `staff_view` and `competition_view` (`views.py`). The tools `fm_db_schema`,
`fm_db_query`, `fm_db_read` and `fm_db_refresh` (`tools.py`) read it. Reads are not atomic and
the game is not paused.

A table stores its direct columns. A column that only the game's getter can give is computed
when a statement names it, for the rows the statement needs (`ondemand.py`). Before every answer
the stored rows are compared with live memory and the rows that changed are read again
(`freshness.py`). No tool starts another process.

## Column sources

`_fields.source` says where a column's values come from:

| source | meaning |
| --- | --- |
| `direct` | a verified direct plan: batched reads of the stored bytes, no getter call |
| `emulated` | the record's own property getter, run in the PropertyVM |
| `extra` | a getter key outside the editor catalog (`extras.EXTRA_FIELDS`); `_fields.name` is the label, inferred unless the note says it is proven; the column name ends in the FourCC |
| `derived` | a native getter slot no key serves (`extras.DERIVED`, code `x:<name>`): `condition_stored`, `injury_days_remaining`, `injuries` |
| `computed` | not a getter value: `player.is_virtual`, `team.club_idx` |

The VM asks the record's own getter first. When the getter does not claim the key, the VM asks
again with the game-layer interceptors in place; the note then starts with `source: game layer`
and names the record classes. Translated names resolve through the game's `languages.fmf` (the
engine passes `lsof` as the VM's file resolver).

Extras become columns for `player`, `non_player`, `club`, `team`, `competition` and `nation` when
the key returned a value for at least half of the census records of the type (429, 156, 85, 98,
36 and 48 columns). A statistic record `{valu, numb}` stores `valu`; `season_appearances_Prat`
stores Prat's `numb` (matches). Every other extra stays readable through `fm_db_read`.

Composite values: `person.club_idx_Ptaj` resolves the `Ttea` member of Ptaj's
`{Pjle, Psjo, Ttea}` contract record (the contracted team).

`team.club_idx` is the club pointer at team record +0x30 (the pointer `tables.managed` reads),
kept when it is a live CLUB entry. `player.is_virtual` is 1 for VIRTUAL_PLAYER records, the
youth-intake placeholders whose getters need the game's random-number state; `player` counts them
(12,739 of 78,782 rows) and `player_view` leaves them out.

## Column states

`_column_state.status`, per table, column and record class:

| status | meaning |
| --- | --- |
| `ready` | read by a verified direct plan at build and kept current by the content check |
| `on_demand` | computed by the getter when a statement names the column; NULL in the table until then |
| `unavailable` | the getter does not handle the code for the class, or fails for a quarter of the sampled records |

`_fields.status` is `ready` when some class can give a value (stored or on demand). `fm_db_schema`
marks on-demand columns with `on_demand: true`. On the running save a build stores 797 columns
and leaves 5,309 (column, class) pairs on demand.

A curated view that can choose between name codes reads the stored ones: `player_view.club` is
the club's database name or short name (`dbnm`, `Csnm`). The translated name `Cnam` costs 0.6 to
1 ms per club and stays selectable as `club.name_Cnam`.

## On-demand cells (`ondemand.py`)

For one statement, `fm_db_query` shadows each base table that has on-demand columns with a
TEMP view of the same name in which every such column `c` is `fm_cell(<id>, idx, c)`, and creates
every stored view that reads the table again as a TEMP view. `fm_cell` returns the stored cell
when it is memoised and valid, computes it when the statement enabled the column, and returns
NULL otherwise.

* **Which rows.** SQLite evaluates a result column for the rows that pass the WHERE clause on
  other columns, so a point lookup or a filtered statement computes the rows it returns or
  sorts. A statement that filters, sorts, groups or joins on the column makes SQLite ask for
  every row: after 1,024 computed cells of one column in one statement the rest of the column is
  computed in one pass with batched page reads.
* **The `SELECT *` rule.** A column is enabled when the statement names it, or names the view
  column built from it. `*` computes nothing: it shows memoised cells and NULL elsewhere, and the
  result's notes list how many columns were left out. Qualify a table with `main.` to read the
  stored cells as they are.
* **Memo.** Computed cells are written into the table. `_memo` holds one validity bitmap per
  column; `_memo_blocks` holds, per block of 256 idx values, the 8-byte words of live memory the
  block's getter calls read and a hash of them. The tracking VM (`fastvm.TrackingFastVM`,
  `build/libfm_vm_accel2.dylib`) records the words. A word the call itself stored in full is left
  out: reference counts, locks, the game's pooled-allocator free lists and the result the call
  built.
* **Invalidation.** Before a memoised cell of a block is used or extended, the block's words are
  read again and hashed. A difference drops every memoised cell of the block (all columns; the
  stored cells become NULL) and they are computed again on demand. An idx whose record pointer
  changed loses its cells.
* **Declared inputs.** Position text (`Ppsr`, `Ppss`, about 1 ms per player) builds its string
  in a scratch buffer of the game that changes every few seconds, so its read set never holds.
  Its value is a function of the stored position ratings (14,000 players, 7,008 rating tuples,
  no tuple with two texts). A cell of such a column (`ondemand.DECLARED_INPUTS`) stays valid
  until the content check updates one of its input cells in the same row. The audit recomputes
  samples of it as of any memoised column. Team names (`Tlna`, `Tsna`, `dbnm`; inputs unique
  id, team type, gender) and competition names (`dbnm`; input unique id) are declared the same
  way: every call reads one heap word shared by all calls that changes every few seconds while
  the names stay equal, so without it a statement that filtered on a team name recomputed all
  66,021 names (130 CPU s) each time.
* **Without the tracking accelerator** cells are computed for the statement and not stored
  (columns with declared inputs are still stored).

Values follow the released path: `bulkplans.canonical(getter result)`, the plan's fallback for a
`_fseeko` refusal, then `snapshot.to_sql`.

Manager view. The masked views read the stored tables, so `tools.manager_prewarm` computes the
cells first: a `public` column the statement names, for the players the view can show; an
`own_club` column only for the manager's own players; `never`, attribute and knowledge columns
never. With a live game the rows are those whose cell the statement read: a masked column built
from an on-demand column calls the connection's need function with `cell:<column>` for each row
it is evaluated for while `prepare_manager_query` probes the statement, and the prewarm computes
those cells, stores them and probes once more for rows a filter on a NULL cell kept out (at most
three rounds). The work depends on the statement's text and on whom the manager knows, not on a
withheld value.

Lock order. The snapshot uses SQLite's rollback journal: a reader's SHARED lock blocks a
writer's commit. Every connection to the snapshot that stays open while another one in the same
process writes is in autocommit and holds a lock only while a statement runs: the masked
connection is opened with `isolation_level=None` (its temp-table INSERTs used to open a
transaction that was never committed, so its later reads kept the snapshot locked and the
prewarm's store waited 30 s and failed with "database is locked"). The writers (content check,
collection refresh, on-demand store, audit) each open, write, commit and close within one call,
and none starts while a statement of another connection of the same call is still being read. It stops after 20 s (`tools.MANAGER_PREWARM_S`); cells not reached read NULL
in that result and a note says so. A manager-view query no longer starts the knowledge store's
detached whole-save fill (`tools.KNOWLEDGE_BACKGROUND_FILL`): it builds the named population
in the calling process and reports partial coverage beyond it.

## Freshness by content (`freshness.py`)

A snapshot is valid for the bytes it was read from, not for a game date. While direct plans are
evaluated the build records, per block of 256 rows, the exact windows (address, length) the
block was read from, a CRC of their bytes and the 16 KiB pages they lie on (`_direct_blocks`),
one hash per page (`_direct_pages`, 16,358 pages) and the table vectors (`_live`).

Each `fm_db_query` (at most once every 3 s):

1. reads every page again in one batch and compares the hashes;
2. for a block with a window on a changed page, computes the CRC of its windows again (a page
   changes far more often than the bytes a plan reads on it);
3. evaluates the blocks whose CRC differs, compares with the stored rows and updates the rows
   that differ, in one transaction;
4. compares every table vector: a new record is inserted, a record that left is deleted, a
   replaced record is read again and loses its memoised cells. The vectors are decoded from
   `_live` once per process (the process keeps them while no other process checked) and written
   back only when one changed (`_fresh` live_digest:<kind>); writing all of them on every check
   cost 1.5 to 2 s plus a 1 to 4 s commit;
5. reads the pages of the evaluated blocks once more. A block whose bytes moved while it was
   read is not published in that round and is evaluated again, up to three rounds; what still
   moves keeps its old rows and its old CRC and the result says `still_changing`.

Every result carries `snapshot.checked_ms_ago`, `rows_refreshed` and `pages_changed`, and a note
"Direct columns checked against live memory N ms ago: ... rows refreshed". `snapshot.stale` stays
in the result for older callers and is false unless a rebuild failed.

A build ends with one such check on the finished file (`Build._settle`): pages that moved during
the build are read again. This replaces the per-table date stamps of the robust lane's
`consistency.py`.

## When a snapshot is built again

| case | what runs | measured (load average 20 to 25) |
| --- | --- | --- |
| normal use | content check, then the statement | check 0.45 s wall, 0.28 CPU-s when nothing changed; 0.9 s, 0.73 CPU-s with 50 changed pages (659 blocks checked) |
| no snapshot, another game process or save, older format, a plan demoted or added | build in the calling process | 19.7 s wall, 17.5 CPU-s: direct 7.5, write 10.5, final check 0.75 |
| `fm_db_refresh()` | the same build, on request | as above |
| new game build without shipped plans | build with the plans there are; the rest on demand | `scripts/fmdb_snapshot.py` derives plans (24 to 40 minutes, documented) |

Free space: a build refuses below 1 GiB free in the cache directory, storing computed cells
below 256 MiB (`engine.MIN_FREE_BUILD`, `MIN_FREE_FILL`). A disk-full error during the write
removes the temporary file and leaves the previous snapshot unchanged.

## Plan audit (`audit.py`)

After each `fm_db_query`, for at most 0.5 CPU-seconds in the same process: random rows of a
random class, every direct plan of the class evaluated and the getter run on the same cached
bytes. A plan that disagrees is demoted in the plan cache and the next call rebuilds the
snapshot without it. A plan whose derivation saw one branch path (`plan['paths']`, robust lane)
is sampled at a tenth of the rate. A fifth of the budget recomputes memoised cells whose block
passes its check; a difference drops the block and marks the column `nomemo`. Coverage
accumulates in `_fresh['audit']` and one line of `_snapshot.notes`.

## Plan cache

`plans/<plugin sha256>.json`, format `fmdb-bulk-plans/2`. Version 2 was derived under the VM
defaults of the gap-fix lane (all 15 interceptors bypassed in the database view, game-layer
fallback, file resolver). A version-1 file is moved to `<sha>.v1.json`; its direct plans are
re-verified against the current getter on 62 records per class instead of traced again; any
disagreement sends the code through the full derivation. Plans are keyed by plugin SHA256, so a
new save on the same game build reuses them.

## Checks (2026-11-11)

* Differential (`scripts/fmdb_snapshot_check.py`, 200 random rows per table with 1,000 or more
  rows, every direct cell against the getter): 0 mismatches in 101,529 cells after the plans
  that disagreed (8 cells: on-loan flag, a translated club name, condition while injured,
  `Pnjd`, `Pmdt`) were demoted.
* Cross-check against the hand-built tools: 12 players on the filled shared snapshot, 1,011
  fields equal, 0 disagree, 9 NULL (columns the fill had not reached); 15 players on a fresh test
  build with the corrected club mapping (tool `current_club` = `club`, `contract_club` =
  `contracted_club`), 1,260 equal, 0 disagree, 30 NULL (condition and date joined, filled only by
  the background process). Personality is no longer NULL.
* `scripts/fmdb_oracle.py`: 31,385 match, 134 mismatch (the documented different semantics),
  82 generic-unavailable, 100 tool-unavailable: unchanged from the gap-fix run.
* `m_player_view` against `visible_attributes_bulk` for 50 scouted players: 2,350 cells equal,
  0 different.
