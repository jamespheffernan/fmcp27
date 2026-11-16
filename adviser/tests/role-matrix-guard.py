"""The parent phase-order pin guards matrix preview before and after packing."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('writer', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
scratch = Path(__file__).resolve().parents[1]/'tmp'
scratch.mkdir(exist_ok=True)
root = Path(tempfile.mkdtemp(prefix='role-matrix-parent-guard-', dir=scratch))
m.OUTPUTS = root/'outputs'
source, donor = m.TEMPLATES/'4231 FM27 Def.fmf', m.TEMPLATES/'4231 FM27 Att.fmf'
_, sb, _ = m.read_template(str(source))
_, db, _ = m.read_template(str(donor))
request = dict(template_path=str(source), template_sha256=m.sha(sb), name='Matrix Parent Guard', preview=True,
               base_role=dict(phase='out_of_possession', position_index=1, donor_position_index=1,
                              donor_template_path=str(donor), donor_template_sha256=m.sha(db)))
assert m.generate(request)['files_created'] is False
assert not m.OUTPUTS.exists()
native = m.ROLE_NATIVE_PLUGIN
changed = root/'changed-parent-serializer.bin'
with native.open('rb') as src, changed.open('wb') as out:
    for offset, size, _ in m.MATRIX_ROLE_NATIVE_SPANS:
        src.seek(0x5ED4000+offset)
        raw = src.read(size)
        if offset == 0x4A8D728:
            raw = bytes([raw[0]^1])+raw[1:]
        out.seek(0x5ED4000+offset)
        out.write(raw)


def refused():
    try:
        m.generate(request)
    except ValueError as exc:
        assert 'Native role-matrix source changed' in str(exc), str(exc)
    else:
        raise AssertionError('Changed parent phase-order native source accepted')
    assert not m.OUTPUTS.exists()


m.ROLE_NATIVE_PLUGIN = changed
try:
    refused()
finally:
    m.ROLE_NATIVE_PLUGIN = native
original_repack = m.repack_native_fmf
def drift(*args, **kwargs):
    original_repack(*args, **kwargs)
    m.ROLE_NATIVE_PLUGIN = changed
m.repack_native_fmf = drift
try:
    refused()
finally:
    m.repack_native_fmf, m.ROLE_NATIVE_PLUGIN = original_repack, native
assert source.read_bytes() == sb and donor.read_bytes() == db
print(json.dumps(dict(parent_pin_refused=True, postpack_refused=True, preview_no_files=True, game_import_verified=False)))
