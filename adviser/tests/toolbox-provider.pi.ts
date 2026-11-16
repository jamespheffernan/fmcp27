// Offline provider for the toolbox: plays the tool calls in PI_FM_TEST_STEPS (a JSON array of
// {name, arguments}) one per model turn, then reports what the first model call was offered and
// every tool result. No model service, network or game is used.
import { createAssistantMessageEventStream, getCurrentTools, getCurrentSystemPrompt } from "@earendil-works/pi-ai";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function fixture(pi: ExtensionAPI) {
  const steps: { name: string; arguments: Record<string, unknown> }[] = JSON.parse(process.env.PI_FM_TEST_STEPS ?? "[]");
  const seen: Record<string, unknown> = {};
  pi.registerProvider("toolbox-fixture", {
    api: "toolbox-fixture",
    baseUrl: "https://fixture.invalid",
    apiKey: "test-only",
    models: [{ id: "offline", name: "Offline toolbox test", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1024 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const step = context.messages.filter(message => message.role === "toolResult").length;
      const output: AssistantMessage = {
        role: "assistant", provider: model.provider, model: model.id, api: model.api,
        timestamp: Date.now(), stopReason: "pending", content: [],
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      };
      stream.push({ type: "start", partial: output });
      if (step === 0) {
        const prompt = getCurrentSystemPrompt(context.messages);
        const start = prompt.indexOf("# Your toolbox");
        Object.assign(seen, {
          declared: getCurrentTools(context.messages).map(tool => tool.name).sort(),
          toolboxSection: start < 0 ? null : prompt.slice(start, prompt.indexOf("\n# ", start + 1)),
          promptHasMarkers: prompt.includes("<!-- fm:"),
        });
      }
      if (step < steps.length) {
        const call = { type: "toolCall" as const, id: `step-${step}`, name: steps[step].name, arguments: steps[step].arguments };
        output.content.push(call);
        stream.push({ type: "toolcall_start", contentIndex: 0, partial: output });
        stream.push({ type: "toolcall_delta", contentIndex: 0, delta: JSON.stringify(call.arguments), partial: output });
        stream.push({ type: "toolcall_end", contentIndex: 0, toolCall: call, partial: output });
        output.stopReason = "toolUse";
      } else {
        const results = context.messages.filter(message => message.role === "toolResult")
          .map(message => ({ name: (message as any).toolName, isError: Boolean((message as any).isError),
            text: ((message as any).content ?? []).map((c: any) => c.text ?? "").join("") }));
        const text = JSON.stringify({ ...seen, results });
        output.content.push({ type: "text", text });
        stream.push({ type: "text_start", contentIndex: 0, partial: output });
        stream.push({ type: "text_delta", contentIndex: 0, delta: text, partial: output });
        stream.push({ type: "text_end", contentIndex: 0, content: text, partial: output });
        output.stopReason = "stop";
      }
      stream.push({ type: "done", reason: output.stopReason, message: output });
      stream.end();
      return stream;
    },
  });
}
