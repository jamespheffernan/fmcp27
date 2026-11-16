// Re-render every sample spec in this folder to <name>.html with a fixed
// generation time, so diffs show renderer changes only.
//   node evals/report-samples/render.mjs
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { join } from 'node:path';
import { renderReport } from '../../pi/fm-report-render.mjs';

const dir = fileURLToPath(new URL('.', import.meta.url));
const generatedAt = new Date('2026-11-11T10:00:00Z');
for (const file of readdirSync(dir).filter(f => f.endsWith('.json')).sort()) {
  const spec = JSON.parse(readFileSync(join(dir, file), 'utf8'));
  delete spec.filename;
  const html = renderReport(spec, { generatedAt, timeZone: 'Europe/London' });
  const out = join(dir, file.replace(/\.json$/, '.html'));
  writeFileSync(out, html);
  console.log(`${out}  ${(Buffer.byteLength(html) / 1024).toFixed(1)} KiB`);
}
