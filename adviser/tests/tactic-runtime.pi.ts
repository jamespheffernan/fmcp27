// Deterministic provider for actual isolated Pi/CodeMode dispatch, without an LLM or game.
import { createAssistantMessageEventStream, getCurrentTools } from '@earendil-works/pi-ai';
import { schemaSha256 } from '../pi/fm-tactic-runtime.mjs';

export default function fixture(pi) {
  pi.registerProvider('tactic-runtime-fixture', {
    api: 'tactic-runtime-fixture', baseUrl: 'https://fixture.invalid', apiKey: 'test-only',
    models: [{ id: 'offline', name: 'Offline registration check', reasoning: false, input: ['text'],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1024 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const tools = getCurrentTools(context.messages);
      const called = context.messages.some(message => message.role === 'toolResult');
      const output = { role: 'assistant', provider: model.provider, model: model.id, api: model.api,
        timestamp: Date.now(), stopReason: 'pending', content: [], usage: {
          input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } } };
      stream.push({ type: 'start', partial: output });
      if (!called) {
        const arguments_ = { code: process.env.PI_FM_RUNTIME_CODE };
        const call = { type: 'toolCall', id: 'runtime-check', name: 'codemode', arguments: arguments_ };
        output.content.push(call);
        stream.push({ type: 'toolcall_start', contentIndex: 0, partial: output });
        stream.push({ type: 'toolcall_delta', contentIndex: 0, delta: JSON.stringify(arguments_), partial: output });
        stream.push({ type: 'toolcall_end', contentIndex: 0, toolCall: call, partial: output });
        output.stopReason = 'toolUse';
      } else {
        const actual = tools.find(tool => tool.name === 'fm_tactic_file');
        const text = JSON.stringify({ actual_provider_schema_sha256: schemaSha256(actual.parameters),
          actual_provider_marking_field: actual.parameters.properties.native_authoring.properties.player_instructions.items.properties.mark_specific_position,
          declared_tools: tools.map(tool => tool.name) });
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
