"""Exact pinned native role-record reproduction; no game/UI/import proof."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='base-role-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
source = m.TEMPLATES / '3421 FM27 .fmf'
donor = m.TEMPLATES / '3421 FM27 Def.fmf'
_, source_bytes, source_members = m.read_template(str(source))
_, donor_bytes, donor_members = m.read_template(str(donor))
assert m.sha(source_bytes) == '52b19d08c643f9145a59c0e17b36bb1961693ea007231dfc182a4d1232979e40'
assert m.sha(donor_bytes) == '0f9859c551cd94eee9f2781323ef5b8447f081090e59e88d0502517e2e563135'
source_tac, donor_tac = source_members['.tac'], donor_members['.tac']
old_name = m.summarize(str(source))['name']
source_record = m.phase_records(source_tac)['in_possession'][5]
donor_record = m.phase_records(donor_tac)['in_possession'][5]
role = dict(phase='in_possession', position_index=5, donor_template_path=str(donor),
            donor_template_sha256=m.sha(donor_bytes), donor_position_index=5)
params = dict(template_path=str(source), template_sha256=m.sha(source_bytes),
              name='Native DMCR Role Verification', base_role=role)


def refuse(call, message):
    before = sorted(root.rglob('*'))
    try:
        call()
    except (ValueError, FileExistsError) as error:
        assert message in str(error), str(error)
    else:
        raise AssertionError('Unsupported role edit accepted')
    assert sorted(root.rglob('*')) == before


preview = m.generate(params | dict(preview=True))
assert preview['status'] == 'preview' and preview['files_created'] is False
assert not m.OUTPUTS.exists()
result = m.generate(params)
_, _, output = m.read_template(result['output_path'])
target = m.phase_records(output['.tac'])['in_possession'][5]
assert target['native_role_word'] == '0000000000200010'
assert target['role']['compiled_english_name'] == 'Defensive Midfielder'
assert source_record['native_role_word'] == '0000000000410000'
assert output['.tac'][target['record_offset']:target['record_end_exclusive']] == donor_tac[donor_record['record_offset']:donor_record['record_end_exclusive']]
restored = m.replace_tac_name(output['.tac'], old_name)
offset = source_record['role_word_offset']
assert restored[:offset] == source_tac[:offset]
assert restored[offset + 8:] == source_tac[offset + 8:]
assert restored[offset:offset + 8] == struct.pack('<Q', 0x200010)
assert restored[:offset] + struct.pack('<Q', 0x410000) + restored[offset + 8:] == source_tac
assert set(output) == set(source_members)
assert all(output[key] == source_members[key] for key in output if key not in ('.tac', '.aom'))
assert m.replace_string(output['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), old_name, params['name']) == source_members['.aom']
before_roles = m.inspect_stored_football(source_tac)['phase_positions_and_roles']
after_roles = m.inspect_stored_football(output['.tac'])['phase_positions_and_roles']
for phase in before_roles:
    for index in range(11):
        if (phase, index) != ('in_possession', 5):
            assert before_roles[phase][index] == after_roles[phase][index]
assert result['edits'] == ['name', 'base_role'] and result['base_role_mode'] == 'explicit_change'
assert result['base_role']['donor_template_sha256'] == m.sha(donor_bytes)
assert result['base_role']['before']['native_role_word'] == '0000000000410000'
assert result['base_role']['after']['native_role_word'] == '0000000000200010'
assert result['verification']['game_load_verified'] is False
assert json.loads(Path(result['receipt_path']).read_text()) == result
inherited = m.generate({key: value for key, value in params.items() if key != 'base_role'} | dict(preview=True))
assert inherited['base_role'] is None and inherited['base_role_mode'] == 'inherit'
assert inherited['stored_football']['phase_positions_and_roles'] == before_roles
assert 'base_role' in m.summarize(str(source))['supported_edits']
assert 'base_role' in m.summarize(str(donor))['supported_edits']  # Proved reverse direction is now eligible.
fm27 = root / 'FM27 Tactics'
fm27.mkdir()
fm27_params = params | dict(name='Native DMCR FM27 Verification', fm27_folder=True, tactics_directory=str(fm27))
saved = m.generate(fm27_params)
assert Path(saved['output_path']).parent == fm27
assert m.summarize(saved['output_path'])['stored_football']['phase_positions_and_roles']['in_possession'][5]['role'] == 'Defensive Midfielder'
saved_bytes = Path(saved['output_path']).read_bytes()
refuse(lambda: m.generate(fm27_params), 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_bytes
refuse(lambda: m.generate(fm27_params | dict(name='../Role Escape')), 'single filename component')

# Public input refusals happen before any output/receipt is created.
for bad in [None, True, False, 5, 'Defensive Midfielder', [], {}]:
    refuse(lambda bad=bad: m.generate(params | dict(base_role=bad)), 'base_role requires')
for change in [dict(phase='out_of_possession'), dict(phase=1), dict(position_index=4),
               dict(position_index=True), dict(donor_position_index=6), dict(donor_position_index=True)]:
    refuse(lambda change=change: m.generate(params | dict(base_role=role | change)), 'only in_possession slot5')
for change in [dict(role='Goalkeeper'), dict(native_role_word='0000000000800010'), dict(extra=True)]:
    refuse(lambda change=change: m.generate(params | dict(base_role=role | change)), 'exact phase')
for change in [dict(donor_template_path=True), dict(donor_template_path=''),
               dict(donor_template_sha256=None), dict(donor_template_sha256='0' * 64)]:
    refuse(lambda change=change: m.generate(params | dict(base_role=role | change)), 'donor')
refuse(lambda: m.generate(params | dict(template_sha256='0' * 64)), 'Template hash changed')
fm26 = m.TEMPLATES / '4231 FM27 .fmf'
refuse(lambda: m.generate(params | dict(template_path=str(fm26), template_sha256=m.summarize(str(fm26))['template_sha256'])), 'requires native FM27')

# Mutate paired plaintext copies to exercise the semantic checks directly,
# independently of the outer pinned-file hash check. These are planted negatives.
def mutate_pair(relative, replacement):
    a, b = bytearray(source_tac), bytearray(donor_tac)
    start_a, start_b = source_record['record_offset'], donor_record['record_offset']
    a[start_a + relative:start_a + relative + len(replacement)] = replacement
    b[start_b + relative:start_b + relative + len(replacement)] = replacement
    return bytes(a), bytes(b)

bad = bytearray(source_tac)
bad[11] = 26
refuse(lambda: m.validate_base_role_records(bytes(bad), donor_tac), 'requires native FM27')
for relative in [0, 1, 2, 8]:
    bad = bytearray(source_tac)
    bad[source_record['record_offset'] + relative] ^= 1
    refuse(lambda bad=bad: m.validate_base_role_records(bytes(bad), donor_tac), 'record version')
a, b = mutate_pair(3, struct.pack('<I', 128))
refuse(lambda: m.validate_base_role_records(a, b), 'requires IP slot5 DM(CR)')
for word, target_source in [(0x210000, True), (0x810000, True), (0x400010, False), (0x200001, False)]:
    a, b = bytearray(source_tac), bytearray(donor_tac)
    chosen, record = (a, source_record) if target_source else (b, donor_record)
    chosen[record['role_word_offset']:record['role_word_offset'] + 8] = struct.pack('<Q', word)
    refuse(lambda a=a, b=b: m.validate_base_role_records(bytes(a), bytes(b)), 'donor base role')
bad = bytearray(source_tac)
bad[source_record['instruction_vector_offset'] + 19] ^= 1
refuse(lambda: m.validate_base_role_records(bytes(bad), donor_tac), 'companion record bytes differ')
for relative, replacement, message in [
    (14 + 8, b'\x03', 'instruction metadata'),
    (14, struct.pack('<Q', 0x11), 'target key'),
    (14 + 24, struct.pack('<Q', 0x10), 'target key'),
    (14 + 24, struct.pack('<Q', 0), 'target key'),
    (14 + 5 * 24, struct.pack('<Q', 0x400010), 'target key'),
    (14 + 7 * 24, struct.pack('<Q', 0x0200000000200000), 'target key'),
    (14 + 11, struct.pack('<Q', 1), 'target key'),
    (14 + 11, struct.pack('<Q', 1 << 63), 'target key'),
]:
    a, b = mutate_pair(relative, replacement)
    refuse(lambda a=a, b=b: m.validate_base_role_records(a, b), message)

from fm_live_mcp import prepared_tactic_roles as labels
old_branches = labels.ROLE_BRANCHES['in_possession']
try:
    labels.ROLE_BRANCHES['in_possession'] = tuple((bit, key, 'Changed label' if bit == 4 else name) for bit, key, name in old_branches)
    refuse(lambda: m.generate(params), 'label bindings changed')
finally:
    labels.ROLE_BRANCHES['in_possession'] = old_branches

# Every pinned native span rejects its own mutation. Sparse files are synthetic
# negative fixtures only; positive generation above used the installed binary.
native_path = m.ROLE_NATIVE_PLUGIN
for bad_index in range(len(m.ROLE_NATIVE_SPANS)):
    path = root / f'changed-native-{bad_index}.bin'
    with native_path.open('rb') as original, path.open('wb') as changed:
        for index, (at, size, _) in enumerate(m.ROLE_NATIVE_SPANS):
            original.seek(0x5ED4000 + at)
            raw = original.read(size)
            if index == bad_index:
                raw = bytes([raw[0] ^ 1]) + raw[1:]
            changed.seek(0x5ED4000 + at)
            changed.write(raw)
    try:
        m.ROLE_NATIVE_PLUGIN = path
        refuse(lambda: m.generate(params), 'Native base-role source changed')
    finally:
        m.ROLE_NATIVE_PLUGIN = native_path

# Both pinned archives must remain stable through generation and delivery.
original_repack = m.repack_native_fmf
for changing in ['source', 'donor']:
    source_copy = root / f'{changing}-source.fmf'
    donor_copy = root / f'{changing}-donor.fmf'
    source_copy.write_bytes(source_bytes)
    donor_copy.write_bytes(donor_bytes)
    request = params | dict(template_path=str(source_copy), base_role=role | dict(donor_template_path=str(donor_copy)))
    def repack_then_change(*args, **kwargs):
        original_repack(*args, **kwargs)
        changed = source_copy if changing == 'source' else donor_copy
        changed.write_bytes(changed.read_bytes() + b'drift')
    try:
        m.repack_native_fmf = repack_then_change
        refuse(lambda: m.generate(request), 'changed during generation')
    finally:
        m.repack_native_fmf = original_repack
assert source.read_bytes() == source_bytes and donor.read_bytes() == donor_bytes

# Delivery rechecks both archives after the final native source verification.
original_verify = m.verify_base_role_native
for changing in ['source', 'donor']:
    source_copy = root / f'delivery-{changing}-source.fmf'
    donor_copy = root / f'delivery-{changing}-donor.fmf'
    source_copy.write_bytes(source_bytes)
    donor_copy.write_bytes(donor_bytes)
    request = params | dict(template_path=str(source_copy), base_role=role | dict(donor_template_path=str(donor_copy)))
    calls = 0
    def verify_then_change():
        global calls
        original_verify()
        calls += 1
        if calls == 2:
            changed = source_copy if changing == 'source' else donor_copy
            changed.write_bytes(changed.read_bytes() + b'delivery drift')
    try:
        m.verify_base_role_native = verify_then_change
        refuse(lambda: m.generate(request), 'changed before delivery')
    finally:
        m.verify_base_role_native = original_verify
print(json.dumps({'changed_output': result['output_path'], 'receipt': result['receipt_path'],
                  'stored_before': 'Box-To-Box Midfielder', 'stored_after': 'Defensive Midfielder',
                  'other_records_preserved': 21, 'game_import_verified': False, 'fixtures_directory': str(root)}))
