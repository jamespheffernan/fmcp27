// Test-only observer: exercises the display hooks through the installed Pi event pipeline.
import { writeFileSync } from 'node:fs';
import { registerActivityDisplay } from '../pi/fm-activity.mjs';

export default function observer(pi) {
  const { log, rebuild } = registerActivityDisplay(pi);
  const snapshots = [];
  const capture = (event) => {
    const id = event.parentToolCallId ?? event.toolCallId;
    snapshots.push({ event: event.type, tool: event.toolName, result: event.result, ...log.line(id) });
  };
  pi.on('tool_execution_start', capture);
  pi.on('tool_execution_end', capture);
  pi.on('agent_end', (_event, ctx) => {
    const lines = () => [...log.groupOf.keys()].filter(id => log.isLast(id)).map(id => log.line(id));
    const live = lines();
    rebuild(ctx);
    writeFileSync(process.env.PI_FM_ACTIVITY_RECEIPT, JSON.stringify({ snapshots, live, restored: lines() }, null, 2));
  });
}
