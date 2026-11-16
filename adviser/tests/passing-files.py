"""Stored passing edits on real native archives; no live FM or import claim."""
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
expected = {'No explicit selection': 0, 'Much More Direct Passing': 2,
            'More Direct Passing': 4, 'Shorter Passing': 8, 'Much Shorter Passing': 16}
mask = 0x1e
templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert templates, 'Real native templates are required'
representatives = {}
for template in templates:
    source = template.read_bytes()
    _, _, members = m.read_template(str(template))
    tac = members['.tac']
    offset = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    original_flags = int.from_bytes(tac[offset:offset + 12], 'little')
    # Prefer genuinely selected sources for the native before/after control.
    if original_flags & mask:
        representatives.setdefault(tac[11], template)
    for name, bits in expected.items():
        modified = m.replace_passing(tac, name)
        flags = int.from_bytes(modified[offset:offset + 12], 'little')
        assert modified[:offset] == tac[:offset]
        assert modified[offset + 12:] == tac[offset + 12:]
        assert flags & mask == bits
        assert flags & ~mask == original_flags & ~mask
        assert m.passing_selection(modified) == (offset, name)
        selected = m.inspect_stored_football(modified)['stored_team_instructions']
        assert [v for v in selected if 1 <= v['native_option_id'] <= 4] == (
            [] if bits == 0 else [{'native_option_id': bits.bit_length() - 1, 'name': name}])
        # Exercise bit0, adjacent bit5 and every remaining bit even if the
        # real source does not happen to select them.
        sentinel_flags = ((1 << 96) - 1) & ~mask
        sentinel = tac[:offset] + sentinel_flags.to_bytes(12, 'little') + tac[offset + 12:]
        sentinel_after = m.replace_passing(sentinel, name)
        assert int.from_bytes(sentinel_after[offset:offset + 12], 'little') == sentinel_flags | bits
    for count in range(2, 5):
        for bits in itertools.combinations(range(1, 5), count):
            flags = (original_flags & ~mask) | sum(1 << bit for bit in bits)
            bad = tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]
            assert m.describe_passing(bad) == {
                'passing_directness': None, 'passing_directness_state': 'conflicting_stored_selections'}
            for name in expected:
                try:
                    m.replace_passing(bad, name)
                except ValueError as error:
                    assert 'contradictory' in str(error)
                else:
                    raise AssertionError('Conflicting passing source was overwritten')
    assert template.read_bytes() == source

assert set(representatives) == {26, 27}, 'Need selected passing controls from native FM26 and FM27 archives'
root = Path(tempfile.mkdtemp(prefix='passing-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
generated = 0
changed_controls = []


def assert_no_files_on_error(params, fragment):
    before = sorted(root.rglob('*'))
    try:
        m.generate(params)
    except (ValueError, FileExistsError) as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError('Invalid edit unexpectedly generated a tactic')
    assert sorted(root.rglob('*')) == before


for version, template in sorted(representatives.items()):
    source = template.read_bytes()
    summary = m.summarize(str(template))
    _, _, before_members = m.read_template(str(template))
    before_tac = before_members['.tac']
    offset = m.parse_tac_plaintext(before_tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    before_flags = int.from_bytes(before_tac[offset:offset + 12], 'little')
    params = dict(template_path=str(template), template_sha256=summary['template_sha256'],
                  name='Passing Native Verification')
    for name, bits in expected.items():
        result = m.generate(params | dict(passing_directness=name))
        output = m.summarize(result['output_path'])
        _, _, after_members = m.read_template(result['output_path'])
        after_tac = m.replace_tac_name(after_members['.tac'], summary['name'])
        after_flags = int.from_bytes(after_tac[offset:offset + 12], 'little')
        assert output['passing_directness'] == name
        assert after_flags == (before_flags & ~mask) | bits
        assert after_tac[:offset] == before_tac[:offset]
        assert after_tac[offset + 12:] == before_tac[offset + 12:]
        assert set(after_members) == set(before_members)
        assert all(after_members[key] == before_members[key] for key in before_members if key not in ('.tac', '.aom'))
        handler = b'TACTICS_TYPE_HANDLER'
        assert m.replace_string(after_members['.aom'], 12 + len(handler), summary['name'], params['name']) == before_members['.aom']
        assert output['stored_football']['phase_positions_and_roles'] == summary['stored_football']['phase_positions_and_roles']
        assert result['passing_directness_mode'] == 'explicit_change'
        assert result['edits'] == ['name', 'passing_directness']
        assert result['verification']['all_unrequested_tactic_bytes_preserved']
        assert result['verification']['game_load_verified'] is False
        assert json.loads(Path(result['receipt_path']).read_text()) == result
        if name == 'Shorter Passing':
            assert summary['passing_directness'] == 'More Direct Passing'
            assert before_flags & mask == 4 and after_flags & mask == 8
            assert before_tac != after_tac
            changed_controls.append({'source_major': version, 'before': summary['passing_directness'],
                                     'after': name, 'output': result['output_path']})
        generated += 1
    before = sorted(root.rglob('*'))
    preview = m.generate(params | dict(passing_directness='Much Shorter Passing', preview=True))
    assert preview['status'] == 'preview' and preview['files_created'] is False
    assert preview['passing_directness'] == 'Much Shorter Passing'
    assert sorted(root.rglob('*')) == before
    inherited = m.generate(params | dict(preview=True))
    assert inherited['passing_directness'] == summary['passing_directness']
    assert inherited['passing_directness_mode'] == 'inherit' and inherited['edits'] == ['name']
    assert sorted(root.rglob('*')) == before
    for wrong in ['Standard', 'Shorter', True, 2, [], {}, None]:
        assert_no_files_on_error(params | dict(passing_directness=wrong), 'Unsupported stored passing')
    assert_no_files_on_error(params | dict(template_sha256='0' * 64), 'Template hash changed')
    old_label = m.OPTION_NAMES[3]
    try:
        m.OPTION_NAMES[3] = 'Changed native meaning'
        assert_no_files_on_error(params | dict(passing_directness='Shorter Passing'), 'labels changed')
    finally:
        m.OPTION_NAMES[3] = old_label
    assert template.read_bytes() == source

template = representatives[27]
_, _, members = m.read_template(str(template))
tac = members['.tac']
offset = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
flags = (int.from_bytes(tac[offset:offset + 12], 'little') & ~mask) | 6
conflict = root / 'conflicting.fmf'
m.repack_native_fmf(template, conflict, plaintext_overrides={'.tac': tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]})
summary = m.summarize(str(conflict))
assert summary['passing_directness'] is None and 'passing_directness' not in summary['supported_edits']
params = dict(template_path=str(conflict), template_sha256=summary['template_sha256'], name='Inherited Conflict')
inherited = m.generate(params)
assert inherited['passing_directness_state'] == 'conflicting_stored_selections'
assert inherited['passing_directness_mode'] == 'inherit'
_, _, inherited_members = m.read_template(inherited['output_path'])
assert m.replace_tac_name(inherited_members['.tac'], summary['name']) == m.read_template(str(conflict))[2]['.tac']
for name in expected:
    assert_no_files_on_error(params | dict(passing_directness=name), 'contradictory')

# Existing FM27 destination and name safety use the same writer as Agent Outputs.
fm27_dir = root / 'FM27 Tactics'
fm27_dir.mkdir()
summary = m.summarize(str(template))
params = dict(template_path=str(template), template_sha256=summary['template_sha256'],
              name='Passing FM27 Destination', passing_directness='Shorter Passing',
              fm27_folder=True, tactics_directory=str(fm27_dir))
saved = m.generate(params)
assert Path(saved['output_path']).parent == fm27_dir
assert m.summarize(saved['output_path'])['passing_directness'] == 'Shorter Passing'
saved_bytes = Path(saved['output_path']).read_bytes()
assert_no_files_on_error(params, 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_bytes
assert_no_files_on_error(params | dict(name='../Passing Escape'), 'single filename component')
assert not (root / 'Passing Escape.fmf').exists()

# A source mutation after the initial pinned read also prevents delivery.
changing_source = root / 'changing-source.fmf'
changing_source.write_bytes(template.read_bytes())
summary = m.summarize(str(changing_source))
params = dict(template_path=str(changing_source), template_sha256=summary['template_sha256'],
              name='Changed Source Refusal', passing_directness='Shorter Passing')
original_repack = m.repack_native_fmf
def repack_then_change_source(*args, **kwargs):
    original_repack(*args, **kwargs)
    changing_source.write_bytes(changing_source.read_bytes() + b'changed')
try:
    m.repack_native_fmf = repack_then_change_source
    assert_no_files_on_error(params, 'Template changed during generation')
finally:
    m.repack_native_fmf = original_repack

print(json.dumps({'templates_checked': len(templates), 'versions': sorted(representatives),
                  'passing_variants_per_template': len(expected), 'archives_generated': generated,
                  'changed_controls': changed_controls, 'fixtures_directory': str(root)}))
