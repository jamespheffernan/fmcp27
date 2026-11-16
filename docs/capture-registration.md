# Register a historical match export

Choose an existing export and register its SHA256. The catalog keeps a reference
to that original file; registration does not copy, edit or rename it.

```sh
shasum -a 256 "/absolute/path/selected.sqlite"
fm-capture register "/absolute/path/selected.sqlite" \
  --source-id my_selected_capture \
  --sha256 EXACT_SHA256_FROM_THE_COMMAND_ABOVE \
  --label "Selected historical match capture"
fm-capture list
```

The module command works with the package's Python installation too:
`python -m fm_live_mcp.captured_match_registry`. Source IDs use lowercase letters,
digits and underscores, beginning with a letter. Each ID and original path can
be registered once. To export and register one new scope in a single command,
add `--register-capture my_selected_capture` to
`python -m fm_live_mcp.export_live_matches ... --output /absolute/new.sqlite`.
Registration remains opt-in. If registration fails after export, the new original
stays at its output path and the command reports the failure.

Registration validates the expected hash, recognized export producer, career
identity, supported schema, fixture dates and IDs, SQLite integrity and foreign
keys. It stores the career, schema and fixture-scope pins in
`~/.local/share/fm-live/captured-match-sources.json`. This small catalog updates
atomically under a local lock. Neither capture files nor existing source IDs
are overwritten. The four built-in historical source IDs keep their original
checks.

`fm_list_captured_match_sources` reloads this explicit catalog without a server
restart. It returns source/capture/career IDs, capture save date, fixture date
coverage, tables and counts. `fm_query_captured_match_data` takes those IDs and
bounded selectors. Neither MCP tool accepts paths or SQL, attaches to the game,
scans Agent Outputs, or registers files. A modified, missing, journalled or
symlinked original becomes unavailable. Its new hash cannot bypass the original
registration. Keep registered originals in place.

Shot coverage remains per side. Unavailable counts stay NULL; a genuine captured
zero stays zero. Older exports keep absent detail tables and columns unavailable.
Registered detail exports expose supported location/body/outcome fields and field
coverage only when physically present. `source_observed_*` tables stay separate:
their counts and actors are verified while `native_expected_goals` remains
unreconciled. These rows never fill missing strict `shots` rows. Each response
identifies the historical capture; it does not label it as the current career
state or latest disk save.
