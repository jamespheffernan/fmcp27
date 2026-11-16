# Match stills MVP

[Enhance Mode](enhance-mode.md) runs everything on this page as one resumable job (`fm_enhance_goal`, `fm-enhance`). This page documents the steps underneath and the evidence contract; use the commands here to run a step by hand.

Turn a retained goal into a photorealistic action still and an imagined celebration. This is an agent-assisted feature: Python captures and packages evidence, Codex's built-in imagegen generates the images, and Python attaches them to a portable HTML gallery. No API key or game write is involved. Historical replay capture reuses existing guarded native readers and can wait briefly for a requested frame to enter the cache.

## Run

From the repo root, using its existing environment:

```bash
.venv/bin/python -m fm_live_mcp.match_stills list
.venv/bin/python -m fm_live_mcp.match_stills capture --match-key 138641 --out evidence/my-capture.json
```

`list` returns currently retained managed-team fixtures. Choose an exact `native_match_key`; do not reuse the example key in another career. The capture combines the existing retained-shot reader with `fmdb.tools.db_read`, then rechecks the fixture and career. This is a non-atomic read. It does not rebuild the SQL snapshot or resume its background fill.

Read the capture's `shots.attempts` and select an `event_id` with `outcome: goal`. The fixture, scorer and event must agree. Own goals are separate in the decoder and are not supported by this MVP.

```bash
.venv/bin/python -m fm_live_mcp.match_stills build \
  --capture evidence/my-capture.json --event-id 1454 \
  --references evidence/references.json \
  --out '/Users/jamesheffernan/Agent Outputs/2026-11-11 — My match stills'
```

The output directory must be new. Kit choices default to `Tko1` for both teams; override with `--home-kit Tko2` or `--away-kit Tko2`/`Tko3`. Playing away does not automatically select an away kit. Choices are explicitly unverified for the actual fixture. Competition, season and alternative-number kit variants are retained in the capture but excluded from the selected base design.

References are optional. Their paths resolve beside the manifest:

```json
[
  {"path":"colwill.png","role":"identity","person_native_id":28124573,
   "source_url":"https://www.chelseafc.com/en/teams/profile/levi-colwill",
   "credit":"Chelsea FC official portrait",
   "instruction":"Use face and build only; replace the clothing with the save's club kit."},
  {"path":"stadium.jpg","role":"stadium","stadium_native_id":688,
   "source_url":"https://www.newcastleunited.com/en/st-james-park",
   "credit":"Newcastle United stadium reference",
   "instruction":"Use architecture only; crowd and lighting are reconstructed."}
]
```

Identity and stadium reference IDs must match the selected scorer and venue. A `kit` role can supply a clothing reference; use its instruction to identify the team and describe any discrepancy with the stored definition. Source photographs are inputs, not redistributed source-code fixtures. Use references you are entitled to supply; this pipeline does not establish their licence.

In Codex, inspect the referenced local images, then call the built-in `image_gen.imagegen` using each generated `goal.request.json` and `celebration.request.json` object. This is the generation step; the gallery does not pretend to run imagegen in a web browser. Requests with no reference images omit `referenced_image_paths`. Read the packet's `visual-review.md` before generating. After generation, prepare a review for the exact candidate:

```bash
.venv/bin/python -m fm_live_mcp.match_stills review-template \
  --packet '/Users/jamesheffernan/Agent Outputs/2026-11-11 — My match stills' \
  --mode goal --image /absolute/path/to/generated-goal.png \
  --out evidence/goal-candidate-review.json
```

Inspect every visible player and complete the review JSON as described below. Attach only after it passes:

```bash
.venv/bin/python -m fm_live_mcp.match_stills attach \
  --packet '/Users/jamesheffernan/Agent Outputs/2026-11-11 — My match stills' \
  --mode goal --image /absolute/path/to/generated-goal.png \
  --review evidence/goal-candidate-review.json
```

Repeat with `--mode celebration`. Open `index.html`. It requires no server or network. A mode cannot be overwritten; create another packet for a new version. `scene.json` records the event, selected kits, reference hashes, capture hash and image/prompt hashes. It records attachment, not independent proof that the image model followed the prompt. `fm-match-stills` is also declared as a console entry point for the next package installation.

## Proportions and likeness review

Both goal and celebration prompts now require connected head, neck, clavicle,
shoulder and torso anatomy. Portraits supply identity; the action supplies head
orientation, expression and gaze. Face lighting, texture, sharpness and scale must
match the body at its camera depth. Use recorded height where available. Compare
proportions in the actual pose; crouching and foreshortening make a fixed head/body
ratio unreliable. The projection guide's head markers are schematic labels.

Before presenting a result, inspect the full frame and each visible figure at
original resolution. The generated `visual-review.md` contains the checklist.
Check the action phase before anatomy: use adjacent replay observations to
distinguish an arriving ball, contact and outgoing flight. A frame inside a goal
event can still show the incoming pass. Never pair that ball position with a
post-contact shooting pose. Record phase and direction in `positions_and_ball`;
leave the check unresolved when the sequence does not establish them.
Keep the immediate challenge clear, nearby recovering players gently softer,
distant players progressively softer and the crowd naturally defocused. Retain
the replay positions, kits, lettering and ID-bound likeness references during
corrections. A face edit must not erase a keeper's back-of-kit details. Unverified
numbers remain unverified even when visually convincing.

The template starts with every check pending. Set `reviewer`, `inspected_at` and
`verdict: "pass"` only after inspection. Give every replay entity a visibility
decision: `visible`, `occluded` or `out_of_frame`. Explain hidden rows; the roster
includes substitutes. For each visible player, complete all six `checks` with
`status: "pass"` and concrete `notes`. Only `identity_and_gaze` permits
`not_visible`, with a reason for an obscured face. A rear-facing player still
needs anatomy, lighting, kit and focus checks. Add any unidentified visible
figure with `person_id: null` and a unique name/location. Complete all five
`scene_checks`, including a census of every rendered player.

Reject a candidate if any figure fails. Repair the connected anatomy and inspect
all figures again, preserving accepted features. Save intermediate requests and
outputs. Update the mode's prompt file to the actual final request before making
a fresh review template. Do not reuse passing notes without inspecting the new
image. The user should see the selected result after this review; tool-native
image previews may still appear during generation.

`attach --review` refuses missing, incomplete, failed or stale reviews before
copying an image into the gallery. The review binds image bytes, prompt bytes and
scene evidence with hashes, and covers every known player. The gallery labels
legacy or modified images whose recorded review is missing or stale. These
checks enforce a review record; they cannot detect anatomy defects or prove
that a reviewer inspected the image. Tests establish gate behaviour, not visual
quality or biometric likeness.

## Evidence contract

| Input | Used now | Boundary |
| --- | --- | --- |
| Retained CBE attempt | Canonical scorer, side, goal outcome, head/feet, native XY and attacked-goal direction | Source-proven projection; raw clock is not a displayed minute |
| Pitch extent | Dimensionless location and a schematic | Does not establish metres or human left/right |
| Fixture | Home/away, date, competition, stored score, venue and kickoff | Stored score stays out of the action image |
| Club getters | `Tko1/2/3`, `Tkg1/2/3`, component colours, style and variant codes | Stored designs, not the actual match selection; style codes remain unmapped |
| Person getters | Height, hair colour/length and skin-colour example | Current save appearance, not a historical observation or a face mesh |
| Stadium reader | Name, capacity, pitch dimensions/type and facilities | Capacity is not attendance; current pitch condition is not match weather |
| Reference photographs | Player likeness and stadium architecture | Dated reference appearance; save club assignment takes precedence |
| Image generation | Pose, camera, crowd, defender/keeper positions, ball flight and celebration | Artistic reconstruction; spatial and likeness fidelity require visual review |

The normal current-match reader deliberately requires a current-career live-client binding. Historical replays use the separate `match_stills_replay` path below. It does not weaken the live reader's contract or substitute average positions.

Disk-save work can reuse `saved_goal_crossings.decode_frame` for scorer-validated goal-line endpoints, following `docs/research/goal-crossings.md`. Those are endpoints, not shot origins or complete body animation. The MVP does not claim to decode historical all-player poses, actual kit selection, attendance, match weather, facial meshes, exact shirt numbers or goal minutes from a save.

## Acceptance on 11 November 2026

Read live reader 0.164.0, career Cesar Jules–Newcastle at 10 December 2030. Captured Newcastle 4–2 PSG, 26 November 2030, match key 138641. Selected Levi Colwill's headed goal, event 1454, native PERSON 28124573. Native origin `(6.6383638382, 47.6179733276)` attacks positive Y, with pitch half-extents `(34, 52.5)`.

Generated goal and celebration images with Codex's built-in imagegen, an official Chelsea Colwill portrait and an official Newcastle stadium image. Both show Newcastle black/white, PSG blue/red, a green opposing keeper and floodlit St James' Park. Exact coordinate compliance, identities of surrounding players and the reconstructed celebration are not verified.

Canonical handoff: `/Users/jamesheffernan/Agent Outputs/2026-11-11 — Newcastle PSG match stills/`. Working evidence: `evidence/match-stills-20261111/`. Tests: `tests/test_match_stills.py`, plus existing retained outcome/source-projection and catalog checks. No reader service or adviser release was installed.

## Historical replay capture

Open the selected goal in FM's historical match review. Read its native start/end ticks from the retained capture. Capture while paused, or start the bounded wait before playing the goal:

```bash
.venv/bin/python -m fm_live_mcp.match_stills replay \
  --capture evidence/my-capture.json --event-id 1454 \
  --tick 15327 --wait-seconds 120 --out evidence/replay.json
```

This only reads an already-decoded frame in the six-slot replay cache. It never seeks the game, calls a game function, advances the career or writes memory. If the exact tick is absent, it fails rather than substituting another frame. Only one playback owner is supported. UI replay navigation is still performed by the user or agent.

The capture checks the replay GAME_MATCH statistics fixture against the canonical resident fixture catalog, ordered TEAM pointers, canonical scorer, event ID, shot type, native xG, origin, actor slot and start/end ticks. Opaque shot-record bytes can differ after replay reconstruction; both hashes are retained, and semantic field equality is required instead of whole-record equality. Native code guards establish event/playback clock and entity/ball coordinate routes. Frame bytes are read twice; metadata, save and process are rechecked. These checks are not an atomic snapshot.

Player entities join through native original roster slots and matching playback UIDs, never current formation slots. Each position is an exact local-time `1.0` endpoint. No interpolation is fabricated when that endpoint is missing. The entity census includes substitutes, and `inside_cbe_pitch_extents` is explicitly not an on-pitch verdict.

Use the frame when building the packet:

```bash
.venv/bin/python -m fm_live_mcp.match_stills build \
  --capture evidence/my-capture.json --event-id 1454 \
  --replay evidence/replay.json --references evidence/replay-references.json \
  --away-kit Tko3 --out '/Users/jamesheffernan/Agent Outputs/My replay still'
```

A replay screenshot reference has this additional manifest form:

```json
{"role":"replay", "path":"replay.png", "source_url":"fm-replay:138641/1454",
 "native_match_key":138641, "event_id":1454, "observed_cursor_tick":15327,
 "credit":"Local game replay", "instruction":"Use the visible kits and composition; remove UI."}
```

The screenshot must actually be observed at the described goal. The manifest is an agent observation, not an automatic screenshot-to-memory synchronization check. Bracket screenshots with matching native reads when possible. Keep the observed UI cursor separate from the exact cached frame tick and from the fixture's displayed goal minute. The packet rejects a different fixture, event, source, unpositioned scorer, or frame outside the goal interval and the one frame after it, which the game keeps with the ball in the net.

The image request includes named player XY and ball XYZ, and prioritises visible replay kits over generic club defaults. The gallery includes the source replay, a position plot, and the generated still. A goal frame does not establish celebration positions; the replay gallery only shows a celebration if one is separately generated and attached. Prompt files can be refined before generation; attachment hashes the actual prompt file and the gallery displays that file.

### Replay acceptance: Colwill versus PSG

Captured native ticks **15327** (goal start) and **15330** (goal end), with 37 canonically named player entities. At 15327 Colwill is `(6.6383638382, 47.6179733276)`, exactly matching the retained shot origin. Ball XYZ is `(3.7158892155, 46.9305877686, 3.4261789322)`. At 15330 it is `(2.3101205826, 54.5717010498, 1.2979452610)`. These are frame endpoints, not a decoded body animation or a continuous ball trajectory.

The shot is a **header**, native type **10**, **goal**, `LocationSixYardBox`, native UI xG **0.1099836528**. Left/right shooting foot remains undecoded; preferred-foot ratings are not used as a substitute. The shipped binary contains left/right foot animation interfaces, but their existence does not prove a shot-foot field or its mapping.

The screenshot confirms Newcastle stripes with cyan details, PSG **red shirts and shorts with blue/red socks**, and a green PSG goalkeeper. Stored PSG `Tko3` agrees with that colour scheme. This is visual match-kit evidence plus a matching stored definition, not a decoded selected-kit ID. The original MVP's default PSG blue kit was wrong for this replay.

An important discrepancy remains explicit: replay CBE half-extents `(34.3125, 50.3250)` differ from retained `(34, 52.5)`. They are not silently treated as interchangeable or used to filter the active XI. The plot uses the retained extents as a labelled schematic scale; raw player and ball positions remain unchanged.

The shot-start screenshot was bracketed by identical native frame hashes at tick 15327. The goal-ending screenshot was observed at cursor 15331 with numeric frame 15330; this adjacent-frame distinction is retained in the reference instruction. Image generation can still change fine geometry, facial likeness, lettering and kit details. Visual review remains required.

Canonical completed replay packet: `/Users/jamesheffernan/Agent Outputs/2026-11-11 — Colwill replay still/`. Working evidence: `evidence/match-stills-replay-20261111/`. Source-only implementation; no running reader or adviser was replaced.

## Editorial camera and player likeness

Add `--camera goal-line` to `build` to choose a low camera on the edge of the pitch: first a long lens from behind the play with the goal across the background, otherwise the attacked goal line or a touchline with the narrowest lens that holds the scorer, the ball and the middle of the goal ([how it is chosen](enhance-mode.md#camera-goal-and-numbers)). The option keeps its old name. The packet records camera origin, look-at point, field of view, projected anchors and the projected goal posts. Player XY and ball XYZ remain unchanged. Camera height, lens and player vertical poses are artistic choices. The optional `scripts/match_stills_camera_guide.py SCENE OUTPUT.png` draws a projection guide with matplotlib; the image model can still deviate from it. Enhance Mode draws the guide itself (`fm_live_mcp.match_stills_camera_guide`, through `uv` when matplotlib is not installed) and passes it as the last input image.

Resolve installed portraits using the exact canonical PERSON IDs of visible replay actors:

```bash
.venv/bin/python -m fm_live_mcp.match_stills faces \
  --replay evidence/replay.json --facepack '/path/to/installed/faces' \
  --person-id 28124573 --person-id 2000160511 --out evidence/faces.json
```

The resolver reads `config.xml` and requires an exact `graphics/pictures/person/ID/portrait` mapping. It records the mapping, config hash, portrait hash and replay name. Missing, duplicate, ambiguous and escaping paths fail explicitly. It does not infer identity from a filename or resemblance. The build accepts identity references for any uniquely identified replay actor and checks local portrait hashes. Facepack mappings establish which portrait the game uses; they cannot certify that the pack depicts the correct real person or their appearance in 2030.

The image tool accepts five input images per call. Use a target image plus at most four portraits for each correction pass. Preserve each request and intermediate output, then use the result as the next edit target. `build` rejects oversized manifests rather than silently dropping references. Facepack clothing must never replace the replay kit. A back-facing player should remain back-facing.

The completed editorial example at `/Users/jamesheffernan/Agent Outputs/2026-11-11 — Colwill editorial still/` uses seven ID-matched portraits: Colwill, Diomande, Mora, Pacho, Woltemade, Fabbian and Hakimi. Two correction passes improved visible likeness and corrected Fabbian's mistaken PSG kit. Pacho's face remains occluded. `face-references.json` and the generation-stage manifest retain the source joins and edit chain. Portraits are inputs, not proof of exact generated likeness; the gallery preserves this distinction alongside the native frame evidence.
