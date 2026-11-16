# Stored player-instruction provenance

`fm_get_managed_player_instructions` reads the active manager's existing working tactical payload. It never creates an edit session, invokes the native getter, changes a role or applies instructions.

Each picked phase assignment retains its canonical person, position and stored base role. The result separates:

- Position-record selected instruction bits for the current normalized role key.
- Per-person records under the existing exact-position and strict-IP lookup policies.
- Narrowly supported native role-rule selections.
- Effective match instructions, which remain unknown.

The native instruction getter4975820 looks up24-byte entries in the position record's vector at8. Each entry has a u64 normalized role key and u64 instruction bitset. Role keys use maskFFFBFFFFF91FFFFF. A clear bit in an existing entry differs from an absent current-role entry. The native missing-entry branch can insert data, so the reader reproduces only the stored lookup and never calls it. Unmapped high bits are preserved. Secondary16-byte shift records are bounded but their semantics remain undecoded.

Installed metadata39 names43 instruction IDs, including22`PI_GET_FORWARD_OFTEN` and23`PI_HOLD_POSITION`. The independent native ForwardRuns group contains22,0,23. Names are native enum symbols, not a claim about localized screen text. FM26 role-reference material was checked, but community role descriptions and local draft tactic specs were not used to decode these native choices.

The native group exporter52E718 returns an option when its stored bit is set **or** the native role rule4973360 returns state3. Exact IP D(R)/D(L) Wing-Back (stored word `0x400008`) and Full-Back (stored word `0x400004`) cases were evaluated with the unmodified native function in an isolated emulator using the exporter's real arguments. The role-rule decoder supports these exact cases only; it pins every executed native instruction and constant. Wing-Back yields3, while Full-Back yields0. Unknown positions, phases and role words stay unavailable. This describes a role-derived editor selection, not observed movement or match execution. The runtime has no emulator dependency.

## Positive capture and freshness

On native11 November2030, Alberto Costa was selected at D(R), IP Wing-Back and OOP Pressing Full-Back. El Hadji Malick Diouf was D(L) with the same base roles. Both personal maps were completely empty. Both fullback IP position records selected native options3,7,15;22and23 were clear. The supported native role rule nevertheless selected22. The precise answer for that captured working tactic is: **Get Forward Often comes from the stored role rule, not an explicit22bit or a personal override.** Applied match instructions remain unknown.

The later native14 November probe could not establish the picked-player/phase assignment boundary (`selection_boundary_unresolved`). It therefore could not authorize reading a creator as the picked XI’s instruction source. The public query returned unavailable and did not reuse the11November snapshot or substitute prepared tactics. A separate owned prepared-tactics control inspected66 phase records across three prepared4231 tactics; no positive stored22bit was found. Real3/7/15 selections and a separately labelled synthetic positive22bit were checked against the unmodified native getter offline. No synthetic bit was written to the game.

The working audit packet lives in `evidence/batches/personal-instruction-source-181/`. It includes the positive raw records and readset-qualified assignments, fresh source-unavailable API result, native option groups, role-case/code-span emulation receipt and opposite/positive bit controls. No game functions, UI actions or game writes were used.
