import assert from 'node:assert/strict';
import { spawn, spawnSync } from 'node:child_process';
import { chmodSync, mkdirSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs';
import net from 'node:net';
import { tmpdir } from 'node:os';
import { dirname, join } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

import { DEFAULT_LAUNCHER, SERVE_SCRIPT, agentPlist, directScript, readerCommand } from '../pi/fm-desktop-reader.mjs';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const client = join(root, 'pi/fm-desktop-reader.mjs');

function scratch(t) {
  // Short path: Unix socket paths are limited to 104 bytes.
  const dir = mkdtempSync('/tmp/pfdr-');
  t.after(() => rmSync(dir, { recursive: true, force: true }));
  return dir;
}

function run(command, args, { input, env }) {
  return new Promise(resolve => {
    const child = spawn(command, args, { env });
    let stdout = '', stderr = '';
    child.stdout.on('data', chunk => { stdout += chunk; });
    child.stderr.on('data', chunk => { stderr += chunk; });
    child.on('exit', code => resolve({ code, stdout, stderr }));
    child.stdin.end(input);
  });
}

test('routes the reader directly in the desktop login and through the agent elsewhere', () => {
  assert.deepEqual(readerCommand('mcp', {}), { command: '/bin/sh', args: [DEFAULT_LAUNCHER] });
  assert.deepEqual(readerCommand('match-report', { PI_FM_MCP_LAUNCHER: '/x/scripts/run_mcp.sh' }),
    { command: '/bin/sh', args: ['/x/scripts/run_match_report.sh'] });
  assert.deepEqual(readerCommand('mcp', { PI_FM_DESKTOP_READER: '1' }),
    { command: process.execPath, args: [client, 'connect', 'mcp'] });
  assert.throws(() => directScript('shell', {}), /unknown FM reader request/);
});

test('the agent is socket-activated in the desktop session and runs only the two reader scripts', t => {
  const dir = scratch(t);
  const env = { HOME: dir, PI_FM_MCP_LAUNCHER: '/x/FMCP & co/scripts/run_mcp.sh', FMCP_CACHE_DIR: '/cache' };
  const path = join(dir, 'agent.plist');
  writeFileSync(path, agentPlist(env));
  assert.equal(spawnSync('/usr/bin/plutil', ['-lint', path]).status, 0);
  const agent = JSON.parse(spawnSync('/usr/bin/plutil', ['-convert', 'json', '-o', '-', path], { encoding: 'utf8' }).stdout);
  assert.equal(agent.LimitLoadToSessionType, 'Aqua');
  assert.deepEqual(agent.inetdCompatibility, { Wait: false });
  assert.deepEqual(agent.Sockets.Listener, { SockPathName: join(dir, '.pi/fm-desktop-reader.sock'), SockPathMode: 0o600 });
  assert.deepEqual(agent.ProgramArguments.slice(3), ['pi-fm-desktop-reader', '/x/FMCP & co/scripts', join(dir, '.pi/fm-desktop-reader.log')]);
  assert.equal(agent.EnvironmentVariables.FMCP_CACHE_DIR, '/cache');
});

test('the agent script takes the request line and hands the rest of the stream to the script', async t => {
  const dir = scratch(t);
  writeFileSync(join(dir, 'run_mcp.sh'), 'echo "mcp got: $(cat)"\n');
  writeFileSync(join(dir, 'run_match_report.sh'), 'echo "report got: $(cat)"\n');
  const serve = input => run('/bin/sh', ['-c', SERVE_SCRIPT, 'serve', dir, join(dir, 'log')], { input });
  assert.equal((await serve('mcp\n{"id":1}\n{"id":2}')).stdout, 'mcp got: {"id":1}\n{"id":2}\n');
  assert.equal((await serve('match-report\n{"source":"observed"}')).stdout, 'report got: {"source":"observed"}\n');
  const refused = await serve('/bin/rm\n');
  assert.equal(refused.code, 2);
  assert.equal(refused.stdout, '');
});

test('connect bridges stdio over the socket, including end of input', async t => {
  const dir = scratch(t);
  const sock = join(dir, 's');
  const server = net.createServer({ allowHalfOpen: true }, connection => {
    let received = '';
    connection.on('data', chunk => { received += chunk; });
    connection.on('end', () => connection.end(`server saw ${JSON.stringify(received)}`));
  });
  await new Promise(resolve => server.listen(sock, resolve));
  t.after(() => server.close());
  const result = await run(process.execPath, [client, 'connect', 'match-report'],
    { input: '{"a":1}', env: { ...process.env, PI_FM_DESKTOP_READER_SOCKET: sock } });
  assert.equal(result.code, 0, result.stderr);
  assert.equal(result.stdout, 'server saw "match-report\\n{\\"a\\":1}"');
});

test('connect runs the script in this session when the agent is not loaded', async t => {
  const dir = scratch(t);
  mkdirSync(join(dir, 'scripts'));
  const launcher = join(dir, 'scripts/run_mcp.sh');
  writeFileSync(launcher, 'echo "direct: $(cat)"; exit 3\n');
  chmodSync(launcher, 0o755);
  const result = await run(process.execPath, [client, 'connect', 'mcp'],
    { input: 'hello', env: { ...process.env, PI_FM_DESKTOP_READER_SOCKET: join(dir, 'missing'), PI_FM_MCP_LAUNCHER: launcher } });
  assert.equal(result.stdout, 'direct: hello\n');
  assert.equal(result.code, 3);
  assert.match(result.stderr, /agent not reachable/);
});

test('pi-fm uses the agent only outside the desktop login and only for the default reader', t => {
  const dir = scratch(t);
  const bin = join(dir, 'bin');
  mkdirSync(bin);
  // Stand-ins: launchctl reports the session type; pi prints what pi-fm passed on.
  writeFileSync(join(bin, 'pi'), '#!/bin/sh\necho "reader=${PI_FM_DESKTOP_READER-unset}"\n');
  chmodSync(join(bin, 'pi'), 0o755);
  const launchctl = join(dir, 'launchctl');
  const piFm = join(dir, 'pi-fm');
  // bin/pi-fm calls /bin/launchctl by absolute path; point a copy at the stand-in.
  const source = spawnSync('/bin/cat', [join(root, 'bin/pi-fm')], { encoding: 'utf8' }).stdout;
  writeFileSync(piFm, source.replace('root="${0:A:h:h}"', `root=${JSON.stringify(root)}`).replace('/bin/launchctl', launchctl));
  chmodSync(piFm, 0o755);
  const start = (session, extra = {}) => {
    writeFileSync(launchctl, `#!/bin/sh\necho ${session}\n`);
    chmodSync(launchctl, 0o755);
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, ...extra };
    for (const key of ['PI_FM_DESKTOP_READER', 'PI_FM_MCP_LAUNCHER', 'SSH_CONNECTION', 'SSH_TTY']) if (!(key in extra)) delete env[key];
    return spawnSync(piFm, ['--version'], { encoding: 'utf8', env }).stdout.trim();
  };
  assert.equal(start('Aqua'), 'reader=unset');
  assert.equal(start('Background'), 'reader=1');
  assert.equal(start('Aqua', { SSH_CONNECTION: '10.0.0.2 5000 10.0.0.1 22' }), 'reader=1');
  assert.equal(start('Background', { PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh') }), 'reader=unset');
  assert.equal(start('Background', { PI_FM_DESKTOP_READER: '0' }), 'reader=0');
});
