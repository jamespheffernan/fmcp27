"""Read complete entity tables from a pinned saved database in wire order."""
from contextlib import contextmanager

from . import saved_database_header, saved_database_tables, snapshot_catalog
from .saved_component_stream import open_component


@contextmanager
def open_at_clubs(filename, expected_snapshot_id, directory):
    with open_archive_at_clubs(filename, expected_snapshot_id, directory) as (reader, source, _, _):
        yield reader, source


@contextmanager
def open_archive_at_clubs(filename, expected_snapshot_id, directory):
    """Keep the database reader and sibling components bound to one checked snapshot."""
    snapshot_catalog.check_filename(filename)
    with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
        current_id = snapshot_catalog.snapshot_id(identity)
        if expected_snapshot_id is not None and expected_snapshot_id != current_id:
            raise ValueError('Snapshot identity changed between pages')
        metadata = snapshot_catalog._metadata(handle, entries)
        root = entries[0].path.split('/')[0]
        databases = [entry for entry in entries if entry.path == f'{root}/game_db.dat']
        if len(databases) != 1:
            raise ValueError('Saved snapshot requires one root game_db.dat')
        with open_component(handle, databases[0]) as reader:
            header = saved_database_header.read_header(reader)
            saved_database_tables.reach_clubs(reader)
            yield reader, dict(source='on-disk save snapshot', filename=filename, snapshot_id=current_id,
                               saved_metadata=metadata, database_format=header), handle, entries


def table(reader, label, decode, *, max_slots=250_000):
    count = reader.u32()
    if reader.u8() != 0 or count > max_slots:
        raise ValueError(f'Unsupported {label} table count or flags')
    for index in range(count):
        yield decode(reader, index, reader.i8())
    saved_database_tables.read_table_footer(reader)


def skip_table(reader, label, decode):
    for _ in table(reader, label, decode):
        pass


def page(rows, matches, offset, limit, *, on_select=None):
    total = matched = 0
    selected = []
    for row in rows:
        total += 1
        if matches(row):
            if offset <= matched < offset + limit:
                if on_select is not None:
                    on_select(row)
                selected.append(row)
            matched += 1
    return total, selected, dict(matched_count=matched, offset=offset, limit=limit,
                                 next_offset=offset+limit if offset+limit < matched else None)


def check_native_id(value):
    if value is not None and (type(value) is not int or not 0 <= value < 1 << 32):
        raise ValueError('Invalid unsigned native ID')


def name_filter(value):
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip() or len(value) > 256:
        raise ValueError('Supply a nonempty name of at most 256 characters')
    return value.strip().casefold()
