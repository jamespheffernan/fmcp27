# Three stored midfield slot labels

Read-only mapping extends the existing native prepared-position decoder:

| Exact native mask | Stored position label | Meaning |
|---|---|---|
|128 / 0x80|DM(C)|Defensive midfield, centre|
|2098176 / 0x200400|M(CR)|Central midfield, centre-right|
|1049600 / 0x100400|M(CL)|Central midfield, centre-left|

These are exact position words, not arbitrary bitwise combinations or conclusions from a player's role. The same position formatter applies to both phase blocks. Names identify stored slots; roles remain independently decoded phase-qualified role words. They do not establish current player assignment, effective per-player overrides, or a formation label.

Native proof: `4927ED0..4927F28` supplies DM side arguments from bits20/21 and sets centre when neither exists. Thus exact128 has centre selected. `49282C8..4928348` tests the full composite masks0x100400 and0x200400 before selecting arguments2 and4, respectively. Centre is selected with central midfield bit10 and no side bits. Shared formatter `49292AC` stores argument2 inw27 andargument4 inw26; `492973C` branches onw26 to route `4929918` resource229446 R. The centre-left route tests argument2 before appending centre and left components: `49292F8` testsw27 then `4929334` selects229449 Centre/`49293AC`229448 C, followed `49295E0`229447 L. Therefore full masks yield CL or CR, not wide M(L)/M(R).

Official installed English resource labels:229437 DM,229440 M,229446 R,229447 L,229448 C (resourceSHA2563ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43). These are already accepted source dependencies of `prepared_tactics_fields`.

All current native byte pins were independently compared with the installed arm64 binary without executing game code. Receipt and extracted native routes: `evidence/batches/midfield-position-labels-147/native-pins.json` and `native-routes.asm` in the research checkout. Existing runtime pins already cover the exact mask tests and named components; no new address assumption is introduced.

Tests cover all three exact masks in both phases and keep unproved composites unknown. Focused prepared-position and role suite:402passed. Initial invocation from another checkout imported that checkout and failed the new mapping assertions; rerunning from the isolated worktree passed.
