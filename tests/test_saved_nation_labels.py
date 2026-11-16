import ctypes
import ctypes.util
import struct

import pytest

from fm_live_mcp import saved_nation_labels as labels
from fm_live_mcp import snapshot_catalog as catalog


def compress(data):
    lib = ctypes.CDLL(ctypes.util.find_library('zstd'))
    lib.ZSTD_compress.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p,
                                 ctypes.c_size_t, ctypes.c_int]
    lib.ZSTD_compress.restype = ctypes.c_size_t
    output = ctypes.create_string_buffer(len(data) + 1024)
    size = lib.ZSTD_compress(output, len(output), data, len(data), 1)
    return output.raw[:size]


def text(value):
    raw = value.encode()
    return struct.pack('<I', len(raw)) + raw


def row(key=765, *, flags=(255, 255), extra=False, name='England'):
    value = (struct.pack('<I', key) + text(name) + bytes([flags[0]]) + text('England') +
             bytes([flags[1]]) + text('ENG') + text('English') + bytes([int(extra)]))
    if extra:
        value += text('auxiliary') + b'\x34\x12\xff'
    return value


def payload(*rows):
    return labels.COMPONENT_HEADER + struct.pack('<I', len(rows)) + b''.join(rows)


def archive(tmp_path, data=None, *, component='8_9', declared_size=None):
    data = payload(row()) if data is None else data
    packed = compress(data)
    table = (text('lang_db') + struct.pack('<I', 1) + text(component) + text('.dat') +
             struct.pack('<5Q', 0, len(packed), len(data) if declared_size is None else declared_size, 0, 0) +
             struct.pack('<I', 0))
    header = catalog.MAGIC + struct.pack('<Q', len(packed) + 17) + bytes(9)
    path = tmp_path / 'lang_db.dat'
    path.write_bytes(labels.OUTER_HEADER + header + packed + catalog.MAGIC + compress(table))
    return path


def select(monkeypatch, path):
    monkeypatch.setattr(labels, 'DEFAULT_RESOURCE', path)


def test_available_labels_are_native_keys_with_external_provenance(tmp_path, monkeypatch):
    path = archive(tmp_path, payload(row(765), row(987654, flags=(0, 1), extra=True, name='')))
    select(monkeypatch, path)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'available' and result['reason'] is None
    assert result['labels'][765] == {
        'name': 'England', 'short_name': 'England', 'abbreviation': 'ENG',
        'name_flag': 255, 'short_name_flag': 255,
    }
    assert result['labels'][987654]['name'] == ''
    assert result['labels'][987654]['short_name_flag'] == 1
    metadata = result['metadata']
    assert metadata['source'] == 'installed_database_baseline'
    assert metadata['resource_component'] == 'lang_db/8_9.dat'
    assert metadata['source_major'] == 3725 and metadata['database_version'] == '2600'
    assert metadata['row_count'] == 2 and metadata['saved_name_equivalence'] is False
    assert metadata['career_display_equivalence'] == 'unverified'
    assert len(metadata['component_sha256']) == 64
    assert str(tmp_path) not in str(metadata)


def test_missing_resource_is_optional_and_does_not_expose_path(tmp_path, monkeypatch):
    select(monkeypatch, tmp_path / 'missing')
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unavailable' and result['labels'] == {}
    assert 'No such file' in result['reason'] and str(tmp_path) not in result['reason']


@pytest.mark.parametrize('component', ['9_8', '8_25', 'nested/8_9'])
def test_wrong_component_is_explicit(tmp_path, monkeypatch, component):
    select(monkeypatch, archive(tmp_path, component=component))
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}
    assert result['reason']


@pytest.mark.parametrize('field,offset', [('source', 8), ('archive', 12), ('footer', -1)])
def test_resource_versions_and_footer_are_checked(tmp_path, monkeypatch, field, offset):
    path = archive(tmp_path)
    data = bytearray(path.read_bytes())
    if field == 'footer':
        table_at = 30 + struct.unpack_from('<Q', data, 21)[0]
        offset = table_at - 9
    data[offset] ^= 1
    path.write_bytes(data)
    select(monkeypatch, path)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}


def test_all_component_truncations_reject(tmp_path, monkeypatch):
    original = payload(row(extra=True))
    for end in range(len(original)):
        select(monkeypatch, archive(tmp_path, original[:end]))
        result = labels.load_english_nation_labels()
        assert result['status'] == 'unsupported' and result['labels'] == {}, end


@pytest.mark.parametrize('data', [
    payload(row(0)), payload(row(), row()), payload(row()) + b'X',
    labels.COMPONENT_HEADER + struct.pack('<I', 10001),
    payload(row()).replace(b'England', b'\xffngland', 1),
    labels.COMPONENT_HEADER + struct.pack('<II', 1, 765) + struct.pack('<I', 8193),
    b'\x00' + payload(row())[1:],
])
def test_malformed_rows_return_explicit_failure(tmp_path, monkeypatch, data):
    select(monkeypatch, archive(tmp_path, data))
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}
    assert result['reason']


@pytest.mark.parametrize('declared_size', [11, 1024 * 1024 + 1, 12, 200])
def test_component_length_and_budget(tmp_path, monkeypatch, declared_size):
    select(monkeypatch, archive(tmp_path, declared_size=declared_size))
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}


def test_replaced_named_resource_is_rejected(tmp_path, monkeypatch):
    path = archive(tmp_path)
    select(monkeypatch, path)
    original = catalog._decompress
    replaced = False

    def decompress(data, capacity):
        nonlocal replaced
        result = original(data, capacity)
        if not replaced:
            replacement = tmp_path / 'replacement'
            replacement.write_bytes(path.read_bytes())
            replacement.replace(path)
            replaced = True
        return result

    monkeypatch.setattr(catalog, '_decompress', decompress)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported'
    assert 'changed during request' in result['reason'] and result['labels'] == {}


def test_same_descriptor_component_mutation_is_rejected(tmp_path, monkeypatch):
    path = archive(tmp_path)
    select(monkeypatch, path)
    original = labels._parse_labels

    def parse(data):
        result = original(data)
        with path.open('r+b') as handle:
            handle.seek(42)
            value = handle.read(1)
            handle.seek(42)
            handle.write(bytes([value[0] ^ 1]))
        return result

    monkeypatch.setattr(labels, '_parse_labels', parse)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}
    assert 'changed during request' in result['reason']


def test_symlink_resource_is_unavailable(tmp_path, monkeypatch):
    path = archive(tmp_path)
    link = tmp_path / 'link.dat'
    link.symlink_to(path)
    select(monkeypatch, link)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unavailable' and result['labels'] == {}


def test_decompressor_unavailable_is_explicit(tmp_path, monkeypatch):
    select(monkeypatch, archive(tmp_path))
    monkeypatch.setattr(catalog, '_decompress', lambda *_: (_ for _ in ()).throw(
        ValueError('Zstandard library unavailable; install libzstd')))
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported'
    assert 'Zstandard library unavailable' in result['reason'] and result['labels'] == {}


def test_reads_always_have_explicit_bounded_lengths(tmp_path, monkeypatch):
    select(monkeypatch, archive(tmp_path))
    original = labels.os.fdopen
    sizes = []

    class BoundedHandle:
        def __init__(self, handle):
            self.handle = handle

        def __enter__(self):
            self.handle.__enter__()
            return self

        def __exit__(self, *args):
            return self.handle.__exit__(*args)

        def __getattr__(self, name):
            return getattr(self.handle, name)

        def read(self, size):
            assert 0 <= size <= catalog.MAX_TABLE_PACKED
            sizes.append(size)
            return self.handle.read(size)

    monkeypatch.setattr(labels.os, 'fdopen', lambda *args: BoundedHandle(original(*args)))
    assert labels.load_english_nation_labels()['status'] == 'available'
    assert sizes and 38 in sizes


def test_oversized_directory_is_rejected_before_reading_it(tmp_path, monkeypatch):
    path = archive(tmp_path)
    with path.open('ab') as handle:
        handle.write(bytes(catalog.MAX_TABLE_PACKED + 1))
    select(monkeypatch, path)
    result = labels.load_english_nation_labels()
    assert result['status'] == 'unsupported' and result['labels'] == {}
    assert 'directory outside bounded range' in result['reason']
