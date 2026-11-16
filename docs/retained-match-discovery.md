# Discover retained shot and pass fixtures

Call `fm_list_retained_match_data(session_id)` before choosing historical shot/pass queries. The default scope lists current retained entries for the managed team and its earliest observed next-opponent candidate. Each resolved row returns a canonical `fixture_ref`, native match key, named fixture summary and independently checked `shot_map`/`pass_network` states. Use the reference with `fm_get_retained_shot_map` or `fm_report_live_pass_network`.

Scopes are `managed`, `next_opponent`, `managed_and_next_opponent` and `team`. Explicit `team` scope requires `team_native_id`. Multiple active coaches require `coach_index` for managed/opponent selection. A same-day opponent remains a candidate because current time and match completion are not proved.

The reader inventories the four guarded HUMAN collections, then resolves their date/team entries with bounded bulk fixture lookups per team and year. It does not guess fixture keys or capture a whole league's players. Up to16 returned candidates are checked per page. Continue `next_offset` with `expected_source_inventory_id`; the pin includes query scope and source metadata. Fixture ordering uses dates and canonical team identities, independent of newly generated opaque references.

Source presence is a candidate, not verified availability. Shot and pass readers reuse the same exact epoch-stamped fixture packet, while their individual reconciliation rules remain separate. A match may have a verified pass network and only partial shot-map availability. Unmatched/ambiguous entries, null sources, missing resident years and incomplete searches remain explicit. Missing retention never becomes zero shots or zero passes. The tool does not load a replay or invoke game code, use a general save-file fallback, export automatically or schedule monitoring.

Current live validation on2030-11-02 found5 Newcastle and2 Southampton fixtures. Southampton's135904/136157 both have available pass networks;136157 retains partial shot coverage under the unchanged one-ULP xG guard. Explicit Manchester United scope found no retained source entries. These observations are capture-specific; no whole-career or perpetual retention promise follows.

The own-match HUMAN+188 insertion is natively capped at five entries under normal insertion. Other collections have distinct rules. Preserve checked analytical rows through the existing explicit export workflow before retention expires.
