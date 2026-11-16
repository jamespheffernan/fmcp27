// Test preload only: deny real reader/helper/game launches before creating a child.
const child = require('node:child_process');
const fs = require('node:fs');
const { syncBuiltinESMExports } = require('node:module');
const trace = process.env.PI_FM_TEST_PROCESS_TRACE;
if (!trace) throw new Error('Offline process guard requires its isolated trace file');
const realLauncher = '/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh';
for (const method of ['spawn', 'spawnSync', 'execFile', 'execFileSync', 'exec', 'execSync', 'fork']) {
  const original = child[method];
  child[method] = function(command, args, ...rest) {
    const words = [String(command), ...(Array.isArray(args) ? args.filter(v => typeof v === 'string') : [])];
    const denied = words.some(value => value.includes(realLauncher) || value.includes('fm_live_helper') || /Football Manager (?:26|27)(?:\.app(?:\/|$)|\/|$|["'])/.test(value) || /(?:^|\/)fm(?:$|["'\s])/.test(value));
    fs.appendFileSync(trace, JSON.stringify({ method, command: String(command).slice(0, 1024), args: words.slice(1).map(v => v.slice(0, 1024)), denied }) + '\n');
    if (denied) {
      const error = new Error('OFFLINE_REAL_READER_LAUNCH_DENIED');
      error.code = 'OFFLINE_REAL_READER_LAUNCH_DENIED';
      throw error;
    }
    return original.call(this, command, args, ...rest);
  };
}
syncBuiltinESMExports();
