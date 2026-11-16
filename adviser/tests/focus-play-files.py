"""Actual file edits; synthetic conflicts and drift stay separately labelled."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('writer', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
root = Path(tempfile.mkdtemp(prefix='focus-play-', dir=Path(__file__).resolve().parents[1] / 'tmp'))
m.OUTPUTS = root / 'outputs'
labels = ['Focus Play Down The Left', 'Focus Play Down The Right', 'Focus Play Through The Middle', 'Focus Play Down Both Flanks']
choices = [[], [labels[0]], [labels[1]], [labels[0], labels[1]], [labels[2]], [labels[3]]]
mask = sum(1 << n for n in range(21, 25))
artifacts = []
negatives = 0


def vector(tac):
    p = m.parse_tac_plaintext(tac)['pre_style_setup']
    at = p['team_instruction_vector_candidate_offset']
    assert p['team_instruction_vector_candidate_size'] == 12 and tac[at - 1] == 3
    return at, int.from_bytes(tac[at:at + 12], 'little')


def bits(values):
    return sum(1 << (labels.index(label) + 21) for label in values)


def preserve(result, before, old_name, expected):
    _, _, after = m.read_template(result['output_path'])
    restored = m.replace_tac_name(after['.tac'], old_name)
    at, _ = vector(before['.tac'])
    assert vector(restored) == (at, expected)
    assert restored[:at] + before['.tac'][at:at + 12] + restored[at + 12:] == before['.tac']
    assert m.phase_records(after['.tac']) == m.phase_records(m.replace_tac_name(before['.tac'], result['name']))
    assert after['.img'] == before['.img']
    assert m.replace_string(after['.aom'], 12 + len(b'TACTICS_TYPE_HANDLER'), old_name, result['name']) == before['.aom']
    assert json.loads(Path(result['receipt_path']).read_text()) == result
    assert result['verification']['all_unrequested_tactic_bytes_preserved'] and not result['verification']['game_load_verified']


def generate(source, values):
    _, raw, before = m.read_template(str(source))
    old = m.summarize(str(source))['name']
    _, flags = vector(before['.tac'])
    result = m.generate(dict(template_path=str(source), template_sha256=m.sha(raw), name='Focus Play Verification', focus_play=values))
    assert result['edits'] == ['name', 'focus_play']
    assert result['focus_play'] == sorted(values, key=labels.index) and result['focus_play_mode'] == 'explicit_change'
    preserve(result, before, old, (flags & ~mask) | bits(values))
    artifacts.append(dict(source=str(source), source_sha256=m.sha(raw), output=result['output_path'], output_sha256=result['output_sha256'], selections=values, old_name=old, new_name=result['name']))
    assert source.read_bytes() == raw
    return result


def refuse(params, reason):
    global negatives
    before = sorted(m.OUTPUTS.rglob('*'))
    try:
        m.generate(params)
    except (ValueError, FileExistsError) as error:
        assert reason in str(error), (reason, str(error))
        negatives += 1
    else:
        raise AssertionError('Invalid focus-play edit was delivered')
    assert sorted(m.OUTPUTS.rglob('*')) == before


templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert len(templates) >= 9
for source in templates:
    _, raw, before = m.read_template(str(source))
    at, flags = vector(before['.tac'])
    summary = m.summarize(str(source))
    assert summary['focus_play_state'] == 'known' and 'focus_play' in summary['supported_edits']
    for values in choices:
        generate(source, values)
    params = dict(template_path=str(source), template_sha256=m.sha(raw), name='Focus Preview', preview=True)
    prior = sorted(m.OUTPUTS.rglob('*'))
    inherited = m.generate(params)
    preview = m.generate(params | dict(focus_play=[labels[2]]))
    assert inherited['focus_play'] == summary['focus_play'] and inherited['focus_play_mode'] == 'inherit'
    assert not preview['files_created'] and not inherited['files_created'] and sorted(m.OUTPUTS.rglob('*')) == prior
source = m.TEMPLATES / '3421 FM27 Att.fmf'
_, raw, before = m.read_template(str(source))
at, flags = vector(before['.tac'])
base = dict(template_path=str(source), template_sha256=m.sha(raw), name='Focus Negative', focus_play=[labels[2]])
for value in [None, True, False, 1, {}, 'Focus Play Through The Middle', ['Central'], [None], [True], [labels[0], labels[0]]]:
    refuse(base | dict(focus_play=value), 'Unsupported stored focus_play')
for value in [[labels[0], labels[2]], [labels[1], labels[3]], [labels[2], labels[3]], [labels[0], labels[1], labels[2]]]:
    refuse(base | dict(focus_play=value), 'Unsupported stored focus_play' if len(value) > 2 else 'Contradictory requested')
generate(source, [labels[1], labels[0]])  # Input order has no semantic effect.
refuse(base | dict(template_sha256='0' * 64), 'Template hash changed')
for bit in range(21, 25):
    old = m.OPTION_NAMES[bit]
    try:
        m.OPTION_NAMES[bit] = 'Changed label'
        refuse(base, 'option labels changed')
    finally:
        m.OPTION_NAMES[bit] = old
# Left+Right is a valid source; every other multiple selection is conflicting.
for chosen in range(16):
    selected = sum(1 << (21 + i) for i in range(4) if chosen & (1 << i))
    path = root / f'source-focus-{chosen}.fmf'
    tac = before['.tac'][:at] + ((flags & ~mask) | selected).to_bytes(12, 'little') + before['.tac'][at + 12:]
    m.repack_native_fmf(source, path, plaintext_overrides={'.tac': tac})
    summary = m.summarize(str(path))
    if chosen in (0, 1, 2, 3, 4, 8):
        assert summary['focus_play_state'] == 'known'
        generate(path, [labels[2]])
    else:
        assert summary['focus_play_state'] == 'conflicting_stored_selections' and 'focus_play' not in summary['supported_edits']
        params = dict(template_path=str(path), template_sha256=m.sha(path.read_bytes()), name='Inherited Focus Conflict')
        result = m.generate(params)
        preserve(result, m.read_template(str(path))[2], summary['name'], (flags & ~mask) | selected)
        for values in choices:
            refuse(params | dict(focus_play=values), 'contradictory stored')
for prefix in [0, 1, 2, 4, 255]:
    path = root / f'prefix-{prefix}.fmf'
    m.repack_native_fmf(source, path, plaintext_overrides={'.tac': before['.tac'][:at - 1] + bytes([prefix]) + before['.tac'][at:]})
    refuse(base | dict(template_path=str(path), template_sha256=m.sha(path.read_bytes())), 'Unsupported native team instruction vector')
unknown = root / 'unknown64.fmf'
m.repack_native_fmf(source, unknown, plaintext_overrides={'.tac': before['.tac'][:at] + (flags | (1 << 64)).to_bytes(12, 'little') + before['.tac'][at + 12:]})
generate(unknown, [labels[2]])
native = m.FOCUS_PLAY_NATIVE_PLUGIN
for index in range(len(m.FOCUS_PLAY_NATIVE_SPANS)):
    path = root / f'changed-native-{index}.bin'
    with native.open('rb') as src, path.open('wb') as dst:
        for j, (offset, n, _) in enumerate(m.FOCUS_PLAY_NATIVE_SPANS):
            src.seek(0x5ed4000 + offset)
            data = src.read(n)
            if j == index:
                data = bytes([data[0] ^ 1]) + data[1:]
            dst.seek(0x5ed4000 + offset)
            dst.write(data)
    try:
        m.FOCUS_PLAY_NATIVE_PLUGIN = path
        refuse(base, 'Native focus-play source changed')
    finally:
        m.FOCUS_PLAY_NATIVE_PLUGIN = native
resource = m.FOCUS_PLAY_ENGLISH_RESOURCE
bad = root / 'changed-English.ltf'
bad.write_text('Changed')
try:
    m.FOCUS_PLAY_ENGLISH_RESOURCE = bad
    refuse(base, 'English definitions changed')
finally:
    m.FOCUS_PLAY_ENGLISH_RESOURCE = resource
combined = m.generate(base | dict(name='Combined Focus', final_third_delivery='Work Ball Into Box', crossing_style='Low Crosses'))
preserve(combined, before, m.summarize(str(source))['name'], (flags & ~(mask | (1 << 9) | (1 << 17) | (7 << 10))) | (1 << 23) | (1 << 17) | (1 << 12))
original = m.repack_native_fmf
copy = root / 'changing-source.fmf'
copy.write_bytes(raw)
def change_source(*args, **kwargs):
    original(*args, **kwargs)
    copy.write_bytes(raw + b'drift')
try:
    m.repack_native_fmf = change_source
    refuse(base | dict(template_path=str(copy)), 'Template changed during generation')
finally:
    m.repack_native_fmf = original
def change_native(*args, **kwargs):
    original(*args, **kwargs)
    m.FOCUS_PLAY_NATIVE_PLUGIN = root / 'changed-native-0.bin'
try:
    m.repack_native_fmf = change_native
    refuse(base | dict(preview=True), 'Native focus-play source changed')
finally:
    m.repack_native_fmf = original
    m.FOCUS_PLAY_NATIVE_PLUGIN = native
verify_native = m.verify_focus_play_native
calls = 0
copy.write_bytes(raw)
def change_before_delivery():
    global calls
    verify_native()
    calls += 1
    if calls == 3:
        copy.write_bytes(raw + b'delivery drift')
try:
    m.verify_focus_play_native = change_before_delivery
    refuse(base | dict(template_path=str(copy)), 'Template changed before delivery')
finally:
    m.verify_focus_play_native = verify_native
folder = root / 'Tactics'
folder.mkdir()
params = base | dict(name='Focus Destination', fm27_folder=True, tactics_directory=str(folder))
result = m.generate(params)
saved = Path(result['output_path']).read_bytes()
refuse(params, 'already exists')
assert Path(result['output_path']).read_bytes() == saved
refuse(params | dict(name='../Escape'), 'single filename component')
print(json.dumps(dict(templates_checked=len(templates), artifacts=artifacts, negative_controls=negatives,
                      native_spans=len(m.FOCUS_PLAY_NATIVE_SPANS), fixtures_directory=str(root), game_import_verified=False)))
