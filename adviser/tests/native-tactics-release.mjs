import { spawnSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { createReadStream } from 'node:fs';
import { mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const validator = join(root, 'tests/native_body_validator.py');
const binary = process.env.PI_FM_NATIVE_BINARY || join(homedir(), 'Library/Application Support/Steam/steamapps/common/Football Manager 27/fm.app/Contents/PlugIns/game_plugin.bundle/Contents/MacOS/game_plugin');
const codecRoot = process.env.PI_FM_TACTIC_CODEC_ROOT || join(homedir(), 'GitHub/FM26 Deepener');
const python = process.env.PI_FM_TACTIC_PYTHON || join(codecRoot, '.venv/bin/python');
const temporary = join(root, 'tmp');
await mkdir(temporary, { recursive: true });
const directory = await mkdtemp(join(temporary, 'native-tactics-'));
const receiptPath = join(directory, 'native-loader-receipt.json');
const validatorSource = await readFile(validator, 'utf8');
const validatorSha256 = createHash('sha256').update(validatorSource).digest('hex');
const auditedValidatorSha256 = 'f8b25c729557c57edaae16d65ab8f6b32f19a7dec2ab22a426fad986f97b5b4a';
if (validatorSha256 !== auditedValidatorSha256) {
  const receipt = { state: 'unsupported_validator', reason: 'Native validator differs from the audited immutable core.', validator_sha256: validatorSha256, expected_validator_sha256: auditedValidatorSha256 };
  await writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
  console.error(JSON.stringify({ ...receipt, receipt: receiptPath }, null, 2));
  process.exit(2);
}
const expected = validatorSource.match(/EXPECTED_NATIVE_SHA256\s*=\s*['"]([a-f0-9]{64})['"]/)?.[1];
if (!expected) throw new Error('Audited native validator has no binary fingerprint.');

async function digest(path) {
  const hash = createHash('sha256');
  for await (const bytes of createReadStream(path)) hash.update(bytes);
  return hash.digest('hex');
}

let actual;
try {
  actual = await digest(binary);
} catch (error) {
  const receipt = { state: 'unsupported_build', reason: `Installed FM27 binary unavailable: ${error.message}`, native_binary: binary, expected_native_binary_sha256: expected };
  await writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
  console.error(JSON.stringify({ ...receipt, receipt: receiptPath }, null, 2));
  process.exit(2);
}
if (actual !== expected) {
  const receipt = { state: 'unsupported_build', reason: 'Installed FM27 binary differs from the audited native loader build.', native_binary: binary, native_binary_sha256: actual, expected_native_binary_sha256: expected };
  await writeFile(receiptPath, JSON.stringify(receipt, null, 2) + '\n');
  console.error(JSON.stringify({ ...receipt, receipt: receiptPath }, null, 2));
  process.exit(2);
}

const generated = spawnSync(python, [join(root, 'tests/native-tactic-variants.py'), directory], { encoding: 'utf8', timeout: 180_000, maxBuffer: 2_097_152 });
if (generated.status !== 0) {
  console.error(generated.stderr || String(generated.error));
  process.exit(generated.status || 1);
}
const batch = JSON.parse(generated.stdout);
const checked = spawnSync('uv', ['run', '--no-project', '--no-python-downloads', '--python', 'python3', '--with', 'unicorn==2.1.4', 'python', validator,
  '--manifest', batch.manifest, '--output', receiptPath], {
  encoding: 'utf8', timeout: 180_000, maxBuffer: 2_097_152,
  env: { ...process.env, PI_FM_NATIVE_BINARY: binary, UV_CACHE_DIR: join(temporary, 'native-validator-uv-cache') },
});
if (checked.stdout) process.stdout.write(checked.stdout);
if (checked.stderr) process.stderr.write(checked.stderr);
console.log(JSON.stringify({ sources: batch.sources, variants: batch.variants, payloads: batch.payloads, manifest: batch.manifest, receipt: receiptPath }));
process.exit(checked.status ?? 1);
