"""Real native templates: tempo edits change only independently checked bits46..49."""
import importlib.util
import itertools
import json
from pathlib import Path
import sys
import tempfile

spec = importlib.util.spec_from_file_location('tactic_files', sys.argv[1])
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
expected = {'No explicit selection': 0, 'Much Higher Tempo': 1 << 46,
            'Higher Tempo': 1 << 47, 'Lower Tempo': 1 << 48, 'Much Lower Tempo': 1 << 49}
mask = 15 << 46
templates = sorted(m.TEMPLATES.glob('*.fmf'))
assert templates
representatives = {}
for template in templates:
    source = template.read_bytes()
    _, _, members = m.read_template(str(template))
    tac = members['.tac']
    offset = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    original_flags = int.from_bytes(tac[offset:offset + 12], 'little')
    representatives.setdefault(tac[11], template)
    for name, bits in expected.items():
        modified = m.replace_tempo(tac, name)
        assert modified[:offset] == tac[:offset]
        assert modified[offset + 12:] == tac[offset + 12:]
        flags = int.from_bytes(modified[offset:offset + 12], 'little')
        assert flags & mask == bits
        assert flags & ~mask == original_flags & ~mask
        assert m.tempo_selection(modified) == (offset, name)
        selected = m.inspect_stored_football(modified)['stored_team_instructions']
        tempo = [v for v in selected if 46 <= v['native_option_id'] <= 49]
        assert tempo == ([] if bits == 0 else [{'native_option_id': bits.bit_length() - 1, 'name': name}])
    for count in range(2, 5):
        for bits in itertools.combinations(range(46, 50), count):
            flags = (original_flags & ~mask) | sum(1 << bit for bit in bits)
            bad = tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]
            assert m.describe_tempo(bad) == {'tempo': None, 'tempo_state': 'conflicting_stored_selections'}
            try:
                m.replace_tempo(bad, 'Higher Tempo')
            except ValueError as error:
                assert 'contradictory' in str(error)
            else:
                raise AssertionError('Contradictory native tempo was overwritten')
    assert template.read_bytes() == source

generated = 0
with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / 'tmp') as td:
    root = Path(td)
    m.OUTPUTS = root / 'outputs'
    for template in representatives.values():
        summary = m.summarize(str(template))
        params = dict(template_path=str(template), template_sha256=summary['template_sha256'], name='Tempo Native Verification')
        for name in expected:
            result = m.generate(params | dict(tempo=name, defensive_line='Higher Defensive Line',
                                             team_tackling='Stay On Feet', mentality='Positive'))
            output = m.summarize(result['output_path'])
            assert output['tempo'] == name
            assert output['defensive_line'] == 'Higher Defensive Line'
            assert output['team_tackling'] == 'Stay On Feet'
            assert output['mentality'] == 'Positive'
            assert output['stored_football']['phase_positions_and_roles'] == summary['stored_football']['phase_positions_and_roles']
            assert result['verification']['all_unrequested_tactic_bytes_preserved']
            assert result['tempo_mode'] == 'explicit_change'
            assert result['verification']['game_load_verified'] is False
            generated += 1
        inherited = m.generate(params | dict(preview=True))
        assert inherited['tempo'] == summary['tempo'] and inherited['tempo_mode'] == 'inherit'
        assert inherited['files_created'] is False
        before = sorted(root.rglob('*'))
        for changes in [dict(tempo='Standard'), dict(tempo=True), dict(template_sha256='0' * 64)]:
            try:
                m.generate(params | changes)
            except ValueError:
                pass
            else:
                raise AssertionError('Unsupported tempo or changed template accepted')
            assert sorted(root.rglob('*')) == before

    template = next(iter(representatives.values()))
    _, _, members = m.read_template(str(template))
    tac = members['.tac']
    offset = m.parse_tac_plaintext(tac)['pre_style_setup']['team_instruction_vector_candidate_offset']
    flags = (int.from_bytes(tac[offset:offset + 12], 'little') & ~mask) | (3 << 46)
    target = root / 'conflicting.fmf'
    m.repack_native_fmf(template, target, plaintext_overrides={'.tac': tac[:offset] + flags.to_bytes(12, 'little') + tac[offset + 12:]})
    summary = m.summarize(str(target))
    assert summary['tempo'] is None and 'tempo' not in summary['supported_edits']
    params = dict(template_path=str(target), template_sha256=summary['template_sha256'], name='Inherited Conflict')
    inherited = m.generate(params)
    assert inherited['tempo_state'] == 'conflicting_stored_selections'
    assert inherited['verification']['all_unrequested_tactic_bytes_preserved']
    before = sorted(root.rglob('*'))
    try:
        m.generate(params | dict(tempo='Higher Tempo'))
    except ValueError as error:
        assert 'contradictory' in str(error)
    else:
        raise AssertionError('Conflicting source accepted for a tempo edit')
    assert sorted(root.rglob('*')) == before

    old_label = m.OPTION_NAMES[47]
    try:
        m.OPTION_NAMES[47] = 'Changed native meaning'
        try:
            m.tempo_selection(tac)
        except ValueError as error:
            assert 'labels changed' in str(error)
        else:
            raise AssertionError('Changed native label silently accepted')
    finally:
        m.OPTION_NAMES[47] = old_label

print(json.dumps({'templates_checked': len(templates), 'versions': sorted(representatives),
                  'tempo_variants_per_template': len(expected), 'archives_generated': generated}))
