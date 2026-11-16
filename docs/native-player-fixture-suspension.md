# Native suspension predicate for an explicit fixture

`fm_get_player_bans(session_id, player_refs, fixture_ref=...)` optionally projects
the native ordinary mode0 suspension predicate on the selected resident fixture's
canonical stored competition and date. Omitting the option preserves the existing
stored-record response. This is a current-source projection for a future fixture:
the result assumes the currently recorded bans remain unchanged.

The checked result is `players[].fixture_suspension.native_suspended`. `false`
means this supported suspension path does not trigger on those explicit inputs.
It does not establish registration, medical clearance, legal clearance or overall
fixture eligibility. `null` includes unsupported ban kinds, multiple records,
unproved runtime/exemption gates, combined player/staff sources and players whose
current canonical TEAM is outside the fixture participants. Virtual references
remain outside this query's accepted inputs.

## Native meaning and scope

The official outer availability consumer at `1F8E80C..83C` dispatches
`GAME_ACTUAL_PLAYER` virtual `+230`, whose current method is `1F8AF7C`. A true
result yields native reason5. The reason converter `14E3400`, using jump-table
entry `5397FDC`, maps reason5 to status byte1. The status renderer at
`2094C08..5C` selects English keys661664/661665, “Sus”/“Suspended”. These are
source relationships; this query never executes that consumer or reads a final
resident availability result.

The public option supplies explicit canonical fixture COMP/date inputs to the
named `1F8AF7C` predicate. The outer consumer obtains its COMP through a separate
UI-manager `+1D0` lookup; the current override `2E88B4C` contains a foreign-thread
TLV branch. That whole outer lookup remains unprojected. No equivalence between
this lookup and the stored fixture-name COMP is claimed.

The supported path is:

1. Rebind the exact fixture inventory, bucket route, slot, object identity,
   canonical competition and source date. Require an unplayed FIXTURE whose
   virtual `+108` is the pinned literal-false method `3D030D8`. Native code then
   skips the global parallel PLAYER/runtime queue.
2. Require a canonical ordinary PLAYER currently belonging to one of the two
   fixture TEAMs. Native `1F8B078..90` returns false for absent secondary or a
   checked empty personal list before reading COMP runtime gates. Those two
   source states remain distinct in the output.
3. For a nonempty source, support one kind1 record with negative finite-duration
   field. Check the exact current competition runtime, native season and normal
   activation branch. Unsupported gates remain unknown.
4. Reconstruct `3CC6904`: native start-date comparison; signed rule index `+14`
   into the typed discipline manager; current/default phase rules; shared-group
   phase carryover; explicit phase selector; then kind1 scope comparisons against
   runtime `+138`, scope COMP runtime `+B0`, and fallback runtime `+7C8→+138`.
5. After an applicable inner result, reconstruct the ordinary domestic false
   branch of `4060580→108F88`. Special national/exemption routes remain unknown.
   A supported applicable record then returns true from `1F8B354..64`.

The native supported mode0 path does **not** read stored total/served counters as
an activation gate. A positive stored balance is not sufficient proof; a zero
balance must not be invented as an exemption. Native date comparisons do use
the record's stored start date. Negative duration skips finite-expiry arithmetic
and cleanup. No historical kickoff state or future ban changes are reconstructed.

## Genuine positive and negative controls

Fresh read-only PID3505, Cesar Jules–Newcastle save428, current and last saved
13November2030:

| Player and source | Exact fixture inputs | Native predicate |
| --- | --- | --- |
| El Hadji Malick Diouf, PERSON2000262615; sole kind1 record, Cup COMP662/native1301427, rule136, selector255, start29October2030, duration−1 | Manchester City–Newcastle,23November2030, PL COMP7/native11; phase0, no carryover phase, all three scope comparisons false | false |
| Same unchanged record, stored balance1 | Bournemouth–Newcastle,18December2030, Carabao Cup Quarter Final COMP662/native1301427; phase4, direct scope and scope runtime match | true |

The cup fixture is a genuine bounded positive control found with the explicit
18December selector; this search does not establish the earliest future cup game.
Across the current28-slot managed roster, the City request returned25 false,
zero true and3 unknown. Trevan Sanusi, Leo Shahar and Matthew Cox had current
TEAMs outside the fixture participants and stayed unknown.

The fresh candidate stdio receipt verifies default-output parity, both Diouf
controls and invalid fixture rejection. It proves the isolated source candidate,
not installation. The tracked freeze is
[`source-proofs/player-fixture-suspension-native-127.json`](source-proofs/player-fixture-suspension-native-127.json).
Working captures and repeatable extraction/probe scripts are in
`evidence/batches/fixture-ban-applicability-127/` in the source worktree.

Tests cover shared-group carryover, fallback COMP acceptance, phase mismatch,
before-start false, unsupported kinds/gates, balance independence, empty versus
absent source, outside TEAM, native-code drift, invalid/changed references and
late fixture-source drift. The final ReadSet verifies every consumed byte and
the process/save before publishing the complete batch. No game function, UI
getter, simulation, cleanup, game write or disk-save fallback is used.
