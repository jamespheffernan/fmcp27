"""Portable original resource fixture plus bounded archive/adversarial controls."""
import hashlib
import struct
from pathlib import Path

import pytest
from fm_live_mcp import saved_injury_labels as labels
from fm_live_mcp import snapshot_catalog as catalog
from test_saved_nation_labels import compress, text

RAW = Path(__file__).with_name('saved_injury_labels_8_6.dat').read_bytes()


def row(key=100, *, name='bruised ankle', sentence='a bruised ankle', flags=(255,255), extra=False):
    raw = struct.pack('<I', key) + text(name) + bytes([flags[0]]) + text(sentence) + bytes([flags[1], int(extra)])
    return raw + (text('auxiliary 東京') + b'\x34\x12\xff' if extra else b'')


def payload(*rows):
    return labels.COMPONENT_HEADER + struct.pack('<I', len(rows)) + b''.join(rows)


def archive(tmp_path, data=RAW, *, component='8_6', declared_size=None):
    packed = compress(data)
    table = (text('lang_db') + struct.pack('<I', 1) + text(component) + text('.dat') +
             struct.pack('<5Q', 0, len(packed), len(data) if declared_size is None else declared_size, 0, 0) + struct.pack('<I', 0))
    header = catalog.MAGIC + struct.pack('<Q', len(packed) + 17) + bytes(9)
    path = tmp_path / 'lang_db.dat'
    path.write_bytes(labels.OUTER_HEADER + header + packed + catalog.MAGIC + compress(table))
    return path


def test_all_original136_ids_and_primary_id_control():
    assert hashlib.sha256(RAW).hexdigest() == labels.VERIFIED_COMPONENT_SHA256
    result = labels._parse_labels(RAW)
    assert len(result) == 136
    assert result[100] == {'name':'bruised ankle','sentence_name':'a bruised ankle','name_flag':255,'sentence_name_flag':255}
    assert result[84]['name'] == 'hernia'
    assert result[111]['name'] == 'tight thigh' and result[108]['sentence_name'] == 'a tight calf'
    assert result[16]['sentence_name'] == 'stress fracture of the foot'


def test_available_resource_has_separate_exact_build_and_locale_provenance(tmp_path, monkeypatch):
    monkeypatch.setattr(labels, 'DEFAULT_RESOURCE', archive(tmp_path))
    out = labels.load_english_injury_labels()
    assert out['status'] == 'available' and out['reason'] is None and len(out['labels']) == 136
    meta = out['metadata']
    assert meta['source'] == 'installed_database_baseline'
    assert (meta['language_id'], meta['language'], meta['database_version'], meta['source_major']) == (8,'English','2600',3725)
    assert meta['saved_name_equivalence'] is False and meta['career_display_equivalence'] == 'unverified'
    assert meta['component_sha256'] == meta['verified_component_sha256'] == labels.VERIFIED_COMPONENT_SHA256
    assert meta['native_codec_plugin_sha256'] == '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
    assert meta['resource_component'] == 'lang_db/8_6.dat' and meta['header_hex'] == RAW[:8].hex()
    assert str(tmp_path) not in str(out)


def test_unverified_resource_revision_is_unsupported_not_a_new_mapping(tmp_path, monkeypatch):
    raw = RAW.replace(b'bruised ankle', b'changed ankle')
    monkeypatch.setattr(labels, 'DEFAULT_RESOURCE', archive(tmp_path, raw))
    out = labels.load_english_injury_labels()
    assert out['status'] == 'unsupported' and out['labels'] == {}
    assert 'verified build baseline' in out['reason']


def test_missing_or_symlink_resource_is_optional(tmp_path, monkeypatch):
    for path in [tmp_path/'missing', tmp_path/'link']:
        if path.name == 'link': path.symlink_to(archive(tmp_path))
        monkeypatch.setattr(labels, 'DEFAULT_RESOURCE', path)
        out = labels.load_english_injury_labels()
        assert out['status'] == 'unavailable' and out['labels'] == {}
        assert str(tmp_path) not in out['reason']


@pytest.mark.parametrize('component', ['8_9','9_6','8_25'])
def test_unproved_language_or_table_does_not_substitute(tmp_path, monkeypatch, component):
    monkeypatch.setattr(labels, 'DEFAULT_RESOURCE', archive(tmp_path, component=component))
    out = labels.load_english_injury_labels()
    assert out['status'] == 'unsupported' and out['labels'] == {}


@pytest.mark.parametrize('field', ['source','archive','footer'])
def test_outer_version_and_footer_reject(tmp_path, monkeypatch, field):
    path = archive(tmp_path)
    raw = bytearray(path.read_bytes())
    at = 8 if field == 'source' else 12 if field == 'archive' else 30+struct.unpack_from('<Q',raw,21)[0]-9
    raw[at] ^= 1; path.write_bytes(raw)
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',path)
    assert labels.load_english_injury_labels()['status'] == 'unsupported'


def test_all6946_original_truncated_prefixes_reject():
    for end in range(len(RAW)):
        with pytest.raises(ValueError): labels._parse_labels(RAW[:end])


def test_pure_codec_preserves_empty_unicode_raw_flags_and_auxiliary_extent():
    out = labels._parse_labels(payload(row(987654, name='', sentence='Épreuve 東京 ', flags=(0,1), extra=True)))
    assert out[987654] == {'name':'','sentence_name':'Épreuve 東京 ','name_flag':0,'sentence_name_flag':1}


@pytest.mark.parametrize('raw', [payload(row(0)),payload(row(),row()),payload(row())+b'x',
    labels.COMPONENT_HEADER+struct.pack('<I',10001),payload(row()).replace(b'bruised',b'\xffruised',1),
    labels.COMPONENT_HEADER+struct.pack('<II',1,100)+struct.pack('<I',8193)])
def test_malformed_pure_rows_reject(raw):
    with pytest.raises((ValueError,UnicodeError)): labels._parse_labels(raw)


def test_replaced_resource_cannot_publish_labels(tmp_path, monkeypatch):
    path = archive(tmp_path); monkeypatch.setattr(labels,'DEFAULT_RESOURCE',path)
    parse = labels._parse_labels
    def replaced(data):
        out = parse(data)
        next_path = tmp_path/'replacement'; next_path.write_bytes(path.read_bytes()); next_path.replace(path)
        return out
    monkeypatch.setattr(labels,'_parse_labels',replaced)
    out = labels.load_english_injury_labels()
    assert out['status'] == 'unsupported' and out['labels'] == {} and 'changed during' in out['reason']


def test_same_descriptor_mutation_is_detected(tmp_path, monkeypatch):
    path = archive(tmp_path); monkeypatch.setattr(labels,'DEFAULT_RESOURCE',path)
    parse = labels._parse_labels
    def changed(data):
        out = parse(data)
        with path.open('r+b') as handle:
            handle.seek(42); value=handle.read(1); handle.seek(42); handle.write(bytes([value[0]^1]))
        return out
    monkeypatch.setattr(labels,'_parse_labels',changed)
    out = labels.load_english_injury_labels()
    assert out['status'] == 'unsupported' and out['labels'] == {} and 'changed during' in out['reason']


def test_decompressor_failure_is_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(labels,'DEFAULT_RESOURCE',archive(tmp_path))
    monkeypatch.setattr(catalog,'_decompress',lambda *_: (_ for _ in ()).throw(ValueError('Zstandard unavailable')))
    out = labels.load_english_injury_labels()
    assert out['status'] == 'unsupported' and out['labels'] == {} and 'Zstandard unavailable' in out['reason']
