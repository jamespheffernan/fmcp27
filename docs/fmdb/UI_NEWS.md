# UI handlers: inbox, calendar and fixture

`fm_live_mcp/fmdb/ui_recipes_news.py` reads three screens through the game's own UI handler
code in `UiHandlerVM` (see `UI_HANDLERS.md` for the VM, the factory and the client/server
ABI). Everything runs on copied live memory; nothing is written to the game. Addresses are
RVAs in the arm64 `game_plugin` of build 27.0.0.2493426. Live numbers below come from the
Newcastle career (manager Cesar Jules) on 10 December 2030, read on 11 November 2026.

```python
from fm_live_mcp.fmdb import ui_recipes_news as news
rows = news.inbox(vm_or_session, limit=50, unread_only=False)
events = news.calendar(vm_or_session, team=None, days=60)
reading = news.fixture(vm_or_session, home_id, away_id, news.si_date(day, kickoff_code))
```

`vm_or_session` is a `UiHandlerVM` or a `fmdb.live.LiveSession` (a VM is then opened with
`rng='copy'` and cached on the session).

## Inbox

### Where it lives

| Piece | Address | Verified behaviour |
|---|---|---|
| Human inbox | HUMAN_NON_PLAYER +0x350 | pointer to `{begin, end, cap}` of NEWS_ITEM pointers, sorted by unique id; 150 items |
| Item unique id | NEWS_ITEM +0x90 (u32) | binary search key of 0x142273C (inbox) and 0x28FF324 (all news) |
| Item flags | NEWS_ITEM +0x98 (u16, server key `Nfla`) | bit 0 = read; agrees with `NewsItemHasBeenRead` on 150 of 150 items |
| All news | NEWS_MANAGER (global 0x56A5908) +0xB8 | every item in the game (5,372), sorted by unique id |
| Owner lookup | 0x2D051C | record `huma` (people index) -> 0x106696C -> PERSON vtable+0x6F0 -> HUMAN |

The earlier attempt found the vector empty because it reached the HUMAN through `'Hhum'` and
virtual 0x6F0 on a different object; the server's own path (`huma` -> people table -> PERSON
-> HUMAN) gives the manager object whose +0x350 holds the inbox.

### Recipe

Handler type 70 (`NEWS_ITEM_UI_HANDLER`), UI_RECORD `{'huma': person index, 'unid': item+0x90}`.
The ten inputs the client consumes (`NeLa NeNE NeRN NeRO NewI Nfla body laNe type yms `) come
from server slot 2 (0x2D0618); `NewI` serialises the item. `inbox()` reads 24 of the 47 client
keys by default (`keys='all'` reads every one) and returns, newest first: subject (`titl`,
falling back to `AJ15`), headline subtitle, body (display text; link markup kept separately as
`body_links`), date (`CqMA`), time sent, read, important, priority, action, can respond,
deadline text, sender, sender team, media source, tags, referenced objects (`8C2l` `3Sd `) and
every key by registry label. `unread_only=True` filters on the flag bit before any handler is
built. Link payloads inside strings are a serialised record format; `body_links` keeps them as
base64 with the shown text. Object references resolve to names through the game's resolver
0x111344C and the record's `dbnm` property.

### Live result

* 150 items; 147 (98 %) return a usable subject and body. Item count and order were identical
  across reads (live test).
* The 3 failures are `RESERVE_U18_COMP_NEWS` items: their `NewI` input calls
  `std::random_device(const std::string&)` (stub, from 0x4360D0C; chain 0x18A5DE0 < 0x18A6094 <
  0x1107F70 < 0x1104578 < 0x141649C < 0x243CD8 < 0x2D0A18). The VM refuses it, so every display
  key of those items is unset; `input_failures` names the blocker.
* Time: 279 s for all 150 items alone (median 0.52 s per item), 375 s with other emulations
  running (median 0.66 s, 90th percentile 4.0 s). Post-match key findings take 22-36 s and
  opposition reports 8-19 s each (long generated text).
* RNG: one draw in all 150 items, in item 1341505 (`RESERVE_U18_COMP_NEWS`, "Phillips shines
  as Walker finds fitness for Newcastle Under 21s"). With `rng='refuse'` its subject still
  reads and its body (`body`) and first speech bubble (`BuFS`) stop at the thread-local RNG,
  so those two depend on the draw. With `rng='copy'` they use the draw the game would make
  next and can differ from the rendered inbox.
* `NewsItemAgeString` needed `modff` and `ActionData` (`8C2l`) needed `strtod`; with both
  modelled in `ui_vm.py` no key of the 147 readable items is unavailable.

Five subjects to check against the inbox:

| Date | Sent | Read | Subject |
|---|---|---|---|
| 10 Dec 2030 | 19:00 | unread | FA Cup draws Newcastle against Wolves |
| 10 Dec 2030 | 18:47 | read | FA Cup Third Round draw today |
| 10 Dec 2030 | 16:48 | unread | Fitness tests |
| 10 Dec 2030 | 13:49 | unread | Player Targets and Promises Updates |
| 10 Dec 2030 | 13:01 | unread | Nosworthy leaves Aston Villa for Newcastle |

## Calendar

### Real input path

The previous blocker (every input stopping at 0x43CCCF0) came from the record. The
`CALENDAR_UI_HANDLER_SERVER` slot 2 (0x97ADC) reads:

* `Hhum` through 0x71248 (people UI id `1 << 24 | person index`), then PERSON vtable+0x678;
* `Team` through 0x71254 (team UI id). The key is `'Team'`, not `'Ttea'`; with `'Ttea'` the
  team is null and the event collector returns nothing;
* `'100 '` through 0x8AD7C (0 = general calendar);
* per-request parameters from its context bag (x3): `nMzT` (SI_DATE), `tstp`, `OBep`, `mPdQ`,
  `ptvl`, and for some keys `stDT`/`enDT` built by 0x99EC4.

Server key `UIww` with context `{'nMzT': SI_DATE}` returns `{'GenE': [events], 'stDT', 'enDT'}`
for two weeks from the Monday of that date. The events come from 0x12ED77C -> current
GAME_HUMAN (global 0x56D2CA0) vtable+0xF8 = 0x203D3B8 with flags 0x1FF7FFE. The collector
needed `memchr` (0x3C95154), now modelled.

An SI_DATE typed value is `{0x56D5878 traits, year << 17 | day of year << 8 | low}`; `low` is
the 7-bit time code that `fm_live_mcp.fixtures.kickoff_time` decodes (57 = 20:00). A property
bag is `{begin, end, cap}` of 16-byte `{u32 key, pad, typed*}` entries (lookup 0x43F899C).

### Recipe

Handler type 9, UI_RECORD `{'Hhum': object_id(1, person index), 'Team': team UI id}`; then
`UIww` once per 14 days from the start date, events de-duplicated and cut to the window.
Event classes (`clEv`): 0 fixture, 1 competition date, 5 transfer-window date, 17 training day.

* Fixture: date, kickoff (time code), competition (`comp`), fixture name (`FxNm`), team
  (`Ttea`), opponent (`Topp`), venue (`FxVn` 1 = home, 2 = away; agrees with `iSHo`),
  opponent league position (`TpoN`), human-controlled team (`HUCD`). `FRfr` = `{'dref':
  0x35 << 24 | team index, 'dcnt': SI_DATE}` resolves (0x111344C with the date as typed extra)
  to a FIXTURE_RECORD whose +0x18 is the db FIXTURE: home +0x08, away +0x10, stadium +0x28.
* Training day: three session codes (`Szio`), not labelled by the server.
* Competition date: competition, stage (`sbsn`), `type`. Type 3 is a draw (the client's
  WeeksOverview text for the 20 Dec event reads "EFL Cup Semi Final Draw"). Types 0 (stage
  match date), 4 (registration deadline) and 23 (round date) are inferred from stage and date
  and returned as `type_inferred`.
* Class 5: Premier League on 1 Jan and 3 Feb 23:00, read as transfer-window dates (inferred).

### Live result and cross-check

60 days from 10 Dec 2030: 98 rows (29 fixtures across the senior, U21 and U18 teams, 60
training days, 7 competition dates, 2 transfer-window dates) in 1.9 s (5 windows), 0 RNG draws.

Against `Bridge.find_fixtures` (team filter per team native id, all cursor pages): 29 of 29
fixtures match on date, home team, away team, kickoff time, competition name and stadium; no
mismatches, none missing on either side. The next fixture reads Villarreal C.F. v Newcastle
United, UEFA Champions League (League Phase), 10 Dec 2030 20:00, away, Estadio de La Cerámica.

### Handler keys

* Server, empty context: 18 of 54 keys return data (`AGq6 ALLE HPHP LZPa MPML R3VC RTdl SuMP
  UIQW UIQa UIww Viiw dYYY dYaw hMMM m8Y4 shsh tEGK`); the other 36 return the string
  "Failed to get data" (they need context parameters).
* Client (`declared_get`, 49 keys): 20 values, 29 unset, 0 unavailable; build 3 ms, keys 3 ms
  to 18 s, 42 s in total. Day and week overviews (`SmallDaysOverview`, `DaysOverview`,
  `WeeksOverview`), training schedules, dropdowns and `IsGeneralCalendar` return values.
  `MonthEvents` (`CTrE`, 18 s) and the per-day keys return nothing: they read a month or day
  selected through the request's UI node (request+0x38, hash lookups in 0x77E228), which a
  screen-less read does not have.

## Fixture

### Client inputs (generic)

The FIXTURE client reads server values from the fourth argument of get_property, a property
bag. Two client slots say what goes in it:

* slot 14 `(this, request, out u32 vector)`: server keys a property needs (no parameters);
* slot 16 `(this, request, declarations)`: groups of 0x48 bytes `{params bag, client params
  bag, sorted u32 keys}`; each key is computed by the server with that params bag as context.

`declared_get(vm, handler, key)` runs both, computes every key on the server and calls slot 4
with the bag. The same function reads the calendar client keys above.

### Recipe

Handler type 50, UI_RECORD `{'fhmT': home team id, 'fawT': away team id, 'fdte': SI_DATE}`
(server fixture lookup 0x207820 -> 0x3D1CFD0).

| Match | Keys: value / unset / unavailable | Time | Inputs |
|---|---|---|---|
| Villarreal v Newcastle, 10 Dec 2030 (next) | 46 / 117 / 1 | 6.5 s | 46, `FxRl` fails |
| Newcastle 0-0 Sheffield United, 7 Dec 2030 (last) | 49 / 114 / 1 | 22.9 s | 44, `FxRl` fails |

Values include kickoff ("20:00", "15:00"), fixture name, home/away teams, league positions
("13th"/"12th"), weather ("Shower 51°F"), TV rights text, board opinion, team news, top
performers with ratings (last match) and `IsFutureMatch`. The one unavailable key was `Odds`
(`strtod`); with `strtod` modelled it reads `{'pI 7': 54, 'gdeZ': 21, 'zZHb': 25, 'UFHx':
'Voted by 97,630 fans and pundits'}`. Score and result keys (`fxhs`, `fxas`, `fxrs`) and
`MatchVenue` stay unset for the played match.

Blocker: server key `FxRl` reads `Hhum` and `ctxt` from its context bag (0x657714, 0x207304 at
0x20AFD4-0x20AFF4); with neither present it dereferences HUMAN+0x438 at 0xCB51D8 (null). The
context comes from the screen's UI context (the 'Hhum'/'Ttea' registry described in
`knowledge_stars.py`), which the declarations do not carry.

RNG: 0 draws for the calendar and both fixtures.

## Shared-file changes

`ui_vm.py`: three libc models added to `UI_EXTERNALS` (`_memchr`, `_modff`, `_strtod`).
No other shared file changed.

## Not verified

* The read/unread state and the five subjects against the owner's inbox screen.
* Training session code meanings and competition `type` codes other than 3.
* Item 1341505's body against the rendered inbox (it draws from the RNG).
