# Current-match host observation persistence

`fm_get_current_match` accepts the strict Boolean `persist_host_observations`, default `true`. Set it to `false` to read the current match without creating the query's automatic host observation files.

```json
{
  "session_id": "the current attached session",
  "include_player_statistics": true,
  "persist_host_observations": false
}
```

The default preserves period and terminal-spatial observation capture, including the stores' context/index files. With `false`, the query skips terminal-spatial capture used only for persistence, process-epoch observation construction, both observation constructors and both stores. Both `host_period_capture` and `host_spatial_period_capture` report `{"state":"not_captured","reason":"disabled_by_request"}`. No storage directory or index is opened or created for those paths.

Fixture identity, team statistics, tactics, playback-scoped chance events, optional player passing and all 33 optional resident statistic fields keep their existing projections and source checks. Observation candidates are removed from the response in both modes. ReadSet verification, process/build/career checks, bounded retries and stream cleanup remain active. Unknown statistics remain null. The flag adds no native function execution, game-memory writes or game input.

The tool retains `readOnlyHint:false`, because the default capability can persist host files. This option applies to this current-match request; other tools retain their own existing defaults. It does not control interpreter bytecode, the MCP/adviser runtime's logs/session files, or other independently invoked tools.

Saved-byte and deterministic lifecycle tests cover Boolean validation before Bridge I/O, default/explicit-true parity, all combinations of existing projection flags, skipped storage/filesystem seams, genuine recorded 33-field projection, final callback drift, read errors and cancellation. These checks are private offline evidence; configured and ordinary acceptance remain the release owner's responsibility.
