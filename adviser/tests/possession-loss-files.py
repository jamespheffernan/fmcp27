"""Stored possession-loss triad through real native archive generation."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='possession-loss-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
expected = {'No explicit selection': 0, 'Counter-Press': 1 << 70, 'Regroup': 1 << 71}
mask = 3 << 70
templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert len(templates) >= 9
archives, changed_fm27 = 0, {}


def vector(tac):
    at = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    return at, int.from_bytes(tac[at:at + 12], 'little')


def preserve(result, members, old_name, requested_name, flags):
    _, _, after = m.read_template(result['output_path'])
    restored_name = m.replace_tac_name(after['.tac'], old_name)
    at, _ = vector(members['.tac'])
    assert vector(restored_name) == (at, flags)
    assert restored_name[:at] == members['.tac'][:at]
    assert restored_name[at + 12:] == members['.tac'][at + 12:]
    assert m.inspect_stored_football(after['.tac'])['phase_positions_and_roles'] == m.inspect_stored_football(members['.tac'])['phase_positions_and_roles']
    assert set(after) == set(members)
    assert all(after[key] == members[key] for key in members if key not in ('.tac', '.aom'))
    assert m.replace_string(after['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), old_name, requested_name) == members['.aom']
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result


def refuse(params, fragment):
    before = sorted(m.OUTPUTS.rglob('*'))
    try:
        m.generate(params)
    except (ValueError, FileExistsError) as error:
        assert fragment in str(error), str(error)
    else:
        raise AssertionError('Invalid possession-loss request accepted')
    assert sorted(m.OUTPUTS.rglob('*')) == before


for template in templates:
    _, source_bytes, members = m.read_template(str(template))
    tac = members['.tac']
    at, flags = vector(tac)
    summary = m.summarize(str(template))
    assert summary['possession_loss_state'] == 'known'
    params = dict(template_path=str(template), template_sha256=m.sha(source_bytes), name='Native Possession Loss Verification')
    for label, bits in expected.items():
        modified = m.replace_possession_loss(tac, label)
        assert vector(modified) == (at, (flags & ~mask) | bits)
        assert modified[:at] == tac[:at] and modified[at + 12:] == tac[at + 12:]
        assert m.possession_loss_selection(modified) == (at, label)
        # All96bits, including adjacent69/72 and unknown high bits, survive
        # except the requested pair. This is a local byte-preservation check.
        sentinel_flags = ((1 << 96) - 1) & ~mask
        sentinel = tac[:at] + sentinel_flags.to_bytes(12, 'little') + tac[at + 12:]
        assert vector(m.replace_possession_loss(sentinel, label)) == (at, sentinel_flags | bits)
        result = m.generate(params | dict(possession_loss=label))
        assert result['possession_loss'] == label and result['possession_loss_mode'] == 'explicit_change'
        assert result['edits'] == ['name', 'possession_loss']
        preserve(result, members, summary['name'], params['name'], (flags & ~mask) | bits)
        selected = [item for item in result['stored_football']['stored_team_instructions'] if item['native_option_id'] in (70, 71)]
        assert selected == ([] if bits == 0 else [{'native_option_id': bits.bit_length() - 1, 'name': label}])
        if tac[11] == 27 and flags & mask != bits:
            changed_fm27.setdefault(label, {'source': str(template), 'source_sha256': m.sha(source_bytes),
                                           'output': result['output_path'], 'output_sha256': result['output_sha256']})
        archives += 1
    before = sorted(m.OUTPUTS.rglob('*'))
    preview = m.generate(params | dict(possession_loss='Regroup', preview=True))
    inherited = m.generate(params | dict(preview=True))
    assert preview['files_created'] is False and inherited['files_created'] is False
    assert inherited['possession_loss'] == summary['possession_loss'] and inherited['possession_loss_mode'] == 'inherit'
    assert inherited['edits'] == ['name']
    assert sorted(m.OUTPUTS.rglob('*')) == before
    assert template.read_bytes() == source_bytes

# The original FM27 sources allselectCounter-Press. A generated nativeFM27
# Regroup file supplies a real different-setting positive for Counter-Press;
# this is not claimed to be a game-saved opposite control.
regroup = Path(changed_fm27['Regroup']['output'])
_, regroup_bytes, regroup_members = m.read_template(str(regroup))
assert regroup_members['.tac'][11] == 27
summary = m.summarize(str(regroup))
params = dict(template_path=str(regroup), template_sha256=m.sha(regroup_bytes),
              name='FM27 Restore Counter Press', possession_loss='Counter-Press')
result = m.generate(params)
_, flags = vector(regroup_members['.tac'])
assert flags & mask == 1 << 71
preserve(result, regroup_members, summary['name'], params['name'], (flags & ~mask) | (1 << 70))
changed_fm27['Counter-Press'] = {'source': str(regroup), 'source_sha256': m.sha(regroup_bytes),
                               'output': result['output_path'], 'output_sha256': result['output_sha256']}
assert set(changed_fm27) == set(expected)

# Combine the triad with allprevious team controls and the1.0.69 donor role
# edit. Readback checks the actual encoded values and only one role changes.
source = m.TEMPLATES / '3421 FM27 Att.fmf'
donor = m.TEMPLATES / '3421 FM27 Def.fmf'
_, source_bytes, source_members = m.read_template(str(source))
source_tac = source_members['.tac']
summary = m.summarize(str(source))
base = dict(template_path=str(source), template_sha256=m.sha(source_bytes), name='Combined Loss Response Controls')
combinations = 0
for label in expected:
    combined = m.generate(base | dict(possession_loss=label, mentality='Positive', team_tackling='Stay On Feet',
        defensive_line='Higher Defensive Line', tempo='Lower Tempo', passing_directness='Shorter Passing',
        team_width='Wider', pressing_frequency='Trigger Press Less Often', base_role=dict(
            phase='in_possession', position_index=5, donor_template_path=str(donor),
            donor_template_sha256=m.summarize(str(donor))['template_sha256'], donor_position_index=5)))
    _, _, members = m.read_template(combined['output_path'])
    readback = m.summarize(combined['output_path'])
    for field, value in dict(possession_loss=label, mentality='Positive', team_tackling='Stay On Feet',
            defensive_line='Higher Defensive Line', tempo='Lower Tempo', passing_directness='Shorter Passing',
            team_width='Wider', pressing_frequency='Trigger Press Less Often').items():
        assert readback[field] == value
    roles_before = summary['stored_football']['phase_positions_and_roles']
    roles_after = readback['stored_football']['phase_positions_and_roles']
    assert roles_after['in_possession'][5]['role'] == 'Defensive Midfielder'
    assert roles_after['in_possession'][5]['native_role_word'] == '0000000000200010'
    assert all(roles_before[phase][slot] == roles_after[phase][slot]
               for phase in roles_before for slot in range(11) if (phase, slot) != ('in_possession', 5))
    # Independently assemble the exact allowed byte differences, rather than
    #accept the writer's own preservation assertion as combination proof.
    expected_tac = bytearray(source_tac)
    setup = m.parse_tac_plaintext(source_tac)['pre_style_setup']
    expected_tac[setup['mentality_offset']] = 5
    at, old_flags = vector(source_tac)
    edited_mask = ((15 << 1) | (15 << 46) | (15 << 50) | (15 << 56)
                   | (15 << 65) | (3 << 70) | (3 << 72))
    edited_bits = ((1 << 3) | (1 << 48) | (1 << 51) | (1 << 57)
                   | (1 << 67) | expected[label] | (2 << 72))
    expected_tac[at:at + 12] = ((old_flags & ~edited_mask) | edited_bits).to_bytes(12, 'little')
    role_at = m.phase_records(source_tac)['in_possession'][5]['role_word_offset']
    expected_tac[role_at:role_at + 8] = struct.pack('<Q', 0x200010)
    assert m.replace_tac_name(members['.tac'], summary['name']) == bytes(expected_tac)
    assert m.replace_string(members['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), summary['name'], base['name']) == source_members['.aom']
    assert combined['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert all(members[key] == source_members[key] for key in source_members if key not in ('.tac', '.aom'))
    combinations += 1

params = base | dict(possession_loss='Regroup')
for bad in [None, True, False, 1, [], {}, 'Standard', 'counter-press', 'Regroup ']:
    refuse(params | dict(possession_loss=bad), 'Unsupported stored possession-loss')
refuse(params | dict(template_sha256='0' * 64), 'Template hash changed')
for bit in (70, 71):
    label = m.OPTION_NAMES[bit]
    try:
        m.OPTION_NAMES[bit] = 'Changed option label'
        refuse(params, 'option labels changed')
    finally:
        m.OPTION_NAMES[bit] = label

# Planted conflict uses a real native archive with its newly recomputed valid
# hash, so only the actual possession-loss invariant can produce refusal.
at, flags = vector(source_tac)
conflict_tac = source_tac[:at] + (flags | mask).to_bytes(12, 'little') + source_tac[at + 12:]
conflict = root / 'valid-hash-conflicting.fmf'
m.repack_native_fmf(source, conflict, plaintext_overrides={'.tac': conflict_tac})
conflict_hash = m.sha(conflict.read_bytes())
conflict_summary = m.summarize(str(conflict))
assert conflict_summary['possession_loss_state'] == 'conflicting_stored_selections'
assert conflict_summary['possession_loss'] is None and 'possession_loss' not in conflict_summary['supported_edits']
conflict_params = dict(template_path=str(conflict), template_sha256=conflict_hash, name='Inherited Loss Conflict')
inherited = m.generate(conflict_params)
assert inherited['possession_loss_mode'] == 'inherit'
preserve(inherited, m.read_template(str(conflict))[2], conflict_summary['name'], conflict_params['name'], flags | mask)
unrelated = m.generate(conflict_params | dict(team_width='Wider'))
preserve(unrelated, m.read_template(str(conflict))[2], conflict_summary['name'], conflict_params['name'],
         ((flags | mask) & ~(15 << 50)) | (1 << 51))
for label in expected:
    refuse(conflict_params | dict(possession_loss=label), 'contradictory')

# Every decisive native span is guarded. These are synthetic negative files,
# not substitutes for the actual installed-native positive generation above.
native = m.LOSS_NATIVE_PLUGIN
for bad_index in range(len(m.LOSS_NATIVE_SPANS)):
    path = root / f'changed-native-{bad_index}.bin'
    with native.open('rb') as original, path.open('wb') as changed:
        for index, (offset, size, _) in enumerate(m.LOSS_NATIVE_SPANS):
            original.seek(0x5ED4000 + offset)
            raw = original.read(size)
            if index == bad_index:
                raw = bytes([raw[0] ^ 1]) + raw[1:]
            changed.seek(0x5ED4000 + offset)
            changed.write(raw)
    try:
        m.LOSS_NATIVE_PLUGIN = path
        refuse(params, 'Native possession-loss source changed')
    finally:
        m.LOSS_NATIVE_PLUGIN = native
resource = m.LOSS_ENGLISH_RESOURCE
changed_resource = root / 'changed-English.ltf'
changed_resource.write_text('Changed native definition')
try:
    m.LOSS_ENGLISH_RESOURCE = changed_resource
    refuse(params, 'English definitions changed')
finally:
    m.LOSS_ENGLISH_RESOURCE = resource

# Source drift and native-source drift after the initial read both stop file
# delivery. Existing source snapshots are never modified by these controls.
copy = root / 'changing-source.fmf'
copy.write_bytes(source_bytes)
original_repack = m.repack_native_fmf
def repack_then_change(*args, **kwargs):
    original_repack(*args, **kwargs)
    copy.write_bytes(copy.read_bytes() + b'drift')
try:
    m.repack_native_fmf = repack_then_change
    refuse(params | dict(template_path=str(copy)), 'Template changed during generation')
finally:
    m.repack_native_fmf = original_repack
def repack_then_change_native(*args, **kwargs):
    original_repack(*args, **kwargs)
    m.LOSS_NATIVE_PLUGIN = root / 'changed-native-0.bin'
try:
    m.repack_native_fmf = repack_then_change_native
    refuse(params | dict(preview=True), 'Native possession-loss source changed')
finally:
    m.repack_native_fmf = original_repack
    m.LOSS_NATIVE_PLUGIN = native
original_verify = m.verify_possession_loss_native
copy = root / 'delivery-changing-source.fmf'
copy.write_bytes(source_bytes)
calls = 0
def verify_then_change():
    global calls
    original_verify()
    calls += 1
    if calls == 3:
        copy.write_bytes(copy.read_bytes() + b'delivery drift')
try:
    m.verify_possession_loss_native = verify_then_change
    refuse(params | dict(template_path=str(copy)), 'Template changed before delivery')
finally:
    m.verify_possession_loss_native = original_verify

fm27_dir = root / 'FM27 Tactics'
fm27_dir.mkdir()
destination_params = params | dict(name='Regroup FM27 Destination', fm27_folder=True, tactics_directory=str(fm27_dir))
saved = m.generate(destination_params)
assert Path(saved['output_path']).parent == fm27_dir
saved_bytes = Path(saved['output_path']).read_bytes()
refuse(destination_params, 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_bytes
refuse(destination_params | dict(name='../Loss Escape'), 'single filename component')
assert source.read_bytes() == source_bytes
print(json.dumps({'templates_checked': len(templates), 'triad_archives': archives,
                  'changed_fm27_controls': changed_fm27, 'combined_previous_controls': combinations,
                  'native_spans_checked': len(m.LOSS_NATIVE_SPANS), 'valid_hash_conflict_refusals': 3,
                  'game_import_verified': False, 'fixtures_directory': str(root)}))
