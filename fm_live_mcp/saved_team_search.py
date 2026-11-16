"""Find teams and overlapping roster memberships inside one checked saved file."""
from functools import partial

from . import saved_club_records, saved_database, saved_squad_tables, saved_team_nation, saved_team_records, snapshot_catalog

MAX_PERSON_FILTERS = 500
MAX_RETURNED_MATCHES = 16_384


def _person_filter(person_indices, snapshot_id):
    if person_indices is None:
        return None
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError('Filtering by saved PERSON indices requires expected_snapshot_id')
    if type(person_indices) is not list or not 1 <= len(person_indices) <= MAX_PERSON_FILTERS:
        raise ValueError('Supply between 1 and 500 saved PERSON indices')
    if any(type(index) is not int or not 0 <= index < 1 << 31 for index in person_indices):
        raise ValueError('Invalid saved PERSON index')
    indices = frozenset(person_indices)
    if len(indices) != len(person_indices):
        raise ValueError('Duplicate PERSON indices in filter')
    return indices


def find_teams(filename, *, native_id=None, owner_kind=None, team_type_code=None, person_indices=None,
               offset=0, limit=50, expected_snapshot_id=None, directory=None,
               include_nation_context=False, nation_native_id=None):
    snapshot_catalog._page(offset, limit)
    saved_database.check_native_id(native_id)
    saved_database.check_native_id(nation_native_id)
    if type(include_nation_context) is not bool:
        raise ValueError("Invalid saved nation context selection")
    with_context = include_nation_context or nation_native_id is not None
    if owner_kind not in (None, 'club', 'national'):
        raise ValueError('Invalid saved TEAM owner kind')
    if team_type_code is not None and (type(team_type_code) is not int or not -128 <= team_type_code <= 127):
        raise ValueError('Invalid signed TEAM type code')
    indices = _person_filter(person_indices, expected_snapshot_id)
    read_team = partial(saved_team_records.read_team, include_roster=False, match_person_indices=indices)

    def matches(team):
        return ((native_id is None or team['native_id'] == native_id) and
                (owner_kind is None or team['owner_kind'] == owner_kind) and
                (team_type_code is None or team['team_type_code'] == team_type_code) and
                (indices is None or bool(team['matched_person_slots'])) and
                (nation_native_id is None or (team.get('nation_context', {}).get('nation') or {}).get('native_id') == nation_native_id))

    returned_matches = 0

    def check_size(team):
        nonlocal returned_matches
        returned_matches += len(team['matched_person_slots'])
        if returned_matches > MAX_RETURNED_MATCHES:
            raise ValueError('Selected roster matches exceed the response budget. Reduce limit or filter fewer indices.')

    with saved_database.open_at_clubs(filename, expected_snapshot_id, directory) as (reader, source):
        saved_database.skip_table(reader, 'CLUB', saved_club_records.read_club)
        context = saved_squad_tables.reach_teams_after_clubs(
            reader, read_nation_context=saved_team_nation.NationContext if with_context else None)

        def decode(reader, ordinal, kind):
            row = read_team(reader, ordinal, kind)
            if context is not None and row['owner_kind'] == 'national':
                row['nation_context'] = context.resolve(row)
            return row

        rows = saved_database.table(reader, 'TEAM', decode)
        total, teams, paging = saved_database.page(rows, matches, offset, limit,
                                                  on_select=check_size if indices is not None else None)
        result = {**source, **paging, 'total_team_slots': total, 'teams': teams}
        if context is not None:
            result['nation_name_source'] = context.finish(total, teams)
        return result
