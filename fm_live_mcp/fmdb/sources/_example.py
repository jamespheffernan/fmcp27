"""Minimal collection source: the shape every `sources/<name>.py` module follows.

Not discovered by the snapshot (the `_` prefix); `discover(engine, only=['_example'])` loads it
and the offline tests use it. A real module reads the live save in `rows()`; rows are tuples in
column order, and `idx` is added (row number) when the module declares no `idx` column.
"""
from __future__ import annotations

from . import Column, SourceTable


def tables(engine) -> list[SourceTable]:
    def rows():
        yield (0, 'none', None)
        yield (1, 'some', 3)

    return [SourceTable(
        name='example_collection',
        description='Example collection table (static rows; documents the source module shape).',
        columns=[Column('code', 'INTEGER', 'example enum value', enum={0: 'none', 1: 'some'}),
                 Column('label', 'TEXT', 'example text'),
                 Column('person_idx', 'INTEGER', 'example reference to person.idx', references='person')],
        rows=rows,
        cost_note='static', mode='eager', invalidation='immutable', identity=('code',),
        source_note='static example rows',
        manager={'scope': 'public'},
        views={'example_collection_view': 'SELECT e.idx, e.label FROM example_collection e'},
    )]
