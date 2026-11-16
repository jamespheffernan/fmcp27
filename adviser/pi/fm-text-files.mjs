import { execFile } from 'node:child_process';
import { realpath } from 'node:fs/promises';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

export const TEXT_TOOL = 'fm_write_text';

async function writeText(params, signal) {
  const project = await realpath(fileURLToPath(new URL('../', import.meta.url)));
  const outputs = join(await realpath(homedir()), 'Agent Outputs');
  return new Promise((resolve, reject) => {
    const child = execFile('/usr/bin/sandbox-exec', [
      '-f', fileURLToPath(new URL('./fm-text-files.sb', import.meta.url)),
      '-D', `PROJECT_ROOT=${project}`, '-D', `OUTPUTS_ROOT=${outputs}`,
      '/usr/bin/python3', '-B', fileURLToPath(new URL('./fm-text-files.py', import.meta.url)),
    ],
      { timeout: 10_000, maxBuffer: 65_536, signal }, (error, stdout, stderr) => {
        if (error) return reject(new Error(stderr.trim() || error.message));
        try {
          resolve(JSON.parse(stdout));
        } catch (error) {
          reject(error);
        }
      });
    child.stdin.on('error', reject);
    child.stdin.end(JSON.stringify(params));
  });
}

export function registerTextFileTool(pi) {
  pi.registerTool({
    name: TEXT_TOOL,
    label: 'Write FM text file',
    description: 'Create a new UTF-8 .md, .txt or .csv file inside the pi-fm project or ~/Agent Outputs. Relative paths use the project root. Creates parent folders; refuses existing files, symlinks, hidden paths and dependency folders. Maximum 1 MiB. Use for reports, notes and skill drafts, never native .fmf tactics. No shell, read access or game changes.',
    parameters: {
      type: 'object', additionalProperties: false,
      properties: {
        path: { type: 'string', description: 'New file path, absolute, ~/Agent Outputs/..., or project-relative.' },
        content: { type: 'string', description: 'Complete UTF-8 text to save.' },
      },
      required: ['path', 'content'],
    },
    async execute(_id, params, signal) {
      try {
        const details = await writeText(params, signal);
        return { content: [{ type: 'text', text: JSON.stringify(details) }], details };
      } catch (error) {
        return { content: [{ type: 'text', text: `Text file creation failed: ${error.message}` }], details: { error: true }, isError: true };
      }
    },
  });
}
