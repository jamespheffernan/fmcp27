# Explicit observed-prefix recording

Candidate capability; fresh positive recording has not yet been observed. The actual
candidate CLI attached read-only and returned `no_unique_native_viewable_client`
with `artifact_written=false`. Source checks are reused from installed fixed-prefix
passing/tracking readers. Unit controls establish orchestration, not a fresh live
positive.

Call `fm_record_current_match(session_id)` only when asked to record the current
observed match. This writes an immutable **host** SQLite and an explicit local
registry reference. It never changes Football Manager, creates a daemon, records
future observations automatically, reads a disk save or substitutes an old fixture.

The current increment preserves:

- Completed native pass events (`category7`, excluding unnamed mask8), with raw
  ended selection `start <= end < fixed_cursor`. Unknown actor names stay null.
- Canonical same-side original-slot identities only for event actors and players
  whose native tracking prefix is nonempty through the selected cursor.
- Native int16 tracking samples, orientation profile and phase byte prefix, plus
  official stored-sample average positions. Zero pairs and post-exit tails stay in
  the official denominator; neither minutes nor active XI can be inferred.
- Observed stop-info period markers, reread at the same fixed cutoff. Period labels
  on individual passes stay unknown in this increment.

Shots, score, full-match completeness, on-pitch membership and replay exclusion
remain explicitly unavailable. An empty `match_periods` table means unclassified,
not an absence of football periods. Raw tracking, native pass records and period
observations remain inside the original for offline reanalysis; the existing
observed reader exposes only its safe analytical tables. Spatial averages carry
raw native-axis semantics; physical units and pressing/marking claims are unproved.

## Storage and discovery

Set `FM_LIVE_OBSERVED_STORE` to an absolute host directory. Without it, the MCP tool
uses `/Volumes/4TB Private/Offloaded/FM Live Captures/observed-runs` only when that
approved external volume is mounted. An unavailable volume produces an error;
there is no silent main-drive bulk fallback.

Run the candidate normal CLI from its source environment:

```sh
python -m fm_live_mcp.observed_run_recorder \
  --store '/Volumes/4TB Private/Offloaded/FM Live Captures/observed-runs' \
  --register
```

Use `--pid PID` only if process discovery needs an explicit choice. The CLI attaches
its own session. The MCP uses an existing session and accepts no filesystem path.

The registry at `~/.local/share/fm-live/observed-match-runs.json` stores the exact
original path, SHA256, fixture tuple, career creation identity and semantic
selection ID. It never copies a capture or scans directories. After recording,
`fm_list_observed_match_runs` discovers the returned source ID and capture hash;
`fm_query_observed_match_run` reads it after game teardown. This remains a distinct
observed-run product, never a retained RESULT export.

## Identity and verification

Each capture verifies the loaded career/process epoch, native owner/fixture,
canonical actor selection, monotonic bound playback cursor, fixed ended pass
selection and exact used tracking prefix. Consumed period markers are reselected.
A changed owner, backwards seek during capture, changed used bytes or career load
rejects the capture before any artifact write.

The native source incarnation is hashed in memory from process/career epoch,
client/engine/CBE ownership and bound playback handle. No native pointers or source
addresses are persisted. Reused official fixture IDs do not join separate native
incarnations. Replay exclusion is **not proved**, even if these observations match.
The recorder never merges observations into a purported complete playthrough.
Changed selected content or cutoff produces a separate immutable source; unchanged
selection ignores observation time, later verification cursor and save-clock changes,
reusing the same original. Captures must not be described as continuous/background
coverage.

Publication uses a temporary SQLite, integrity/source readback, fsync and atomic
non-overwriting hard-link publication. Registry publication is separately locked
and atomic. If registry publication fails, the host artifact remains and the tool
returns its path/hash with `registered=false`; it does not claim discoverability.
Modified originals fail their query pins. Built-in approved source IDs are protected.

## Validation

`tests/test_observed_run_recorder.py` covers partial portable replay, existing-reader
interop, unchanged deduplication, distinct incarnations and changed semantics,
future-event/tracking rejection, absent/drifting source with no host artifact,
career/hash pins, protected IDs, changed analytical cells, and capture orchestration
with epoch rejection. These controls do not replace a fresh native positive.

The additive [generic tactical collection](observed-tactical-capture.md) candidate
preserves a separately verified optional settings sample for future runs; its
interpretation and unverified fresh-positive limit remain explicit.
