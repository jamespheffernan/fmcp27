import { writeFileSync } from 'node:fs';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

// Harmless negative fixture: the FM guard must reject this before execute runs.
export default function verify(pi: ExtensionAPI) {
  let executed = false;
  pi.registerTool({
    name: 'mcp__fm_live__test_non_readonly',
    label: 'FM boundary test',
    description: 'Verification fixture that must be blocked by the read-only guard.',
    parameters: { type: 'object', properties: {}, additionalProperties: false } as any,
    annotations: { readOnlyHint: false },
    async execute() {
      executed = true;
      return { content: [{ type: 'text', text: 'Boundary failure: fixture executed' }] };
    },
  });
  pi.on('session_shutdown', () => {
    writeFileSync('evidence/codemode-boundary.json', JSON.stringify({ executed }) + '\n');
  });
}
