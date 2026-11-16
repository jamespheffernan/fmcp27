"""Resolve one saved club's team list and same-file player references."""
from functools import partial

from . import (
    saved_club_records, saved_database, saved_squad_tables, saved_team_records,
)

MAX_TEAM_SLOTS = 250_000
MAX_RETURNED_ROSTER_SLOTS = 65_535


def _select_club(reader, native_id):
    # The native fixup restores a missing TEAM backlink from the CLUB vector.
    # A second club claiming that same TEAM makes that restoration ambiguous.
    claims = bytearray(MAX_TEAM_SLOTS)
    selected = None
    decode = partial(saved_club_records.read_club, include_team_indices=True)
    for club in saved_database.table(reader, 'CLUB', decode):
        for index in club['team_indices']:
            if index is not None and 0 <= index < MAX_TEAM_SLOTS:
                claims[index] = min(2, claims[index] + 1)
        if club['native_id'] == native_id:
            if selected is not None:
                raise ValueError('Saved club native ID has duplicate records')
            selected = club
    if selected is None:
        raise ValueError('Saved club native ID not found')
    indices = selected.pop('team_indices')
    for index in indices:
        if index is None:
            continue
        if not 0 <= index < MAX_TEAM_SLOTS:
            raise ValueError('Saved club TEAM reference is outside supported bounds')
        if claims[index] != 1:
            raise ValueError('Saved TEAM has duplicate club membership claims')
    return selected, indices


def get_saved_club_squads(filename, club_native_id, expected_snapshot_id=None, *, directory=None):
    if club_native_id is None:
        raise ValueError('Supply a club native ID')
    saved_database.check_native_id(club_native_id)
    with saved_database.open_at_clubs(filename, expected_snapshot_id, directory) as (reader, source):
        club, indices = _select_club(reader, club_native_id)
        saved_squad_tables.reach_teams_after_clubs(reader)
        selected = {index for index in indices if index is not None}
        found = {}
        roster_slots = 0
        total = 0

        def decode(reader, ordinal, kind):
            return saved_team_records.read_team(reader, ordinal, kind, include_roster=ordinal in selected)

        for team in saved_database.table(reader, 'TEAM', decode, max_slots=MAX_TEAM_SLOTS):
            total += 1
            index = team['database_index']
            club_owner = team['owner_kind'] == 'club'
            backlink = team['owner_index']
            if index in selected:
                if not club_owner or backlink not in (None, club['database_index']):
                    raise ValueError('Saved TEAM owner conflicts with the club membership vector')
                if team.get('unverified_negative_person_indices'):
                    raise ValueError('Saved TEAM has an unsupported negative PERSON reference')
                team['owner_link_source'] = 'club_vector_fixup' if backlink is None else 'team_backlink'
                roster_slots += team['roster_count']
                if roster_slots > MAX_RETURNED_ROSTER_SLOTS:
                    raise ValueError('Saved club rosters exceed the response budget')
                found[index] = team
            elif club_owner and backlink == club['database_index']:
                raise ValueError('Saved TEAM owner points to club but TEAM is absent from its vector')
        if found.keys() != selected:
            raise ValueError('Saved club TEAM reference is outside the saved TEAM table')
        return {
            **source, 'club': club, 'team_indices': indices, 'team_count': len(found),
            'total_team_slots_in_save': total,
            'teams': [found[index] for index in indices if index is not None],
            'roster_reference_kind': 'same-file PERSON database index',
        }
