"""Public native generation with changed archive identities and planted negatives."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='base-role-variants-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
original_source_sha = '52b19d08c643f9145a59c0e17b36bb1961693ea007231dfc182a4d1232979e40'
original_donor_sha = '0f9859c551cd94eee9f2781323ef5b8447f081090e59e88d0502517e2e563135'
native_donor = m.TEMPLATES / '3421 FM27 Def.fmf'
_, original_donor_bytes, original_donor_members = m.read_template(str(native_donor))
assert m.sha(original_donor_bytes) == original_donor_sha
# Create a real supported native donor variant, rather than depend on old tmp
# directories. Its different name/width leave the complete target record exact.
donor_result = m.generate(dict(template_path=str(native_donor), template_sha256=original_donor_sha,
                               name='Variant DMCR Donor', team_width='Narrower'))
donor = Path(donor_result['output_path'])
_, donor_bytes, donor_members = m.read_template(str(donor))
assert m.sha(donor_bytes) != original_donor_sha
donor_tac = donor_members['.tac']
donor_record = m.phase_records(donor_tac)['in_possession'][5]
original_donor_record = m.phase_records(original_donor_members['.tac'])['in_possession'][5]
assert donor_tac[donor_record['record_offset']:donor_record['record_end_exclusive']] == original_donor_members['.tac'][original_donor_record['record_offset']:original_donor_record['record_end_exclusive']]
sources = [m.TEMPLATES / name for name in ['3421 FM27 Att.fmf',
           'Newcastle 3421 Positive - Stay On Feet.fmf', 'Newcastle Wildcard - Twin Tens 3421.fmf']]
# An independently named/changed native archive also defeats a filename or
# replacement archive-hash allowlist masquerading as a record invariant.
extra_source = m.generate(dict(template_path=str(sources[0]), template_sha256=m.summarize(str(sources[0]))['template_sha256'],
                               name='Unlisted Native Variant Source', tempo='Lower Tempo'))
sources.append(Path(extra_source['output_path']))
role = dict(phase='in_possession', position_index=5, donor_template_path=str(donor),
            donor_template_sha256=m.sha(donor_bytes), donor_position_index=5)
positives = []
for index, source in enumerate(sources):
    _, source_bytes, members = m.read_template(str(source))
    assert m.sha(source_bytes) != original_source_sha
    summary = m.summarize(str(source))
    assert summary['base_role_eligibility'] == 'requires_matching_inspected_donor_and_native_checks'
    assert 'base_role' in summary['supported_edits']
    params = dict(template_path=str(source), template_sha256=m.sha(source_bytes),
                  name=f'Native Role Variant Verification {index}', base_role=role)
    before_preview = sorted(m.OUTPUTS.rglob('*'))
    preview = m.generate(params | dict(preview=True))
    assert preview['files_created'] is False and preview['base_role_mode'] == 'explicit_change'
    assert sorted(m.OUTPUTS.rglob('*')) == before_preview
    result = m.generate(params)
    _, _, output = m.read_template(result['output_path'])
    record = m.phase_records(output['.tac'])['in_possession'][5]
    assert output['.tac'][record['record_offset']:record['record_end_exclusive']] == donor_tac[donor_record['record_offset']:donor_record['record_end_exclusive']]
    restored = m.replace_tac_name(output['.tac'], summary['name'])
    source_record = m.phase_records(members['.tac'])['in_possession'][5]
    offset = source_record['role_word_offset']
    assert struct.unpack_from('<Q', restored, offset)[0] == 0x200010
    assert struct.unpack_from('<Q', members['.tac'], offset)[0] == 0x410000
    assert restored[:offset] + struct.pack('<Q', 0x410000) + restored[offset + 8:] == members['.tac']
    assert set(output) == set(members)
    assert all(output[key] == members[key] for key in members if key not in ('.tac', '.aom'))
    assert m.replace_string(output['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), summary['name'], params['name']) == members['.aom']
    before_roles = m.inspect_stored_football(members['.tac'])['phase_positions_and_roles']
    after_roles = m.inspect_stored_football(output['.tac'])['phase_positions_and_roles']
    assert all(before_roles[phase][slot] == after_roles[phase][slot]
               for phase in before_roles for slot in range(11) if (phase, slot) != ('in_possession', 5))
    assert result['base_role']['donor_template_sha256'] == m.sha(donor_bytes)
    assert result['template_sha256'] == m.sha(source_bytes)
    assert result['edits'] == ['name', 'base_role']
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result
    before_inherit = sorted(m.OUTPUTS.rglob('*'))
    inherited = m.generate({key: value for key, value in params.items() if key != 'base_role'} | dict(preview=True))
    assert inherited['base_role'] is None and inherited['base_role_mode'] == 'inherit'
    assert inherited['stored_football']['phase_positions_and_roles'] == before_roles
    assert sorted(m.OUTPUTS.rglob('*')) == before_inherit
    assert source.read_bytes() == source_bytes and donor.read_bytes() == donor_bytes
    positives.append({'source_path': str(source), 'source_sha256': m.sha(source_bytes),
                      'donor_path': str(donor), 'donor_sha256': m.sha(donor_bytes),
                      'output_path': result['output_path'], 'other_phase_records_preserved': 21})

# Every following malformed pair goes through public generate with freshly
# computed, correct archive hashes. Old whole-archive allowlists cannot provide
# the semantic refusal on behalf of the actual invariant checks.
source = sources[0]
_, source_bytes, source_members = m.read_template(str(source))
source_tac = source_members['.tac']
source_record = m.phase_records(source_tac)['in_possession'][5]
refusals = []


def public_refusal(label, source_plaintext, donor_plaintext, expected):
    bad_source, bad_donor = root / (label + '-source.fmf'), root / (label + '-donor.fmf')
    m.repack_native_fmf(source, bad_source, plaintext_overrides={'.tac': source_plaintext})
    m.repack_native_fmf(donor, bad_donor, plaintext_overrides={'.tac': donor_plaintext})
    source_hash, donor_hash = m.sha(bad_source.read_bytes()), m.sha(bad_donor.read_bytes())
    assert source_hash != original_source_sha and donor_hash != original_donor_sha
    request = dict(template_path=str(bad_source), template_sha256=source_hash, name='Refused ' + label,
                   base_role=role | dict(donor_template_path=str(bad_donor), donor_template_sha256=donor_hash))
    before = sorted(m.OUTPUTS.rglob('*'))
    try:
        m.generate(request)
    except ValueError as error:
        assert expected in str(error), str(error)
        assert 'outside the exact pinned' not in str(error)
        refusals.append({'case': label, 'error': str(error), 'valid_source_sha256': source_hash,
                         'valid_donor_sha256': donor_hash})
    else:
        raise AssertionError('Malformed native pair accepted: ' + label)
    assert sorted(m.OUTPUTS.rglob('*')) == before


def paired(relative, replacement):
    a, b = bytearray(source_tac), bytearray(donor_tac)
    for raw, record in [(a, source_record), (b, donor_record)]:
        at = record['record_offset'] + relative
        assert raw[at:at + len(replacement)] != replacement, 'Planted negative must change actual bytes'
        raw[at:at + len(replacement)] = replacement
    return bytes(a), bytes(b)


for label, relative, replacement, error in [
    ('metadata', 14 + 8, b'\x03', 'instruction metadata'),
    ('missing-key', 14, struct.pack('<Q', 0x11), 'target key'),
    ('duplicate-key', 14 + 24, struct.pack('<Q', 0x10), 'target key'),
    ('unsorted-key', 14 + 24, struct.pack('<Q', 0), 'target key'),
    ('noncanonical-duplicate', 14 + 5 * 24, struct.pack('<Q', 0x400010), 'target key'),
    ('noncanonical-key', 14 + 7 * 24, struct.pack('<Q', 0x0200000000200000), 'target key'),
    ('nonzero-low-pi', 14 + 11, struct.pack('<Q', 1), 'target key'),
    ('nonzero-high-pi', 14 + 11, struct.pack('<Q', 1 << 63), 'target key'),
    ('equal-unknown-prefix', 9, b'\x00', 'companion prefix'),
    ('equal-pi-state-prefix', 14 + 19, b'\xfe', 'companion prefix'),
    ('wrong-position', 3, struct.pack('<I', 128), 'IP slot5 DM(CR)'),
    ('wrong-record-version', 0, b'\x43', 'record version'),
]:
    a, b = paired(relative, replacement)
    public_refusal(label, a, b, error)
bad = bytearray(source_tac)
bad[source_record['instruction_vector_offset'] + 19] ^= 1
public_refusal('prefix-mismatch', bytes(bad), donor_tac, 'companion record bytes differ')
for label, major, which in [('fm26-source', 26, 'source'), ('fm26-donor', 26, 'donor')]:
    a, b = bytearray(source_tac), bytearray(donor_tac)
    (a if which == 'source' else b)[11] = major
    public_refusal(label, bytes(a), bytes(b), 'requires native FM27')
for label, word, which in [('source-role', 0x400020, 'source'), ('source-fixed-bit', 0x810000, 'source'),
                           ('donor-role', 0x200001, 'donor'), ('donor-fixed-bit', 0x400010, 'donor')]:
    a, b = bytearray(source_tac), bytearray(donor_tac)
    raw, record = (a, source_record) if which == 'source' else (b, donor_record)
    raw[record['role_word_offset']:record['role_word_offset'] + 8] = struct.pack('<Q', word)
    public_refusal(label, bytes(a), bytes(b), 'donor base role')
# Source eligibility remains conditional: another perfectly valid inspected
# source record is not automatically a valid donor.
public_refusal('eligible-is-not-donor', source_tac, source_tac, 'donor base role')
assert m.summarize(str(donor))['base_role_eligibility'] == 'requires_matching_inspected_donor_and_native_checks'  # Proved reverse direction.

print(json.dumps({'positive_variants': positives, 'public_recomputed_hash_refusals': refusals,
                  'public_refusal_count': len(refusals), 'new_role_pairs': 0, 'game_import_verified': False,
                  'fixtures_directory': str(root)}))
