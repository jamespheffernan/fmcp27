# Manager-visible attributes

`fm_get_manager_visible_attributes(session_id, player_refs, fields=None, coach_name=None)` returns what the selected manager sees of ordinary players' attributes. It is read-only and separate from the default full-information tools.

## Result

Each requested player and field is exactly one of:

| State | Fields | Meaning |
| --- | --- | --- |
| `exact` | `value` | The manager sees the value (native H state 2). |
| `range` | `minimum`, `maximum` | The manager sees a scouting range (H state 1). The stored value lies inside it. |
| `unknown` | none | The manager sees nothing (H state 0). No attribute byte is read. |
| `unavailable` | `reason`, optional `detail` | An unsupported subject or a failed source check. Never a guess. |

`unavailable` reasons: `unsupported_record_kind_compact_or_generated`, `unsupported_all_actual_source_family`, `unavailable_source` (with the failed check in `detail`). The response also carries `scope`, `oracle_verified_scope`, `context_matches_oracle_verified_scope`, `firewall`, `cost` and per-player `state_counts`.

## How it is computed

The `knowledge_*` modules read game memory and evaluate the native PERSON_UI report selection, the H state (known, range or unknown) and the Range projection for the requested field. Four package overlays complete that source: `knowledge_used_range_overlay` (reciprocal used-length budget), `knowledge_club_info_overlay` (literal non-scout CLUB INFO kinds), `knowledge_relation_fixes` (no-stored-TEAM mask 0; special-country, association, next-fixture and game-team helpers replayed from the original ARM64 bytes in a read-only Unicorn VM) and `knowledge_structural_operand` (exact structural offer reads).

## Firewall

`knowledge_field_firewall` and the private journal bridge in `knowledge_manager_visible` enforce:

- Every primary record's stored attribute block (`primary+0x148` to `primary+0x18d`) is a forbidden interval, bound before any player is resolved.
- A hidden byte is read only as an exact one-byte region, only after `Journal.authorize` re-ran the approved source's native H state and found it 1 or 2. A caller-supplied state is never enough.
- Any journal error poisons the capture for good, even if a source maps the error to `unavailable`; the call is then rejected with no partial result.
- The private bridge refuses every helper operation except `probe`, `images` and `read-bytes`, and refuses profile decoding.
- Two complete physical fences re-read every distinct consumed region and compare it with its first read.
- The task port is segmented below both native helper limits, and a kernel process-incarnation token is checked around every port.

## Speed

The evidence collectors re-read every region on every call (5.1 million physical reads for 28 players and one field, of which 16,228 were distinct). The journal here reads each distinct region once and serves repeats from the journal; the forbidden-interval rule is rechecked whenever geometry is bound, so a repeated read can never reach a hidden byte. Inside the per-field loop the loaded-image answer and the process check use a cached image list and the kernel incarnation token instead of launching `ps` and the helper for each lifetime callback; the outer context checks before, after and at the end still use the ordinary process check. Measured on 8 December 2030 at 0.13 s per player-field: 28 players and one field about 4 s, six players and all 47 fields about 37 s.

## Verified scope and limits

Replayed against the original code: one coach and club (Cesar Jules, Newcastle United), 8 December 2030, 28 ordinary all_actual `PLAYER` and `PLAYER_STAFF` slots, all 47 fields. Not covered: perceived stars, CA/PA, completed report contents and freshness, the Manager search population, compact or generated people, other managers, clubs or dates (same code, unverified, flagged in the response).

The offline oracle is in the research lane (`codex/continuous-knowledge-20261109`, evidence `knowledge-*-20261109`): `collect_field.py` captures from the immutable 0.150 reader plus private providers, `check_recorded_field.py` replays each capture through the original ARM64 UI, H and Range code.

For hundreds or thousands of players, `knowledge_bulk` computes the same cells once per player instead of once per cell (`docs/knowledge-bulk.md`).
