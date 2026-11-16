import { createHash } from 'node:crypto';
import { readFileSync } from 'node:fs';

const ROOT = new URL('../', import.meta.url);
const FILES = ['package.json', 'pi/fm-tactic-files.mjs', 'pi/fm-tactic-runtime.mjs',
  'pi/fm-tactic-files.py', 'pi/fm_tactic_native_authoring.py', 'pi/fm_tactic_native_core.py',
  'skills/fm-create-tactic/SKILL.md', 'skills/fm-tactical-analysis/SKILL.md'];
const ADAPTERS = ['pi/fm-tactic-files.mjs', 'pi/fm-tactic-runtime.mjs'];

function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  }
  return value;
}

export function schemaSha256(parameters) {
  return createHash('sha256').update(JSON.stringify(canonical(parameters))).digest('hex');
}

function freeze(value) {
  if (value && typeof value === 'object') {
    Object.values(value).forEach(freeze);
    Object.freeze(value);
  }
  return value;
}

export function snapshotParameters(parameters) {
  return freeze(structuredClone(parameters));
}

export function observeFiles(root = ROOT) {
  const files = {};
  let adviserVersion = null;
  for (const path of FILES) {
    try {
      const raw = readFileSync(new URL(path, root));
      files[path] = { state: 'observed', sha256: createHash('sha256').update(raw).digest('hex') };
      if (path === 'package.json') adviserVersion = JSON.parse(raw).version ?? null;
    } catch (error) {
      files[path] = { state: 'unavailable', reason: error.code || 'unreadable_or_invalid' };
    }
  }
  return { observed_at: new Date().toISOString(), adviser_version: adviserVersion, files,
    scope: 'Filesystem observations only; not proof of executed JS modules or loaded Python code.' };
}

export function captureRegistration(parameters) {
  const target = parameters.properties?.native_authoring?.properties?.player_instructions?.items
    ?.properties?.mark_specific_position;
  return freeze({ contract_version: 1,
    evidence: 'Exact parameters object captured immediately before pi.registerTool.',
    schema_sha256: schemaSha256(parameters),
    capabilities: { mark_specific_position: target?.type === 'string' && Array.isArray(target.enum),
      mark_specific_position_targets: target?.type === 'string' && Array.isArray(target.enum) ? [...target.enum] : null },
    filesystem_at_registration: observeFiles() });
}

export function runtimeInfo(registered, current = observeFiles()) {
  const matches = ADAPTERS.map(path => {
    const before = registered.filesystem_at_registration.files[path];
    const after = current.files[path];
    return before?.state === 'observed' && after?.state === 'observed'
      ? before.sha256 === after.sha256 : null;
  });
  return { registered, current_filesystem: current,
    registration_adapter_files_match_current_disk: matches.includes(false) ? false
      : matches.every(value => value === true) ? true : null,
    ui_controls_verified: false };
}

export function requireMatchingRegistration(registered) {
  const runtime = runtimeInfo(registered);
  if (runtime.registration_adapter_files_match_current_disk === true) return;
  const before = registered.filesystem_at_registration.adviser_version ?? 'unknown';
  const now = runtime.current_filesystem.adviser_version ?? 'unknown';
  const error = new Error(`Tactic registration/filesystem mismatch: registration adviser ${before}, current disk ${now}, schema ${registered.schema_sha256}. Stop this generation and inspect authoring_runtime; preserve the exact requested plan. A new isolated Pi context can check current capabilities; existing sessions are unchanged.`);
  error.diagnostic = { kind: 'tactic_registration_filesystem_mismatch',
    automatic_substitution_applied: false, authoring_runtime: runtime };
  throw error;
}
