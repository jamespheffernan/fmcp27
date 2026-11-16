"""Exact same-source identity joins for retained starting-history references.

Only compact numeric canonical extents and reciprocal membership counts survive
preparation. No database bytes, full TEAM/CLUB dictionaries or name strings are
cached. Names are reparsed from selected already-validated record extents.
"""
from array import array
from collections import OrderedDict
from functools import partial
import sys

from . import (saved_club_records, saved_competition_records, saved_component_stream,
               saved_fixture_name_lookup as fixture, saved_team_records)

MAX_CACHE_BYTES = 16 * 1024**2
MAX_CACHES = 4
MAX_CANDIDATES = 20
_CACHE = OrderedDict()


class Context:
    def __init__(self):
        self.clubs = array('I')  # start,end,subtype; original index is implicit
        self.teams = array('I')  # primary,secondary,start,end,subtype
        self.competitions = array('I')
        self.claim_owner = array('i')
        self.claim_count = array('I')
        self.counts = None

    @property
    def memory_bytes(self):
        return sum(sys.getsizeof(value) for value in (
            self.clubs, self.teams, self.competitions, self.claim_owner, self.claim_count))

    def _check_budget(self):
        if self.memory_bytes > MAX_CACHE_BYTES:
            raise ValueError('Starting-history name context exceeds numeric extent budget')

    def club(self, row, kind, start, end):
        self.clubs.extend((start, end, kind & 255))
        for index in row.get('team_indices', ()):
            if index is None or not 0 <= index < fixture.MAX_TABLE_ROWS:
                continue
            growth = index + 1 - len(self.claim_count)
            if growth > 0:
                self.claim_count.extend(array('I', [0]) * growth)
                self.claim_owner.extend(array('i', [-1]) * growth)
            self.claim_count[index] += 1
            self.claim_owner[index] = row['database_index']
        self._check_budget()

    def team(self, row, kind, start, end):
        self.teams.extend((row['native_id'], row['secondary_id'], start, end, kind & 255))
        self._check_budget()

    def competition(self, row, kind, start, end):
        self.competitions.extend((row['native_id'], row['secondary_id'], start, end, kind & 255))
        self._check_budget()


def prepare(data):
    context = Context()
    header, competitions, stages, _ = fixture._canonical_context(
        data, on_club=context.club, on_competition=context.competition, on_team=context.team)
    if (header['source_major'], header['source_minor']) != (3754, 9):
        raise ValueError('Unsupported starting-history name context source version')
    context.counts = (len(competitions), len(stages))
    return context


def publish(digest, context):
    if context.memory_bytes > MAX_CACHE_BYTES:
        raise ValueError('Starting-history name context exceeds cache budget')
    _CACHE[digest] = context
    _CACHE.move_to_end(digest)
    while len(_CACHE) > MAX_CACHES or sum(c.memory_bytes for c in _CACHE.values()) > MAX_CACHE_BYTES:
        _CACHE.popitem(last=False)


def _record(data, ordinal, extent, decoder):
    start, end, kind = extent
    # A memoryview slice avoids copying large source extents. Reader receives no
    # bytes outside this complete canonical record, even if a decoder regresses.
    view = memoryview(data)[start:end]
    class BoundedSource(fixture._Source):
        def read(self, size):
            return bytes(super().read(size))

    reader = saved_component_stream.Reader(BoundedSource(view), len(view))
    row = decoder(reader, ordinal, kind if kind < 128 else kind - 256)
    if reader.offset != end - start:
        raise ValueError('Starting-history name record extent mismatch')
    return row


def _matches(values, requested):
    matches = {pair: {'count': 0, 'indices': []} for pair in requested}
    for at in range(0, len(values), 5):
        pair = (values[at], values[at + 1])
        if pair in matches:
            match = matches[pair]
            match['count'] += 1
            if len(match['indices']) < MAX_CANDIDATES:
                match['indices'].append(at // 5)
    return matches


def enrich(data, context, rows):
    for key, values, decoder in (
        ('team_reference', context.teams, partial(saved_team_records.read_team, include_roster=False)),
        ('competition_reference', context.competitions, saved_competition_records.read_competition),
    ):
        requested = {(row[key]['native_id_word'], row[key]['secondary_word']) for row in rows
                     if row[key]['state'] != 'stored_all_ones_identity_pair'}
        matches = _matches(values, requested)
        resolved = {}
        for pair, match in matches.items():
            indices, count = match['indices'], match['count']
            info = {'state': 'identity_not_found' if count == 0 else
                    'ambiguous_identity_pair' if count > 1 else 'matched_identity_pair',
                    'candidate_count': count, 'candidate_database_indices': indices,
                    'candidates_omitted': count - len(indices), 'name': None, 'short_name': None,
                    'name_source': None}
            if count == 1:
                index = indices[0]
                record = _record(data, index, values[index*5+2:index*5+5], decoder)
                info['database_index'] = index
                if key == 'competition_reference':
                    info.update(name=record['name'], short_name=record['short_name'],
                                stored_name_state=record['stored_name_state'],
                                name_source='same_snapshot_stored_COMP_record')
                else:
                    claims = context.claim_count[index] if index < len(context.claim_count) else 0
                    info.update(team_type_code=record['team_type_code'], owner_kind=record['owner_kind'],
                                team_owner_index=record['owner_index'], club_vector_claim_count=claims)
                    if record['owner_kind'] != 'club':
                        info['state'] = 'non_club_team_owner'
                    elif claims != 1:
                        info['state'] = 'missing_reciprocal_club' if claims == 0 else 'ambiguous_club_membership'
                    else:
                        club_index = context.claim_owner[index]
                        if record['owner_index'] not in (None, club_index):
                            info['state'] = 'conflicting_club_owner'
                        else:
                            club = _record(data, club_index, context.clubs[club_index*3:club_index*3+3],
                                           saved_club_records.read_club)
                            info.update(state='resolved_owning_club', name=club['name'], short_name=club['short_name'],
                                        name_source='same_snapshot_reciprocal_CLUB_record',
                                        owner_link_source='club_vector_fixup' if record['owner_index'] is None else 'team_backlink',
                                        club={'database_index': club_index, 'native_id': club['native_id'],
                                              'secondary_id': club['secondary_id']})
            resolved[pair] = info
        for row in rows:
            ref = row[key]
            if ref['state'] != 'stored_all_ones_identity_pair':
                ref.update(resolved[(ref['native_id_word'], ref['secondary_word'])])
