# Resident stored manager plans

`resident_match_plans.inspect(read, base, engine, expected_team_indices=None)`
returns participating canonical TEAM identities and each side's currently
resident stored `GAME_MATCH_MANAGER` plan. The caller supplies a freshly checked
resident `GAME_MATCH`, owns the ReadSet and final process/load verification, and
independently binds any named fixture. No public tool is registered here.

Source closure checks the typed GAME_MATCH and GAME_MATCH_MANAGER objects, the
MATCH side pointers, canonical TEAM table membership at side+B8, every nonnull
player-manager MATCH/side reverse link, and both manager MATCH/side reverse links.
Null manager slots are counted without assuming an unused/on-field state. The
per-side manager must be unique, and the sides/teams distinct. Optional ordered
TEAM indices must match; team equality alone does not prove fixture identity.

Native MATCH_MANAGER::load_tactics at451F248..2A4 passes manager+1800 to the
engine tactic supplier. MATCH_PLAYER::setup_basic_tactical_positions at46FF604
consumes this manager's position rows at1920/1C40 and role words at1960/1C80.
Those agree with the existing checked prepared-creator phase layout at120/440,
relative to the embedded plan at1800. The same native producer applies the
accepted phase role masks. Exact instruction membership, mentality, role and
English-label guards from the existing decoders are verified for both sides;
pressing and trap names are not inferred from behaviour or the opponent name.

Fresh Nov2 active-process proof returns canonical TEAM545/native688 Newcastle:
`4231 FM27 Att`, Attacking; TEAM570/native713 Southampton: `4-3-3 DM Wide`,
Balanced. Southampton's stored options include Much Shorter Passing, Play Through
Press, Wider, Counter, Higher Defensive Line, Mid Block, Trigger Press More Often
and Trap Outside. These are **stored manager settings**, not a recommendation,
effective individual instructions, tactical success or proof of kickoff settings.

The first position array has Newcastle's back four/two DMs/three AMs/one striker;
Southampton's back four/one DM/two CMs/two wide AMs/one striker. The second
Southampton array has four midfielders across M(R/CR/CL/L) behind one striker.
Both arrays and their raw masks are retained. Do not infer individual player
presence or an exact match clock from these shapes.

The live proof checked20 Newcastle and26 Southampton player reverse links;
six extra Newcastle slots had null managers and remain unclassified. The engine
can advance ahead of the displayed clock. The result explicitly withholds actual
kickoff, display-clock alignment and exact fixture binding; a combined outer
adapter must add a separately verified fixture/clock policy. `content_sha256`
identifies returned content, not a globally unique fixture.

Working proof: isolated `evidence/batches/halftime-opening-plan-160/` files
`verified-resident-plan.json`, `active-current-tactic-arrays.json`,
`match-manager-load-tactics.asm` and `tactic-position-producer.asm`.
No UI, game functions, saved files, generated tactics or last-save substitutes.
