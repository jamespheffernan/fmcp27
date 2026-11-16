# One coherent current playback frame

`fm_get_current_match_frame(session_id, person_native_id=None,
include_proximity=False)` returns a distinct instantaneous product. The existing
`fm_get_current_match_spatial` remains the recorded-sample average product.

The new tool selects an already cached frame at the initially observed playback
cursor and exposes its endpoint samples at **exact native local parameter1.0**.
It never chooses a nearest frame or nearest sample time, calls a native frame
getter, interpolates missing points, or falls back to a historical result.
Missing or multiple endpoint samples remain null. Absent client/playback/cache
or unique exact cursor frame returns unavailable with null player/ball data.

## Names and temporal scope

Default rows are canonical players independently recorded in a nonempty CBE
tracking prefix through this fixed tick. Source and client copies must agree on
their original side/slot/PERSON identity. A person selector without this evidence
has positions withheld. This admission policy establishes prior recorded
participation; it does not establish current on-pitch status, rendered visibility
or an active XI. Departed players can remain admitted, while unseen future
entrants and unexposed substitutes' identities are not returned.

The private census includes every typed player entity in the selected frame.
Official native entity classes separate players from non-player entities; three
unresolved player identities in the positive Forest controls remain explicit.
Canonical identity comes from the provider-owned source GAME_MATCH and a native
original-slot constructor. Canonical PERSON IDs are not assumed to equal
playback UIDs. Frame/setup/source-player UID and ordered canonical TEAM checks
must agree. The fixture and official match unique ID are rechecked.

## Coherence while the match advances

Capture anchors tickT and copies only the required native entity/ball samples,
setup identity fields and original-side bases. It reselects **that exact tick**
in the current cache and verifies the same consumed coordinate bytes, sample
parameters, runtime classes and UIDs. Buffer relocation is permitted; eviction,
backwards playback, changed fields or source relinking rejects the result.
Unconsumed appearance fields and unused cache extents are not misclassified as
immutable coordinate data.

Canonical actor metadata, current-day fixture/manager/client/engine ownership,
independently censored tracking prefix and process/career epoch receive separate
bookends. The complete world and actor ReadSets remain strict. The response
reports frame tick, observed and verification cursors, source ID and coverage.
This is an optimistic checked sequence, not an atomic game-memory snapshot or
proof of what pixels were displayed.

## Coordinates and optional separation

Raw player samples use native XY; the ball also retains height as native XYZ.
Exact named entity/ball world-transform routes prove that both sides and the ball
share the same native XY ground plane. Nine complete native spans and three
virtual routes guard this basis on every capture. Physical metres, human
left/right, forward direction and the displayed human minute remain unproved.

`include_proximity=True` requires one selected canonical person. It applies the
separate pure `frame_proximity.project_frame_proximity` helper at the exact1.0
endpoint. Ball separation ignores ball height. Every typed player entity,
including unnamed or unexposed entities, is considered for possible-opponent
uncertainty. A nearer hidden/unknown candidate or missing endpoint prevents an
unqualified nearest-opponent result. The population can include substitutes;
this is not nearest **on-pitch** opponent, possession, reception, marking,
pressure or a tactical assignment. Future/unexposed names remain withheld.

## Actual source controls

Two genuine same-epoch Forest captures resolved37of40 typed player entities at
frames6020 and6856, leaving three identities unknown and11non-player entities
separate. All frame/setup/entity bytes and triple UIDs were rechecked. These
controls did not infer participation from coordinates or player count.

The integrated source overlay then captured a moving default snapshot at
frame16508, revalidated at16509:40typed players,37canonical,3unresolved,
11non-players and24prior-recorded named rows in3.15seconds. A separate selected
Kobel snapshot at16519, revalidated at16520, completed in2.65seconds. Its ball
planar separation was68.0529867834native units; the closest admitted named
opponent in that typed census was Kalimuendo at53.8364794613native units. Both
responses explicitly leave on-pitch coverage and physical units unproved.
These are dated source controls, not an installation claim or seeded answers.

Working receipts: `evidence/batches/synchronized-spatial-180/` named mirrors,
`endpoint-overlay-default.json`, `endpoint-overlay-selected.json`; independent
world-space proof: `evidence/batches/current-frame-world-182/`. No game functions,
UI operations, saved-game fallback, game writes or public memory/file arguments
are used.
