# Playback entity index to canonical player identity

`active_match_entity_identity.inspect_bound` is a private, read-only adapter for
one **already resident exact cursor frame**. It executes no native frame getter.
A missing or ambiguous exact frame remains unavailable. This candidate has
portable positive/mismatch controls and a fresh checked unavailable observation;
it does not yet have an online named positive control.

## Proved native constructor

The official `match_entity_setup` layout signature at0xD67C names stride0x160,
kind+0, teamIndex+0x3A and uniqueID+0x3C. Named `get_entity_setup` at0x20C9C
calls primary interface virtual+0x28 ->0x734748, which copies the playback
+0x1DA8 vector. `0x738FF4` calls constructor0x73619C on playback+0x28 MATCH_INFO,
then installs its output in that vector.

Native0x741220 constructs MATCH_INFO by visiting GAME_MATCH side pointers
+0x15370/+0x15378 and each side's +0x140 original MATCH_PLAYER array. It derives
entity index from the signed side base at MATCH_INFO+0x1B (home) or+0x1C (away),
plus original roster slot. At0x741938..940 it calls0x741E3C with MATCH_PLAYER+8.
That routine copies input+0x40, hence MATCH_PLAYER+0x48, into the source entity
UID. Constructor0x73619C/0x736B4C preserves the entity index and copies this UID
to setup+0x3C; the ordered side is written to setup+0x3A.

The named `get_entities_info` at0x2212C dispatches primary virtual+0xB0 ->0x735624.
It enumerates frame entity indices through0x48B3128 and copies entity+8 as the
official `entity_info.uniqueId`. Its player-only branch calls virtual+0x10:
typed FRAME_PLAYER_DATA vtable0x56A07A0 returns1 at0x4AB20D0, whereas typed
FRAME_PERSON_DATA vtable0x56A0750 returns0 at0x4AB1F94. The adapter verifies both
RTTI classes and the getter links instead of labelling all51 observed entities
as players.

## Join contract and safeguards

The helper builds canonical identities from the **provider-owned source
GAME_MATCH**. A client engine and playback source can be separate copies of one
official match; an unbound current engine is never substituted. Both ordered source TEAM pointers must equal the bound client engine copies
and pass canonical TEAM table membership; each output row includes its
`team_native_id`. The existing
actor adapter checks typed MATCH_PLAYER ownership, PERSON table membership,
same-team roster, original slot and typed player-stat PERSON word. The new
helper reconstructs the entity index using the native side base, then requires
setup player kind, ordered side, setup UID, that MATCH_PLAYER's UID and typed
frame entity UID to agree. It retains canonical PERSON ID and playback UID as
separate fields. Their numeric namespaces are not equated.

Unmatched entities remain unresolved; duplicate actor/index identities, changed
native bindings, unknown runtime classes and invalid geometry reject the source.
Missing setup/cache and missing unique exact cursor frames return unavailable
with null player rows. Native guards cover14 field/constructor/consumer spans.
The helper does not claim active XI, on-pitch participation, nearest opponent,
metric units, rendered pixels or live-versus-replay. It captures no coordinates.

The caller must bind one current-day canonical fixture/client/engine and a
matching official playback cursor. It must verify its complete shared ReadSet
and unchanged process/career epoch after the capture. The adapter returns
`caller_readset_and_epoch_verification_required:true` and
`online_positive_control_verified:false`; a pure projection cannot certify I/O.
The capture script completes those bookends and preserves fixture, save,
official match ID, observed native cursor and an opaque epoch hash. Strict
changed-source rejection remains in place; moving playback may need a fresh
capture, and no reader checks are relaxed.

## Capture the next genuine observation

From the isolated worktree, use the canonical Python/helper and a new evidence
filename (the script refuses overwrite):

```sh
'/Volumes/4TB Private/Offloaded/FMCP 27/.venv/bin/python' scripts/capture_playback_entity_identity.py --helper '/Volumes/4TB Private/Offloaded/FMCP 27/build/fm_live_helper' --output '/Volumes/4TB Private/Offloaded/FMCP 27/evidence/batches/synchronized-spatial-180/next-genuine-play.json'
```

A fresh current-career read after playback closed returned checked unavailable
with zero resolved entities **and null player data**, not evidence of an empty
XI. It passed strict ReadSet and unchanged epoch checks. No game input was used
to reopen or pause a match.

## Existing capture audit

The two separately audited Forest traces at native cursors4795 and11730 retain
canonical actors and an official match ID. Neither recorded the side-base bytes,
playback setup header, frame-cache root or provider source-engine side ranges.
A byte-by-byte union within each individual trace still lacks those ranges.
No bytes were borrowed across traces or from current state. The structured
current-shape/scorecard packets and Lille actor/24-tick controls also do not
contain this complete new constructor/frame join. The earlier batch180 raw
frame sample capture retained sample coordinates but not the frame UID graph.
Therefore **no historical named actor is recovered by this new join**.

Working proof: `evidence/batches/synchronized-spatial-180/identity-native-proof.json`,
source disassemblies, `forest-range-audit.json`, and
`helper-capture-no-playback.json`. This is an isolated candidate, not an
installed or ordinary Pi capability claim.
