// Offline provider for the lean tool surface: records what the first model call is offered, finds a
// deferred reader tool with tool_search, then calls it without a session id. No model service,
// network or game is used.
import { createAssistantMessageEventStream, getCurrentTools, getCurrentSystemPrompt } from "@earendil-works/pi-ai";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

const SHOT_MAP = "mcp__fm_live__fm_get_retained_shot_map";

export default function fixture(pi: ExtensionAPI) {
  const seen: Record<string, unknown> = {};
  pi.registerProvider("exposure-fixture", {
    api: "exposure-fixture",
    baseUrl: "https://fixture.invalid",
    apiKey: "test-only",
    models: [{ id: "offline", name: "Offline exposure test", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1024 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const step = context.messages.filter(message => message.role === "toolResult").length;
      const tools = getCurrentTools(context.messages);
      const names = tools.map(tool => tool.name).sort();
      const prompt = getCurrentSystemPrompt(context.messages);
      const output: AssistantMessage = {
        role: "assistant", provider: model.provider, model: model.id, api: model.api,
        timestamp: Date.now(), stopReason: "pending", content: [],
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      };
      stream.push({ type: "start", partial: output });
      let call: { type: "toolCall"; id: string; name: string; arguments: Record<string, unknown> } | null = null;
      if (step === 0) {
        Object.assign(seen, {
          firstDeclared: names,
          firstToolChars: JSON.stringify(tools).length,
          promptChars: prompt.length,
          promptHasSql: prompt.includes("# SQL\n"),
          promptHasSave: prompt.includes("- Game date: 2030-12-13") && prompt.includes("Fixture United"),
          promptHasCard: prompt.includes("`player_view` (player)"),
          promptHasAttachError: prompt.includes("could not attach to the game"),
          attachLines: prompt.split("\n").filter(line => /Reader error:|Fix:/.test(line)).join("\n"),
          declaredSessionParam: JSON.stringify(tools).includes("session_id"),
          promptHasReport: prompt.includes("`fm_report`"),
          promptHasMarkers: prompt.includes("<!-- fm:"),
          promptHasCoreGuide: prompt.includes("# Core procedure"),
        });
        call = { type: "toolCall", id: "search", name: "tool_search", arguments: { query: "retained shot map" } };
      } else if (step === 1) {
        seen.afterSearch = names;
        if (names.includes(SHOT_MAP)) call = { type: "toolCall", id: "shots", name: SHOT_MAP, arguments: {} };
      }
      if (call) {
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
