---
name: fm-create-tactic
description: Create a complete native tactic with both phase layouts, roles, team selections and player instructions. Use for importable FMF files, translating a whole football plan, changing a formation or saving a tactic to FM27.
---

# Create a native tactic

## Establish the whole plan

Use `fm-tactical-analysis` for the football reasoning, then turn the agreed plan into an actual file when requested. Preserve the intended width, runs, cover and transition responses. File creation does not select a lineup or control the running game.

Account for eleven positions and roles in each phase. A role in Football Manager 27 has no duty. Each player has one role in possession and one role out of possession, and that is all the game shows. Never write a role with Defend, Support or Attack after it. Keep native slot indices separate from named-player recommendations: a tactic record does not assign that player. Distinguish explicit selections, a clean instruction basis and deliberate inheritance. Complete this step when every requested part has an encoding decision; an old donor limitation is not a reason to ask for manual role edits when native authoring supports the plan.

Before finalizing an exact file-compatible role table, check the intended phase and actual position against the native legal roles. A global role label does not establish that the role is legal at that position. If the plan changes layouts, preview the complete intended layouts and roles before presenting that exact plan: the source catalog describes its current positions. Conceptual football advice can remain conceptual without manufacturing a file.

## Discover current native choices and inspect a source

Read the current `fm_tactic_file` schema. Call `authoring_catalog` for source-backed position names, the roles of each phase, player-instruction `metadata_name` values and native English team selections. When a position has no compiled English name, use its joined `metadata_mask_components` name. These are exact names, not inferred UI synonyms. Call `list_templates` and `inspect` a source archive; retain its path, SHA256, source format and decoded setup. Filenames do not establish formations.

Call `authoring_catalog` with `template_path` when the legal roles at the source's current positions would help: each entry of `legal_roles_for_current_positions` lists that position's `legal_roles` by name. Those roles describe that layout. A changed layout still needs the native validation performed by preview/generation. Supported source26/27 files retain their format; the tool also requires a canonical complete native serialization. If a source refuses that check, inspect another suitable supported source and build the requested layouts through the native pipeline. Never patch a version byte or invent a role word.

### Inspect stored player instructions

A template-bound `authoring_catalog` also returns `template_instruction_inspection`; the global catalog returns null there. Its22 `current_role_profiles` report the normalized current-role key, `entry_present`, `stored_bits`, selected IDs/names and unclassified bits43–63. An absent profile stays absent; it is not an inserted default. Inactive role profiles are not merged into the current selection, and unknown high bits remain unknown.

Each profile has42 `native_editor_availability` rows:924 across both phases. Keep `native_available` separate from raw `native_state` values0–3. In particular, states2/3 are not decoded as mandatory/on, and availability is not a stored selection, a visible FM27 UI choice or an effective instruction. Give manual advice through the user's actual roles and PI controls, preserving their reported UI limits.

Retain `phase_correspondence` as the source's stored/forward/inverse map, not a named lineup. `specific_player_target` is a context-relative raw byte/signed index with no canonical PERSON binding. Target objects are null when their current PI34/35 bit is clear; nonzero inactive payload bytes are not active targets. `specific_position_target` preserves the raw mask, whether its encoding is known and whether the mask is in the target domain for new authoring. A mask in that domain still requires valid phase and actor availability for a new request. Inherited GK or unknown encodings do not become newly authorable targets. Inspection verifies unchanged full native serialization and creator bytes; it does not reconstruct effective match instructions.

A full template catalog can exceed Code Mode’s262144-character per-value store limit. Keep it in a local variable and project the source path/hash, requested slots’ legal roles and needed inspection fields before calling `store`. Stored choices remain bound to that source layout and hash. After storing the parsed `inspect` result as `inspectedTemplate`, this example retains only out-of-possession slot5:

```javascript
const s = load("inspectedTemplate");
const c = JSON.parse(await tools.fm_tactic_file({action:"authoring_catalog", template_path:s.template_path, template_sha256:s.template_sha256}));
const phase = "out_of_possession", position_index = 5;
const legal = c.legal_roles_for_current_positions.find(r => r.phase === phase && r.position_index === position_index);
const i = c.template_instruction_inspection;
const p = i.current_role_profiles.find(p => p.phase === phase && p.position_index === position_index);
if (!legal || !p) throw new Error("Requested source slot is absent");
const compact = {template_path:c.template_path, template_sha256:c.template_sha256,
  authoring_runtime:c.authoring_runtime ?? null,
  position_name:legal.position_name, position_mask:legal.position_mask,
  legal_roles:legal.legal_roles,
  phase_correspondence:i.phase_correspondence,
  phase:p.phase, position_index:p.position_index, entry_present:p.entry_present,
  current_role_key:p.current_role_key, stored_bits:p.stored_bits,
  selected:p.selected_metadata_names, high_bits:p.unclassified_stored_bits,
  availability:p.native_editor_availability.filter(a => [28,35].includes(a.native_option)),
  specific_player_target:p.specific_player_target, specific_position_target:p.specific_position_target};
store("nativeCatalog", compact);
text(compact);
```

Complete when the source is pinned and every requested position, role and named selection comes from the current catalog. The whole-plan pipeline does not require a donor fingerprint.

## Build one native authoring request

Use `generate` with `native_authoring` for a whole plan. Put its mutually dependent changes in one request so a refusal cannot leave a partly written tactic.

- Set `positions` to a complete eleven-name array for each phase that changes: `in_possession` and/or `out_of_possession`. Put the goalkeeper at index0 and use eleven distinct canonical native masks. Different aliases for the same mask still conflict. Layout edits target the explicit phase records under the fixed `preserve_existing_player_correspondence` policy: retain the source cross-phase player identity map, verified by original native forward/inverse accessors and reload. Creating or rebinding that correspondence is unavailable. An omitted phase inherits its layout.
- Set `roles` to `{phase, position_index, role}` entries: the role's exact name and nothing else. For a whole plan, explicitly supply all22 phase/index pairs, including intended retained roles. Indices run0–10 within each phase. Use a catalogued role that the native phase/position checks accept; the writer finds the one stored word the game accepts for that role at that position. Duplicate slots, unsupported names, a role the game does not offer at that position and normalization that changes the requested role refuse the operation. Omitted slots otherwise inherit, subject to original native position/role reconciliation.
- Set `team_instructions` to the complete desired list of explicit native English selections. This replaces the entire stored team selection; `[]` clears all explicit team choices. Omission inherits them. For a clean Positive/Mid Block/Regroup/Counter plan, set top-level `mentality: "Positive"` and include only `Counter`, `Mid Block` and `Regroup` in this list. Width, tempo or passing described as Standard/default add no explicit selection; they must not silently retain unrelated source bits. `No explicit selection` is not a list item.
- Choose `instruction_policy`. Use `native_defaults` when the plan calls for a clean current-role instruction basis: the original native reset clears optional stored selections for the current role across all22 phase records before explicit player instructions. Use `preserve`, the default, for deliberate inheritance except changes made by native reconciliation. Inactive role profiles remain unless that reconciliation changes them. A reset is not proof of effective defaults, mandatory selections, player overrides or applied match behavior.
- Add `player_instructions` only for explicit optional selections. Each `{phase, position_index, instructions}` row completely replaces that slot's current-role selection using exact `PI_*` metadata enum names. An empty `instructions` array clears Boolean selections; a supplied typed marking target still adds PI35. Omitted rows follow `instruction_policy`. Native availability and the exact post-setter selection must match; two individually available choices can still conflict or couple. Preserve the returned availability scope rather than translating an unclassified editor state into a mandatory/on instruction.

`PI_SWITCH_POSITION` (28) is an ordinary Boolean selection in `instructions`, subject to the original native availability check. It supplies no partner target and does not rebind the stored phase/player correspondence. `PI_NONE` is a sentinel; use an empty list to clear selections.

For specific-position marking, add `mark_specific_position` to an out-of-possession player-instruction row, for example `"mark_specific_position": "D(C)"`. Choose one of the25 canonical non-GK catalog targets; use its joined metadata-mask name only when the position has no compiled English name. Keep `instructions` present, even when it is `[]`. The typed field automatically adds native PI35, selects position-target mode and clears active specific-player target mode; do not also put `PI_MARK_SPECIFIC_POSITION` in the Boolean list. The tool checks actor-record native availability, the selected bit, the original target accessor and serialized reload. Those25 targets match the masks emitted by the original compiled PI35 menu builder. GK is accepted by the separate low-level storage codec but is absent from that menu source and is excluded from authoring. This is compiled-source proof; live-rendered UI observation remains unverified. It changes the marking target, not the player's own position or the stored cross-phase correspondence.

To remove active specific-position marking, send a replacement row with `instructions: []` and omit `mark_specific_position`. This supplies the menu's None behavior; `"None"` and numeric zero are not explicit target values. Stored inactive target bytes may remain, but the original target getter reports no active position target when PI35 is clear. Omitting the entire row follows `instruction_policy` instead and may preserve an existing selection. Keep those two omissions distinct.

Top-level `mentality` remains separate and may combine with native authoring. `PI_MARK_SPECIFIC_PLAYER` (34) still needs a person binding the API does not supply. Team instruction `Distribute To Specific Team-Mate` also needs a recipient binding and remains withheld. Explain these precise gaps if requested. Other named roles, legal layouts and admitted instructions should be attempted through the native pipeline rather than delegated to manual fixes.

Complete when the request accounts for both phase layouts, all22 intended roles, the full team selection and the current-role instruction policy. Compare any remaining inheritance with the football plan before creating the file.

## Preserve legacy calls when appropriate

The existing `base_role`, `phase_position` and `stored_role_instructions` donor branches remain available for their exact schema cases. Inspect source and donor, check eligibility and retain both SHA256 pins. A donor name alone is not provenance. Keep those calls separate from `native_authoring`; they cannot combine.

Legacy scalar team controls remain available for small edits, including mentality, tackling, defensive line, tempo, passing, width, pressing, goal kicks, crossing, final-third delivery, focus, wide support and transition responses. Omission inherits that control. `No explicit selection`, or `[]` for a list control, clears its stored selection without proving an effective default. Read exact enums and conflicts from the schema.

Scalar team-selection fields may combine with `native_authoring` only when its complete `team_instructions` field is absent. Use the complete list for a clean whole plan so leftover source selections are accounted for. Mentality may combine with that list. Compatibility does not change the distinction between inherited settings and changes actually encoded.

## Handle exact request refusals

For the exact registered request contract, call `fm_tactic_file` with only `{"action":"schema"}`. This works even when `describeTool("fm_tactic_file")` renders `args: unknown`. Parse its `registered_parameters` JSON schema and retain `schema_sha256`; they describe the same immutable parameters object supplied at that registration. For example, inspect `registered_parameters.properties.native_authoring.properties.player_instructions.items` for the complete strict row contract and typed marking targets. The schema action does not inspect a template or run the native backend. Other inspection/catalog results keep their compact fingerprint/capabilities instead of repeating the full schema. An older session that rejects this new action still has unknown discovery capability; its current guide cannot supply a missing registered contract.

Inspect `authoring_runtime` on `inspect` or `authoring_catalog` before relying on a newly documented field. Its `registered.schema_sha256` fingerprints the exact parameters object supplied at tool registration, and `registered.capabilities` describes that object's typed marking field. Registration/current package, adapter, backend and guide hashes are explicitly filesystem observations, not proof of executed JS or loaded Python code. Adapter drift refuses generation with both observed versions and the registered schema hash; inspection remains available for diagnosis. Retain these compact runtime fields alongside the source pin when investigating a mismatch.

After a game update the writer runs the installed build's own tactic code through the reader's address map. `list_templates` reports it under `native_build`: `state` (`pinned`, `mapped`, or `unsupported` with the command that maps the build) and `unavailable_functions`, the writer functions whose game code changed on that build without a review. A refusal that names the game build and one of those functions affects only that edit: on 27.0.1 the legacy scalar team controls (crossing, final-third delivery, focus, wide support, goal kicks, pressing block, possession loss and gain) and the donor-based role edits refuse, while `native_authoring` (positions, roles, team instructions, player instructions) works. Express those team choices in `native_authoring.team_instructions` instead; do not drop them from the plan.

An existing session without `authoring_runtime` has unknown registration freshness; that alone does not invalidate an otherwise legal request. If a required requested field such as `mark_specific_position` is absent from the actual schema or is rejected as unknown, stop that requested generation and report the field/schema mismatch. Current guide or backend files cannot establish that the session registered the field. Preserve the exact requested roles and PI target; replacing specific-position marking with tighter marking is a changed plan, not a fix. A new isolated Pi context can verify current capabilities. Existing user sessions remain untouched; capability metadata cannot retrofit their cached tool definitions.

A role validation refusal may carry `details.diagnostic`, also preserved in the structured JSON error content. Report its exact `phase`, `position_index`, actual position, requested role and `rejection_reason`. Use the `legal_roles` list to explain the native alternatives at that position. Invalid phase/index diagnostics instead provide their valid domains. Keep `automatic_substitution_applied: false` explicit; the failed operation did not replace the requested role or produce a successful file.

A different legal role is a revised football decision. State the change and its trade-off, then preview the revised plan before continuing. Never present that revision as a match for the original exact request. Native/source failures without a validation diagnostic remain fatal source or execution failures; they do not establish alternative legal choices.

## Preview and write the actual file

For a complex plan, call `generate` with `preview: true`, the inspected source path/SHA256, name and complete agreed edits. A successful preview creates no file or receipt. Check both resulting phase layouts, all22 roles, the exact team selections, requested player instructions and reset/inherit modes. Check the complete native serialization/reload results. Resolve a concrete mismatch before writing; a preview alone does not fulfil a request for a file.

Then call `generate` with the same pinned source and agreed edits to create the actual archive. Default output is the canonical Agent Outputs destination. When asked to save directly to FM27, use `fm27_folder: true`; the writer derives a safe new name and receipt in its Tactics directory. Supply `tactics_directory` only for an explicitly supplied existing custom directory. This places a file for import and does not import or activate it.

When both a canonical original and a Tactics copy are requested, create and verify the Agent Outputs original first, then the same named plan at the requested Tactics destination. Check returned output hashes before describing them as identical copies. Each destination needs its own successful receipt. Never overwrite an existing source, output or receipt.

A source-hash change requires fresh inspection and reassessment before retrying. A collision requires a fresh safe name or a report of the existing-file refusal. Use the native tactic writer for `.fmf`; a JSON draft or text-writer output is not a tactic archive.

## Deliver the verified result

Read the actual success result and receipt, not just the requested arguments. Lead with the created file and link its exact absolute path and receipt. Report the encoded layouts, roles, complete team selections and player-instruction policy, then any material inherited or unsupported part. Preserve source/donor hashes and native authoring source pins in provenance.

Original native creator/serializer execution and complete reload establish the returned structural checks. They do not establish full UI parity, game import, lineup assignment, effective instructions or match outcomes. Retained thumbnails may be recompressed while preserving their decoded content. Keep those limits beside the corresponding claims without turning a supported whole-plan request into manual instructions.

Completion means the requested actual archive exists with a successful receipt and every requested plan element is checked against readback. A requested preview is explicitly labelled as a preview. Advice, an inherited setting and an encoded change remain distinct.
