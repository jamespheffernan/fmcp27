# Collection tables

The snapshot holds the 24 `DATABASE_TABLE` singletons. A save holds much more: contracts hang
off people, fixtures and league tables off competitions, offers and news off managers.
`fm_live_mcp/fmdb/sources/` turns those collections into snapshot tables. Numbers below are
from the Newcastle career (Cesar Jules) on 10 December 2030, read on 11 November 2026 with
the machine's load average between 40 and 117.

## The contract

A module `fm_live_mcp/fmdb/sources/<name>.py` exposes

```python
def tables(engine) -> list[SourceTable]          # tables with rows of their own
def views(engine) -> dict[str, tuple]            # optional: {view: (description, SELECT template[, manager policy])}
```

```python
Column(name, sql_type, meaning, enum=None, references=None)
SourceTable(name, description, columns, rows, key='idx', cost_note='',
            mode=None,            # 'eager' | 'lazy'; None means lazy
            invalidation=None,    # 'immutable' | 'append' | 'content' | 'game_date'; None means 'game_date'
            fingerprint=None,     # () -> str, cheap change detector for 'content'
            identity=(),          # columns that identify a row, for 'immutable' / 'append'
            new_rows=None,        # (set of identity tuples already stored) -> rows not in it
            source_note='', indexes=(), manager={'scope': 'never'}, views={}, coverage=None,
            not_read=None,        # () -> lines: what the statement named whose read failed, with the reason
            slow=False)           # first contract: accepted, means lazy
```

`rows()` yields tuples in column order; an `idx` row number is added when the module declares
no `idx` column. View templates write `{table.CODE}` or `{table.CODE1|CODE2}` for a core
column, resolved through `_fields.code`. `coverage()` runs after `rows()` and says what was not
read (it becomes the table's note). `not_read()` runs after `rows()` or `new_rows()` and lists
what the statement named whose read failed, one line each with the reason; the lines go into the
answer as `collections[table]['not_read']` and as a note (`sources.not_read_note`), so rows that
are missing because a read failed are told apart from rows that do not exist (the history
tables, HISTORIES.md). `sources/_example.py` is the smallest module; modules whose
name starts with `_` load only when named (`discover(engine, only=['_example'])`).

Rules:

* **Cost.** No work per game day that a query has not asked for. `lazy` tables (the default) are
  created empty with status `lazy` at snapshot build and built the first time a query
  references them: `tools.db_query` calls `sources.refresh_for_query` before the statement runs,
  with the tables the authorizer saw the statement read (views included). `eager` tables are built during the snapshot build and must cost about 2 CPU s or
  less on a quiet machine (`EAGER_BUDGET_S`; a larger cost is logged).
* **Invalidation.** `immutable` (rows never change once created) and `append` (the collection
  only grows) add only rows whose `identity` is new, calling `new_rows(existing)` when given so
  the source reads only what is new. `content` tables compare `fingerprint()` with the stored
  one and rebuild only when it differs. `game_date` tables rebuild when the game date changes.
  A referenced table is re-checked at most every `CHECK_INTERVAL_S` (5 s).
* **New snapshot.** A rebuild (another game process or save, or `fm_db_refresh()`; a new game date
  no longer rebuilds, see SNAPSHOT.md "Freshness by content") carries the rows of `immutable`, `append` and
  `content` tables over from the previous snapshot file (`ATTACH`, `INSERT ... SELECT`); the next
  reference only checks them. `game_date` tables start empty again. A table whose columns
  changed is built afresh.
* **No background work.** Nothing here starts or relies on the background fill or any other
  process. `python -m fm_live_mcp.fmdb.sources build [--table T]` builds tables on request for
  scripts; `status` lists their state.
* **Failure.** A module that fails to import, or a table whose rows raise, never stops a build
  or a query: the table is marked `unavailable` with the reason (`_source_failures`), the query
  notes it, and a later reference retries after 60 s.
* **Cost is visible.** `_tables.classes_json` holds mode, invalidation, status, rows, wall and
  CPU seconds of the last build; `_source_tables` adds the fingerprint, game date, refresh count
  and the last refresh (`full`, `added`, `unchanged`, `carried`). `fm_db_schema` lists them.

## Tables

Costs measured on 11 November 2026 at load average 80 to 130 (eleven agents), single process,
`nice -n 10`. "First" is the first query that references the table (rows plus fingerprint);
"check" is a later reference when nothing changed, including the first reference after a
snapshot rebuild, which carries the rows over (1.5 s wall for all ten tables). No table is
eager: the snapshot build's collection phase costs 0.05 s.

| Table | Rows | Mode, invalidation | First: CPU s (wall) | Check: CPU s | Source route | Checked against |
|---|---:|---|---:|---:|---|---|
| `contract` | 77,810 | lazy, content: contract pointers of every person and the first 0x70 bytes of every contract | 10.5 (15) | 1.8 | PERSON -0x98 (main) and -0x90 holder (loan/trial), owner-checked; getter keys through direct plans verified against each contract class's getter, the rest emulated per record | `wages.decode` 3,000/3,000; person `Pcex`/`Pcwg` 76,663/76,663; person `Pcsd` 4,522/4,522 where filled; `contract_club_idx`/`contract_team_idx` 76,663/76,663 |
| `contract_clause` | 273,901 | lazy, content (same fingerprint) | 0.8 + 1.7 fingerprint | 1.7 | FULL_CONTRACT entry vector +0x68; loan clause words +0xB0/+0xB8; no emulation | `contract_terms.decode` 2,000/2,000 contracts (kind, order, selection), 7,725 values and 326 expiry dates equal |
| `fixture` | 79,171 | lazy, content: record pointers of the main and linked years | 0.8 (1.4) | 0.1 | GAME_COMP_MANAGER calendar buckets of the main year and linked years (2029-2033) | league tables below |
| `fixture_history` | 123,644 | lazy, append by (calendar_year, group_index) | 156 (167) | 0.9 | archived years 2023-2028: groups the game holds in memory, and every other group loaded by emulating the game's own loader (below) | loading 8 groups that are also in memory reproduces their 14,568 records byte for byte; year totals equal across three game states |
| `fixture_coverage` | 7 | lazy, content (fixture fingerprint) | 0.8 | 0.1 | years and groups held in memory | |
| `competition_stage` | 1,521 | lazy, content (fixture fingerprint: tables change when results do) | 10.4 (30) | 0.1 | competition +0xB0 runtime, stages +0x1D8 (`competition_stages`) | |
| `standing` | 3,285 | lazy, content (fixture fingerprint) | 9.6 (26) | 0.1 | league stage rows +0xC0 (`competition_stages.standings`) | 840/840 top-level rows with resident results agree with played/goals computed from the fixtures; Premier League 20/20 including points |
| `transfer_offer` | 16,421 | lazy, content: both offer vectors and every offer's 0x110-byte head | 0.7 (1.7) | 0.1 | BASE_TRANSFER_MANAGER offer vectors +0x20/+0x38 (`live_transfer_offers` checks) | Newcastle purchases: fee in `amount_raw` (Ramsey 39,000,000), selling club in team3 |
| `player_injury` | 3,851 | lazy, content: every player's injury vector pointer and bounds | 0.5 (1.1) | 0.5 | player primary +0xF0 injury vector (`player_health` layout) | `player_health.decode` 6,845/6,845 players (count and start dates) |
| `news_item` | 5,522 | lazy, content: the decoded rows (inbox read flags change in place) | 0.1 (0.2) | 0.2 | NEWS_MANAGER +0xB8 (5,372) plus the human inbox HUMAN +0x350 (150) | inbox 150 items, 146 read, as `UI_NEWS.md` reports |

Tables built in separate queries share nothing: `contract` and `contract_clause`, or
`competition_stage` and `standing`, each pay their own read when referenced in different
statements, and once when referenced together.

Views over the core tables (`relations.py`): `club_rival`, `club_affiliate`,
`person_favourite`, `club_favourite_person`, `player_position`, `person_nationality`. They
cost nothing to build; they explode the core list columns, which are computed on demand when a
statement names them (`ondemand.py`), so a NULL list means "not read yet" and `[]` "read, empty".

Resolved views: `contract_view`, `contract_clause_view`, `fixture_view` and `fixture_result`
(the calendar years in memory: `fixture` only), `fixture_history_view` (the archived years),
`fixture_all` (`fixture` plus `fixture_history`), `standing_view`, `transfer_offer_view`,
`player_injury_view`. A statement on `fixture_view` costs the `fixture` check; the archived
years are loaded only by a statement that names `fixture_history`, `fixture_history_view` or
`fixture_all`.

Names in resolved views. A template placeholder `{table.CODE1|CODE2}` takes the first
alternative that is stored (direct for at least nine rows in ten), else the first that exists.
Team, competition and injury names have no stored code (every name code is on demand), so
`sources.create_views` writes each placeholder to `_view_columns` under the view column it
feeds (a placeholder in FROM or WHERE feeds every column): a statement that names
`home_team`, `team_name` or `injury` has the name computed for the rows it reads, as for the
curated views. Before this, the planner did not see through these views and the names read NULL.

## Archived fixtures: the game's own loader

GAME_COMP_MANAGER holds the main calendar year (2030) and linked years (2029, 2031-2033) in
memory. Archived years 2026 and 2028 hold 10 and 8 of their 66 groups; 2023-2025 and 2027 have
no year manager at all. The rest sits in `Temporary/fixture_group_archive.obs`, which the game
keeps open and reads on demand: group byte +0xB70 bit 0 clear makes 0x3D2246C call
GAME_COMP_MANAGER vtable +0x2C0 (0x1ACD00C). That function looks up `{group, year}` in the
archive index at manager +0xAD00 (entries vector +0x30/+0x38; entry +0x10 group, +0x14 year),
builds a stream over the file (0x1894340) and deserialises the group (0x3D313AC).

`fixture_tables._archived` calls 0x1ACD00C in a private VM with a zeroed VM-private group
object as the destination, then reads the day vectors and records from VM memory with the same
layout as resident fixtures. `sources/_archive_vm.py` lets the game's stdio calls
(`fseeko`/`fread`) read `.obs` and `.cmt` files in the game's `Temporary` directory, read-only,
besides the `.fmf` data files the shared VM allows; a FILE with unflushed write data is read
with those bytes laid over the disk file where their place is established, and refused otherwise
(HISTORIES.md). Nothing is written to the game or to the file.

The game moves archived years and groups between memory and the archive as it pages them: on
11 November 2026 the resident archived years changed from 2026/2028 to 2027/2028 within an
hour, and the archive index shrank to the groups not in memory. `fixture_history` therefore
reads an archived year's resident groups and its archive entries together, compares the
residency before and after the pass (and repeats it once if they moved), and stores rows by
(calendar_year, group_index) so a later reference adds only groups it does not hold. A group
whose load fails is not stored and is tried again on the next reference. Year totals agreed
across three different residency states: 2023 84, 2024 143, 2025 20,418, 2026 33,852, 2027
34,756, 2028 34,391.

The archive VM is the classic PropertyVM. With FastVM, after the game had swapped its
resident years, some groups loaded short without an error (2026: 1,001 records from 54 groups
where the classic VM read 33,852 from 66); the cause is not established. Loads also fail
("unreadable live memory", "write to shipped code", pointers like 0xffffffff00007000 decoded
from the stream): every large group loaded at 20:35 and 21:50, and every large group failed
at 21:20 and 22:10, in the same game date, with the game open. The loader reads the archive
through a file object at archive +0x18 (seek through its vtable +0x20, one `fseeko`, then
`memcpy` only: no `fread`), so it reads buffered state the game changes; the cause is not
established. Safeguards: a group is stored only when two loads in fresh VMs agree, every
record passes the vtable and bucket-date checks, and an archive entry with data yields
records; anything else is retried on the next reference, and stored groups are never read
again. Next: trace the file object's read path (vtable at archive +0x18) to see whether it
serves a memory window the game remaps, and if so read the archive file directly with the
saved_fixture_archive decoder for the positions the index gives.

## Manager view

Each table and view carries a policy in `_source_tables.manager_json` /
`_source_views.manager_json` (scopes: `public`, `own_club` with the column that names the club,
`never`). The manager connection still exposes only its masked `m_*` views; its authorizer
denies every collection table until the manager view adds masked views for them.

| Table | Policy | Reason |
|---|---|---|
| `contract` | own_club on `club_idx`; public columns idx, person, role, class, teams, club, squad number, expiry | wages, fees and clauses show for the manager's own players only |
| `contract_clause` | own_club through `contract.club_idx` | clauses show for own players only |
| `fixture`, `fixture_history`, `fixture_coverage`, `competition_stage`, `standing` | public | fixtures, results and tables are public screens |
| `transfer_offer` | own_club on any of the three team clubs | the manager sees offers his club made or received |
| `player_injury` | public | injuries show on every profile and in news |
| `news_item` | own_club: `source = 'inbox'` | the manager sees his inbox |
| `club_rival`, `club_affiliate`, `person_nationality` | public | shown on profiles |
| `person_favourite`, `club_favourite_person`, `player_position` | own_club | shown for own or scouted players only |

## Not read yet, and the next route

* Contract squad status: no contract class getter answers `PFms`, and the person getter does
  not either (`PMsq` is unset on every live player). Read instead as the hand-built
  `playing_time.decode` reads the agreed playing time: FULL_CONTRACT +0x54, the byte its slot 32
  accessor 0x1005C78 returns (accessor bytes checked). `contract.squad_status_code` (labels in
  `_enum_labels`), `contract_view.squad_status`, `person.contract_squad_status_code` (computed at
  build) and `player_view.squad_status` carry it; own club only in the manager view.
* Contracts of 7 PERSON classes (support staff, officials, agents, journalists, virtual and
  retired people) are skipped: their slot 121 is not the verified contract getter.
* Histories (player career, staff, club and competition winners, awards, injuries, transfers
  before this season): the 39 auxiliary `DATABASE_TABLE` singletons are all empty in a running
  game. The game keeps history in `Temporary/pl_hist_dt.cmt`, `non_pl_hist_dt.cmt`,
  `comp_history_dt.cmt`, `award_year_hist_dt.cmt`, `injury_histories_dt.cmt`,
  `person_record_history_dt.cmt`, `competition_archive.obs`. The UI VM already pages person
  history in through `get_list` 0x14A0FB0 (owner thread, `UI_HANDLERS.md`). Next: the same
  archive-VM approach as fixtures, calling the history loaders save-wide.
* News item subject, body and linked people/clubs: generated by UI code (`fm_ui_inbox`).
* Offer state labels and the meaning of the four packed dates on offers.
* Shortlists, scout assignments and reports, promises, concerns, bans, international call-ups:
  hand-built per-record decoders exist (`shortlist_source`, `assessment_source`,
  `player_promise_inventory_source`, `player_ban_source`); not yet enumerated save-wide.
* Naming records and kits (`prnm`, `alnm`, `ktfl`): embedded lists on records; the core
  snapshot's list columns hold them as JSON.
