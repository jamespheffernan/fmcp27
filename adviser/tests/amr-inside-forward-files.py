"""Real source-format26 AM(R) donor edit; no game import or UI claim."""
import importlib.util
import json
from pathlib import Path
import struct
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
scratch = Path(__file__).resolve().parents[1]/'tmp'
scratch.mkdir(exist_ok=True)
root = Path(tempfile.mkdtemp(prefix='amr-inside-forward-', dir=scratch))
m.OUTPUTS = root/'outputs'
source = m.TEMPLATES/'4231 FM27 Att.fmf'
donor = m.TEMPLATES/'4231 FM27 .fmf'
_, sb, sm = m.read_template(str(source))
_, db, dm = m.read_template(str(donor))
st, dt = sm['.tac'], dm['.tac']
slot = int(sys.argv[2]) if len(sys.argv) > 2 else 7
position, mask = {7: ('AM(R)', 2048), 9: ('AM(L)', 4096)}[slot]
a, b = m.phase_records(st)['in_possession'][slot], m.phase_records(dt)['in_possession'][slot]
assert st[11] == dt[11] == 26
assert a['native_role_word'] == '0000000000400080' and b['native_role_word'] == '0000000008800000'
role = dict(phase='in_possession', position_index=slot, donor_position_index=slot,
            donor_template_path=str(donor), donor_template_sha256=m.sha(db))
params = dict(template_path=str(source), template_sha256=m.sha(sb), name='Native AMR Inside Forward Attack', base_role=role)
refusals, artifacts = [], []

def refuse(request, fragment):
    before = sorted(root.rglob('*'))
    try:
        m.generate(request)
    except (ValueError, FileExistsError) as error:
        assert fragment in str(error), str(error)
        refusals.append(fragment)
    else:
        raise AssertionError('Unsupported AM(R) edit accepted')
    assert sorted(root.rglob('*')) == before

def records(tac):
    return {(phase, slot): tac[r['record_offset']:r['record_end_exclusive']]
            for phase, rows in m.phase_records(tac).items() for slot, r in enumerate(rows)}

def preserve(result, before, source_name, new_name, expected=None):
    _, _, out = m.read_template(result['output_path'])
    target = m.phase_records(out['.tac'])['in_possession'][slot]
    assert out['.tac'][target['record_offset']:target['record_end_exclusive']] == dt[b['record_offset']:b['record_end_exclusive']]
    old_records, new_records = records(before['.tac']), records(out['.tac'])
    assert len(old_records) == len(new_records) == 22
    assert sum(old_records[k] == new_records[k] for k in old_records) == 21
    reverted = m.replace_tac_name(out['.tac'], source_name)
    at = m.phase_records(before['.tac'])['in_possession'][slot]['role_word_offset']
    assert struct.unpack_from('<Q', reverted, at)[0] == 0x8800000
    reverted = reverted[:at] + struct.pack('<Q', 0x400080) + reverted[at+8:]
    assert reverted == (before['.tac'] if expected is None else expected)
    assert set(before) == set(out)
    assert all(before[k] == out[k] for k in before if k not in ('.tac', '.aom'))
    assert m.replace_string(out['.aom'], 12+len(b'TACTICS_TYPE_HANDLER'), source_name, new_name) == before['.aom']
    assert result['base_role']['before'] == dict(role='Winger', native_role_word='0000000000400080')
    assert result['base_role']['after'] == dict(role='Inside Forward', native_role_word='0000000008800000')
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] is True
    assert result['verification']['game_load_verified'] is False
    assert json.loads(Path(result['receipt_path']).read_text()) == result
    assert out['.tac'][11] == 26
    artifacts.append(result['output_path'])

summary = m.summarize(str(source))
assert summary['source_game_major'] == 26
assert summary['base_role_cases'] == [dict(phase='in_possession', position_index=7, position='AM(R)'), dict(phase='in_possession', position_index=9, position='AM(L)'),
                                    dict(phase='out_of_possession', position_index=1, position='D(R)'), dict(phase='out_of_possession', position_index=4, position='D(L)')]
preview = m.generate(params | dict(preview=True))
assert preview['status'] == 'preview' and preview['files_created'] is False and not m.OUTPUTS.exists()
result = m.generate(params)
preserve(result, sm, summary['name'], params['name'])
assert result['edits'] == ['name', 'base_role'] and result['base_role_mode'] == 'explicit_change'

# Inheritance preserves the original Winger and never gets changed-role credit.
inherit = m.generate({k:v for k,v in params.items() if k != 'base_role'} | dict(name='Inherited AMR Winger'))
_, _, inherited = m.read_template(inherit['output_path'])
assert m.replace_tac_name(inherited['.tac'], summary['name']) == st
assert inherit['base_role'] is None and inherit['base_role_mode'] == 'inherit'

# Another actual source and generated outside-record variants retain the same local gate.
defensive = m.TEMPLATES/'4231 FM27 Def.fmf'
_, vb, vm = m.read_template(str(defensive))
changed = m.generate(params | dict(template_path=str(defensive), template_sha256=m.sha(vb), name='Native Defensive Source AMR Inside Forward'))
preserve(changed, vm, m.summarize(str(defensive))['name'], 'Native Defensive Source AMR Inside Forward')
variant = m.generate(dict(template_path=str(source), template_sha256=m.sha(sb), name='AMR Source With Lower Tempo', tempo='Lower Tempo'))
vp = Path(variant['output_path'])
_, variant_blob, variant_members = m.read_template(str(vp))
variant_result = m.generate(params | dict(template_path=str(vp), template_sha256=m.sha(variant_blob), name='Variant AMR Inside Forward'))
preserve(variant_result, variant_members, m.summarize(str(vp))['name'], 'Variant AMR Inside Forward')

# Role and team-control edits compose, without treating either as the other's proof.
combined = m.generate(params | dict(name='AMR Inside Forward And Lower Tempo', tempo='Lower Tempo'))
expected = m.replace_tempo(st, 'Lower Tempo')
preserve(combined, sm, summary['name'], 'AMR Inside Forward And Lower Tempo', expected)

for bad in (None, True, False, 1, [], {}, 'Inside Forward'):
    refuse(params | dict(base_role=bad), 'base_role requires')
for change in (dict(phase=None), dict(position_index=9 if slot == 7 else 7),
               dict(position_index=True), dict(donor_position_index=9 if slot == 7 else 7), dict(donor_position_index=True)):
    refuse(params | dict(base_role=role | change), 'supports only')
refuse(params | dict(base_role=role | dict(phase='out_of_possession')),
       'requires native FM27' if slot == 7 else 'requires source-format27')
for change in (dict(role='Inside Forward'), dict(native_role_word='0000000008800000'), dict(extra=True)):
    refuse(params | dict(base_role=role | change), 'exact phase')
for change in (dict(donor_template_path=True), dict(donor_template_path=''), dict(donor_template_sha256=None), dict(donor_template_sha256='0'*64)):
    refuse(params | dict(base_role=role | change), 'donor')
refuse(params | dict(template_sha256='0'*64), 'Template hash changed')

# Correctly hashed repacked native pairs ensure semantic checks, not whole-file pins, reject.
case = 0
def planted(label, edit, fragment, both=True):
    global case
    case += 1
    aa, bb = bytearray(st), bytearray(dt)
    edit(aa, a)
    if both:
        edit(bb, b)
    sp, dp = root/f'{case}-{label}-source.fmf', root/f'{case}-{label}-donor.fmf'
    m.repack_native_fmf(source, sp, plaintext_overrides={'.tac': bytes(aa)})
    m.repack_native_fmf(donor, dp, plaintext_overrides={'.tac': bytes(bb)})
    request = params | dict(template_path=str(sp), template_sha256=m.sha(sp.read_bytes()),
                            base_role=role | dict(donor_template_path=str(dp), donor_template_sha256=m.sha(dp.read_bytes())))
    refuse(request, fragment)

planted('unproved-major27', lambda raw,r: raw.__setitem__(11,27), 'requires source-format26')
for rel in (0,1,2,8):
    planted('record-version-'+str(rel), lambda raw,r,rel=rel:raw.__setitem__(r['record_offset']+rel,raw[r['record_offset']+rel]^1), 'record version')
planted('wrong-position', lambda raw,r:struct.pack_into('<I',raw,r['record_offset']+3,4096 if slot == 7 else 2048), f'requires IP slot{slot}')
planted('metadata', lambda raw,r:raw.__setitem__(r['instruction_vector_offset']+8,3), 'instruction metadata')
planted('missing-key', lambda raw,r:struct.pack_into('<Q',raw,r['instruction_vector_offset']+24,0x8000001), 'target key')
planted('duplicate-key', lambda raw,r:struct.pack_into('<Q',raw,r['instruction_vector_offset']+48,0x8000000), 'target key')
planted('unsorted-key', lambda raw,r:struct.pack_into('<Q',raw,r['instruction_vector_offset'],0x80000000001), 'target key')
planted('unnormalized-key', lambda raw,r:struct.pack_into('<Q',raw,r['instruction_vector_offset']+24,0x8800000), 'target key')
for bits in (0, 1<<16, 1<<18, 1<<25, 0x2050000 | 1<<31):
    planted('target-PI-'+hex(bits), lambda raw,r,bits=bits:struct.pack_into('<Q',raw,r['instruction_vector_offset']+24+11,bits), 'exact PI bits')
planted('other-PI', lambda raw,r:struct.pack_into('<Q',raw,r['instruction_vector_offset']+11,0), 'companion prefix')
planted('one-side-prefix', lambda raw,r:raw.__setitem__(r['instruction_vector_offset']+11,1), 'companion record bytes differ', False)
for word, original in ((0x800080,a),(0x4400080,a),(0x8400000,b),(0x8800001,b)):
    aa, bb = bytearray(st), bytearray(dt)
    raw = aa if original is a else bb
    struct.pack_into('<Q',raw,original['role_word_offset'],word)
    case += 1
    sp, dp = root/f'{case}-wrong-role-source.fmf',root/f'{case}-wrong-role-donor.fmf'
    m.repack_native_fmf(source,sp,plaintext_overrides={'.tac':bytes(aa)})
    m.repack_native_fmf(donor,dp,plaintext_overrides={'.tac':bytes(bb)})
    refuse(params | dict(template_path=str(sp),template_sha256=m.sha(sp.read_bytes()),base_role=role | dict(donor_template_path=str(dp),donor_template_sha256=m.sha(dp.read_bytes()))),'source or donor role')

decode = m.decode_word
def wrong_label(word, phase):
    value = decode(word,phase)
    if word == 0x8800000:
        value['compiled_english_name'] = 'Changed role'
    return value
m.decode_word = wrong_label
try:
    refuse(params,'label bindings changed')
finally:
    m.decode_word = decode

native = m.ROLE_NATIVE_PLUGIN
for selected in range(len(m.INSIDE_FORWARD_NATIVE_SPANS)):
    path = root/f'changed-native-{selected}.bin'
    with native.open('rb') as src,path.open('wb') as out:
        for index,(offset,size,_) in enumerate(m.INSIDE_FORWARD_NATIVE_SPANS):
            src.seek(0x5ED4000+offset)
            raw = src.read(size)
            if selected == index:
                raw = bytes([raw[0]^1])+raw[1:]
            out.seek(0x5ED4000+offset)
            out.write(raw)
    m.ROLE_NATIVE_PLUGIN = path
    try:
        refuse(params,'inside-forward source changed')
    finally:
        m.ROLE_NATIVE_PLUGIN = native

assert source.read_bytes() == sb and donor.read_bytes() == db
print(json.dumps({'stored_before':'Winger','stored_after':'Inside Forward',
                  'source_format_major':26,'phase':'in_possession','position_index':slot,'position':position,
                  'other_records_preserved':21,'positive_artifacts':artifacts,'refusals':len(refusals),
                  'game_import_verified':False,'source_sha256':m.sha(sb),'donor_sha256':m.sha(db)},indent=2))
