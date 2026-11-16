// Deterministic local provider + local tools exercise actual Pi dispatch, not MCP transport.
// No model service, network request, FM reader or game process is used.
import { writeFileSync } from 'node:fs';
import { createAssistantMessageEventStream } from '@earendil-works/pi-ai';
import type { AssistantMessage } from '@earendil-works/pi-ai';
import type { ExtensionAPI } from '@earendil-works/pi-coding-agent';

export const CASES = [
  { name: 'mcp__fm_live__fm_record_current_match', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_get_current_match', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_get_current_match_shot_origins', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_report_retained_match_periods', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_report_retained_pass_network_by_period', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_report_retained_possession_by_period', hint: false, allowed: true },
  { name: 'mcp__fm_live__fm_get_policy_read', hint: true, allowed: true },
  { name: 'mcp__fm_live__fm_set_tactic', hint: false, allowed: false },
  { name: 'mcp__fm_live__fm_report_retained_possession_by_period_extra', hint: false, allowed: false },
  { name: 'mcp__other__fm_record_current_match', hint: false, allowed: false },
  { name: 'mcp__other__fm_get_policy_read', hint: true, allowed: false },
];

export default function fixture(pi: ExtensionAPI) {
  const executed: string[] = [];
  for (const item of CASES) {
    pi.registerTool({
      name: item.name, label: 'Local host-policy fixture',
      description: 'Harmless local dispatch fixture; no MCP or game I/O.',
      parameters: { type: 'object', properties: { link_retained: { type: 'boolean' } }, additionalProperties: false } as any,
      annotations: { readOnlyHint: item.hint },
      async execute(_id, input) {
        executed.push(item.name);
        return { content: [{ type: 'text', text: JSON.stringify({ fixtureExecuted: item.name, input }) }] };
      },
    });
  }
  pi.on('session_shutdown', () => writeFileSync(process.env.PI_FM_POLICY_RECEIPT!,
    JSON.stringify({ route: process.env.PI_FM_POLICY_ROUTE, cases: CASES, executed,
      scope: 'Actual installed Pi dispatch and nested CodeMode hooks with local synthetic tools, not real MCP/model/game transport.' }) + '\n'));
  pi.registerProvider('host-policy-fixture', {
    api: 'host-policy-fixture', baseUrl: 'https://fixture.invalid', apiKey: 'local-test-only',
    models: [{ id: 'offline', name: 'Offline host-policy control', reasoning: false, input: ['text'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 2048 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const completed = context.messages.filter(message => message.role === 'toolResult').length;
      const output: AssistantMessage = {
        role: 'assistant', provider: model.provider, model: model.id, api: model.api,
        timestamp: Date.now(), stopReason: 'pending', content: [],
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      };
      stream.push({ type: 'start', partial: output });
      const nested = process.env.PI_FM_POLICY_ROUTE === 'codemode';
      if (completed < (nested ? 1 : CASES.length)) {
        const name = nested ? 'codemode' : CASES[completed].name;
        const args = nested ? { code: `for (const name of ${JSON.stringify(CASES.map(item => item.name))}) { try { text({name,result:await tools[name]({link_retained:true})}); } catch (error) { text({name,error:String(error)}); } }` }
          : { link_retained: true };
        const call = { type: 'toolCall' as const, id: `host-policy-${completed}`, name, arguments: args };
        output.content.push(call);
        stream.push({ type: 'toolcall_start', contentIndex: 0, partial: output });
        stream.push({ type: 'toolcall_delta', contentIndex: 0, delta: JSON.stringify(args), partial: output });
        stream.push({ type: 'toolcall_end', contentIndex: 0, toolCall: call, partial: output });
        output.stopReason = 'toolUse';
      } else {
        const text = 'Offline policy dispatch fixture completed; no external model or FM source used.';
        output.content.push({ type: 'text', text });
        stream.push({ type: 'text_start', contentIndex: 0, partial: output });
        stream.push({ type: 'text_delta', contentIndex: 0, delta: text, partial: output });
        stream.push({ type: 'text_end', contentIndex: 0, content: text, partial: output });
        output.stopReason = 'stop';
      }
      stream.push({ type: 'done', reason: output.stopReason, message: output });
      stream.end();
      return stream;
    },
  });
}
