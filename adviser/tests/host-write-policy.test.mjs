import assert from 'node:assert/strict';
import { registerHooks } from 'node:module';
import test from 'node:test';
import { pathToFileURL } from 'node:url';

registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier === '@earendil-works/pi-coding-agent') return {
      url: new URL('./mcp-stub.mjs', import.meta.url).href, shortCircuit: true,
    };
    return nextResolve(specifier, context);
  },
});
const source = process.env.PI_FM_POLICY_SOURCE;
const { default: extend } = await import(source ? pathToFileURL(source).href : '../pi/fm.pi.ts');
const exact = [
  'mcp__fm_live__fm_record_current_match',
  'mcp__fm_live__fm_get_current_match',
  'mcp__fm_live__fm_get_current_match_shot_origins',
  'mcp__fm_live__fm_report_retained_match_periods',
  'mcp__fm_live__fm_report_retained_pass_network_by_period',
  'mcp__fm_live__fm_report_retained_possession_by_period',
];
function fixture() {
  const handlers = new Map(), tools = [];
  extend({ registerTool: tool => tools.push(tool), registerMcpServer() {},
    on: (event, callback) => handlers.set(event, callback), getAllTools: () => tools });
  return { tools, call: name => handlers.get('tool_call')({ toolName: name, input: { link_retained: true } }) };
}

for (const name of exact) {
  test(`permits exact registered false host writer ${name}`, () => {
    const f = fixture();
    assert.equal(f.call(name)?.block, true, 'unregistered name must not acquire access');
    const tool = { name, annotations: { readOnlyHint: false } };f.tools.push(tool);
    assert.equal(f.call(name), undefined);
    tool.annotations.readOnlyHint = true;
    assert.equal(f.call(name), undefined, 'existing true behavior remains');
    for (const hint of [undefined, null, 0, 1, '', 'false', 'true', [], {}]) {
      tool.annotations.readOnlyHint = hint;
      assert.equal(f.call(name)?.block, true, `nonboolean ${JSON.stringify(hint)}`);
    }
    delete tool.annotations;
    assert.equal(f.call(name)?.block, true);
    f.tools.pop();
    assert.equal(f.call(name)?.block, true, 'revoked registration must revoke access');
  });
}

test('rejects every near-name, foreign-server and unrelated false tool', () => {
  const f = fixture();
  const denied = [
    'mcp__fm_live__fm_set_tactic', 'mcp__fm_live__fm_write_save',
    'mcp__fm_live__fm_native_call', 'mcp__fm_live__fm_observation_delete',
    'mcp__fm_live__fm_get_save', 'mcp__fm_live__fm_report_other',
    ...exact.flatMap(name => [name + '_extra', name + '_delete', name.toUpperCase(),
      name.replace('mcp__fm_live__', 'mcp__other__'), name.replace('mcp__fm_live__', ''), name + ' ']),
  ];
  for (const name of denied) {
    f.tools.push({ name, annotations: { readOnlyHint: false } });
    assert.equal(f.call(name)?.block, true, name);
  }
});

test('keeps true FM reads and existing bounded local tools while rejecting other surfaces', () => {
  const f = fixture(), read = 'mcp__fm_live__fm_get_save';
  f.tools.push({ name: read, annotations: { readOnlyHint: true } });
  assert.equal(f.call(read), undefined);
  for (const name of ['codemode', 'papercut', 'fm_read_skill', 'fm_tactic_file', 'fm_write_text']) {
    assert.equal(f.call(name), undefined, name);
  }
  if (!f.tools.some(tool => tool.name === 'fm_match_report')) f.tools.push({ name: 'fm_match_report' });
  assert.equal(f.call('fm_match_report'), undefined);
  f.tools.splice(f.tools.findIndex(tool => tool.name === 'fm_match_report'), 1);
  assert.equal(f.call('fm_match_report')?.block, true);
  for (const name of ['bash', 'read', 'write', 'computer', 'mcp__other__fm_get_save', 'fm_read_skill_extra']) {
    f.tools.push({ name, annotations: { readOnlyHint: true } });
    assert.equal(f.call(name)?.block, true, name);
  }
  f.tools.find(tool => tool.name === read).annotations.readOnlyHint = false;
  assert.equal(f.call(read)?.block, true);
});
