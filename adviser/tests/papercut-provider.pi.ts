// Offline provider fixture. Emits a tool call through the installed Pi pipeline.
import { createAssistantMessageEventStream, getCurrentTools, getCurrentSystemPrompt } from "@earendil-works/pi-ai";
import type { AssistantMessage } from "@earendil-works/pi-ai";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function fixture(pi: ExtensionAPI) {
  pi.registerProvider("papercut-fixture", {
    api: "papercut-fixture",
    baseUrl: "https://fixture.invalid",
    apiKey: "test-only",
    models: [{ id: "offline", name: "Offline papercut test", reasoning: false, input: ["text"],
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 }, contextWindow: 200000, maxTokens: 1024 }],
    streamSimple(model, context) {
      const stream = createAssistantMessageEventStream();
      const called = context.messages.some(message => message.role === "toolResult");
      const names = getCurrentTools(context.messages).map(tool => tool.name).sort();
      const output: AssistantMessage = {
        role: "assistant", provider: model.provider, model: model.id, api: model.api,
        timestamp: Date.now(), stopReason: "pending", content: [],
        usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
          cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      };
      stream.push({ type: "start", partial: output });
      const route = process.env.PI_FM_TEST_ROUTE;
      if (!called && (route === "reader" || names.includes("papercut"))) {
        const fixtureLog = 'Isolated runtime fixture, not a production papercut.';
        let name = "papercut";
        let args: Record<string, unknown> = { text: fixtureLog, kind: "tool" };
        if (route === "tactic-direct" || route === "tactic-codemode") {
          name = "fm_tactic_file";
          args = JSON.parse(process.env.PI_FM_TEST_TACTIC_PARAMS || '{}');
          if (route === "tactic-codemode") {
            name = "codemode";
            args = { code: `text(await tools.fm_tactic_file(${JSON.stringify(args)}));` };
          }
        } else if (route === "text-direct" || route === "text-codemode") {
          name = "fm_write_text";
          args = JSON.parse(process.env.PI_FM_TEST_TEXT_PARAMS || '{}');
          if (route === "text-codemode") {
            name = "codemode";
            args = { code: `text(await tools.fm_write_text(${JSON.stringify(args)}));` };
          }
        } else if (route === "skills-direct" || route === "skills-dynamics-direct") {
          name = "fm_read_skill";
          args = { id: route === "skills-dynamics-direct" ? "fm-playing-time-dynamics" : "fm-recruitment" };
        } else if (route === "skills-codemode") {
          name = "codemode";
          args = { code: 'text(await tools.fm_read_skill({id:"index"})); for (const id of ["fm-tools","fm-live-investigation","fm-tactical-analysis","fm-create-tactic","fm-club-finance","fm-squad-planning","fm-training-development","fm-staff-planning","fm-contracts-loans","fm-season-planning","fm-recruitment","fm-playing-time-dynamics","fm-set-pieces","fm-club-development"]) text(await tools.fm_read_skill({id})); try { text(await tools.fm_read_skill({id:"../../etc/passwd"})); } catch (error) { text({invalid_rejected:true,error:String(error)}); }' };
        } else if (route === "codemode") {
          name = "codemode";
          args = { code: `text(await tools.papercut(${JSON.stringify(args)}));` };
        } else if (route === "reader") {
          name = "codemode";
          args = { code: 'const found = ALL_TOOLS.some(t => t.name === "mcp__fm_live__fm_status"); if (found) text(await tools.mcp__fm_live__fm_status({})); else text("reader absent");' };
        }
        const call = { type: "toolCall" as const, id: "fixture-call", name, arguments: args };
        output.content.push(call);
        stream.push({ type: "toolcall_start", contentIndex: 0, partial: output });
        stream.push({ type: "toolcall_delta", contentIndex: 0, delta: JSON.stringify(call.arguments), partial: output });
        stream.push({ type: "toolcall_end", contentIndex: 0, toolCall: call, partial: output });
        output.stopReason = "toolUse";
      } else {
        const text = JSON.stringify({ declaredTools: names, guidanceIndexLoaded: getCurrentSystemPrompt(context.messages).includes("# Football guidance"), loadedGuides: ["# Using pi-fm tools", "# FM live investigation", "# Evidence-based tactical analysis", "# Create a native tactic", "# Club finance", "# Squad construction", "# Training and development", "# Staff planning", "# Contracts and loans", "# Season and competition planning", "# Recruitment decisions", "# Playing time and dynamics"].filter(heading => getCurrentSystemPrompt(context.messages).includes(heading)) });
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
