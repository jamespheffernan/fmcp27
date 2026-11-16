from pathlib import Path

import pytest

from fm_live_mcp.match_stills_faces import face_references
from fm_live_mcp.match_stills import build_packet, prepare
from test_match_stills_replay import source, replay_for
from test_match_stills import capture


def pack(tmp_path, records):
    (tmp_path/'config.xml').write_text('<record><list>' + records + '</list></record>')
    (tmp_path/'portrait.png').write_bytes(b'\x89PNG\r\n\x1a\nportrait')
    return tmp_path


def mapping(pid=28124573, stem='portrait'):
    return f'<record from="{stem}" to="graphics/pictures/person/{pid}/portrait"/>'


def test_exact_mapping_and_non_scorer_identity(source, tmp_path):
    replay = replay_for(source)
    replay['players'].append({'canonical_person_id': 12, 'person_name': 'Other player',
                              'native_xy': [1, 2], 'side_index': 1})
    refs = face_references(replay, pack(tmp_path, mapping(12)), [12])
    assert refs[0]['person_name'] == 'Other player'
    assert refs[0]['portrait_binding']['to'] == 'graphics/pictures/person/12/portrait'
    assert prepare(source[0], 1454, refs, replay=replay)['references'] == refs
    with pytest.raises(ValueError, match='another player'):
        prepare(source[0], 1454, refs)


@pytest.mark.parametrize('records,ids,error', [
    (mapping(), [99], 'absent'),
    (mapping(), [28124573, 28124573], 'distinct'),
    (mapping(99), [28124573], 'No configured'),
    (mapping()+mapping(), [28124573], 'Ambiguous'),
    (mapping(stem='../escape'), [28124573], 'inside'),
    (mapping(stem='missing'), [28124573], 'missing'),
])
def test_rejects_unproven_portraits(source, tmp_path, records, ids, error):
    with pytest.raises(ValueError, match=error):
        face_references(replay_for(source), pack(tmp_path, records), ids)


def test_rejects_replaced_portrait_bytes(source, tmp_path):
    import json
    replay = replay_for(source)
    refs = face_references(replay, pack(tmp_path, mapping()), [28124573])
    (tmp_path/'portrait.png').write_bytes(b'\x89PNG\r\n\x1a\nchanged')
    for name, value in [('capture', source[0]), ('replay', replay), ('refs', refs)]:
        (tmp_path/f'{name}.json').write_text(json.dumps(value))
    with pytest.raises(ValueError, match='intact PERSON'):
        build_packet(tmp_path/'capture.json', tmp_path/'refs.json', 1454,
                     tmp_path/'output', replay_path=tmp_path/'replay.json')
    assert not (tmp_path/'output').exists()
