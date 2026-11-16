# Current formation slots and where the bench ends

The HUMAN-owned working tactic edit session holds the working selection at session+2200: 26
PERSON indices. Two boundaries apply to it, and the game decides them separately.

## The first eleven

Native formation and role lookup 23928F4..2392944 searches the selection, rejects missing persons
and indices above 10, bounds the selected creator, then reads the creator's 72-byte position record
at 120+48*index (hex offsets). This path never reads a bench end. The reader exposes
`formation_boundary_state=native_first_11` from the checked working selection alone: slots 0..10
keep their categories and their non-empty count whatever is known about the bench. The
in-possession, out-of-possession and stored player-instruction readers use this boundary only.

## The bench end

### The rule

For a TEAM and a fixture the game computes one number:

    substitutes = min(48F9CFC(fixture+3E as a signed byte, team is not fixture+8), fixture vtable+B0())
    bench end   = 11 + substitutes

48F9CFC maps the fixture's substitution rule code and the side to the number of substitutes that
may be named. The FIXTURE vtable's +B0 is the ceiling getter 3CFAB7C, which returns 15.
`fixture_rules.substitutions` already mirrors both as `named_substitute_cap`
(`fm_get_fixture_rules`); `tests/test_four_tools_271.py` proves the mirror against both builds'
helpers for every signed code.

Slots 11 up to the bench end are the substitutes. The game computes that end in three places, and
they differ only in the fixture they use:

| Where | Fixture | Result goes to |
|---|---|---|
| Session constructor 22BFA44 | a match in the list 27CD2D4 returns for the HUMAN whose home or away TEAM is the session's; none when the list has no such match | session+35B0 and +35B1 (stores at 22BFD40, 22BFD44; skipped by the `cbz` at 22BFCB8 when no match was found) |
| Session evaluator 22C3A00 | its second argument. The screen property at 53C128 passes 17AD6E0(team, current date), the TEAM's fixture on the current date, and skips the call when there is none; 28FD978 passes the fixture 329A994 returns for the TEAM | session+35B0 and +35B1 at 22C3ABC, before any slot is classified; 35B1 again at 22C40A4 |
| Selection screen model 2E4D258 | 17743B8(team, 365): the TEAM's next fixture | model+5194 (store at 2E4DC1C), without the 11 |

A third session writer, 22C0820, stores the same sum in 35B1 at 22C08E4 for the fixture it is
given. A scan of both builds found no other store: it looked for byte accesses at +5B0 and +5B1
from a base formed by `add x, x, #3, lsl #12` in the same function, and for the constants 35B0
and 35B1 (an earlier raw scan for a direct +35B1 access found nothing because the code never
forms one). The constructor zeroes 35B0..35B6
(22BFB2C), a second constructor 22BF768 zeroes them for a session without a TEAM, and the
session's stream methods 22CE494 and 22CE774 write and read 35B0 and 35B2, one byte each. 35B1
is not in the stream, so a session read back from a stream written while a fixture was bound
would hold an end in 35B0 and zero in 35B1; the reader leaves that pair unresolved.

Which matches 27CD2D4 lists, and which fixture 329A994 returns, were not analysed further.

### What zero means

A session holding zero in both bytes has never been given a fixture, and neither had the session
whose stream it was read from. The constructor found no match in its list, and nothing has
evaluated the selection against a fixture since. The session
read zero on each of the three days it was read: 2030-11-14, 2030-12-31 (the day before a match)
and 2031-01-16. The evaluator never reads the zero, because it stores the end at 22C3ABC before
its slot loop runs.

The evaluator's loop 22C4300..22C43CC classifies each of the 26 slots that holds a resolvable
person: index 0..10 is a starter (out+2F6), an index below 35B1 a substitute (+2F7), an index
below 35B0 a further person (+2F8), anything later the rest (+2F9); empty slots from 11 up to
35B1 are counted, and people in +2F8 fill them. With 35B0 equal to 35B1, as both stores at
22C3ABC leave them, +2F8 stays empty.

### What the selection screen uses

The screen does not read the session's bytes for its slot labels. Its model keeps its own count at
model+5194: 15 from the constructor (2E4CFE8, also CD8B0), replaced in 2E4D258 by the minimum
above when 17743B8(team, 365) returns a fixture. The slot label 535DA0..535DF4 gives slot i the
numbered substitute label (number i-10, from 486959C) exactly while 11 <= i < 11 + model+5194.

17743B8 returns the pointer cached at [[team+A0]+B8] as it is when the caller asks for more than
364 days (1774410..177442C, return at 177471C). With no cached pointer the game searches the
fixture list on its own thread and caches the result; the reader does not repeat that search.

### What the reader reports

`fm_get_managed_team_sheet` labels slots 11.. in one of three ways, named in
`role_boundary_state` and `bench_boundary_source`:

| State | Source | Meaning |
|---|---|---|
| `native_first_11_and_stored_selected_end` | `session_stored_fixture_extent` | 35B1 holds 11..26: the end the game stored for the fixture it bound to the session |
| `native_first_11_and_next_fixture_named_substitute_cap` | `selection_screen_rule_for_cached_next_fixture` | both bytes zero, and the TEAM's cached next fixture gives the count the selection screen uses; `bench_fixture` carries its date, side, rule code and caps |
| `stored_boundary_unmapped` | none | neither is established; `bench_boundary_unavailable_reason` says why |

The second case reads only what the game reads: the cached pointer, the FIXTURE type, the two TEAM
pointers, the rule code and the ceiling getter. It stays unresolved when the TEAM has no cached
next fixture, the object is not a FIXTURE, the TEAM is not exactly one of its sides, its date is
before the current date, the rule code is outside the game's table, or the guarded code changed.
A pair of stored bytes that is neither zero nor a valid end also stays unresolved.

In every case the bench is the bench of the editable selection. It is not a submitted match
squad: `match_submission_state` stays `not_established`. The next-fixture count is the model's
count. It does not include the second store at 22C40A4, where the evaluator replaces 35B1 with
11 plus a count its own check 22C1E50 produced, when that check produced one.

`fm_get_player_injury_status` without `player_refs` and `fm_report_simultaneous_bench_cover`
answer for both resolved states and repeat the source. `fm_get_fixture_player_checks` still
requires the stored end, because it checks a fixture the caller names, which need not be the next
one.

### Proof

* `tests/test_bench_extent_native.py` runs each block named above from both builds' plugin files
  in the static VM: the three session stores and the model's store against the mirror for rule
  codes 0..90 and four codes outside the table, both sides; the constructor's zeroing and skip;
  the model's default; the model's call of 17743B8(team, 365) and the cached-pointer return; the
  slot label for six counts and all 26 slots; the evaluator's loop against the team sheet's
  counts over 60 random selections.
* Live, 2031-01-16 on 27.0.1.2503222: the session's bytes are 0 and 0. The TEAM's cached next
  fixture is the away match of 2031-01-18, rule code 58, nine named substitutes; the fixture scan
  of `fm_get_next_match_squad` finds the same match independently. The running build's code,
  emulated over the bytes read from the game, stores 20 and 20 in the session, 9 in the model,
  labels slots 11..19 as substitutes and counts 11 starters and 9 substitutes in the stored
  selection, whose slots 11..19 hold nine players and 20..25 are empty.
* On 27.0.1 every function above is the pinned function with the same field offsets: twelve
  functions touch 35B0 or 35B1 on each build, at the same offsets inside matched functions. The
  remaining readers only load 35B0: 1F94AE8, 22CD71C, 22C48C4 and 22C4BE0 compare an index with
  it, 22AE484 copies it into another object, and 22CD934 was not read further.

Addresses on 27.0.1.2503222: constructor 22CEC84, evaluator 22D2C00 (loop 22D3500), third writer
22CFA60, model 2E5C390 (constructor 2E5C028), slot label 5365E8, 17743B8 at 177E808, 17AD6E0 at
17B7B4C, 48F9CFC at 49FF358, ceiling getter 3D10F08.

### Not established

* A session with a stored end was observed once, on 14 November 2026 (27.0.1, game date
  2031-01-16, two days before the fixture): at 16:57 UTC the session held 0 in both bytes and the
  reader took 20 from the selection-screen rule; at 17:05 UTC, with the same eleven and the same
  nine named substitutes, the session held 20 and the reader took the stored end. So the game's
  own stored value equalled the rule's result for that fixture. What the owner did in the game
  between the two reads is not known, and neither read was compared with the screen. A session
  bound on a match day itself has not been observed.
* The foreground screen was not read. That the model at +5194 belongs to the screen showing this
  session's selection rests on the label code and the model's TEAM and HUMAN arguments.
* How 1774884 chooses the next fixture when none is cached, and when the game clears the cache.

## Other requirements

Existing native byte guards, canonical TEAM/HUMAN/PERSON ownership, selected creator bounds,
duplicate and empty-player policy, OOP map bounds and the verified ReadSet all remain required. No
saved or prepared fallback, session creation, native call, match submission, effective instruction
precedence or foreground-screen claim is introduced. The current formation slots do not prove
historical starters.

Batch 182 recorded a fresh 2030-11-14 current source, all 22 phase records compared against the
native-consumer lookup contract, and Costa's and Diouf's distinct explicit selected bits, role rule
and personal-record state. Working evidence is under
`evidence/batches/current-assignment-boundary-182/`.
