export const calls = [];
export const codemodeCalls = [];
export const toolSearchCalls = [];
export function createCodemodeExtension(options) {
  return pi => codemodeCalls.push({ options, pi });
}
export function createMcpExtension(options) {
  return pi => calls.push({ options, pi });
}
export function createToolSearchExtension() {
  return pi => {
    toolSearchCalls.push({ pi });
    pi.registerTool?.({ name: 'tool_search' });
  };
}
