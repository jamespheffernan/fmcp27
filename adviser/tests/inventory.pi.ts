import { writeFileSync } from 'node:fs';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';
export default function verify(pi: ExtensionAPI) {
  pi.registerCommand('fmverify', {
    description: 'Record the actual tool inventory for this launcher test.',
    handler: async (_args, ctx) => {
      const deadline = Date.now() + 30000;
      while (!pi.getActiveTools().includes('mcp__fm_live__fm_get_save') && Date.now() < deadline) {
        await new Promise(resolve => setTimeout(resolve, 100));
      }
      const active = pi.getActiveTools();
      const all = pi.getAllTools();
      const helpers = ['codemode', 'papercut', 'fm_tactic_file', 'fm_write_text', 'fm_read_skill'];
      const allowedHelpers = [...helpers, 'fm_match_report'];
      const foreign = active.filter(name => !allowedHelpers.includes(name) && !name.startsWith('mcp__fm_live__'));
      const hostRecorders = all.filter(tool => tool.name === 'mcp__fm_live__fm_record_current_match' && active.includes(tool.name) && tool.annotations?.readOnlyHint === false).map(tool => tool.name);
      const nonReadOnly = all.filter(tool => !allowedHelpers.includes(tool.name) && !hostRecorders.includes(tool.name) && active.includes(tool.name) && tool.annotations?.readOnlyHint !== true).map(tool => tool.name);
      const receipt = { active, foreign, hostRecorders, nonReadOnly, allRegistered: all.map(t => t.name), passed: helpers.every(name => active.includes(name)) && active.includes('mcp__fm_live__fm_get_save') && foreign.length === 0 && nonReadOnly.length === 0 };
      writeFileSync('evidence/actual-tool-inventory.json', JSON.stringify(receipt, null, 2) + '\n');
      ctx.shutdown();
    },
  });
}
