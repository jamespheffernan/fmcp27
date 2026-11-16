"""Resolve installed FM portraits by exact replay PERSON IDs and config mappings."""
from __future__ import annotations

import hashlib
from pathlib import Path
import xml.etree.ElementTree as ET


def find_facepacks(graphics: Path) -> list[Path]:
    """Folders under the user's graphics directory whose config.xml maps PERSON portraits."""
    found = []
    for config in sorted(graphics.rglob('config.xml')) if graphics.is_dir() else []:
        try:
            if b'graphics/pictures/person/' in config.read_bytes():
                found.append(config.parent)
        except OSError:
            continue
    return found


def face_references(replay: dict, facepack: Path, person_ids: list[int], *, skip_missing: bool = False) -> list[dict]:
    if replay.get('state') != 'verified_historical_replay_frame':
        raise ValueError('Verified replay identities are required')
    if not person_ids or len(set(person_ids)) != len(person_ids):
        raise ValueError('Supply distinct visible player IDs')
    people = {}
    for person_id in person_ids:
        matches = [p for p in replay['players'] if p['canonical_person_id'] == person_id]
        if len(matches) != 1:
            raise ValueError(f'Player {person_id} is absent or ambiguous in replay')
        people[person_id] = matches[0]
    root = facepack.resolve()
    config = root/'config.xml'
    with config.open('rb') as source:
        config_hash = hashlib.file_digest(source, 'sha256').hexdigest()
    targets = {f'graphics/pictures/person/{pid}/portrait': pid for pid in person_ids}
    mappings = {}
    for _, element in ET.iterparse(config, events=('end',)):
        target = element.get('to')
        if element.tag == 'record' and target in targets:
            pid = targets[target]
            if pid in mappings:
                raise ValueError(f'Ambiguous portrait mapping for {pid}')
            mappings[pid] = (element.get('from', ''), target)
        element.clear()
    refs = []
    for pid in person_ids:
        if pid not in mappings:
            if skip_missing:
                continue
            raise ValueError(f'No configured portrait for {pid}')
        stem, target = mappings[pid]
        if not stem or Path(stem).name != stem or '\\' in stem or stem in ('.', '..'):
            raise ValueError('Portrait mapping must name an image inside the facepack')
        path = (root/f'{stem}.png').resolve()
        if path.parent != root or not path.is_file():
            if skip_missing:
                continue
            raise ValueError(f'Configured portrait missing or outside facepack: {pid}')
        data = path.read_bytes()
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError(f'Configured portrait is not PNG: {pid}')
        name = people[pid]['person_name']
        refs.append({'role': 'identity', 'person_native_id': pid, 'person_name': name,
                     'path': str(path), 'source_url': f'fm-graphics:portrait/{pid}',
                     'credit': f'Installed facepack · {name} · PERSON {pid}',
                     'instruction': f'{name}, PERSON {pid}: likeness only. Preserve match kit and pose; ignore portrait clothing. Photo date and 2030 appearance are unverified.',
                     'portrait_binding': {'state': 'exact_config_PERSON_mapping',
                         'config_path': str(config), 'config_sha256': config_hash,
                         'from': stem, 'to': target, 'asset_sha256': hashlib.sha256(data).hexdigest()}})
    return refs
