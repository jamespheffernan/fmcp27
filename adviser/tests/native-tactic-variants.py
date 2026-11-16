"""Build fresh native variants for the optional independent FM27 loader gate."""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys


def generate_variants(directory: Path) -> dict:
    root = Path(__file__).resolve().parent.parent
    spec = importlib.util.spec_from_file_location('tactic_files', root / 'pi/fm-tactic-files.py')
    writer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(writer)
    writer.OUTPUTS = directory / 'generated'
    variants = []
    source_count = 0
    generated_count = 0
    excluded = []
    for path in sorted(writer.TEMPLATES.glob('*.fmf')):
        try:
            source = writer.summarize(str(path))
        except (ValueError, OSError, KeyError) as error:
            excluded.append({'source_path': str(path), 'error': str(error)})
            continue
        index = source_count
        source_count += 1
        _, _, source_members = writer.read_template(str(path))
        original_payload = source_members['.tac']
        original_path = directory / f'original-{index + 1}.tac'
        original_path.write_bytes(original_payload)
        original_id = writer.parse_tac_plaintext(original_payload)['pre_style_setup']['mentality_id']
        variants.append({'kind': 'original', 'source_path': str(path), 'source_sha256': source['template_sha256'],
                         'source_game_major': source['source_game_major'], 'output_path': str(path), 'output_sha256': source['template_sha256'],
                         'payload_path': str(original_path), 'payload_sha256': hashlib.sha256(original_payload).hexdigest(),
                         'payload_bytes': len(original_payload),
                         'requested': {'name': source['name'], 'mentality_id': original_id,
                                       'team_tackling_flags': writer.tackling_selection(original_payload)[1]}})
        for choice, tackling in enumerate(writer.TACKLING_FLAGS):
            name = f'Native Gate {index + 1} - {choice + 1} Ç'
            mentality_id = (index * 3 + choice) % 7 + 1
            mentality = writer.MENTALITIES[mentality_id]
            result = writer.generate({'action': 'generate', 'template_path': str(path), 'template_sha256': source['template_sha256'],
                                      'name': name, 'mentality': mentality, 'team_tackling': tackling})
            payload = writer.extract_member_plaintexts(result['output_path'])['.tac']
            payload_path = directory / f'variant-{index + 1}-{choice + 1}.tac'
            payload_path.write_bytes(payload)
            generated_count += 1
            variants.append({'kind': 'generated_variant', 'source_path': str(path), 'source_sha256': source['template_sha256'],
                             'source_game_major': source['source_game_major'],
                             'output_path': result['output_path'], 'output_sha256': result['output_sha256'],
                             'payload_path': str(payload_path), 'payload_sha256': hashlib.sha256(payload).hexdigest(),
                             'payload_bytes': len(payload),
                             'requested': {'name': name, 'mentality': mentality, 'mentality_id': mentality_id,
                                           'team_tackling': tackling, 'team_tackling_flags': writer.TACKLING_FLAGS[tackling]},
                             'structural_verification': result['verification']})
    if not variants:
        raise ValueError(f'No supported native templates found in {writer.TEMPLATES}.')
    for row in variants:
        if hashlib.sha256(Path(row['source_path']).read_bytes()).hexdigest() != row['source_sha256']:
            raise ValueError('An original template changed during batch generation.')
    return {'state': 'fresh_native_variants_generated', 'source_count': source_count, 'original_count': source_count,
            'variant_count': generated_count, 'payload_count': len(variants), 'variants': variants, 'excluded_templates': excluded,
            'all_source_hashes_unchanged': True,
            'scope': 'Fresh standalone native .fmf variants in task temporary workspace; no UI, game calls or save writes.'}


if __name__ == '__main__':
    directory = Path(sys.argv[1]).resolve(strict=True)
    result = generate_variants(directory)
    manifest = directory / 'manifest.json'
    manifest.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'manifest': str(manifest), 'sources': result['source_count'], 'variants': result['variant_count'], 'payloads': result['payload_count']}))
