"""Bounded public archive checks; no large native-span fixture files."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('writer', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='stored-role-files-', dir=Path(__file__).resolve().parents[1]/'tmp'))
m.OUTPUTS = root/'outputs'
base, attack, defensive = [m.TEMPLATES/name for name in ('3421 FM27 .fmf', '3421 FM27 Att.fmf', '3421 FM27 Def.fmf')]
sources = {path: m.read_template(str(path)) for path in (base, attack, defensive)}
artifacts, refusals = [], 0


def instruction_request(path):
    return dict(phase='in_possession', position_index=9, donor_position_index=9,
                donor_template_path=str(path), donor_template_sha256=m.sha(sources[path][1]))


def params(source, donor, name):
    return dict(template_path=str(source), template_sha256=m.sha(sources[source][1]), name=name,
                stored_role_instructions=instruction_request(donor))


def files():
    return {p: m.sha(p.read_bytes()) for p in m.OUTPUTS.rglob('*') if p.is_file()}


def refuse(request, fragment):
    global refusals
    before = files()
    try:
        m.generate(request)
    except (ValueError, FileExistsError) as exc:
        assert fragment in str(exc), str(exc)
    else:
        raise AssertionError('Unsupported instruction archive accepted')
    assert files() == before
    refusals += 1


def preserve(request, result):
    source = sources[Path(request['template_path'])]
    donor = sources[Path(request['stored_role_instructions']['donor_template_path'])]
    _, _, output = m.read_template(result['output_path'])
    current, _, _ = m.stored_role_pi_record(output['.tac'])
    target, _, _ = m.stored_role_pi_record(donor[2]['.tac'])
    assert output['.tac'][current['record_offset']:current['record_end_exclusive']] == donor[2]['.tac'][target['record_offset']:target['record_end_exclusive']]
    restored = m.replace_tac_name(output['.tac'], m.summarize(str(source[0]))['name'])
    _, offset, _ = m.stored_role_pi_record(source[2]['.tac'])
    restored = restored[:offset] + source[2]['.tac'][offset:offset+8] + restored[offset+8:]
    if 'base_role' in request:
        role = request['base_role']
        row = m.phase_records(source[2]['.tac'])[role['phase']][role['position_index']]
        at = row['role_word_offset']
        restored = restored[:at] + source[2]['.tac'][at:at+8] + restored[at+8:]
    if 'tempo' in request:
        restored = m.replace_tempo(restored, m.tempo_selection(source[2]['.tac'])[1])
    if 'crossing_style' in request:
        restored = m.replace_stored_control(restored, 'crossing_style', m.stored_control_selection(source[2]['.tac'], 'crossing_style')[1])
    assert restored == source[2]['.tac']
    assert set(output) == set(source[2])
    assert all(output[key] == source[2][key] for key in output if key not in ('.tac', '.aom'))
    assert m.replace_string(output['.aom'], 12+len(b'TACTICS_TYPE_HANDLER'), m.summarize(str(source[0]))['name'], request['name']) == source[2]['.aom']
    assert result['stored_role_instructions_mode'] == 'explicit_change'
    assert 'stored_role_instructions' in result['edits']
    assert 'unrequested player instruction bytes' in result['preserved']
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result
    artifacts.append(result['output_path'])


for source, donor in [(base, attack), (attack, base)]:
    request = params(source, donor, 'Native Stored Instructions '+('Selected' if donor == attack else 'Cleared'))
    before = files()
    preview = m.generate(request | dict(preview=True))
    assert preview['files_created'] is False and files() == before
    result = m.generate(request)
    preserve(request, result)

combined = params(defensive, attack, 'Native Stored Instructions With BBM Lower Tempo And Low Crosses')
combined.update(base_role=instruction_request(attack) | dict(position_index=5, donor_position_index=5),
                tempo='Lower Tempo', crossing_style='Low Crosses')
preserve(combined, m.generate(combined))

# Omission preserves the complete instruction record and receives no edit credit.
inherit = params(base, attack, 'Inherited Native Instruction Record')
inherit.pop('stored_role_instructions')
result = m.generate(inherit)
_, _, inherited = m.read_template(result['output_path'])
assert m.replace_tac_name(inherited['.tac'], m.summarize(str(base))['name']) == sources[base][2]['.tac']
assert result['stored_role_instructions'] is None and result['stored_role_instructions_mode'] == 'inherit'
assert 'stored_role_instructions' not in result['edits'] and 'player instruction bytes' in result['preserved']

request = params(base, attack, 'Native Instruction Public Refusals')
for invalid in (None, True, {}, dict(option_ids=[24, 27])):
    refuse(request | dict(stored_role_instructions=invalid), 'exact phase')
refuse(request | dict(stored_role_instructions=instruction_request(base)), 'no-op')
refuse(request | dict(stored_role_instructions=instruction_request(attack) | dict(donor_template_sha256='0'*64)), 'donor hash')
refuse(request | dict(template_sha256='0'*64), 'Template hash')

class ChangedMetadata:
    def read_bytes(self):
        return b'Changed enum metadata'


original_repack, original_inspect = m.repack_native_fmf, m.inspect_stored_football
metadata = m.STORED_ROLE_PI_METADATA
def postpack(*args, **kwargs):
    original_repack(*args, **kwargs)
    m.STORED_ROLE_PI_METADATA = ChangedMetadata()
m.repack_native_fmf = postpack
try:
    refuse(request | dict(preview=True), 'enum metadata changed')
finally:
    m.repack_native_fmf, m.STORED_ROLE_PI_METADATA = original_repack, metadata
def final_delivery(*args, **kwargs):
    result = original_inspect(*args, **kwargs)
    m.STORED_ROLE_PI_METADATA = ChangedMetadata()
    return result
m.inspect_stored_football = final_delivery
try:
    refuse(request, 'enum metadata changed')
finally:
    m.inspect_stored_football, m.STORED_ROLE_PI_METADATA = original_inspect, metadata

# Donor/source identities are checked after packing and immediately before delivery.
for kind in ('source', 'donor'):
    blob = sources[base if kind == 'source' else attack][1]
    changing = root/f'changing-{kind}.fmf'
    changing.write_bytes(blob)
    altered = request | (dict(template_path=str(changing)) if kind == 'source' else dict(stored_role_instructions=instruction_request(attack) | dict(donor_template_path=str(changing))))
    def identity_drift(*args, **kwargs):
        original_repack(*args, **kwargs)
        changing.write_bytes(changing.read_bytes()+b'drift')
    m.repack_native_fmf = identity_drift
    try:
        refuse(altered, 'changed during generation')
    finally:
        m.repack_native_fmf = original_repack
    changing.write_bytes(blob)
    def late_identity(*args, **kwargs):
        result = original_inspect(*args, **kwargs)
        changing.write_bytes(changing.read_bytes()+b'drift')
        return result
    m.inspect_stored_football = late_identity
    try:
        refuse(altered, 'changed before delivery')
    finally:
        m.inspect_stored_football = original_inspect

destination = root/'FM27 Tactics'
destination.mkdir()
saved_request = request | dict(name='Native Stored Instructions In Folder', fm27_folder=True, tactics_directory=str(destination))
saved = m.generate(saved_request)
saved_blob = Path(saved['output_path']).read_bytes()
refuse(saved_request, 'already exists')
assert Path(saved['output_path']).read_bytes() == saved_blob
for path, (_, blob, _) in sources.items():
    assert path.read_bytes() == blob
print(json.dumps(dict(artifacts=artifacts, public_refusals=refusals, native_fixture_files_created=0,
                      files_directory=str(root), game_import_verified=False), indent=2))
