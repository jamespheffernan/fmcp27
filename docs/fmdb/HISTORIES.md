# Histories

Build 27.0.0.2493426, Newcastle career (manager Cesar Jules), game date 13 Dec 2030, 12 Nov 2026.
Code: `fm_live_mcp/fmdb/sources/histories.py` (tables), `fm_live_mcp/fmdb/history_read.py` (routes).
Tests: `tests/test_fmdb_histories.py` (offline), `tests/test_fmdb_histories_live.py`.

## Where each history lives in a live career

| History | Store | Route used |
|---|---|---|
| Starting playing history (seasons before the save began: club, apps, goals, fee, loan) | `Temporary/pl_hist_dt.cmt`, paged per person by `FILE_LLIST::get_list` 0x14A0FB0 | record getter `Plhs` (emulated, owner-thread retry) |
| Starting non-playing history | `non_pl_hist_dt.cmt` | record getter `Pnph` |
| Career spells including this save (every club, loan and job, with dates) | `non_pl_hist_dt.cmt` + `person_record_history_dt.cmt`, built by the PERSON server (data key `hisA`, 0x2081810 > 0x1380478 > 0x2080dbc) | PERSON_UI_HANDLER `erHw` StaffHistory |
| Career totals (all apps and goals, league, current club), milestone counts | PERSON server; `pl_hist_dt.cmt` + `player_stats_hist_dt.cmt` merged by 0xF1FBB0 | PERSON_UI_HANDLER `GNGR` `Ny6I` `h4UR` `DGAq` `0F6G` `y1oK` `XA61` `Dmwv` `ZpBW` `lcn9` |
| Injury history | `injury_histories_dt.cmt` (loader 0x132D1DC from 0x272FA14) | PERSON server data `Phis` (structured, injury reference) + client `b1SW` (labelled rows) |
| Club league history | `tc_league_history_dt.cmt` | CLUB_UI_HANDLER `LgHs` |
| Competition past winners | `comp_history_dt.cmt` (3.5 MB, held open by the game), paged by GAME_COMP_MANAGER vfunc 0x3B8 (0x1AC58F4) from 0xEF510C | COMPETITION_UI_HANDLER `hist` (server data `chst`) in the UI VM |
| Award past winners | `award_year_hist_dt.cmt` (reopened on demand) + `retired_person_hist_archive.obs` | AWARD_UI_HANDLER `I20k` PastWinners (server data `AwHi`, `AwSd`); UI object table type 0 |
| Season statistics per season, club and competition scope (every season, this save's included) | `pl_hist_dt.cmt` + `player_stats_hist_dt.cmt` (138 MB), rows built by 0xF1FB44 | 0xF1FB44 > 0xF74E50 (block list) > client 0x39AF34 (SeasonStats row), all emulated |
| Club transfer history (this save's seasons) | `transfer_archive.obs` | CLUB_UI_HANDLER `PTin`/`PTou`/`ptia`/`ptoa` (data `Cpts`) with the screen's season selection set in the VM |

The database lists `Clhs`, `Tchl` (club), `chst` (competition), `AWsh` (award), `Pacl`, `PPsT`
(person) are empty on every record sampled: the live game keeps those histories in the
`Temporary` archives, not on the records.

## Tables

All ten are `lazy`, `append`, identity (key, entry, read_date), replace_key (key), check
interval 0, manager scope `public` (the profile and club history screens show them for any
person or club).

* `person_playing_history`, `person_non_playing_history`, `person_career_spells`, `person_season_statistics`,
  `person_career_totals`, `player_injury_history` keyed by `person_idx`.
* `club_league_history` and `club_transfer_history` keyed by `club_idx`, `competition_history` by `competition_idx`,
  `award_history` by `award_idx`.

Computed on reference. Before the statement runs, `statement_keys` runs it once on a read-only
connection where the table is a TEMP view of every candidate key (`person` or `club` idx) whose
WHERE term records each row it yields. `WHERE person_idx = ?`, `IN (...)`, a join on the key or
`IN (SELECT idx FROM person WHERE club_idx = ...)` visit only those keys; an unrestricted
statement visits every candidate and is refused when more than 400 keys would be read
(`sources.StatementTooWide`, raised by `tools.db_query` as the error text: how to narrow it).
Rows are kept until the game date changes; one PERSON handler read feeds the four person UI
tables for 300 s on the same date.

A read that fails for a key (the game's code stops in the VM, or a value is unavailable) stores
no row and no read mark for that key. The answer names the key and the reason in
`collections[table]['not_read']` and in a note, and the next statement that names the key reads
it again. A key that was read and has no history gets a read mark for the game date and is not
read again on that date. Until 14 November 2026 a failed key was marked like an empty one and
its reason reached only the table's stored note, so the answer for a club whose read failed was
the answer for a club with no history: no rows and no note. The same now holds for the person
tables: the virtual player 73009 has no `person_career_spells` rows because reading them draws
random numbers, and the answer says so (`person 73009: reading spells drew random numbers (not
stored)`).

Random numbers: the UI VM counts draws per key. HonoursCount `uu70` draws 10 and is not read; no
key used here draws.

## Season statistics (`person_season_statistics`)

Route (code in `fm_live_mcp/fmdb/history_season.py`), every step shipped code in the UI VM:

1. `0xF1FB44(PLAYER_STATS_MANAGER [0x56A83C8], people-table entry, out vector<ROW*>, 1, &u16, 1)`
   (the PERSON server's call at 0x1F6930C) returns one row per season and club: +0x00 team
   record, +0x10 competition record, +0x18 team unique id (0xFFFFFFFF on the current season's
   row, so the team comes from +0x00), +0x1C fee (-1 none), +0x20 i16 year, +0x24 byte 1 = loan,
   then six blocks of 0x20 bytes at +0x28 + 0x20 * scope.
2. The PERSON server answers data keys `Psfr` and `Psle` (0x20BB788 dispatch) with
   `0xD5866C(person, scope, out)`: block = `[0x56D2D08]->vfunc 0x200(person, scope)` for the
   current season, then `0xF74E50(block, out vector<variant*>)`, an 83-entry list: entries 0..12
   are the block's bytes +0xC..+0x18, 13 and 14 its i16 at +8/+0xA, 15..82 the stored i16 list
   read through 0xF75588. The same function applied to a career row's block gives that season's
   list.
3. The PERSON client (0x376980) turns `Psle`/`Psfr` into SeasonStats rows with
   `0x39AF34(out variant, &list, competition)`; its keys carry the UI registry labels
   (`ovAp` Appearances, `ovGo` Goals, `ovAR` AverageRating, `OaAs` Assists, `RPSj`
   StartingAppearances ...). 36 keys, 33 labelled.

Which entries each key reads was found by changing one list entry at a time and re-running
0x39AF34 (`history_season.KEYS`). Two consequences: a byte entry equal to 0xFF is unset (0xF75588
reads it as -1), so a value that reads one is NULL; and the goalkeeping keys share entries with
outfield ones (PenaltiesFaced/entry 21 with the tackle attempts in TackleCompletionPercentage,
PenaltiesSaved/TackleCompleted entry 22, SavesHeld entry 23, SavesParried/HeaderCompleted entry
24). The game emits both; for Kobel (goalkeeper) the goalkeeping values are plausible (2027
League: 31 apps, 9 clean sheets, 5 penalties faced, 1 saved), for Gordon they are his tackle and
header counts.

Scopes are the block index (the screen parameter `PlayerStatsScope`; views use 5 and 0). Names
are the hand-built decoder's (`current_player_statistics.CATEGORY_LABELS`): 0 Non Competitive,
1 League, 2 Cup, 3 Continental, 4 International, 5 Overall (Club). The data agree: on 13 Dec 2030
Gordon's per-competition rows (`WSiZ`) sum to the blocks (League = Premier League 10 apps; Cup =
FA Community Shield 1; Continental = Champions League 3 + UEFA Super Cup 1), and Overall (Club) =
League + Cup + Continental on every season checked (friendlies and caps excluded).

Rows kept: the Overall (Club) row of every career row, and scopes 0-4 where the player had games.
Seasons before the save carry appearances, starts and goals only (assists read 0xFF, NULL); the
other counters read 0 there.

Checks (13 Dec 2030, load 9-12): Gordon 50 rows, Kobel 67, Woltemade 55, regen Greenwood 22,
Ribéry 51, Harper 47, Ameobi 44, Vital 43; retired name record and virtual player 0. Each about
0.5 s through `fm_db_query`.

* Against `person_playing_history` (Plhs), Overall (Club) rows in order (year, team, apps,
  goals): 9 of 10 people equal; Vital differs in 3 seasons (1980, 1982, 1983) where Plhs has no
  apps and NULL goals and the career row has goals 0.
* Against `fm_get_player_statistics_history` (hand-built archive decoder, 2025-2029), per
  (year, category): Gordon 22 of 22, Kobel 25 of 27, Woltemade 24 of 24, Greenwood 10 of 15 equal
  in apps, goals, starts and assists; the other 7 are rows with 0 apps, which the table does not
  keep. The current season (2030) is not in that decoder; it equals the PERSON handler's own
  `JgH0` SeasonStatsCombinedRow (15 apps, 2 goals, 6.84) and the League row of `WSiZ`.
* Fee: the career rows put a transfer fee on the season row of the club joined (Gordon's
  £40m on Newcastle 2022); Plhs puts it on the row of the club left (Everton 2022).

## Competition and award past winners (`competition_history`, `award_history`)

The record getter `chst` reads the database's own competition-history table (0xF1A24C walks
`[0x56D3280]+0x88` for records whose +0x18 is the competition), which is empty in a live career.
The History screen goes another way: the COMPETITION server's data key `chst` (0x2011550, needs
byte 0x56D34E0 = 1) calls 0xEF510C, which for a competition with a game object at +0xB0 calls
0x3B3C440 and 0x3AD3CBC, and that pages the list in through GAME_COMP_MANAGER
(`[[0x56D57D0]+0x158]`) vfunc 0x3B8 = 0x1AC58F4 from `Temporary/comp_history_dt.cmt`. Read
through COMPETITION_UI_HANDLER `hist` (record `{'dref': 0x19 << 24 | idx}`) in the UI VM it
returns the labelled rows: Year, StageName (empty on every row of 13 leagues and cups checked on 13 Dec 2030,
including the Champions League, Europa League, World Cup and FA Cup: not kept), MissingHistoryString, FirstPlaced, SecondPlaced,
ThirdPlaced, JointFirstPlaced, PlayoffWinner, HostNation, HostStadium. The round-2 note that the
handler answered empty lists does not hold on this build and career: the UI VM read it the first
time (the earlier attempt used another binding).

Award records are UI object table type 0: the DATABASE_RECORD factory builds AWARD_UI_HANDLER for
`{'dref': idx}` (types probed 0..0x4F: 0 award, 1 person, 3 club, 5 continent, 8 language,
9 national-team container, 0xA nation, 0x15 stadium, 0x18 team, 0x19 competition, 0x38
agreement, 0x39 fixture name). `I20k` PastWinners (server data `AwHi`, `AwSd`) reads
`award_year_hist_dt.cmt` and `retired_person_hist_archive.obs`. Each season: DisplayString,
WinnersCount, Winners (Person, Team, StatValue, Appearances, Goals, Assists, AverageRating ...).
`key_15` (client key '15  ', no registry label) equals the winner's age on the rows checked.

Checks (13 Dec 2030, load 9):

* Premier League: 131 seasons 1888/89-2029/30 (2029/30 Newcastle United, Liverpool, Arsenal).
  Against `fm_get_saved_competition_history` (`Cesar Jules - Newcastle (v02).fm`, saved 4 Dec
  2030), by season and owner-club name of first, second and third: 130 of 130 equal; live has one
  more season (2029/30) that the saved file's retained rows do not include.
* Champions League 75 seasons (1955/56-2029/30), UEFA Super Cup 55, FA Community Shield 108.
* Ballon d'Or: 222 rows over 74 seasons 1955-1956..2029-2030, three placed per season (2029-2030
  Kylian Mbappé, Real Madrid, 53 apps, 7.71); 2019-2020 has three rows with no person (the award
  was not given). The Best FIFA Men's Player 39 seasons, PFA Player and Young Player 57 each.
* Cost: one UI VM per statement, 0.5-1.2 s for one competition or award.

## Club transfer history (`club_transfer_history`)

`Cpts` no longer fails on this build: it answers a record with every list empty and `year` 1900.
The CLUB server (0x1FAF8A8) builds the parameter bag for 0x2E22F78 from a copy of the global
property bag at 0x56D38C0, then adds `dref`, `type` and `Ttea`. 0x2E22F78 reads `year` from that
bag (1900 when absent) and `mont`; the global is the front end's selection on the club's transfer
history screen and is empty in the live game. So the table writes, in the VM's private copy only,
a bag `{'year': y}` made by the game's own constructors (int32 typed value 0x4403EC0, bag insert
0x43F72E4) into that global, once per season from `styr` to `edyr` (both reported by `Cpts`:
2025..2030), and reads the client keys PastTransfersIncoming `PTin`, PastTransfersOutgoing `PTou`
and the season amounts `ptia`/`ptoa`. `mont` changes neither list nor amounts (0, 1, 7, 8, 13
tried). The context argument of server slot 2 is not that bag (a context bag with `year` changed
nothing).

Newcastle (club 414), 13 Dec 2030: 2025 in 12 / out 16 (£215.4m / £142.0m) ... 2030 in 13 / out 12
(£274.7m / £194.6m); 2025 includes Nick Woltemade £65M from VfB Stuttgart, Malick Thiaw £30M from
A.C. Milan, Aaron Ramsdale "Loan - £3.2M" from Southampton. Two routes agree: Kobel "£48.5M"
(listed in 2026) against the career row fee 48,602,100; Woltemade "£65M" against 64,815,508.
`year` is the screen's season selection, which puts the January 2026 window in 2026 while the
career rows file Kobel's move under season 2025. Cost 1.5-4.5 s per club (six seasons, two
directions). The items' BuyingTeamString (`byts`) is empty on every row (135 Newcastle rows: the
buying team is always a team, `buying_team_idx`), so the column was dropped; SellingTeamString
(`slts`) holds the wording only where there is no selling team ("Free Transfer", 4 rows) and is
kept as `selling_team_text`.

A club is answered whole or not at all. One season the game does not answer makes the club
unavailable with that season's reason, because a history with a season missing would read as
complete.

### The PAST_TRADE pool (14 November 2026)

On 14 November 2026 (27.0.1, game date 18 Jan 2031) the table returned no rows for any club, and
the answer gave no reason. Every club's read stopped in season 2025:
`PTin 2025: data key Cpts: external call _pthread_condattr_init` (27.0.1 frames 0x1FCA8B4 >
0x2E327EC > 0x2E302D4 > 0x2D7B474 > 0x2D83CF4 > 0x2E41F88 > 0x1853CAC > 0x185555C > 0x436F340 >
0x4370208 > call site 0x43BF864). Seasons 2030 to 2026 had read correctly before it. All six
clubs tried that have a history stopped in 2025.

`Cpts` reads a season's past transfers from the game's file (`fseeko` and `fread` in the VM). The
record deserialiser (0x1848F60; 27.0.1 0x1853A1C) reads a flag byte and, for a record whose flag is 1,
takes an object from the game's `PAST_TRADE` pool. That pool is a function-local static
(initialiser 0x184AA38, pool 0x56B4E70, guard byte 0x56B4FB0; 27.0.1 0x18554F4, 0x5750E70,
0x5750FB0) that a game process builds the first time it needs one. In the running game the guard
byte and the pool's memory were zero: that process had not built it. The VM therefore ran the
constructor itself (0x43566D4 > 0x4357514 > 0x43A6BF4; 27.0.1 0x436F2FC > 0x437013C > 0x43BF810),
which sets up two mutexes, then a mutex and a condition variable. The VM modelled
`pthread_mutexattr_*`, `pthread_mutex_init` and `pthread_cond_init` as no-ops and refused
`pthread_condattr_init`.

Neither the 27.0.1 update nor a reader change caused it. The initialiser has the same calls on
both builds, and run on each preserved plugin file alone (the static VM, no game) it stopped at
`pthread_condattr_init` on 27.0.0 and on 27.0.1. The read fails in any game process that has not
built the pool, as soon as a season's list holds a record with the flag. On this save season 2025
holds the first one; seasons 2026 to 2030 read without the pool. The checks of 12 November read
season 2025 (in 12 / out 16), so in that game process the read did not have to build the pool:
the game had built it, or already held the season's records in memory. Which of the two was not
recorded.

Fix: `_pthread_condattr_init` and `_pthread_condattr_destroy` are no-ops like the other lock
set-up calls (REFUSALS.md). The attribute object only feeds `pthread_cond_init`, already a
no-op; waiting on a condition is still refused. The pool is built in the VM's private memory
during the season's read and nothing is written to the game.
`tests/test_fmdb_histories.py::test_the_past_trade_pool_is_built_inside_the_vm` runs the
initialiser on both plugin files.

Checks through `fm_db_query` (18 Jan 2031, 27.0.1, guard byte still zero in the game):

* Newcastle 143 rows. Season 2025 is in 12 / out 16 with amounts 215,381,000 / 142,016,000, as on
  13 Dec 2030, with the same Woltemade (£65M, VfB Stuttgart), Thiaw (£30M, A.C. Milan) and
  Ramsdale ("Loan - £3.2M", Southampton) rows. Season 2030 is in 15 / out 18 (13 / 12 on 13 Dec
  2030); `edyr` is still 2030 and a selection of 2031 gives empty lists.
* Manchester United 168 rows, Leyton Orient 84, KF Tirana 36, Flamurtari 6, KF Laçi 3, each over
  2025 to 2030 (KF Laçi 2026 and 2027 only).
* Merthyr Tydfil (club 410: no nation, no division) reports no seasons (`styr`..`edyr` 0..0). The
  answer's note names it as not read; whether 0..0 always means a club without a history is not
  established.
* Cost 3.2 to 5.0 s per club.

Two reads in the first diagnostic run stopped differently: after four clubs had failed in 2025,
KF Laçi stopped in 2027 and Leyton Orient in 2030 with `write to shipped code`. Two further runs
did not show it and its cause was not established. That reason is in `vm.STALE_SYMPTOMS`, which
the record getter retries once on fresh pages; `club_transfers` does not retry, so such a stop
is reported as not read and the next statement reads the club again.

### Unflushed write data in a game file (14 November 2026)

After the game moved from 18 to 21 Jan 2031 and saved, the table refused (Newcastle, Manchester
United) with `PTin 2027: data key Cpts: game file has unflushed write data`. The answer named it;
the table was unavailable.

The file is `Temporary/retired_person_hist_archive.obs`: an 8-byte header, then one zstd record
per retired person (67 on disk, 68 bytes each, one of 65). The rows of a season are resolved
through the game's retired-person history store (27.0.1 frames 0x2E32FB4 > 0x3B18A8 > 0x18534FC >
0x1107B40 > 0x110B8B0 > 0x2103F10 > 0x2103BD4 `PERSON_HISTORY` > 0x2AAB0F4 > 0x189F084 >
0x4397C48), which seeks to byte 1,844 (record 27) and asks for up to 131,075 bytes: the rest of
the file. On this save seasons 2027 and 2026 make that read; 2025 and 2028 to 2030 do not.

The game's FILE for that archive was in write mode (`_flags` 0x1498: `__SWR`, `__SRW`, `__SOFF`)
with 68 bytes in its buffer, `_offset` 4,561, the kernel's file offset 4,561 and 4,561 bytes on
disk: one more record, written with `fwrite` and not flushed. libc keeps such bytes in the FILE
until the game's next `fseeko`, `fread`, `fflush` or `fclose` on that FILE, or until the 4,096-byte
buffer fills. Time alone does not clear it; the game clears it when it next reads that archive
itself. The file was last written to disk at 18:37:26 UTC and the save file was complete at
18:38:34; the game date moved three days in the same minutes. Whether the save or the days'
processing appended the record is not established. Any day that archives a person leaves this
state behind, so it recurs.

What the game would read is known: `fseeko` flushes before it seeks, and a read on a stream in
write mode flushes before it fills, each time at the descriptor's current file offset. So the
models in `ui_vm` now serve the disk file with the buffered bytes laid over it at the kernel's
offset (`_GameFile`), instead of refusing. The offset comes from the kernel (`proc_pidfdinfo`) and
must equal the FILE's `_offset` when libc holds one; the FILE and its buffer in the VM's page copy
must equal the process read again, before and after the disk read. An appending stream or
descriptor, a string stream, or a position that cannot be read keep the refusal, with the cause in
brackets; a stream that moved stops the call with `game file changed while it was read`.
`tests/test_fmdb_game_files.py` runs this machine's libc as the game (`fopen` `r+`, `fseeko`,
`fwrite`, no flush: the same `_flags` 0x1498 and 4,096-byte buffer) and requires the model's bytes
to equal what libc's own `fseeko` and `fread` then return, for a record appended at the end, a
write inside the file, a write larger than the buffer (part flushed, `__SOFF` clear) and a write
past the end.

In the same state (the five FILEs below still unflushed), through `fm_db_query`: Newcastle 145
rows. The read at 1,844 returned 2,785 bytes, 2,717 from disk and the 68 buffered. Seasons 2025 to
2029 are the 110 rows read on 18 Jan; 2030 has two more loans out (Isaac Moran to Notts County,
Liam Chung to Luton Town). Season 2027 has the same rows with the buffered record as without it:
the record belongs to no row of that season, but the game reads it.

The class, on 21 Jan 2031. libc's list of the game's open FILEs (read from the game for this
check only) had five game files with unflushed write data:

| File | Buffered | At | Read through |
|---|---|---|---|
| `retired_person_hist_archive.obs` | 68 | 4,561 (end of file) | the VM: `club_transfer_history` (`Cpts`), `award_history` (`AwHi`) |
| `tc_history_dt.cmt` | 42 | 411,230 (end of file) | no statement tried reached it |
| `tc_manager_history_dt.cmt` | 31 | 77,105 (end of file) | no statement tried reached it |
| `draft_archive.obs` | 8 | 0 (empty file) | no statement tried reached it |
| `pks_3.obs` | 2,508 | 1,068,678 (inside the file, 1,084,091 bytes) | `match_archive` and `live_match_backing`, with `pread` on the disk file |

* With the old refusal put back, `club_transfer_history` (Newcastle, Manchester United) and
  `award_history` (awards 0, 1, 2) refused; with the fix they answer (award 0: 222 rows, 1: 120,
  2: 147). The other eight history tables answered either way for the keys tried (clubs 414 and
  406, competitions 7 and 9, people 13009, 7518, 1 and 71529) and reached no such file.
* `PsHi`, which docs/builds/27.0.1.md lists with this refusal, answered on eight objects (four
  people, two retired records, a club and a team) either way and reached no such file. Which file it
  met on 12 November is not known.
* `pks_3.obs` is read from the disk by two readers with a descriptor of their own
  (`match_archive`, `live_match_backing`), not through the VM. Its newest index entry (key 142293,
  FC Lausanne-Sport Under 18s v FC Luzern Under 18s of 21 Jan, file bytes 1,067,806 to 1,071,186)
  had its last 2,508 bytes in the game's buffer and older bytes on disk in their place; the FILE
  held no `_offset` (`__SOFF` clear: libc had passed one whole buffer through). The newest match
  therefore had no rows in `match_team_stats` and `match_player_stats` and no note, and
  `fm_query_match_data` failed with "Invalid or oversized compressed frame". Both readers now lay
  the same bytes over what they `pread` (MATCH.md, "A frame the game has not flushed").

A club's read that the game changes under it (a `vm.STALE_SYMPTOMS` stop or a moved file stream:
four such stops in about 40 club reads while the owner played) is now made once more on a fresh
page copy before it is reported as not read.

## Checks (13 Dec 2030)

Twelve people through `fm_db_query` (Gordon 13009, Kobel 35795, Woltemade 33495, Ribéry 7518,
Harper 4008, Ameobi 5137, Vital 370, regen Greenwood 136908, Cesar Jules 109669, retired 1 and
71529, virtual 73009):

* Gordon: 10 starting seasons (161 apps; 2020 loan to Preston; £40m fee 2022), 3 spells, career
  415 apps 95 goals, 14 injuries. Kobel 10 spells. Vital 16 spells (8 player, 8 staff).
* Regen: no starting history (generated in the save), 3 spells, 65 apps, 2 injuries.
* Staff who played (Ribéry, Harper, Ameobi): starting history 23-30 seasons; career totals are
  NULL (the PERSON handler gives no playing totals for a non-player record).
* Retired name records and the virtual player: every table empty.
* Injury references: all 54 injury rows of 4 players resolve to an injury row; for Gordon's 14
  the description equals the injury table's name.

Against the saved-file tools (`Cesar Jules - Newcastle (v02).fm`, saved 4 Dec 2030):

* Injury history, Gordon: the 13 saved rows equal the first 13 live rows (date and injury
  index). Live has one more: 2 Nov 2030, partially torn hamstring, 41 days.
* Non-playing history, Vital: 16 of 16 rows equal (team index, order; the one team the save
  cannot resolve is NULL live too).
* Starting history and Kobel's injuries: the saved tools returned no rows, so no comparison.

Cost (load average 5-14): 0.4 s for one person's getter histories, 0.3-1.5 s for one PERSON
handler read; a 26-player squad 14 s at load 14, 10 people 0.6 s at load 5.

## Manager view (evidence)

Every history table is declared `public`. Evidence from the game's own code: for a player of
another club who has never been scouted (Alik Nachreiner, person 101543, club 2413) the PERSON
client declares (slot 14) only history data keys for the history panels (`erHw` < `hisA`, `b1SW`
< `Phis`, `WSiZ` < `NH3 `/`Pbsd`/`Psfr`/`Psle`, `JgH0` < `JgH0`/`Psle`, `GNGR`, `lcn9` < `hisA`/
`lcn9`), none of them a knowledge or scouting key, and the server answers each with full rows
(spells since 2023, a 2026 calf strain, 11 league apps this season, 143 career apps). The
`CanView*` flags are not a scouting mask: they are membership tests in server data `vcvp`
(0x3B1B8C), which is empty when person+0x18 bit 0x8000000 is set (or vfunc 0x510 is false, as it
is for ACTUAL_PLAYER: 0xCA4980 returns 0) and bit 0x40000 is clear; Gordon (own player) has
flags 0x418580200, so `vcvp` is empty for him too. Which person class sets bit 0x40000 or
overrides vfunc 0x510 was not established. Competition winners, award winners and club
transfers are shown on public screens (no person knowledge involved).

## Retired players

Retired people that left the database survive as name records in the person table
(RETIRED_PERSON_NAME_POINTERS / RETIRED_PERSON_NAME_STRINGS, e.g. person 1 Axel Smeets, 71529
Fotaq Strakosha); their names read from memory, and the PERSON handler gives every history list
empty for them (the game's own handler, so the profile shows none). `retired_person_hist_archive.obs`
is read by the game when it serialises a RETIRED_PERSON_NAME_STRINGS record: AWARD past winners
call 0x19811DC > 0x1104334 (RETIRED_PERSON_NAME_STRINGS) > 0x11082E8 > 0x20F59B8 > 0x20F5634 >
0x2A9B0E4, which reads 131,075-byte pages of the file through fread (positions 76..3,136 seen).
So award history rows already pass through that loader. Not established: what else the 4 KB
archive holds (the RETIREMENT_MANAGER +0x108 `OBJECT_STORAGE<RETIRED_PERSON_DATA>` is the other
candidate). Next: emulate 0x1104334(record, VM memory stream) for every name record and decode
the stream with the client side of the same exchange.

## Archived fixture loader (`fixture_all`, `fixture_history_view`)

Reproduced on 12 Nov 2026 (13 Dec 2030 game date, load 8-13): the two largest archived groups
(2028/29 255,236 bytes, 2027/29 242,538) loaded 20 times each, every load in a fresh archive VM:
39 of 40 loads gave 6,742 and 6,587 records, byte-identical across all runs (one SHA-1 per group);
1 load (run 12, 2028/29) stopped after 0.2 s on "unreadable live memory": the game had remapped a
page between the copies. The stream path, read from code: the archive's file object is a
`sicore::SEGMENT_INPUT_STREAM` (base offset +0x20, length +0x28, position +0x30) over a
`FILE_INPUT_STREAM<FILE_POINTER_LIBC>` whose holder caches the FILE position at +0x10; its seek
(0x4429B9C) skips `fseeko` when that cached position already equals the target, and its read
(0x4429C30) is a plain `fread`. Two changes in `sources/_archive_vm.py` make both observed causes
deterministic: an unreadable-memory stop is retried once on fresh pages (`call`), and an `fread`
on a FILE the VM never seeked continues from libc's own position (`_offset - _r` while `__SOFF`
is set) instead of stopping. The second case was not hit in the 40 loads; the after-fix 20-run
repeat was not run (each load takes about 20 s).

## Remaining gaps

* Staleness (all ten tables): rows are kept until the game date changes. A match played, an
  injury or a transfer completed on the current date leaves them stale until the next day. Not
  done: the per-key stamps. Inputs established by this work, which the stamps should cover:
  person_season_statistics the current-season blocks (`[0x56D2D08]` vfunc 0x200(person, scope),
  0x20 bytes each plus the 0x44-entry i16 list they point to) and the sizes of
  `pl_hist_dt.cmt`/`player_stats_hist_dt.cmt`; the PERSON handler tables `person_record_history_dt.cmt`
  and `injury_histories_dt.cmt` sizes plus the person record's club and injury list; transfer
  history `transfer_archive.obs` size plus the club's current window lists. No game date moved during
  this work, so no change was observed.
* Retired players: see above.
