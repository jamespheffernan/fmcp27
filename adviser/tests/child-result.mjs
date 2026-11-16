// Bounded diagnostics for failed synchronous fixture/native child processes.
function bounded(value, limit) {
  const text = value == null ? '' : String(value);
  if (text.length <= limit) return text;
  const half = Math.floor(limit / 2);
  return `${text.slice(0, half)}\n[truncated ${text.length - 2 * half} characters]\n${text.slice(-half)}`;
}

export function childFailure(result, context) {
  const error = result.error;
  return [
    `context=${bounded(context, 1024)}`,
    `status=${String(result.status)} signal=${String(result.signal)}`,
    `error=${bounded(error ? `${error.name}: ${error.message}; code=${String(error.code)}; errno=${String(error.errno)}; syscall=${String(error.syscall)}\n${error.stack || ''}` : 'none', 2048)}`,
    `stdout(${result.stdout?.length ?? 0} characters)=${bounded(result.stdout, 4096)}`,
    `stderr(${result.stderr?.length ?? 0} characters)=${bounded(result.stderr, 4096)}`,
  ].join('\n');
}
