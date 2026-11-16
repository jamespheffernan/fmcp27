"""Native stored width/pressing edits; exact bits, no FM import assertion."""
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
groups = {
    'team_width': {'No explicit selection': 0, 'Much Wider': 1 << 50, 'Wider': 1 << 51,
                   'Narrower': 1 << 52, 'Much Narrower': 1 << 53},
    'pressing_frequency': {'No explicit selection': 0, 'Trigger Press Much More Often': 1 << 65,
                          'Trigger Press More Often': 1 << 66, 'Trigger Press Less Often': 1 << 67,
                          'Trigger Press Much Less Often': 1 << 68},
}
masks = {'team_width': 15 << 50, 'pressing_frequency': 15 << 65}
templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert templates, 'Real native templates are required'
root = Path(tempfile.mkdtemp(prefix='width-pressing-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
representatives = {}
archives = 0


def vector(tac):
    offset = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    return offset, int.from_bytes(tac[offset:offset + 12], 'little')


def check_preservation(result, before, old_name, new_name, expected_flags):
    _, _, after = m.read_template(result['output_path'])
    restored_name = m.replace_tac_name(after['.tac'], old_name)
    offset, before_flags = vector(before['.tac'])
    assert vector(restored_name) == (offset, expected_flags)
    assert restored_name[:offset] == before['.tac'][:offset]
    assert restored_name[offset + 12:] == before['.tac'][offset + 12:]
    assert set(after) == set(before)
    assert all(after[key] == before[key] for key in before if key not in ('.tac', '.aom'))
    assert m.replace_string(after['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), old_name, new_name) == before['.aom']
    assert m.inspect_stored_football(after['.tac'])['phase_positions_and_roles'] == m.inspect_stored_football(before['.tac'])['phase_positions_and_roles']
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['template_unchanged'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result


def refuse(params, text):
    before = sorted(root.rglob('*'))
    try:
        m.generate(params)
    except (ValueError, FileExistsError) as error:
        assert text in str(error), str(error)
    else:
        raise AssertionError('Invalid native control edit was accepted')
    assert sorted(root.rglob('*')) == before


for template in templates:
    source = template.read_bytes()
    _, _, members = m.read_template(str(template))
    tac = members['.tac']
    offset, flags = vector(tac)
    representatives.setdefault(tac[11], template)
    summary = m.summarize(str(template))
    params = dict(template_path=str(template), template_sha256=summary['template_sha256'],
                  name='Native Width Pressing Verification')
    for field, choices in groups.items():
        mask = masks[field]
        assert flags & mask in choices.values()
        for label, bits in choices.items():
            changed = m.replace_stored_control(tac, field, label)
            assert changed[:offset] == tac[:offset] and changed[offset + 12:] == tac[offset + 12:]
            assert vector(changed) == (offset, (flags & ~mask) | bits)
            assert m.stored_control_selection(changed, field) == (offset, label)
            instructions = m.inspect_stored_football(changed)['stored_team_instructions']
            assert [item for item in instructions if mask & (1 << item['native_option_id'])] == (
                [] if bits == 0 else [{'native_option_id': bits.bit_length() - 1, 'name': label}])
            sentinel_flags = ((1 << 96) - 1) & ~mask
            sentinel = tac[:offset] + sentinel_flags.to_bytes(12, 'little') + tac[offset + 12:]
            assert vector(m.replace_stored_control(sentinel, field, label)) == (offset, sentinel_flags | bits)
            result = m.generate(params | {field: label})
            assert result[field] == label and result[field + '_mode'] == 'explicit_change'
            assert result['edits'] == ['name', field]
            check_preservation(result, members, summary['name'], params['name'], (flags & ~mask) | bits)
            archives += 1
        group_bits = [bit for bit in range(96) if mask & (1 << bit)]
        for count in range(2, 5):
            for selected in itertools.combinations(group_bits, count):
                conflicting_flags = (flags & ~mask) | sum(1 << bit for bit in selected)
                conflicting = tac[:offset] + conflicting_flags.to_bytes(12, 'little') + tac[offset + 12:]
                assert m.describe_stored_controls(conflicting)[field + '_state'] == 'conflicting_stored_selections'
                for label in choices:
                    try:
                        m.replace_stored_control(conflicting, field, label)
                    except ValueError as error:
                        assert 'contradictory' in str(error)
                    else:
                        raise AssertionError('Conflicting stored selection was replaced')
    before = sorted(root.rglob('*'))
    inherited = m.generate(params | dict(preview=True))
    assert inherited['edits'] == ['name'] and inherited['files_created'] is False
    for field in groups:
        assert inherited[field] == summary[field] and inherited[field + '_mode'] == 'inherit'
    preview = m.generate(params | dict(team_width='Wider', pressing_frequency='Trigger Press Less Often', preview=True))
    assert preview['team_width'] == 'Wider' and preview['pressing_frequency'] == 'Trigger Press Less Often'
    assert preview['files_created'] is False and sorted(root.rglob('*')) == before
    assert template.read_bytes() == source

assert set(representatives) == {26, 27}
combined_controls = []
for version, template in sorted(representatives.items()):
    summary = m.summarize(str(template))
    _, _, members = m.read_template(str(template))
    _, flags = vector(members['.tac'])
    params = dict(template_path=str(template), template_sha256=summary['template_sha256'],
                  name='Combined Native Width Pressing', team_width='Wider',
                  pressing_frequency='Trigger Press Less Often')
    assert summary['team_width'] in ['Narrower', 'Much Narrower']
    assert summary['pressing_frequency'] in ['Trigger Press Much More Often', 'Trigger Press More Often']
    result = m.generate(params)
    target_flags = (flags & ~(masks['team_width'] | masks['pressing_frequency'])) | (1 << 51) | (1 << 67)
    check_preservation(result, members, summary['name'], params['name'], target_flags)
    assert result['edits'] == ['name', 'team_width', 'pressing_frequency']
    assert all(result[field] != summary[field] for field in groups)
    combined_controls.append({'source_major': version, 'before': {field: summary[field] for field in groups},
                              'after': {field: result[field] for field in groups}, 'output': result['output_path']})
    for field, choices in groups.items():
        for wrong in ['Standard', True, False, 3, [], {}, None]:
            refuse(params | {field: wrong}, f'Unsupported stored {field}')
        first_bit = next(value.bit_length() - 1 for value in choices.values() if value)
        old_label = m.OPTION_NAMES[first_bit]
        try:
            m.OPTION_NAMES[first_bit] = 'Changed native meaning'
            refuse(params, 'labels changed')
        finally:
            m.OPTION_NAMES[first_bit] = old_label
    refuse(params | dict(template_sha256='0' * 64), 'Template hash changed')

template = representatives[27]
summary = m.summarize(str(template))
_, _, members = m.read_template(str(template))
tac = members['.tac']
offset, flags = vector(tac)
for field, choices in groups.items():
    selected_bits = list(choices.values())[1:3]
    conflicting_flags = (flags & ~masks[field]) | selected_bits[0] | selected_bits[1]
    conflict = root / (field + '-conflicting.fmf')
    m.repack_native_fmf(template, conflict, plaintext_overrides={'.tac': tac[:offset] + conflicting_flags.to_bytes(12, 'little') + tac[offset + 12:]})
    conflict_summary = m.summarize(str(conflict))
    assert conflict_summary[field] is None and field not in conflict_summary['supported_edits']
    params = dict(template_path=str(conflict), template_sha256=conflict_summary['template_sha256'],
                  name='Inherited ' + field + ' Conflict')
    inherited = m.generate(params)
    assert inherited[field + '_state'] == 'conflicting_stored_selections' and inherited[field + '_mode'] == 'inherit'
    check_preservation(inherited, m.read_template(str(conflict))[2], conflict_summary['name'], params['name'], conflicting_flags)
    other = next(key for key in groups if key != field)
    label, bits = list(groups[other].items())[1]
    unrelated = m.generate(params | {other: label})
    check_preservation(unrelated, m.read_template(str(conflict))[2], conflict_summary['name'], params['name'],
                       (conflicting_flags & ~masks[other]) | bits)
    for label in choices:
        refuse(params | {field: label}, 'contradictory')

fm27_dir = root / 'FM27 Tactics'
fm27_dir.mkdir()
params = dict(template_path=str(template), template_sha256=summary['template_sha256'], name='Width Pressing FM27',
              team_width='Wider', pressing_frequency='Trigger Press Less Often', fm27_folder=True,
              tactics_directory=str(fm27_dir))
saved = m.generate(params)
assert Path(saved['output_path']).parent == fm27_dir
check_preservation(saved, members, summary['name'], params['name'],
                   (flags & ~(masks['team_width'] | masks['pressing_frequency'])) | (1 << 51) | (1 << 67))
saved_bytes = Path(saved['output_path']).read_bytes()
refuse(params, 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_bytes
refuse(params | dict(name='../Width Escape'), 'single filename component')

changing = root / 'changing-source.fmf'
changing.write_bytes(template.read_bytes())
params = dict(template_path=str(changing), template_sha256=m.summarize(str(changing))['template_sha256'],
              name='Changed Source Refusal', team_width='Wider', pressing_frequency='Trigger Press Less Often')
original_repack = m.repack_native_fmf
def repack_then_change(*args, **kwargs):
    original_repack(*args, **kwargs)
    changing.write_bytes(changing.read_bytes() + b'changed')
try:
    m.repack_native_fmf = repack_then_change
    refuse(params, 'Template changed during generation')
finally:
    m.repack_native_fmf = original_repack

print(json.dumps({'templates_checked': len(templates), 'versions': sorted(representatives),
                  'selections_per_control': 5, 'controls': list(groups), 'single_control_archives': archives,
                  'combined_controls': combined_controls, 'fixtures_directory': str(root)}))
