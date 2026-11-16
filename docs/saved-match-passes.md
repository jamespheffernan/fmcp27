# Every pass of a stored match, read from a save

`fm_list_saved_match_event_streams` and `fm_get_saved_match_passes` read the game's per-pass match record from a saved career. `fm_get_saved_match_crosses` and `fm_get_saved_match_shots` read the crosses and shots of the same matches (section below). The game does not need to be running. The code is `fm_live_mcp/saved_match_events.py`; the pass decoding is shared with the live readers (`fm_live_mcp/fmdb/match_pass_decode.py`).

## What the save holds

The game keeps a full event record for a limited set of matches: the human manager's three retained lists (the live readers call them own team, opponents and other, at human +0x188, +0x170 and +0x1A0). It writes those lists into `game_db.dat` inside the save. Each entry is one match and holds every event the match engine filed: passes, crosses, shots, tackles, duels, possession won and lost.

Measured on two saves of one career:

| Save written | Entries | Own team | Oldest entry | Entries with a stored statistics frame |
|---|---|---|---|---|
| 12 Nov 2026 | 32 | 5 (7 to 21 Dec 2030) | 14 Mar 2026 | 21 |
| 14 Nov 2026 | 36 | 5 (29 Dec 2030 to 12 Jan 2031) | 14 Mar 2026 | 25 |

The own-team list holds the last five matches. The other entries are matches of other teams, five or fewer per team; eleven of them are from 2026 and were still in the save whose latest match is 12 January 2031. An entry of a recent match also carries tracking paths (about 90 KB); an old entry has been trimmed to its events and pass-map tables (about 1.3 KB after the events).

## Layout

```
list    u16 entry count, entries
entry   u8 record present (1), u32 version (0x12), u32 event count, events,
        u32 shot count + 25-byte shots (home), the same (away), f32 half width, f32 half length,
        u32 clock, u32 clock, i32 clock (-1 without extra time),
        per side: u32 n + n*4 pass-pair counts, u32 n + n*11 position sums, u32 n + n*4 top pairs,
        u8, u32 n + n*(u8 id, u32 first clock, u32 samples, samples*(i16, i16)) tracking paths,
        u32 n + n bytes, u16,
        u16 day word (low 9 bits: day of the year from 1), u16 year, i32 owner team native id,
        u8 owner side (0 home, 1 away)
event   f32 x, f32 y, u16 0, u32 n, n*(f32 x, f32 y) path samples, u8 category, u8 actor slot,
        u8 side, u16 clock, u8 time to the linked event, u8 elapsed minute, u8 second,
        u16 flags, u8 linked actor slot (0xFF none), u32 event id, u16 end clock
```

The date, owner team and owner side follow the record they describe. The reader walks every entry from its first byte to the owner side and refuses an entry that does not parse whole.

Evidence. A memory capture of 13 December 2030 held fragments of 16 event vectors. Nine belong to matches the save of the following day holds: 2,460 of their 2,462 records are equal to the save byte for byte in every field. The other record, present twice in memory, has flags 0x407 in memory and 0x003 in the save; the reason is not established. Both saves parse with nothing left over between entries (32 and 36 entries).

## Players and the check against the game's counters

An event names a side and a player slot, not a person. The roster comes from the match's stored statistics frame in `match_stats_cfg.dat`, which the reader already decodes. `fm_get_saved_match_passes` with a `fixture_key` accepts a stream only when its owner team is the frame's team on the owner side and every stored player's passes attempted and completed equal the stream's counts for that side and slot. In the two saves every entry that has a frame closes: 21 of 21 and 25 of 25, between 32 and 46 players each. The entries from 2026 have no frame left in the save; select those by `match_date` and `owner_team_native_id`, and the rows carry a side and a slot with no person and no counter check.

Wolves v Newcastle of 12 January 2031, the last match played before the save of 14 November 2026: 515 attempts and 448 completed for Wolves, 517 and 450 for Newcastle, equal to the stored counters for all 40 players; 19 throw-ins.

## Row fields

`person_index`, `recipient_person_index` (completed passes), `outcome` (completed, intercepted, blocked, out_of_play, not_completed_other), `won_by_person_index`, `displayed_minute`, `second`, `origin_x/y`, `end_x/y` with `end_state`, `target_x/y` (not_completed_other only), `restart` (throw_in, corner, free_kick or null), `counted`, `key_pass`, `chance_created`, `assist_marked`, the native category and the flags word.

A throw-in has `counted` false: the game does not count it as a pass attempt. A failed pass has no stored intended recipient. The three markers are set by the game on some records only (see the flags section of `match_pass_decode.py`); `side_coverage` reports the markers found beside the stored key-pass and chances-created totals.

## Crosses and shots

`fm_get_saved_match_crosses` and `fm_get_saved_match_shots` read the same entries and take the same selectors as the pass tool. By `fixture_key` the entry is first bound as above, on every player's passes; the rows are then returned only when the cross or shot counters close as well.

Checked on the four saves of the career on disk on 14 November 2026 (written 12 Nov 17:09, 13 Nov 08:13, 13 Nov 21:20 and 14 Nov 10:49). Every entry that has a statistics frame closes on both: 21 of 21, 27 of 27, 26 of 26 and 25 of 25. The 11 entries from 2026 have no frame and are returned by date and owner team, with a side and a slot.

**Crosses** are the events of categories 12 to 17, the ones the live reader `retained_cross_events.py` takes. Each stored player's crosses attempted and completed (wire bytes 89 and 90) must equal the events of that side and slot, and the completed ones of category 12. In the 14 Nov save that holds for all 899 players of the 25 entries: 1,534 crosses, 253 completed. A completed cross stores its receiver's slot; no other cross does. The game's code names category 12 only. The reader names the others from where the stored ball path ends, measured on all 36 entries (2,159 crosses):

| Category | Named | The stored path ends |
|---|---|---|
| 13 | intercepted | at an opposing player's event, 162 of 162 |
| 14 | blocked | at an opposing category-54 event, 103 of 104 |
| 15 | not_completed_other | at no stored event, 1,463 of 1,463 |
| 16 | out_of_play | outside the pitch, 48 of 48 |

Pass categories 8, 9, 10 and 11 show the same four signs. Category 17 did not occur. All 419 crosses flagged as corners start at a corner flag.

**Shots.** A row is a shot-end event (category 1 goal, 2 missed target, 3 hit woodwork, 4 saved, 5 blocked). Each stored player's shots and shots on target (wire bytes 41 and 42) and both team totals must equal the events; goal and saved are the shots on target. That holds for all 899 players and 50 sides of the 25 entries: 628 shots, 263 on target. Expected goals and the shot type come from the entry's two shot vectors, one per side. A shot record is 25 bytes:

```
u32 event id, 8 zero bytes, f32 expected goals, u32 event id again, u32 clock of the event, u8 shot type
```

It is the stored form of the 48-byte record `live_retained_shots.py` reads from memory (expected goals, event id, shot type at +32, +36, +44). On the 972 records of the 36 entries the two ids are equal and the clock is the linked event's. The linked event is a shot-end event of the vector's side, or an own goal (category 49) by the other side; an own goal is not a shot and is returned in `own_goals`. Type 4 is on five shots, all taken from the penalty spot with expected goals between 0.77 and 0.87. Type 3 is on the 12 shots whose event carries the free-kick flag and on no other. Head and feet follow the live reader's type groups.

The stored expected-goals counters do not equal a plain sum of the record values. They equal the sum of each value rounded to 1/2^24, added in float32 in event order: 898 of 899 players and 49 of 50 sides, to the last bit. The record holds more digits than the counters add; the reason is not established. The one side that differs has a shot with no shot record: the home side's last event of a match between two other clubs that went to extra time (14 December 2030, fixture 140204, minute 122, a direct free kick off target). The stored counters include it at 0.0195; the row has `expected_goals` null and `side_coverage` reports `shots_without_a_shot_record` 1.

Wolves v Newcastle of 12 January 2031: 40 crosses and 5 completed for Wolves, 28 and 11 for Newcastle; 17 shots, 11 on target and 2.3618 expected goals for Wolves, 15, 4 and 1.7405 for Newcastle, all equal to the stored values; three goals in the rows for a 1-2 result.

## Limits

* The cross failure types rest on where the stored path ends, not on the game's code. `completed` is the game's own.
* Whether a shot record's type and expected goals equal the live 48-byte record field for field is unverified: no memory capture of a shot vector exists for a match these saves hold.
* The record exists only for the matches in the retained lists. Any other match has aggregate counters and no per-pass rows.
* Unverified against a live match: that a retained match in memory equals its entry in a save written afterwards for every event (compared so far on fragments captured the day before the save). `probe_live_pass_record.py` in the lane directory `fmdb-20261111/lane-passes/scripts` makes that comparison in one run.
* Which goal a side attacks is not decoded here; the live readers use flag 0x100 for that.
* The pass-pair tables, position sums and tracking paths in the entry are walked and not decoded.
* Entries of another record version are refused.
