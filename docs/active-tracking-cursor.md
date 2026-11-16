# Active tracking at a native playback cursor

`active_match_tracking.inspect_bound` reads the current GAME_MATCH-owned CBE and reconstructs official tracking means through one checked playback cursor. It uses the caller's playback context and actor binding. The caller verifies the final shared ReadSet and process/career epoch.

## Native time binding

Native `781e70..781e9c` passes the same `x20` tick to CBE event trimming (`48966f0`), tracking trimming (`48966e8`), possession trimming (`489668c`) and shot trimming (`4896740`). Tracking trimming calls `4891f94`. That function computes `floor(tick/24)*24+24`, subtracts each stream's native start tick, divides by24 and resizes its signed-int16-pair vector. Its retained sample points satisfy `start_tick+index*24<=tick`. The decoder follows that inclusive cutoff; it invents no seconds or minutes conversion.

The active source binds typed client, owned GAME_MATCH, canonical fixture identities and match unique ID. It reads CBE through GAME_MATCH `+14e98`. It reads only the position and possession byte prefixes selected by the captured cursor. Future entrants contribute no output actor row. Changing future coordinate or possession bytes cannot change the prefix projection.

`inspect_bound` reuses the existing active event/playback native domain guard. It then checks exact tracking consumer and native trim instruction spans. It retains the all-sample, in-possession and out-of-possession decoder's float32 arithmetic, unknown phase handling and zero-tail coverage caveat.

## Actor binding

The caller supplies `active_match_people.inspect_actor_bindings` from the same checked source. It must establish `validated_native_stored_slots` and the same official match unique ID. The tracking key remains `2*original_slot+side`; current tactical positions provide no substitute identity. Unresolved selected keys remain explicit in `unresolved_tracking_actors`. Resolved selected players remain available under partial coverage.

## Actual live control

A fresh read on6November2030 bound LOSC Lille858 against Newcastle United688 in the UEFA Champions League. The same317ms ReadSet captured and verified fixture ownership, playback, canonical actor rows and tracking prefixes. Playback was4559; each of22 named players contributed189 samples, ending at4536. Total selected samples were4,158. No position beyond the playback cutoff was read.

The verified buffered maximum was4631 while the engine frontier was4559. These are separate upper bounds. The tracking adapter requires the cursor to lie within each bound; requiring buffered maximum to precede the engine frontier would reject this real observation.

The raw positive control is `evidence/batches/active-tracking-cursor-170/combined-active.json` with its exact consumed bytes in `combined-readset.json`. The portable regression is `tests/fixtures/active_lille_tracking_cursor.json.gz`. Earlier moving observations failed ReadSet verification and remain failed candidates, not positive controls.

The pure projector leaves `online_positive_control_verified:false`: it cannot verify a caller's I/O. The outer capture may establish that claim only after its own ReadSet and epoch checks succeed. These source observations do not establish rendered pixels or distinguish live viewing from replay.
