// Runs the FM reader inside the Mac's desktop login when pi-fm was started outside it.
//
// macOS lets a process read Football Manager's memory only from the desktop login session.
// SSH and mosh logins get a separate background session, so the reader there fails with
// task_for_pid_failed and no password prompt ever appears. bin/pi-fm detects that case and sets
// PI_FM_DESKTOP_READER=1; the reader and match-report runs then go through a launchd agent that
// lives in the desktop session and is reached over a Unix socket.
//
//   node pi/fm-desktop-reader.mjs install          load the agent (run once from the desktop)
//   node pi/fm-desktop-reader.mjs status           report whether the agent is loaded
//   node pi/fm-desktop-reader.mjs connect <kind>   bridge stdio to the agent (kind: mcp, match-report)

import { spawn, spawnSync } from 'node:child_process';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

export const LABEL = 'com.jamesheffernan.pi-fm-desktop-reader';
export const DEFAULT_LAUNCHER = '/Volumes/4TB Private/Offloaded/FMCP 27/scripts/run_mcp.sh';
const DEFAULT_CACHE = '/Volumes/4TB Private/Offloaded/Agent Work/fmcp-source-cache';
const THIS_FILE = fileURLToPath(import.meta.url);
const SCRIPTS = { mcp: 'run_mcp.sh', 'match-report': 'run_match_report.sh' };

export const socketPath = (env = process.env) =>
  env.PI_FM_DESKTOP_READER_SOCKET || join(env.HOME || homedir(), '.pi', 'fm-desktop-reader.sock');
const plistPath = (env = process.env) => join(env.HOME || homedir(), 'Library', 'LaunchAgents', `${LABEL}.plist`);
const logPath = (env = process.env) => join(env.HOME || homedir(), '.pi', 'fm-desktop-reader.log');

/** The script that serves one request kind directly, in this process's own session. */
export function directScript(kind, env = process.env) {
  if (!SCRIPTS[kind]) throw new Error(`unknown FM reader request: ${kind}`);
  const launcher = env.PI_FM_MCP_LAUNCHER || DEFAULT_LAUNCHER;
  return kind === 'mcp' ? launcher : join(dirname(launcher), SCRIPTS[kind]);
}

/** How pi-fm starts the reader (kind "mcp") or a match report (kind "match-report"). */
export function readerCommand(kind, env = process.env) {
  if (env.PI_FM_DESKTOP_READER === '1') return { command: process.execPath, args: [THIS_FILE, 'connect', kind] };
  return { command: '/bin/sh', args: [directScript(kind, env)] };
}

// Runs in the agent with stdin and stdout on the accepted socket. It reads the request line one
// byte at a time (the shell does this on sockets), so the rest of the stream reaches the script.
export const SERVE_SCRIPT = [
  'exec 2>>"$2"',
  'IFS= read -r kind || exit 2',
  'case "$kind" in',
  '  mcp) exec /bin/sh "$1/run_mcp.sh" ;;',
  '  match-report) exec /bin/sh "$1/run_match_report.sh" ;;',
  '  *) echo "pi-fm desktop reader: unknown request: $kind" >&2; exit 2 ;;',
  'esac',
].join('\n');

const xml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
const plistValue = (value, indent) => {
  const pad = '  '.repeat(indent);
  if (typeof value === 'boolean') return `${pad}<${value}/>`;
  if (typeof value === 'number') return `${pad}<integer>${value}</integer>`;
  if (Array.isArray(value)) return [`${pad}<array>`, ...value.map(item => plistValue(item, indent + 1)), `${pad}</array>`].join('\n');
  if (value && typeof value === 'object') {
    return [`${pad}<dict>`, ...Object.entries(value).flatMap(([key, item]) => [`${pad}  <key>${xml(key)}</key>`, plistValue(item, indent + 1)]), `${pad}</dict>`].join('\n');
  }
  return `${pad}<string>${xml(value)}</string>`;
};

/** The launchd agent: one reader process per connection, in the desktop session. */
export function agentPlist(env = process.env) {
  const scripts = dirname(env.PI_FM_MCP_LAUNCHER || DEFAULT_LAUNCHER);
  const agent = {
    Label: LABEL,
    ProgramArguments: ['/bin/sh', '-c', SERVE_SCRIPT, 'pi-fm-desktop-reader', scripts, logPath(env)],
    Sockets: { Listener: { SockPathName: socketPath(env), SockPathMode: 0o600 } },
    inetdCompatibility: { Wait: false },
    LimitLoadToSessionType: 'Aqua',
    EnvironmentVariables: {
      PATH: '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin',
      FMCP_CACHE_DIR: env.FMCP_CACHE_DIR ?? DEFAULT_CACHE,
      PI_HARNESS: 'pi-fm',
    },
  };
  return `<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n<plist version="1.0">\n${plistValue(agent, 0)}\n</plist>\n`;
}

const launchctl = args => spawnSync('/bin/launchctl', args, { encoding: 'utf8' });
const domain = () => `gui/${process.getuid()}`;

function loaded() {
  return launchctl(['print', `${domain()}/${LABEL}`]).status === 0;
}

function install() {
  if (launchctl(['managername']).stdout.trim() !== 'Aqua') {
    throw new Error('run this from a Terminal on the Mac itself; the agent must load into the desktop login');
  }
  const path = plistPath();
  const body = agentPlist();
  let current = '';
  try { current = readFileSync(path, 'utf8'); } catch {}
  if (current === body && loaded()) return 'already loaded';
  mkdirSync(dirname(path), { recursive: true });
  mkdirSync(dirname(socketPath()), { recursive: true });
  writeFileSync(path, body);
  launchctl(['bootout', `${domain()}/${LABEL}`]);
  const result = launchctl(['bootstrap', domain(), path]);
  if (result.status !== 0) throw new Error(`launchctl bootstrap failed: ${(result.stderr || result.stdout).trim()}`);
  return 'loaded';
}

/** Bridges this process's stdio to the agent; runs the script directly if the agent is absent. */
export function connect(kind, env = process.env) {
  const direct = directScript(kind, env);
  const socket = net.connect(socketPath(env));
  let connected = false;
  socket.on('connect', () => {
    connected = true;
    socket.write(`${kind}\n`);
    process.stdin.pipe(socket);
    socket.pipe(process.stdout);
  });
  socket.on('error', error => {
    if (connected) {
      process.stderr.write(`pi-fm desktop reader: ${error.message}\n`);
      process.exitCode = 1;
      process.stdin.destroy();
      return;
    }
    process.stderr.write(`pi-fm desktop reader: agent not reachable (${error.code}); reading FM from this session instead. ` +
      `If FM attach fails, run "node ${THIS_FILE} install" from a Terminal on the Mac.\n`);
    const child = spawn('/bin/sh', [direct], { stdio: 'inherit', env });
    child.on('exit', (code, signal) => { process.exitCode = code ?? (signal ? 1 : 0); });
  });
  // The reader closed the connection: stop reading stdin so this process can exit.
  socket.on('close', () => { if (connected) process.stdin.destroy(); });
}

function main([command, kind]) {
  if (command === 'connect') return connect(kind);
  if (command === 'install') return console.log(`${LABEL}: ${install()}`);
  if (command === 'status') {
    const state = loaded() ? 'loaded' : 'not loaded';
    console.log(`${LABEL}: ${state}; socket ${socketPath()}`);
    process.exitCode = state === 'loaded' ? 0 : 1;
    return;
  }
  console.error('usage: fm-desktop-reader.mjs install | status | connect <mcp|match-report>');
  process.exitCode = 2;
}

if (process.argv[1] && resolve(process.argv[1]) === THIS_FILE) {
  try { main(process.argv.slice(2)); } catch (error) { console.error(`pi-fm desktop reader: ${error.message}`); process.exitCode = 1; }
}
