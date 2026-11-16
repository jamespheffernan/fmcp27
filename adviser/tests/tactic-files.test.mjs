import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, symlinkSync, readFileSync, writeFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';
import { runTacticFile } from '../pi/fm-tactic-files.mjs';
import { childFailure } from './child-result.mjs';

const python = '/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/bin/python';
const adapter = fileURLToPath(new URL('../pi/fm-tactic-files.py', import.meta.url));

test('real native FM27 templates support roundtrip, preserve unedited bytes and reject unsupported requests', async t => {
  const catalog = spawnSync(python, ['-c', `
import importlib.util, json
spec = importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
print(json.dumps([str(path) for path in m.TEMPLATES.glob('*.fmf')]))
`], { encoding: 'utf8', timeout: 60_000 });
  assert.equal(catalog.status, 0, childFailure(catalog, `native template catalog; python=${python}`));
  const templates = JSON.parse(catalog.stdout);
  assert.ok(templates.length >= 6);
  for (const template of templates) await t.test(template.split('/').at(-1), () => {
    const result = spawnSync(python, ['-c', `
import importlib.util, pathlib, tempfile, json, hashlib, sys
spec = importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
scratch_root = pathlib.Path(m.__file__).resolve().parent.parent / 'tmp'
scratch_root.mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(dir=scratch_root) as scratch:
    m.OUTPUTS = pathlib.Path(scratch)
    templates = [pathlib.Path(sys.argv[1])]
    for template in templates:
        original = template.read_bytes()
        source = m.summarize(str(template))
        params = dict(action='generate', template_path=str(template), template_sha256=source['template_sha256'], name='Roundtrip Ç New Name', mentality='Cautious')
        result = m.generate(params)
        output = pathlib.Path(result['output_path'])
        assert output.read_bytes()[:9] == original[:9]
        assert result['verification']['all_unrequested_tactic_bytes_preserved']
        assert result['verification']['game_load_verified'] is False
        assert result['name'] == 'Roundtrip Ç New Name'
        assert result['stored_football'] == source['stored_football']
        assert result['mentality'] == 'Cautious'
        assert template.read_bytes() == original
        toc = m.probe(output)['toc']['strings']
        assert sum(x['text'] == 'Roundtrip Ç New Name' for x in toc) == 2
        assert str(output).startswith(scratch)
        again = m.generate(params)
        assert result['output_path'] != again['output_path']
        assert output.exists()
        for label in ['No explicit selection', 'Get Stuck In', 'Stay On Feet']:
            tackle_result = m.generate(params | dict(team_tackling=label))
            assert tackle_result['team_tackling'] == label
            assert tackle_result['verification']['all_unrequested_tactic_bytes_preserved']
        for changes in [dict(template_sha256='0'*64),dict(formation='4-3-3'),dict(name=''),dict(mentality='invented'),dict(team_tackling='Standard')]:
            bad = params | changes
            before = sorted(pathlib.Path(scratch).rglob('*'))
            try:
                m.generate(bad)
                raise AssertionError('unsupported generation succeeded')
            except ValueError:
                pass
            assert sorted(pathlib.Path(scratch).rglob('*')) == before
    print(json.dumps({'native_templates_roundtripped': len(templates)}))
`, template], { encoding: 'utf8', timeout: 60_000 });
    assert.equal(result.status, 0, childFailure(result, `native template roundtrip; python=${python}; template=${template}`));
    assert.equal(JSON.parse(result.stdout).native_templates_roundtripped, 1);
  });
});

test('process adapter lists existing templates and returns source versions instead of upgrading them', async () => {
  const result = await runTacticFile({ action: 'list_templates' });
  assert.ok(result.templates.length >= 6);
  assert.equal(result.excluded.length, 0);
  for (const template of result.templates) {
    assert.equal(template.stored_football.phase_positions_and_roles.in_possession.length, 11);
    assert.equal(template.stored_football.phase_positions_and_roles.out_of_possession.length, 11);
    assert.equal(template.stored_football.formation, null);
  }
  const base = result.templates.find(t => t.name === '3421 FM27 ');
  assert.equal(base.stored_football.phase_positions_and_roles.in_possession[0].role, 'Ball-Playing Goalkeeper');
  assert.ok(base.stored_football.stored_team_instructions.some(t => t.name === 'Get Stuck In'));
  assert.deepEqual(new Set(result.templates.map(t => t.source_game_major)), new Set([26, 27]));
  assert.deepEqual(result.supported_edits, ['name', 'mentality', 'team_tackling', 'defensive_line', 'tempo', 'passing_directness', 'team_width', 'pressing_frequency', 'goal_kick_length', 'crossing_style', 'final_third_delivery', 'pressing_block', 'focus_play', 'wide_support', 'base_role', 'stored_role_instructions', 'phase_position', 'native_authoring', 'possession_loss', 'possession_gain']);
  await assert.rejects(runTacticFile({ action: 'generate', name: 'Invalid', template_path: '/tmp/unknown.fmf', template_sha256: 'bad' }));
});

test('FM27 destination uses a safe name, supports custom user data and refuses output or receipt collisions', () => {
  const result = spawnSync(python, ['-c', `
import importlib.util, pathlib, tempfile, json
spec = importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
source = m.summarize(str(next(m.TEMPLATES.glob('*.fmf'))))
with tempfile.TemporaryDirectory() as scratch:
    root = pathlib.Path(scratch).resolve()
    m.OUTPUTS = root / 'Agent Outputs'
    m.TEMPLATES = root / 'default-user-data' / 'Tactics'
    m.TEMPLATES.mkdir(parents=True)
    params = dict(action='generate', template_path=source['template_path'], template_sha256=source['template_sha256'], name='Newcastle 3421 Positive - Stay On Feet', mentality='Positive', team_tackling='Stay On Feet', fm27_folder=True)
    made = m.generate(params)
    output = pathlib.Path(made['output_path'])
    assert output == m.TEMPLATES / 'Newcastle 3421 Positive - Stay On Feet.fmf'
    assert made['destination'] == 'fm27_tactics'
    original = output.read_bytes()
    receipt = pathlib.Path(made['receipt_path']).read_bytes()
    try:
        m.generate(params)
        raise AssertionError('Existing file was overwritten')
    except FileExistsError:
        pass
    assert output.read_bytes() == original
    assert pathlib.Path(made['receipt_path']).read_bytes() == receipt
    try:
        m.generate(params | dict(name=params['name'].lower()))
        raise AssertionError('Case-folded collision was accepted')
    except FileExistsError:
        pass
    custom = root / 'custom-user-data' / 'Tactics'
    custom.mkdir(parents=True)
    escaped = m.generate(params | dict(name='Unsafe: Name', tactics_directory=str(custom)))
    assert pathlib.Path(escaped['output_path']).parent == custom
    assert pathlib.Path(escaped['receipt_path']).parent == custom / '.fm-tactics-receipts'
    try:
        m.generate(params | dict(name='../../Unsafe Name', tactics_directory=str(custom)))
        raise AssertionError('Traversal name was accepted')
    except ValueError:
        pass
    blocked = custom / '.fm-tactics-receipts' / 'Receipt Collision.receipt.json'
    blocked.write_text('existing receipt')
    try:
        m.generate(params | dict(name='Receipt Collision', tactics_directory=str(custom)))
        raise AssertionError('Existing receipt was overwritten')
    except FileExistsError:
        pass
    assert blocked.read_text() == 'existing receipt'
    assert not (custom / 'Receipt Collision.fmf').exists()
    # Simulate a receipt failure after the artifact was exclusively created.
    real_dump = m.json.dump
    def failed_dump(*args, **kwargs):
        raise OSError('simulated receipt write failure')
    m.json.dump = failed_dump
    try:
        m.generate(params | dict(name='Failed Receipt', tactics_directory=str(custom)))
        raise AssertionError('Receipt write failure was ignored')
    except OSError:
        pass
    finally:
        m.json.dump = real_dump
    assert not (custom / 'Failed Receipt.fmf').exists()
    assert not (custom / '.fm-tactics-receipts' / 'Failed Receipt.receipt.json').exists()
    inherited = m.generate({k:v for k,v in params.items() if k != 'fm27_folder'})
    assert pathlib.Path(inherited['output_path']).is_relative_to(m.OUTPUTS)
    assert inherited['destination'] == 'agent_outputs'
    print(json.dumps({'fm27_default':True,'custom_user_data':True,'safe_filename':True,'no_overwrite':True,'agent_outputs_preserved':True}))
`], { encoding: 'utf8', timeout: 30_000 });
  assert.equal(result.status, 0, result.stderr);
  assert.ok(JSON.parse(result.stdout).no_overwrite);
});


for (const route of ['tactic-direct', 'tactic-codemode']) {
  test(`offline Pi fixture dispatch creates a real native tactic through ${route}`, async () => {
    const root = fileURLToPath(new URL('../', import.meta.url));
    mkdirSync(join(root, 'evidence'), { recursive: true });
    const scratch = mkdtempSync(join(root, 'evidence', `${route}-`));
    mkdirSync(join(scratch, '.agents'));
    symlinkSync(join(homedir(), '.agents', 'skills'), join(scratch, '.agents', 'skills'));
    const templates = await runTacticFile({ action: 'list_templates' });
    const template = templates.templates.find(t => t.source_game_major === 27);
    const params = { action: 'generate', template_path: template.template_path, template_sha256: template.template_sha256, name: `Pi Runtime ${route}`, mentality: 'Positive', team_tackling: 'Stay On Feet' };
    const run = spawnSync(join(root, 'bin/pi-fm'), [
      '-e', join(root, 'tests/papercut-provider.pi.ts'), '--no-mcp', '--no-session', '--mode', 'json', '--print', 'Create a native tactic',
    ], {
      encoding: 'utf8', timeout: 30_000, maxBuffer: 8 * 1024 * 1024,
      env: { ...process.env, HOME: scratch, PI_CODING_AGENT_DIR: join(scratch, '.pi', 'agent'), PI_FM_MODEL: 'papercut-fixture/offline',
        PI_FM_TEST_ROUTE: route, PI_FM_TEST_TACTIC_PARAMS: JSON.stringify(params), PI_OFFLINE: '1',
        PI_FM_MCP_LAUNCHER: join(root, 'tests/startup-reader-fixture.sh'), PI_FM_TEST_READER_DIR: scratch,
        PI_FM_TEST_FAILED_STARTS: '0', PI_FM_TEST_FIRST_DELAY: '0',
        PI_FM_TEST_PROCESS_TRACE: join(scratch, 'process-launches.jsonl'),
        NODE_OPTIONS: `${process.env.NODE_OPTIONS || ''} --require=${JSON.stringify(join(root, 'tests/offline-reader-launch-guard.cjs'))}` },
    });
    writeFileSync(join(scratch, 'offline-pi.jsonl'), run.stdout);
    writeFileSync(join(scratch, 'offline-pi.stderr'), run.stderr);
    assert.equal(run.status, 0, childFailure(run, `offline Pi fixture dispatch; route=${route}`));
    const launches = readFileSync(join(scratch, 'process-launches.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.ok(launches.some(row => row.command === '/bin/sh' && row.args.includes(join(root, 'tests/startup-reader-fixture.sh'))));
    assert.ok(launches.every(row => row.denied === false), JSON.stringify(launches));
    const requests = readFileSync(join(scratch, 'requests.jsonl'), 'utf8').trim().split('\n').map(JSON.parse);
    assert.ok(requests.some(row => row.method === 'initialize'));
    assert.ok(requests.some(row => row.method === 'tools/list'));
    // The harness's own fm_attach before the first model call (pi/fm-reader-session.mjs) is the one
    // reader call; writing a tactic makes none.
    assert.deepEqual(requests.filter(row => row.method === 'tools/call').map(row => row.name), ['fm_attach']);
    assert.equal(readFileSync(join(scratch, 'attempts'), 'utf8'), '1');
    const events = run.stdout.trim().split('\n').map(JSON.parse);
    const generated = events.find(e => e.type === 'tool_execution_end' && e.toolName === 'fm_tactic_file');
    assert.ok(generated, run.stdout);
    assert.equal(generated.isError, false);
    const details = generated.result.details;
    assert.equal(details.verification.game_load_verified, false);
    assert.equal(details.team_tackling, 'Stay On Feet');
    assert.ok(details.output_path.startsWith(join(scratch, 'Agent Outputs')));
    assert.equal(readFileSync(details.output_path).subarray(2, 6).toString(), 'afe.');
    assert.equal(JSON.parse(readFileSync(details.receipt_path)).output_sha256, details.output_sha256);
    if (route === 'tactic-codemode') assert.ok(events.some(e => e.type === 'tool_execution_end' && e.toolName === 'codemode' && !e.isError));
  });
}


test('native position read parser rejects truncated position streams and unknown record versions', () => {
  const run = spawnSync(python, ['-c', `
import importlib.util, sys
sys.path.insert(0, ${JSON.stringify(fileURLToPath(new URL('../pi/', import.meta.url)))})
spec = importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
for path in m.TEMPLATES.glob('*.fmf'):
    _, _, members = m.read_template(str(path))
    tac = members['.tac']
    first = m.parse_tac_plaintext(tac)['tactical_style']['end_exclusive'] + 4
    decoded = m.decode_position_records(tac, first)
    for broken in [tac[:first+3],tac[:decoded['records_end_exclusive']-1],tac[:first]+b'\\x42'+tac[first+1:]]:
        try:
            m.decode_position_records(broken, first)
            raise AssertionError('invalid native position records accepted')
        except ValueError:
            pass
print('ok')
`], { encoding: 'utf8', timeout: 30_000 });
  assert.equal(run.status, 0, run.stderr);
  assert.equal(run.stdout.trim(), 'ok');
});

test('defensive-line preview preserves inheritance and creates no destination files', () => {
  const result = spawnSync(python, ['-c', `
import importlib.util, pathlib, tempfile
spec=importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
source=m.summarize(str(next(m.TEMPLATES.glob('3421 FM27 .fmf'))))
with tempfile.TemporaryDirectory() as td:
    dest=pathlib.Path(td)
    params=dict(action='generate',template_path=source['template_path'],template_sha256=source['template_sha256'],name='Preview Higher',fm27_folder=True,tactics_directory=str(dest),preview=True)
    for selection in [None,*m.DEFENSIVE_LINE_FLAGS]:
        request=params if selection is None else params | dict(defensive_line=selection)
        result=m.generate(request)
        assert result['status']=='preview' and result['files_created'] is False
        assert result['defensive_line']==(source['defensive_line'] if selection is None else selection)
        assert result['defensive_line_mode']==('inherit' if selection is None else 'explicit_change')
        assert not list(dest.iterdir())
    actual=m.generate(params | dict(preview=False,defensive_line='Higher Defensive Line'))
    assert m.summarize(actual['output_path'])['defensive_line']=='Higher Defensive Line'
    assert actual['verification']['all_unrequested_tactic_bytes_preserved']
`], {encoding:'utf8',timeout:30000});
  assert.equal(result.status,0,result.stderr);
});

test('conflicting stored heights permit unrelated inherited edits but reject height changes', () => {
  const run = spawnSync(python, ['-c', `
import importlib.util,pathlib,tempfile
spec=importlib.util.spec_from_file_location('tactic_files', ${JSON.stringify(adapter)})
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
source=next(m.TEMPLATES.glob('3421 FM27 .fmf'))
_,_,members=m.read_template(str(source))
offset,_=m.defensive_line_selection(members['.tac']);tac=bytearray(members['.tac']);tac[offset]=(tac[offset]&240)|3
with tempfile.TemporaryDirectory() as td:
    root=pathlib.Path(td);m.OUTPUTS=root/'outputs';target=root/'source.fmf'
    m.repack_native_fmf(source,target,plaintext_overrides={'.tac':bytes(tac)})
    summary=m.summarize(str(target));assert summary['defensive_line'] is None
    assert 'defensive_line' not in summary['supported_edits']
    params=dict(template_path=str(target),template_sha256=summary['template_sha256'],name='Conflict inheritance')
    for preview in [True,False]:
        result=m.generate(params|dict(preview=preview));assert result['defensive_line'] is None
        assert result['defensive_line_state']=='conflicting_stored_selections'
        assert result['verification']['all_unrequested_tactic_bytes_preserved']
        try:m.generate(params|dict(preview=preview,defensive_line='Higher Defensive Line'))
        except ValueError as e:assert 'contradictory' in str(e)
        else:raise AssertionError('Conflicting edit accepted')
`], {encoding:'utf8',timeout:30000});
  assert.equal(run.status,0,run.stderr);
});
