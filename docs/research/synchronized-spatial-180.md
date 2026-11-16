# Synchronized ball and entity positions: native source exists, named pressure metric not proved

The current playback frame source contains ball and entity position samples
under the same native frame tick. This is stronger evidence than the existing
retained CBE tracking means. It does not yet authorize a named nearest-defender
or receiver-pressure statistic.

## Previously established source

CBE +0xD0 contains player streams keyed by `2*original_slot+side`, with signed
int16 XY pairs at `start_tick+i*24`. The same native clock is used to trim CBE
events, tracking, phase bytes and shots. The phase byte stream identifies a side,
not ball coordinates or a possessing player. The proved 52-key player source
has no ball row. Zero pairs/post-exit tails are retained and cannot establish
on-pitch participation. The public spatial means are unsuitable as instantaneous
locations. Existing full retained tracking can align player sample ticks, but
ball availability is not thereby established.

## New direct native source

The named exported `get_ball_position` at 0x1FF74 dispatches virtual +0xB0 on
typed playback shim 0x54EC490. Its target 0x73DA58 loads the backing playback
owner and branches to 0x73B7CC. That consumer passes the requested native tick
into 0x48B4F8C using provider +0x38. It reads the reconstructed frame's ball
sample count at +0x100 and first XYZ floats at +0x120/+0x124/+0x128. It returns
zero when the native construction/count gate fails; a reader must preserve
validity rather than mistake that fallback for a ball at pitch centre.

The named `get_entity_world_transform` export 0x1FD5C dispatches virtual +0xA0,
target 0x73DA48 -> 0x73B8B8. This reads the same provider's cache through
0x781988, obtains entity records through 0x48B3128, and builds an interpolated
world transform. Frame +0x38 is the native tick; provider +0x220 owns six cached
frames of stride 0x420. The entity getter indexes the frame's pointer table by
signed entity index, bounded by frame +0x26. Each entity record has sample count
+0x10 and inline samples at +0x20, stride 0x20. The consumer reads XY at sample
+0/+4 and a local interpolation parameter at sample +0x10. Ball world-transform
consumer 0x73B4D8 reads ball samples with stride 0x40, XYZ at frame +0x120 and
local parameter at frame +0x140. Both world-transform consumers merge previous
and current frames and interpolate; simply taking one raw coordinate is not an
implementation of the displayed transform.

## Fresh passive control

On career date 11 November 2030/save427, strict same-readset capture found one
typed playback owner, official match ID 2341023333120 and populated cache. The
last complete sample capture had frame tick13649, 51 entity records/51 position
samples, and one ball sample. Every entity and the ball had local parameter1.0.
Ball raw XYZ was (3.3804218769,-48.0693778992,0.6999999881). These are raw native
coordinates, not a metric distance or a named football event. Earlier complete
captures contained multiple ball/entity subframe samples, confirming that a
frame tick alone does not always select a unique pair.

The inventory used the official typed playback capture without a viewable
client argument: its state is `present_client_unbound`. GAME_MATCH ownership and
same frame identity are verified; canonical current-day fixture/client binding,
rendered pixels and live-versus-replay remain unproved in this new capture.
No game function, UI operation, file-save fallback or game write was used.

## Exact remaining gates

Follow-up: the source constructor and fail-closed portable identity adapter are
now documented in `playback-entity-identity-180.md`. An online named positive
control remains pending; the coordinate/participation/reception gates below
remain separate.


1. Bind playback entity index to canonical PERSON, team and active participation
   at the selected tick. The 51 frame entities must not be assumed to be the
   existing CBE `2*slot+side` encoding; officials/non-player entities are possible
   and no classification is asserted here.
2. Reproduce native subframe selection/interpolation, its validity gate and the
   same coordinate transform for ball and every selected player. A local time
   alignment control exists, but physical units and common pitch axes must be
   proved before reporting metres.
3. Join a completed pass's canonical recipient and **reception/end tick** to the
   frame domain. Existing completed-pass recipient and native event clock do not
   themselves establish the exact moment of reception. No source equates the
   retained three-point pass path with a complete ball trajectory.
4. Retain prefix, fixture, actor and process/career revalidation while playback
   advances. A historical retained CBE source does not prove that its full
   playback frame stream remains resident.

No nearest defender, distance in metres, pressing intensity, marking assignment
or receiver-space value is reported. The useful next source is the native
playback entity-index constructor/identity getter and the frame interpolation
consumer, not more averages or correlations against event coordinates.

Working receipts: `evidence/batches/synchronized-spatial-180/` contains named
export/shim/frame disassemblies, plugin SHA, source scripts, two bounded raw
inventories and the strictly verified full-frame sample packet. No production
module or public interface changed.
