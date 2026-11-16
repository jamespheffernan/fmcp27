"""Whole-source sequential metadata plus adversarial late-name conjunctions."""
import mmap
import struct

import pytest

from fm_live_mcp import saved_name_vectors as names
from test_saved_club_search import database
from test_saved_world_search import framed


def metadata(count, *, damaged=None):
    result = struct.pack('<I', count)
    for index in range(count):
        stored = index if damaged != index else index + 1
        result += struct.pack('<Hi4sH', 65535, stored, b'raw!', 0)
    return result


def overlay(values, *, indices=None):
    result = struct.pack('<I', len(values))
    for ordinal, value in enumerate(values):
        raw = value if isinstance(value, bytes) else value.encode('utf-8')
        index = ordinal if indices is None else indices[ordinal]
        result += struct.pack('<II', index, len(raw)) + raw
    return result


def fixture(tables=(('Oldřich', '', '東京'), ('Nejedlý', 'Smith'), ('Rua',)),
            *, flags=1, person_count=3, middle=b'opaque supplement bytes', metadata_override=None,
            late_override=None):
    #Empty verified entity tables through NATIONAL_TEAM_CONTAINER. No mocked
    #header, ordinal walker or predecessor route is used.
    prefix = database([]) + framed([]) * 8
    early = prefix + (b''.join(metadata(len(t)) for t in tables)
                      if metadata_override is None else metadata_override)
    late = b''.join(overlay(t) for t in tables) if late_override is None else late_override
    person = struct.pack('<IB', person_count, flags) + b'\xff' * person_count
    return early + middle + late + person


def mapped(tmp_path, raw, *, access=mmap.ACCESS_READ):
    path = tmp_path / 'source.bin'
    path.write_bytes(raw)
    with path.open('r+b') as source:
        with mmap.mmap(source.fileno(), 0, access=access) as view:
            yield view


def test_dynamic_counts_unicode_empty_and_nonowning_mmap(tmp_path):
    raw = fixture()
    for data in mapped(tmp_path, raw):
        layout = names.locate(data)
        assert layout.name_counts == {'first': 3, 'second': 2, 'common': 1}
        assert layout.person_count == 3 and layout.person_flags == 1
        assert layout.person_records_offset == layout.person_offset + 5
        assert struct.unpack_from('<I', data, layout.person_offset)[0] == 3
        assert layout.lookup('first', 0) == 'Oldřich'
        assert layout.lookup('first', 1) == ''
        assert layout.lookup('first', 2) == '東京'
        assert layout.lookup('second', 0) == 'Nejedlý'
        assert layout.lookup('common', -1) is None
        assert 'structural candidate' in layout.provenance['person_header']
        assert 'sequential' in layout.provenance['early_names']
        layout.name_counts['first'] = 999
        assert layout.name_counts['first'] == 3
    #The layout held no exported memoryview preventing the mmap context closing.
    with pytest.raises(ValueError):
        layout.lookup('first', 0)


@pytest.mark.parametrize('tables', [((), (), ()), (('A',), (), ('B',)),
                                   (('A', 'B'), ('C', 'D', 'E', 'F'), ())])
@pytest.mark.parametrize('flags', [0, 1])
def test_small_and_zero_counts_are_discovered_dynamically(tables, flags):
    raw = fixture(tables, flags=flags, middle=b'nonzero-boundary')
    result = names.locate(raw)
    assert result.name_counts == dict(zip(names.NAMESPACES, map(len, tables)))


@pytest.mark.parametrize('position', [0, 1, 2])
def test_every_early_vector_checks_all_original_ordinals(position):
    counts = (3, 2, 1)
    early = b''.join(metadata(n, damaged=n-1 if slot == position else None)
                     for slot, n in enumerate(counts))
    with pytest.raises(ValueError, match='ordinal|repair|disorder'):
        names.locate(fixture(metadata_override=early))


@pytest.mark.parametrize('position', [0, 1, 2])
def test_each_late_vector_requires_full_count_and_order(position):
    tables = (('A', 'B', 'C'), ('D', 'E'), ('F',))
    late = b''.join(overlay(t, indices=[0] * len(t) if slot == position else None)
                    for slot, t in enumerate(tables))
    if position == 2:
        late = overlay(tables[0]) + overlay(tables[1]) + overlay(tables[2], indices=[7])
    with pytest.raises(ValueError, match='No complete'):
        names.locate(fixture(tables, late_override=late))


def test_ambiguity_is_rejected_and_late_decoy_is_checked_completely():
    tables = (('A', 'B', 'C'), ('D', 'E'), ('F',))
    conjunction = b''.join(overlay(t) for t in tables) + struct.pack('<IB', 1, 1) + b'\xff'
    with pytest.raises(ValueError, match='Ambiguous'):
        names.locate(fixture(tables, middle=conjunction + b'gap'))
    unsupported = b''.join(overlay(t) for t in tables) + struct.pack('<IB', 1, 2) + b'\xff'
    with pytest.raises(ValueError, match='Ambiguous'):
        names.locate(fixture(tables, middle=unsupported + b'gap'))
    #The decoy has the right C8 count/index0 but a late ordinal is wrong.
    decoy = overlay(tables[0], indices=[0, 1, 9]) + b'gap'
    assert names.locate(fixture(tables, middle=decoy)).lookup('first', 2) == 'C'


def test_opaque_non_utf8_is_not_used_to_prune_geometry():
    layout = names.locate(fixture(((b'\xff',), ('B',), ('C',))))
    assert layout.lookup_raw('first', 0) == b'\xff'
    with pytest.raises(ValueError, match='UTF-8'):
        layout.lookup('first', 0)


def test_string_extent_and_person_header_controls():
    for raw in (fixture()[:-5], fixture(flags=2), fixture(person_count=names.MAX_PERSON_ROWS + 1)):
        with pytest.raises(ValueError):
            names.locate(raw)
    huge = struct.pack('<III', 3, 0, 0xffffffff)
    with pytest.raises(ValueError, match='No complete'):
        names.locate(fixture(late_override=huge))


def test_lookup_validation_and_response_budget():
    layout = names.locate(fixture())
    for namespace, index in [('nation', 0), ('first', True), ('first', -2), ('first', 3)]:
        with pytest.raises(ValueError):
            layout.lookup(namespace, index)
    large = 'A' * (names.MAX_TEXT_BYTES + 1)
    layout = names.locate(fixture(((large,), ('B',), ('C',))))
    with pytest.raises(ValueError, match='budget'):
        layout.lookup('first', 0)


def test_wrong_source_header_and_mutable_buffers_are_rejected(tmp_path):
    for raw in (b'wrong header' + fixture()[12:], fixture()[:7] + b'\0' + fixture()[8:]):
        with pytest.raises(ValueError):
            names.locate(raw)
    with pytest.raises(ValueError, match='read-only'):
        names.locate(bytearray(fixture()))
    with pytest.raises(ValueError):
        names.locate(memoryview(fixture()).cast('c'))
    for view in mapped(tmp_path, fixture(), access=mmap.ACCESS_WRITE):
        with pytest.raises(ValueError, match='read-only'):
            names.locate(view)


def test_candidate_and_work_exhaustion_abort_instead_of_pruning(monkeypatch):
    monkeypatch.setattr(names, 'MAX_CANDIDATES', 0)
    with pytest.raises(ValueError, match='candidate search budget'):
        names.locate(fixture())
    monkeypatch.setattr(names, 'MAX_CANDIDATES', 4096)
    monkeypatch.setattr(names, 'MAX_ROW_WORK', 1)
    with pytest.raises(ValueError, match='work budget'):
        names.locate(fixture())


def test_every_late_truncation_fails_without_full_conjunction():
    raw = fixture()
    layout = names.locate(raw)
    for end in range(layout.overlay_offset, layout.person_offset + 5):
        with pytest.raises(ValueError):
            names.locate(raw[:end])


def test_pinned_real_archive_mmap_when_explicitly_selected():
    """Opt-in corpus replay; spool only this component on approved project storage."""
    import hashlib
    import os
    from pathlib import Path
    import tempfile
    import time
    from fm_live_mcp import snapshot_catalog
    from fm_live_mcp.saved_component_stream import open_component

    selected = os.environ.get('FM_SAVED_NAME_REAL_SNAPSHOT')
    if not selected:
        pytest.skip('No real archive explicitly selected')
    path = Path(selected)

    def packed_digest(handle, entry):
        handle.seek(26 + entry.start)
        remaining = entry.compressed_size
        digest = hashlib.sha256()
        while remaining:
            raw = handle.read(min(128 << 10, remaining))
            assert raw
            digest.update(raw)
            remaining -= len(raw)
        return digest.hexdigest()

    with snapshot_catalog.checked_snapshot(path.name, directory=path.parent) as (handle, entries, identity):
        entry, = [e for e in entries if e.path.count('/') == 1 and e.path.endswith('/game_db.dat')]
        before = packed_digest(handle, entry)
        #Raw data never goes to the main-drive pytest tmp_path or games directory.
        with tempfile.TemporaryFile(dir=Path(__file__).resolve().parents[1]) as spool:
            spool_started = time.monotonic()
            with open_component(handle, entry) as reader:
                while reader.offset < entry.uncompressed_size:
                    spool.write(reader.take(min(128 << 10, entry.uncompressed_size - reader.offset)))
                assert reader.source.read(1) == b'' and reader.source.finished
            spool.flush()
            spool_seconds = time.monotonic() - spool_started
            with mmap.mmap(spool.fileno(), 0, access=mmap.ACCESS_READ) as data:
                early_seconds = []
                original_early = names._early_names
                def timed_early(source):
                    started = time.monotonic()
                    result = original_early(source)
                    early_seconds.append(time.monotonic() - started)
                    return result
                names._early_names = timed_early
                started = time.monotonic()
                try:
                    layout = names.locate(data)
                finally:
                    names._early_names = original_early
                locate_seconds = time.monotonic() - started
                assert layout.person_count > 0
                assert all(layout.lookup_raw(namespace, 0) is not None
                           for namespace, count in layout.name_counts.items() if count)
                assert all(layout.lookup_raw(namespace, count - 1) is not None
                           for namespace, count in layout.name_counts.items() if count)
                print({'snapshot_id': snapshot_catalog.snapshot_id(identity),
                       'spool_seconds': spool_seconds, 'locate_seconds': locate_seconds,
                       'early_seconds': early_seconds[0], 'late_seconds': locate_seconds - early_seconds[0],
                       'raw_bytes': len(data), 'early_offset': layout.early_offset,
                       'overlay_offset': layout.overlay_offset, 'name_counts': layout.name_counts,
                       'person_offset': layout.person_offset, 'person_count': layout.person_count,
                       'provenance': layout.provenance})
        assert packed_digest(handle, entry) == before
