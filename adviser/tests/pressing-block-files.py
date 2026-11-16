"""Stored pressing-block group through real native archive generation."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='pressing-block-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
expected = {'No explicit selection': 0, 'High Press': 1 << 61, 'Mid Block': 1 << 62, 'Low Block': 1 << 63}
mask = 7 << 61
templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert len(templates) >= 9
archives, changed_fm27, artifacts = 0, {}, []


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
        raise AssertionError('Invalid pressing-block request accepted')
    assert sorted(m.OUTPUTS.rglob('*')) == before


for template in templates:
    _, source_bytes, members = m.read_template(str(template))
    tac = members['.tac']
    at, flags = vector(tac)
    summary = m.summarize(str(template))
    assert summary['pressing_block_state'] == 'known'
    params = dict(template_path=str(template), template_sha256=m.sha(source_bytes), name='Native Pressing Block Verification')
    for label, bits in expected.items():
        modified = m.replace_stored_control(tac, 'pressing_block', label)
        assert vector(modified) == (at, (flags & ~mask) | bits)
        assert modified[:at] == tac[:at] and modified[at + 12:] == tac[at + 12:]
        assert m.stored_control_selection(modified, 'pressing_block') == (at, label)
        # All96bits, including adjacent60/64 and unknown high bits, survive
        # except the requested group. This is a local byte-preservation check.
        sentinel_flags = ((1 << 96) - 1) & ~mask
        sentinel = tac[:at] + sentinel_flags.to_bytes(12, 'little') + tac[at + 12:]
        assert vector(m.replace_stored_control(sentinel, 'pressing_block', label)) == (at, sentinel_flags | bits)
        result = m.generate(params | dict(pressing_block=label))
        assert result['pressing_block'] == label and result['pressing_block_mode'] == 'explicit_change'
        assert result['edits'] == ['name', 'pressing_block']
        preserve(result, members, summary['name'], params['name'], (flags & ~mask) | bits)
        artifacts.append(dict(source=str(template), source_sha256=m.sha(source_bytes), output=result['output_path'], output_sha256=result['output_sha256'], requested_name=params['name'], original_name=summary['name'], selection=label))
        selected = [item for item in result['stored_football']['stored_team_instructions'] if item['native_option_id'] in (61, 62, 63)]
        assert selected == ([] if bits == 0 else [{'native_option_id': bits.bit_length() - 1, 'name': label}])
        if tac[11] == 27 and flags & mask != bits:
            changed_fm27.setdefault(label, {'source': str(template), 'source_sha256': m.sha(source_bytes),
                                           'output': result['output_path'], 'output_sha256': result['output_sha256']})
        archives += 1
    before = sorted(m.OUTPUTS.rglob('*'))
    preview = m.generate(params | dict(pressing_block='High Press', preview=True))
    inherited = m.generate(params | dict(preview=True))
    assert preview['files_created'] is False and inherited['files_created'] is False
    assert inherited['pressing_block'] == summary['pressing_block'] and inherited['pressing_block_mode'] == 'inherit'
    assert inherited['edits'] == ['name']
    assert sorted(m.OUTPUTS.rglob('*')) == before
    assert template.read_bytes() == source_bytes

# All real FM27 templates select High Press. Use the actually generated
# native Mid Block archive for a changed-setting High positive; this does not
# claim a game-saved opposite template or game import.
mid_block = Path(changed_fm27['Mid Block']['output'])
_, mid_bytes, mid_members = m.read_template(str(mid_block))
assert mid_members['.tac'][11] == 27
summary = m.summarize(str(mid_block))
params = dict(template_path=str(mid_block), template_sha256=m.sha(mid_bytes),
              name='FM27 Restore High Press', pressing_block='High Press')
result = m.generate(params)
_, flags = vector(mid_members['.tac'])
assert flags & mask == 1 << 62
preserve(result, mid_members, summary['name'], params['name'], (flags & ~mask) | (1 << 61))
artifacts.append(dict(source=str(mid_block), source_sha256=m.sha(mid_bytes), output=result['output_path'], output_sha256=result['output_sha256'], requested_name=params['name'], original_name=summary['name'], selection='High Press'))
changed_fm27['High Press'] = {'source': str(mid_block), 'source_sha256': m.sha(mid_bytes),
                            'output': result['output_path'], 'output_sha256': result['output_sha256']}
assert set(changed_fm27) == set(expected)

# Combine the group with allprevious team controls and the1.0.69 donor role
# edit. Readback checks the actual encoded values and only one role changes.
source = m.TEMPLATES / '3421 FM27 Att.fmf'
donor = m.TEMPLATES / '3421 FM27 Def.fmf'
_, source_bytes, source_members = m.read_template(str(source))
source_tac = source_members['.tac']
summary = m.summarize(str(source))
base = dict(template_path=str(source), template_sha256=m.sha(source_bytes), name='Combined Pressing Block Controls')
combinations = 0
for label in expected:
    combined = m.generate(base | dict(pressing_block=label, crossing_style='Low Crosses', goal_kick_length='Long Goal Kicks', possession_loss='Regroup', possession_gain='Hold Shape', mentality='Positive', team_tackling='Stay On Feet',
        defensive_line='Higher Defensive Line', tempo='Lower Tempo', passing_directness='Shorter Passing',
        team_width='Wider', pressing_frequency='Trigger Press Less Often', base_role=dict(
            phase='in_possession', position_index=5, donor_template_path=str(donor),
            donor_template_sha256=m.summarize(str(donor))['template_sha256'], donor_position_index=5)))
    _, _, members = m.read_template(combined['output_path'])
    readback = m.summarize(combined['output_path'])
    for field, value in dict(pressing_block=label, crossing_style='Low Crosses', goal_kick_length='Long Goal Kicks', possession_loss='Regroup', possession_gain='Hold Shape', mentality='Positive', team_tackling='Stay On Feet',
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
                   | (15 << 65) | (7 << 10) | (7 << 61) | (3 << 44) | (3 << 54) | (3 << 70) | (3 << 72))
    edited_bits = ((1 << 3) | (1 << 48) | (1 << 51) | (1 << 57)
                   | (1 << 67) | (1 << 12) | (1 << 45) | expected[label] | (1 << 55) | (1 << 71) | (2 << 72))
    expected_tac[at:at + 12] = ((old_flags & ~edited_mask) | edited_bits).to_bytes(12, 'little')
    role_at = m.phase_records(source_tac)['in_possession'][5]['role_word_offset']
    expected_tac[role_at:role_at + 8] = struct.pack('<Q', 0x200010)
    assert m.replace_tac_name(members['.tac'], summary['name']) == bytes(expected_tac)
    assert m.replace_string(members['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), summary['name'], base['name']) == source_members['.aom']
    assert combined['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert all(members[key] == source_members[key] for key in source_members if key not in ('.tac', '.aom'))
    combinations += 1

params = base | dict(pressing_block='High Press')
for bad in [None, True, False, 1, [], {}, 'Standard', 'high press', 'High Press ']:
    refuse(params | dict(pressing_block=bad), 'Unsupported stored pressing_block')
refuse(params | dict(template_sha256='0' * 64), 'Template hash changed')
for bit in (61, 62, 63):
    label = m.OPTION_NAMES[bit]
    try:
        m.OPTION_NAMES[bit] = 'Changed option label'
        refuse(params, 'option labels changed')
    finally:
        m.OPTION_NAMES[bit] = label

# Every invalid three-bit combination is a real native FMF with a recomputed
# valid archive hash. Only the semantic conflict can cause refusal.
conflict_refusals = 0
at, flags = vector(source_tac)
for pattern in (3, 5, 6, 7):
    conflict_flags = (flags & ~mask) | (pattern << 61)
    conflict_tac = source_tac[:at] + conflict_flags.to_bytes(12, 'little') + source_tac[at + 12:]
    conflict = root / f'valid-hash-conflicting-{pattern}.fmf'
    m.repack_native_fmf(source, conflict, plaintext_overrides={'.tac': conflict_tac})
    conflict_hash = m.sha(conflict.read_bytes())
    conflict_summary = m.summarize(str(conflict))
    assert conflict_summary['pressing_block_state'] == 'conflicting_stored_selections'
    assert conflict_summary['pressing_block'] is None and 'pressing_block' not in conflict_summary['supported_edits']
    conflict_params = dict(template_path=str(conflict), template_sha256=conflict_hash, name='Inherited Crossing Conflict')
    inherited = m.generate(conflict_params)
    assert inherited['pressing_block_mode'] == 'inherit'
    preserve(inherited, m.read_template(str(conflict))[2], conflict_summary['name'], conflict_params['name'], conflict_flags)
    unrelated = m.generate(conflict_params | dict(team_width='Wider'))
    preserve(unrelated, m.read_template(str(conflict))[2], conflict_summary['name'], conflict_params['name'],
             (conflict_flags & ~(15 << 50)) | (1 << 51))
    for label in expected:
        refuse(conflict_params | dict(pressing_block=label), 'contradictory')
        conflict_refusals += 1

# A valid-hash native source can retain an unlabelled bit64. Editing the
# requested known pair must preserve that unknown option without inventing a name.
at, source_flags = vector(source_tac)
unknown_tac = source_tac[:at] + (source_flags | (1 << 64)).to_bytes(12, 'little') + source_tac[at + 12:]
unknown = root / 'valid-hash-unlabelled-option.fmf'
m.repack_native_fmf(source, unknown, plaintext_overrides={'.tac': unknown_tac})
unknown_summary = m.summarize(str(unknown))
assert {'native_option_id': 64, 'name': None} in unknown_summary['stored_football']['stored_team_instructions']
unknown_result = m.generate(dict(template_path=str(unknown), template_sha256=m.sha(unknown.read_bytes()),
    name='Preserved Unknown Option Pressing Block Edit', pressing_block='Mid Block'))
preserve(unknown_result, m.read_template(str(unknown))[2], unknown_summary['name'],
    'Preserved Unknown Option Pressing Block Edit', ((source_flags | (1 << 64)) & ~mask) | (1 << 62))

artifacts.append(dict(source=str(unknown), source_sha256=m.sha(unknown.read_bytes()), output=unknown_result['output_path'], output_sha256=unknown_result['output_sha256'], requested_name='Preserved Unknown Option Pressing Block Edit', original_name=unknown_summary['name'], selection='Mid Block'))

# A valid FMF envelope/hash does not validate the inner vector count. The
# native packer emits count3 + three u32 words; refuse other prefixes before
# publishing any requested pressing-block selection. Shared width/pressing reads
# use the same bounded vector source and must refuse it too.
at, source_flags = vector(source_tac)
for prefix in (0, 1, 2, 4, 255):
    bad_tac = source_tac[:at - 1] + bytes([prefix]) + source_tac[at:]
    bad = root / f'valid-hash-vector-prefix-{prefix}.fmf'
    m.repack_native_fmf(source, bad, plaintext_overrides={'.tac': bad_tac})
    bad_params = dict(template_path=str(bad), template_sha256=m.sha(bad.read_bytes()), name='Rejected Vector Prefix')
    for label in expected:
        refuse(bad_params | dict(pressing_block=label), 'Unsupported native team instruction vector')
    for field, label in [('team_width', 'Wider'), ('pressing_frequency', 'Trigger Press Less Often')]:
        refuse(bad_params | {field: label}, 'Unsupported native team instruction vector')

# Every decisive native span is guarded. These are synthetic negative files,
# not substitutes for the actual installed-native positive generation above.
native = m.PRESSING_BLOCK_NATIVE_PLUGIN
for bad_index in range(len(m.PRESSING_BLOCK_NATIVE_SPANS)):
    path = root / f'changed-native-{bad_index}.bin'
    with native.open('rb') as original, path.open('wb') as changed:
        for index, (offset, size, _) in enumerate(m.PRESSING_BLOCK_NATIVE_SPANS):
            original.seek(0x5ED4000 + offset)
            raw = original.read(size)
            if index == bad_index:
                raw = bytes([raw[0] ^ 1]) + raw[1:]
            changed.seek(0x5ED4000 + offset)
            changed.write(raw)
    try:
        m.PRESSING_BLOCK_NATIVE_PLUGIN = path
        refuse(params, 'Native pressing-block source changed')
    finally:
        m.PRESSING_BLOCK_NATIVE_PLUGIN = native
resource = m.PRESSING_BLOCK_ENGLISH_RESOURCE
changed_resource = root / 'changed-English.ltf'
changed_resource.write_text('Changed native definition')
try:
    m.PRESSING_BLOCK_ENGLISH_RESOURCE = changed_resource
    refuse(params, 'English definitions changed')
finally:
    m.PRESSING_BLOCK_ENGLISH_RESOURCE = resource

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
    m.PRESSING_BLOCK_NATIVE_PLUGIN = root / 'changed-native-0.bin'
try:
    m.repack_native_fmf = repack_then_change_native
    refuse(params | dict(preview=True), 'Native pressing-block source changed')
finally:
    m.repack_native_fmf = original_repack
    m.PRESSING_BLOCK_NATIVE_PLUGIN = native
original_verify = m.verify_pressing_block_native
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
    m.verify_pressing_block_native = verify_then_change
    refuse(params | dict(template_path=str(copy)), 'Template changed before delivery')
finally:
    m.verify_pressing_block_native = original_verify

fm27_dir = root / 'FM27 Tactics'
fm27_dir.mkdir()
destination_params = params | dict(name='High Press FM27 Destination', fm27_folder=True, tactics_directory=str(fm27_dir))
saved = m.generate(destination_params)
assert Path(saved['output_path']).parent == fm27_dir
saved_bytes = Path(saved['output_path']).read_bytes()
refuse(destination_params, 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_bytes
refuse(destination_params | dict(name='../Pressing Block Escape'), 'single filename component')
assert source.read_bytes() == source_bytes
print(json.dumps({'templates_checked': len(templates), 'selection_archives': archives,
                  'changed_fm27_controls': changed_fm27, 'combined_previous_controls': combinations,
                  'native_spans_checked': len(m.PRESSING_BLOCK_NATIVE_SPANS), 'valid_hash_conflict_refusals': conflict_refusals, 'valid_hash_vector_prefix_refusals': 30,
                  'game_import_verified': False, 'fixtures_directory': str(root), 'artifacts': artifacts}))
