"""Actual native archives for all26 finite edits and public semantic refusals."""
import importlib.util
import itertools
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('writer', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
scratch = Path(__file__).resolve().parents[1]/'tmp'
scratch.mkdir(exist_ok=True)
root = Path(tempfile.mkdtemp(prefix='role-matrix-', dir=scratch))
m.OUTPUTS = root/'outputs'
observed = {}
for path in sorted(m.TEMPLATES.glob('*.fmf')):
    _, blob, members = m.read_template(str(path))
    tac = members['.tac']
    for phase, records in m.phase_records(tac).items():
        for record in records:
            case = (tac[11], phase, record['position_index'])
            if case not in m.MATRIX_ROLE_CASES:
                continue
            mask, prefix, words, _ = m.MATRIX_ROLE_CASES[case]
            word = int(record['native_role_word'], 16)
            if record['position_mask'] == mask and word in words and m.sha(tac[record['record_offset']:record['role_word_offset']]) == prefix:
                observed.setdefault(case, {})[word] = (path, blob, members, record)

assert len(observed) == len(m.MATRIX_ROLE_CASES) == 9
artifacts, refusals, variants = [], [], []


def params(case, source, donor, name):
    return dict(template_path=str(source[0]), template_sha256=m.sha(source[1]), name=name,
                base_role=dict(phase=case[1], position_index=case[2], donor_position_index=case[2],
                               donor_template_path=str(donor[0]), donor_template_sha256=m.sha(donor[1])))


def records(tac):
    return {(phase, slot): tac[r['record_offset']:r['record_end_exclusive']]
            for phase, rows in m.phase_records(tac).items() for slot, r in enumerate(rows)}


def preserve(case, source, donor, request, result, expected=None):
    _, _, out = m.read_template(result['output_path'])
    phase, slot = case[1:]
    a, b = source[3], donor[3]
    target = m.phase_records(out['.tac'])[phase][slot]
    assert out['.tac'][target['record_offset']:target['record_end_exclusive']] == donor[2]['.tac'][b['record_offset']:b['record_end_exclusive']]
    before, after = records(source[2]['.tac']), records(out['.tac'])
    assert len(before) == len(after) == 22
    assert sum(before[k] == after[k] for k in before) == 21
    old_name = m.summarize(str(source[0]))['name']
    restored = m.replace_tac_name(out['.tac'], old_name)
    at = a['role_word_offset']
    restored = restored[:at] + bytes.fromhex(a['native_role_word'])[::-1] + restored[at+8:]
    assert restored == (source[2]['.tac'] if expected is None else expected)
    assert m.replace_string(out['.aom'], 12+len(b'TACTICS_TYPE_HANDLER'), old_name, request['name']) == source[2]['.aom']
    assert set(source[2]) == set(out)
    assert all(source[2][k] == out[k] for k in source[2] if k not in ('.tac', '.aom'))
    assert out['.tac'][11] == case[0]
    for key, record in [('before', a), ('after', b)]:
        assert result['base_role'][key] == dict(role=record['role']['compiled_english_name'], native_role_word=record['native_role_word'])
    assert result['base_role']['position_index'] == slot
    assert result['base_role_mode'] == 'explicit_change'
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result


def refuse(request):
    before = sorted(m.OUTPUTS.rglob('*'))
    try:
        m.generate(request)
    except ValueError as exc:
        refusals.append(str(exc))
    else:
        raise AssertionError('Unproved role-matrix request accepted')
    assert sorted(m.OUTPUTS.rglob('*')) == before


for case, choices in observed.items():
    words = m.MATRIX_ROLE_CASES[case][2]
    assert set(choices) == set(words)
    for source_word, donor_word in itertools.permutations(words, 2):
        source, donor = choices[source_word], choices[donor_word]
        request = params(case, source, donor, f'Native Matrix {case[0]} {case[1]} {case[2]} {source_word:x} to {donor_word:x}')
        before = sorted(m.OUTPUTS.rglob('*'))
        preview = m.generate(request | dict(preview=True))
        assert preview['status'] == 'preview' and preview['files_created'] is False
        assert sorted(m.OUTPUTS.rglob('*')) == before
        result = m.generate(request)
        preserve(case, source, donor, request, result)
        artifacts.append(dict(case=case, before=source_word, after=donor_word,
                              output=result['output_path'], sha256=result['output_sha256']))
    # A generated archive can differ outside the exact proved record.
    source, donor = choices[words[-1]], choices[words[0]]
    original = params(case, source, donor, 'Matrix Variant')
    variant = m.generate({k: v for k, v in original.items() if k != 'base_role'} | dict(name='Matrix Source Lower Tempo', tempo='Lower Tempo'))
    vp, vb, vm = m.read_template(variant['output_path'])
    vr = m.phase_records(vm['.tac'])[case[1]][case[2]]
    source_variant = (vp, vb, vm, vr)
    request = params(case, source_variant, donor, 'Matrix Variant Role And Low Crosses') | dict(crossing_style='Low Crosses')
    changed = m.generate(request)
    expected = m.replace_stored_control(vm['.tac'], 'crossing_style', 'Low Crosses')
    preserve(case, source_variant, donor, request, changed, expected)
    variants.append(changed['output_path'])

    # Every planted pair is newly repacked and correctly hash-pinned. Mutating
    # both prefixes distinguishes semantic guards from equality-only checks.
    count = 0
    def planted(label, edit, both=True):
        global count
        count += 1
        a, b = bytearray(source[2]['.tac']), bytearray(donor[2]['.tac'])
        edit(a, source[3])
        if both:
            edit(b, donor[3])
        sp, dp = root/f'{case[0]}-{case[1]}-{case[2]}-{count}-source.fmf', root/f'{case[0]}-{case[1]}-{case[2]}-{count}-donor.fmf'
        m.repack_native_fmf(source[0], sp, plaintext_overrides={'.tac': bytes(a)})
        m.repack_native_fmf(donor[0], dp, plaintext_overrides={'.tac': bytes(b)})
        request = original | dict(name='Refuse '+label, template_path=str(sp), template_sha256=m.sha(sp.read_bytes()),
                                  base_role=original['base_role'] | dict(donor_template_path=str(dp), donor_template_sha256=m.sha(dp.read_bytes())))
        refuse(request)

    target_key = words[0] & 0xFFFBFFFFF91FFFFF
    target_index = next(i for i in range(source[3]['instruction_entry_count']) if struct.unpack_from('<Q', source[2]['.tac'], source[3]['instruction_vector_offset']+24*i)[0] == target_key)
    other_index = 0 if target_index else 1
    planted('unproved format', lambda raw, r: raw.__setitem__(11, 27 if case[0] == 26 else 26))
    planted('wrong position', lambda raw, r: struct.pack_into('<I', raw, r['record_offset']+3, 4 if r['position_mask'] != 4 else 8))
    for rel in (0, 1, 2, 8):
        planted('record header', lambda raw, r, rel=rel: raw.__setitem__(r['record_offset']+rel, raw[r['record_offset']+rel]^1))
    planted('instruction metadata', lambda raw, r: raw.__setitem__(r['instruction_vector_offset']+8, 3))
    planted('missing target', lambda raw, r: struct.pack_into('<Q', raw, r['instruction_vector_offset']+24*target_index, target_key | 1<<63))
    planted('duplicate target', lambda raw, r: struct.pack_into('<Q', raw, r['instruction_vector_offset']+24*other_index, target_key))
    planted('unnormalized target', lambda raw, r: struct.pack_into('<Q', raw, r['instruction_vector_offset']+24*target_index, target_key | 1<<21))
    planted('wrong target PI', lambda raw, r: struct.pack_into('<Q', raw, r['instruction_vector_offset']+24*target_index+11, m.MATRIX_ROLE_CASES[case][3]^1))
    planted('other PI', lambda raw, r: raw.__setitem__(r['instruction_vector_offset']+24*other_index+11, raw[r['instruction_vector_offset']+24*other_index+11]^1))
    planted('one-sided prefix', lambda raw, r: raw.__setitem__(r['instruction_vector_offset']+11, raw[r['instruction_vector_offset']+11]^1), False)
    planted('unproved role word', lambda raw, r: struct.pack_into('<Q', raw, r['role_word_offset'], int(r['native_role_word'], 16) | 1<<63))
    refuse(original | dict(base_role=original['base_role'] | dict(donor_template_path=str(source[0]), donor_template_sha256=m.sha(source[1]))))
    # Unsupported request shapes never become arbitrary role-word authoring.
    refuse(original | dict(base_role=original['base_role'] | dict(role='Invented Role')))
    refuse(original | dict(base_role=original['base_role'] | dict(native_role_word='ffffffffffffffff')))
    refuse(original | dict(base_role=original['base_role'] | dict(donor_template_sha256='0'*64)))
    refuse(original | dict(template_sha256='0'*64))
    assert source[0].read_bytes() == source[1] and donor[0].read_bytes() == donor[1]

assert len(artifacts) == 26 and len(variants) == 9 and len(refusals) >= 160
# Each compiled role binding is checked on an actual supported request.
original_decode = m.decode_word
for (phase, word), _ in m.MATRIX_ROLE_LABELS.items():
    case = next(case for case in observed if case[1] == phase and word in observed[case])
    choices = observed[case]
    source = choices[word]
    donor = next(value for key, value in choices.items() if key != word)
    def changed_decode(value, mode, word=word, phase=phase):
        decoded = original_decode(value, mode)
        if value == word and mode == phase:
            decoded['compiled_english_name'] = 'Changed compiled label'
        return decoded
    m.decode_word = changed_decode
    try:
        refuse(params(case, source, donor, 'Refuse Compiled Binding Drift'))
    finally:
        m.decode_word = original_decode
# Pin failure and post-pack drift controls exercise the new matrix route.
case = (26, 'out_of_possession', 1)
source, donor = observed[case][0x200800], observed[case][0x400400]
request = params(case, source, donor, 'Matrix Native Guard')
native = m.ROLE_NATIVE_PLUGIN
for selected in range(len(m.MATRIX_ROLE_NATIVE_SPANS)):
    path = root/f'changed-native-{selected}.bin'
    with native.open('rb') as src, path.open('wb') as out:
        for index, (offset, size, _) in enumerate(m.MATRIX_ROLE_NATIVE_SPANS):
            src.seek(0x5ED4000+offset)
            raw = src.read(size)
            if selected == index:
                raw = bytes([raw[0]^1])+raw[1:]
            out.seek(0x5ED4000+offset)
            out.write(raw)
    m.ROLE_NATIVE_PLUGIN = path
    try:
        refuse(request)
    finally:
        m.ROLE_NATIVE_PLUGIN = native
original_repack = m.repack_native_fmf
def drift(*args, **kwargs):
    original_repack(*args, **kwargs)
    m.ROLE_NATIVE_PLUGIN = root/'changed-native-0.bin'
m.repack_native_fmf = drift
try:
    refuse(request | dict(preview=True))
finally:
    m.repack_native_fmf, m.ROLE_NATIVE_PLUGIN = original_repack, native
resource = m.LOSS_ENGLISH_RESOURCE
bad = root/'changed-English.ltf'
bad.write_text('Changed definitions')
m.LOSS_ENGLISH_RESOURCE = bad
try:
    refuse(request)
finally:
    m.LOSS_ENGLISH_RESOURCE = resource
print(json.dumps(dict(artifacts=artifacts, variant_artifacts=variants, public_refusals=len(refusals),
                      exact_prefixes=9, directed_changes=26, game_import_verified=False), indent=2))
