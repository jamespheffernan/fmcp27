import { execFile } from 'node:child_process';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath } from 'node:url';
import { captureRegistration, requireMatchingRegistration, runtimeInfo, snapshotParameters } from './fm-tactic-runtime.mjs';

export const TACTIC_TOOL = 'fm_tactic_file';
const LEGACY_DONOR_EDITS = ['base_role', 'phase_position', 'stored_role_instructions'];
const TEAM_SELECTION_FIELDS = ['team_tackling', 'defensive_line', 'tempo', 'passing_directness', 'team_width',
  'pressing_frequency', 'goal_kick_length', 'crossing_style', 'final_third_delivery', 'pressing_block',
  'focus_play', 'wide_support', 'possession_loss', 'possession_gain'];
const POSITION_MARK_TARGETS = ["D(R)", "D(CR)", "D(C)", "D(CL)", "D(L)", "WB(R)", "DM(CR)", "DM(C)", "DM(CL)", "WB(L)", "M(R)", "M(CR)", "MidfielderCentre", "M(CL)", "M(L)", "AM(R)", "AM(CR)", "AM(C)", "AM(CL)", "AM(L)", "AttackerRight", "ST(CR)", "ST(C)", "ST(CL)", "AttackerLeft"];
const codecRoot = process.env.PI_FM_TACTIC_CODEC_ROOT || '/Users/jamesheffernan/GitHub/FM26 Deepener';

function tacticFailure(stderr, code) {
  const message = stderr.trim() || `Tactic writer exited ${code}`;
  const error = new Error(message);
  // Only the trusted outer CLI's normal rejection envelope can carry a
  // diagnostic. Transport failures and ordinary text errors remain fatal.
  if (code !== 1) return error;
  let packet;
  try { packet = JSON.parse(message); } catch { return error; }
  if (packet && !Array.isArray(packet) && typeof packet.error === 'string' &&
      packet.diagnostic && typeof packet.diagnostic === 'object' && !Array.isArray(packet.diagnostic)) {
    error.message = packet.error;
    error.diagnostic = packet.diagnostic;
  }
  return error;
}

export async function runTacticFile(params, signal) {
  // Fail serialization before owning a child that could wait forever for EOF.
  const input = JSON.stringify(params);
  const python = process.env.PI_FM_TACTIC_PYTHON || `${codecRoot}/.venv/bin/python`;
  let child;
  const completed = new Promise(resolve => {
    child = execFile(python, [fileURLToPath(new URL('./fm-tactic-files.py', import.meta.url))],
      { timeout: 60_000, maxBuffer: 1_048_576, encoding: 'utf8', signal }, (error, stdout, stderr) => {
        resolve({ error, stdout, stderr });
      });
  });
  if (!child) await completed; // Preserve synchronous execFile argument errors.
  let stoppedForInput = false;
  let inputError;
  const failInput = error => {
    inputError ??= error;
    // A failed write cannot produce a trustworthy result. Reap only this
    // owned child, even if it ignores SIGTERM; retain the stdin error listener.
    if (!child.killed && child.exitCode === null && child.signalCode === null && child.pid) {
      stoppedForInput = child.kill('SIGKILL');
    }
  };
  child.stdin?.on('error', failInput);
  const sent = pipeline(Readable.from([input ?? '']), child.stdin, { signal }).catch(failInput);
  const [{ error, stdout, stderr }] = await Promise.all([completed, sent]);
  // Spawn, abort and buffer errors keep their authoritative callback identity;
  // a timeout/signal not caused by input cleanup does too.
  if (error && (typeof error.code === 'string' || ((error.killed || error.signal) && !stoppedForInput))) throw error;
  if (inputError) throw inputError;
  if (error) throw tacticFailure(stderr, error.code);
  return JSON.parse(stdout);
}

// A role edit is {phase, position_index, role}. Requests written for the earlier interface also
// carried `duty`; that field no longer exists. It is dropped before schema validation and
// before the backend runs, so such a request still works: it selects nothing and is never echoed.
export function dropLegacyRoleFields(params) {
  const roles = params?.native_authoring?.roles;
  const legacy = row => row && typeof row === 'object' && !Array.isArray(row) && 'duty' in row;
  if (!Array.isArray(roles) || !roles.some(legacy)) return params;
  return { ...params, native_authoring: { ...params.native_authoring,
    roles: roles.map(row => {
      if (!legacy(row)) return row;
      const { duty: _dropped, ...rest } = row;
      return rest;
    }) } };
}

export function registerTacticFileTool(pi) {
  const tool = {
    name: TACTIC_TOOL,
    label: 'Native FM tactic file',
    description: 'Discover native authoring choices, list/inspect .fmf templates or create a complete standalone tactic. Call with {action:"schema"} for the exact registered JSON parameters and matching SHA256, including when describeTool renders args:unknown; this local introspection needs no template or native backend. Use authoring_catalog for source-backed positions, the roles of each phase, team instructions and player-instruction enum names; include template_path for the legal roles at its current positions. Each player has one role in possession and one out of possession; a role is written by its name alone, with nothing after it. Generate native_authoring can set both full eleven-position layouts, up to22 phase roles, complete team selections and current-role player instructions without a donor. Omitted fields inherit; native_defaults explicitly resets current-role optional player selections, while team_instructions replaces the complete stored team selection. Native legality and availability are checked by the isolated original creator/serializer. Legacy pinned-donor edits and scalar controls remain supported with documented combination limits. Defaults to Agent Outputs; fm27_folder=true creates a new safe file in Tactics when requested. Never overwrites or controls the running game. Stored authoring and native reload checks do not verify FM import, lineup assignment, effective instructions or match outcomes.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        action: { type: 'string', enum: ['list_templates', 'inspect', 'authoring_catalog', 'generate', 'schema'] },
        template_path: { type: 'string', description: 'Native .fmf source path from list_templates or supplied by the user. Required for inspect/generate; optional for authoring_catalog, where it adds the legal roles at the actual source positions.' },
        template_sha256: { type: 'string', description: 'Exact SHA256 returned by inspect/list_templates; required for generate.' },
        name: { type: 'string', description: 'New tactic name; required for generate.' },
        fm27_folder: { type: 'boolean', description: 'Set true when asked to save directly to FM27. Creates a new name-derived .fmf and receipt in its user-data Tactics folder; never overwrites. Default false keeps Agent Outputs.' },
        tactics_directory: { type: 'string', description: 'Optional existing custom FM27 Tactics directory. Use only when explicitly supplied; requires fm27_folder=true.' },
        preview: { type: 'boolean', description: 'Validate edits and read back planned result without creating output or receipt. Use for preview requests.' },
        native_authoring: {
          type: 'object', additionalProperties: false,
          description: 'Author a whole native plan without donor fingerprints. Use exact names from authoring_catalog. Omitted layouts, roles and team selections inherit. Roles/layouts may trigger original native reconciliation. Cannot combine with legacy donor edits; complete team_instructions cannot combine with top-level team-selection controls. Mentality remains separate and may combine. The backend atomically checks canonical source serialization, native phase/position/role legality, availability, every requested selection and complete native serialization/reload before any output.',
          properties: {
            positions: {
              type: 'object', additionalProperties: false,
              description: 'Optional complete layout for either or both phases. Each supplied phase requires exactly11 distinct canonical native positions, goalkeeper at index0. Use compiled position names from authoring_catalog, or its joined metadata-mask components where an English name is unavailable. The backend rejects duplicate masks even if different aliases were used. Layout edits target explicit phase records under the fixed preserve_existing_player_correspondence policy: retain the source cross-phase player identity map, checked through original native accessors and reload. Creating or rebinding that correspondence is unavailable. Omitted phases inherit.',
              properties: Object.fromEntries(['in_possession', 'out_of_possession'].map(phase => [phase, {
                type: 'array', minItems: 11, maxItems: 11, uniqueItems: true,
                items: { type: 'string', minLength: 1 },
              }])),
            },
            roles: {
              type: 'array', maxItems: 22, uniqueItems: true,
              description: 'Named roles for up to22 distinct phase/index pairs. For a whole plan, supply all22 explicitly. Each entry is phase, position_index and role, nothing else. Choose the exact compiled English role name from authoring_catalog; which roles are legal depends on the resulting phase and position. The backend finds the one stored word the game accepts for that role there and writes it. Duplicate slots, unknown names, a role the game does not offer at that position and native normalization that fails to reproduce the requested role refuse the whole operation. Omitted slots inherit subject to native position/role reconciliation.',
              items: {
                type: 'object', additionalProperties: false,
                properties: {
                  phase: { type: 'string', enum: ['in_possession', 'out_of_possession'] },
                  position_index: { type: 'integer', minimum: 0, maximum: 10 },
                  role: { type: 'string', minLength: 1 },
                }, required: ['phase', 'position_index', 'role'],
              },
            },
            team_instructions: {
              type: 'array', maxItems: 79, uniqueItems: true,
              items: { type: 'string', minLength: 1, not: { const: 'Distribute To Specific Team-Mate' } },
              description: 'Complete replacement of explicit stored team selections using exact native English names from authoring_catalog. [] clears all explicit selections; omission inherits them. Native conflicts and unknown names refuse atomically. Team option41 Distribute To Specific Team-Mate requires a recipient binding and is withheld. No explicit selection is not an item here: omit a named option to leave its stored bit clear. Do not combine with scalar team controls; top-level mentality may combine.',
            },
            instruction_policy: {
              type: 'string', enum: ['native_defaults', 'preserve'],
              description: 'preserve is the default: retain current-role stored selections except original position/role reconciliation. native_defaults resets current-role optional stored selections across all22 phase records before explicit player_instructions. Inactive role profiles remain unless native reconciliation changes them. This is not proof of effective defaults, mandatory selections or player overrides.',
            },
            player_instructions: {
              type: 'array', maxItems: 22, uniqueItems: true,
              description: 'Complete current-role optional selection for each requested distinct phase/index pair, applied after roles and instruction_policy. [] clears Boolean selections; a supplied mark_specific_position still adds35. Use exact metadata PI_* enum names from authoring_catalog; native availability and exact post-setter selections must match. Omitted rows follow instruction_policy. PI_SWITCH_POSITION (28) is an admitted plain Boolean toggle, subject to native availability. PI_NONE is a sentinel and PI_MARK_SPECIFIC_PLAYER (34) remains withheld. Raw PI_MARK_SPECIFIC_POSITION (35) is refused in this list: use the OOP-only mark_specific_position target field, which adds35 automatically.',
              items: {
                type: 'object', additionalProperties: false,
                properties: {
                  phase: { type: 'string', enum: ['in_possession', 'out_of_possession'] },
                  position_index: { type: 'integer', minimum: 0, maximum: 10 },
                  mark_specific_position: {
                    type: 'string', enum: POSITION_MARK_TARGETS,
                    description: 'Optional typed target for original specific-position marking, OOP only. Use one canonical position name from authoring_catalog, with the joined metadata-mask name for unnamed positions. This field adds native PI35 automatically and selects position-target mode, clearing active specific-player mode. instructions remains required and lists Boolean selections only. Actor-record native availability, selected bit, target accessor and reload must match. The25 admitted non-GK targets match the original compiled PI35 menu builder. GK is a storage-only diagnostic encoding and is excluded from authoring. Live-rendered UI observation remains unverified. To clear active PI35, omit this field in a replacement row with instructions:[]. Inactive target payload bytes may remain; no player identity or phase correspondence is rebound.',
                  },
                  instructions: {
                    type: 'array', maxItems: 40, uniqueItems: true,
                    items: { type: 'string', pattern: '^PI_[A-Z0-9_]+$', not: {
                      enum: ['PI_NONE', 'PI_MARK_SPECIFIC_PLAYER', 'PI_MARK_SPECIFIC_POSITION'],
                    } },
                  },
                }, required: ['phase', 'position_index', 'instructions'],
                allOf: [{ anyOf: [
                  { not: { required: ['mark_specific_position'] } },
                  { properties: { phase: { const: 'out_of_possession' } } },
                ] }],
              },
            },
          },
        },
        focus_play: { type: 'array', items: { type: 'string', enum: ['Focus Play Down The Left', 'Focus Play Down The Right', 'Focus Play Through The Middle', 'Focus Play Down Both Flanks'] }, uniqueItems: true, maxItems: 2, description: 'Omit to inherit stored focus bits21–24. Supply [] to clear them, or a distinct list of exact native selections. Left and Right may coexist; Middle and Both Flanks each require a single selection. Both Flanks is its own native bit24, separate from the compatible Left+Right bits21+22. Contradictory source/requested selections refuse edits. This does not encode crossing targets, supporting runs, effective phase behavior or verified game import.' },
        wide_support: { type: 'array', items: { type: 'string', enum: ['Look For Overlap', 'Overlap Left', 'Overlap Right', 'Look For Underlap', 'Underlap Left', 'Underlap Right'] }, uniqueItems: true, maxItems: 3, description: 'Omit to inherit stored overlap/underlap bits25–30; [] clears them. Supply exact distinct native labels whose pairs are compatible in the native opposition table. Overlap Left plus Underlap Right is compatible; Overlap Left plus Underlap Left conflicts. Global Look For choices are separate native bits. Contradictory source/requested selections refuse edits. This does not encode a named player run, guarantee box arrivals, prove effective phase behavior or verify game import.' },
        final_third_delivery: { type: 'string', enum: ['No explicit selection', 'Hit Early Crosses', 'Work Ball Into Box'], description: 'Omit to inherit. Select stored final-third delivery at bit9 or17, or clear both with No explicit selection without claiming an effective default. Conflicting source selections refuse edits. This is separate from crossing style and supporting player runs. Native UI setter parity, phase applicability, effective behavior and game import are unverified.' },
        pressing_block: { type: 'string', enum: ['No explicit selection', 'High Press', 'Mid Block', 'Low Block'], description: 'Omit to inherit. Select one stored pressing-block option at bits61/62/63, or clear all three with No explicit selection without claiming an effective default. Conflicting source selections refuse edits. This is separate from stored pressing frequency and defensive-line height; full native UI setter parity, effective pressing height, phase applicability and game import are unverified.' },
        crossing_style: { type: 'string', enum: ['No explicit selection', 'Floated Crosses', 'Whipped Crosses', 'Low Crosses'], description: 'Omit to inherit. Select one stored crossing style at bits10/11/12, or clear all three with No explicit selection without claiming an effective default. Conflicting source selections refuse edits. Low Crosses is a named stored delivery style; it does not encode cutbacks or fullback movement. Full native UI setter parity, effective behavior, phase applicability and game import are unverified.' },
        goal_kick_length: { type: 'string', enum: ['No explicit selection', 'Short Goal Kicks', 'Long Goal Kicks'], description: 'Omit to inherit. Select one stored goal-kick length at bits44/45, or clear both with No explicit selection without claiming an effective default. Conflicting source selections refuse edits. This does not select an open-play goalkeeper distribution method, receiver or conditional press bypass; full native UI setter parity, effective behavior and game import are unverified.' },
        possession_gain: { type: 'string', enum: ['No explicit selection', 'Counter', 'Hold Shape'], description: 'Omit to inherit. Replace only stored bits54/55: Counter names launching a counter attack when winning possession; Hold Shape names retaining formational shape upon winning possession. No explicit selection clears both without claiming an effective default. Conflicting source selections refuse edits. This does not encode space-dependent conditional countering; full UI setter parity, effective behavior and game import are unverified.' },
        possession_loss: { type: 'string', enum: ['No explicit selection', 'Counter-Press', 'Regroup'], description: 'Omit to inherit. Replace only stored bits70/71: Counter-Press names pressing immediately after losing possession; Regroup names defensive recovery after losing possession. No explicit selection clears both without claiming an effective default. Conflicting source selections refuse edits. This does not encode conditional pressing or fullback movement; full UI setter parity, effective behavior and game import are unverified.' },
        base_role: {
          type: 'object', additionalProperties: false,
          description: 'Omit to inherit. Exactly 26 proved directed changes across nine complete companion prefixes. Source-format27: IP slot5 DM(CR) Box-To-Box Midfielder to Defensive Midfielder or reverse; OOP slot4 WB(R) or OOP slot7 WB(L) Pressing Wing-Back to Wing-Back or reverse; OOP slot8 AM(CR) and slot9 AM(CL) Attacking Midfielder to Tracking Attacking Midfielder or reverse with their zero-PI target. Source-format26: IP slot7 AM(R) or slot9 AM(L) Winger to Inside Forward or reverse; OOP slot1 D(R) and slot4 D(L) any distinct pair among Pressing Full-Back, Full-Back and Holding Full-Back. Requires a matching inspected donor and native checks. Both records must share the complete proved companion prefix, unique existing normalized target key and exact native instruction/normalization proof. No-op or unproved word/format/position/companion combinations refuse. Eligible archive variants may differ elsewhere. Stored-record reproduction only; import, full UI setter parity and effective instructions are unverified.',
          properties: {
            phase: { type: 'string', enum: ['in_possession', 'out_of_possession'] },
            position_index: { type: 'integer', enum: [1, 4, 5, 7, 8, 9] },
            donor_template_path: { type: 'string', description: 'Inspected native donor for an exact proved distinct source/target word pair in the requested source-format, phase and position case. The complete companion record must match the source. Inspect the actual donor role; no arbitrary role word or fabricated version is accepted.' },
            donor_template_sha256: { type: 'string', description: 'Exact SHA256 returned by inspect for this donor; required even when the source is eligible.' },
            donor_position_index: { type: 'integer', enum: [1, 4, 5, 7, 8, 9] },
          },
          required: ['phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'],
        },
        phase_position: {
          type: 'object', additionalProperties: false,
          description: 'Omit to inherit. Native-format27 OOP slot4 WB(R) to D(R), or slot7 WB(L) to D(L), Wing-Back to the exact inspected Full-Back donor record including its reconciled instruction entries. Source-format26 additionally supports OOP slot7 M(R) to AM(R) or slot8 M(L) to AM(L), Tracking Wide Midfielder to the exact Winger donor record. Source/donor formats must match; source version remains inherited. All eleven source OOP records must match a proved phase. Either flank may be changed first and the other changed in a subsequent generated file; other phase configurations, reverse directions, no-ops and arbitrary position masks refuse. Original creator position setter, record serializer and complete native loader were verified offline. Full UI parity, effective behavior, personal overrides and game import remain unverified.',
          properties: {
            phase: { type: 'string', enum: ['out_of_possession'] },
            position_index: { type: 'integer', enum: [4, 7, 8] },
            donor_template_path: { type: 'string', description: 'Inspected same-format donor with the exact proved complete target record at the same slot: format27 D(R/L) Full-Back, or format26 AM(R/L) Winger.' },
            donor_template_sha256: { type: 'string', description: 'Exact SHA256 returned by inspect for this donor.' },
            donor_position_index: { type: 'integer', enum: [4, 7, 8] },
          },
          required: ['phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'],
        },
        stored_role_instructions: {
          type: 'object', additionalProperties: false,
          description: 'Omit to inherit. Only native-format27 in_possession slot9 AM(CL), Attacking Midfielder, with the exact proved complete companion record. Transfer the inspected donor current-role selection: no stored options or native options24/27 (PI_ROAM_FROM_POSITION and PI_MOVE_INTO_CHANNELS). Both source/donor hashes and a distinct proved profile are required. Native availability and original selection/clear routines were verified offline. Other entries and role bytes are preserved. Personal overrides, role-derived selections, effective instructions, full UI setter parity and game import remain unverified.',
          properties: {
            phase: { type: 'string', enum: ['in_possession'] },
            position_index: { type: 'integer', enum: [9] },
            donor_template_path: { type: 'string', description: 'Inspected native-format27 donor with the matching IP9 AM(CL) Attacking Midfielder record and the other proved stored profile.' },
            donor_template_sha256: { type: 'string', description: 'Exact SHA256 returned by inspect for this donor.' },
            donor_position_index: { type: 'integer', enum: [9] },
          },
          required: ['phase', 'position_index', 'donor_template_path', 'donor_template_sha256', 'donor_position_index'],
        },
        team_width: { type: 'string', enum: ['No explicit selection', 'Much Wider', 'Wider', 'Narrower', 'Much Narrower'], description: 'Omit to inherit. Replace stored width bits50–53 with one named selection, or clear them with No explicit selection. Conflicting source selections refuse edits. Native UI clearing, effective default, phase applicability and game import are unverified.' },
        pressing_frequency: { type: 'string', enum: ['No explicit selection', 'Trigger Press Much More Often', 'Trigger Press More Often', 'Trigger Press Less Often', 'Trigger Press Much Less Often'], description: 'Omit to inherit. Replace stored pressing-frequency bits65–68 with one named selection, or clear them with No explicit selection. Conflicting source selections refuse edits. Native UI clearing, effective default, phase applicability and game import are unverified.' },
        passing_directness: { type: 'string', enum: ['No explicit selection', 'Much More Direct Passing', 'More Direct Passing', 'Shorter Passing', 'Much Shorter Passing'], description: 'Omit to inherit. Replace the four stored passing selection bits with one named selection, or clear them with No explicit selection. Conflicting source selections refuse edits. Native UI clearing, effective default, phase applicability and game import are unverified.' },
        tempo: { type: 'string', enum: ['No explicit selection', 'Much Higher Tempo', 'Higher Tempo', 'Lower Tempo', 'Much Lower Tempo'], description: 'Omit to inherit. Select one stored tempo option or clear it with No explicit selection. Effective default, phase applicability and game import are unverified.' },
        defensive_line: { type: 'string', enum: ['No explicit selection', 'Much Higher Defensive Line', 'Higher Defensive Line', 'Lower Defensive Line', 'Much Lower Defensive Line'], description: 'Omit to inherit. Set an explicit stored height or clear it with No explicit selection. Effective default and phase applicability are unknown.' },
        team_tackling: { type: 'string', enum: ['No explicit selection', 'Get Stuck In', 'Stay On Feet'], description: 'Set the stored tackling flags; omission inherits the template. No explicit selection clears both flags; effective default and phase applicability are unverified.' },
        mentality: { type: 'string', enum: ['Very Defensive', 'Defensive', 'Cautious', 'Balanced', 'Positive', 'Attacking', 'Very Attacking'] },
      },
      required: ['action'],
      allOf: [
        ...LEGACY_DONOR_EDITS.map(field => ({ not: { required: ['native_authoring', field] } })),
        { anyOf: [{ not: { required: ['native_authoring'] } }, { properties: { action: { const: 'generate' } } }] },
        { not: {
          required: ['native_authoring'],
          properties: { native_authoring: { required: ['team_instructions'] } },
          anyOf: TEAM_SELECTION_FIELDS.map(field => ({ required: [field] })),
        } },
      ],
    },
    prepareArguments: dropLegacyRoleFields,
    async execute(_id, rawParams, signal) {
      const params = dropLegacyRoleFields(rawParams);
      try {
        if (params.action === 'schema') {
          if (Object.keys(params).length !== 1) throw new Error('schema accepts only action; no template or generation fields');
          const details = { tool_name: TACTIC_TOOL, registered_parameters: registeredParameters,
            schema_sha256: registered.schema_sha256, authoring_runtime: runtimeInfo(registered),
            scope: 'Immutable JSON parameters supplied at this registration. File observations do not attest executed JS or loaded Python; native/UI behavior needs separate evidence.' };
          return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
        }
        if (params.action === 'generate') requireMatchingRegistration(registered);
        const result = await runTacticFile(params, signal);
        const details = ['inspect', 'authoring_catalog'].includes(params.action)
          ? { ...result, authoring_runtime: runtimeInfo(registered) } : result;
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
      } catch (error) {
        const message = `Native tactic file operation failed: ${error.message}`;
        const details = { error: true };
        if (error.diagnostic) details.diagnostic = error.diagnostic;
        return { content: [{ type: 'text', text: details.diagnostic
          ? JSON.stringify({ error: message, diagnostic: details.diagnostic }) : message }], details, isError: true };
      }
    },
  };
  const registeredParameters = snapshotParameters(tool.parameters);
  tool.parameters = registeredParameters;
  const registered = captureRegistration(registeredParameters);
  pi.registerTool(tool);
}
