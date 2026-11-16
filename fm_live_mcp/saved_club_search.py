"""Search the complete checked CLUB table of a single saved snapshot."""
from . import saved_club_records, saved_database, snapshot_catalog


def find_clubs(filename, *, name=None, native_id=None, offset=0, limit=50,
               expected_snapshot_id=None, directory=None):
    snapshot_catalog._page(offset, limit)
    saved_database.check_native_id(native_id)
    needle = saved_database.name_filter(name)

    def matches(row):
        return ((native_id is None or row['native_id'] == native_id) and
                (needle is None or any(needle in (row[key] or '').casefold()
                                       for key in ('name', 'short_name'))))

    with saved_database.open_at_clubs(filename, expected_snapshot_id, directory) as (reader, source):
        rows = saved_database.table(reader, 'CLUB', saved_club_records.read_club)
        count, clubs, paging = saved_database.page(rows, matches, offset, limit)
        return {**source, **paging, 'population': 'complete_saved_CLUB_table_including_league_body_clubs',
                'total_club_slots': count, 'clubs': clubs}
