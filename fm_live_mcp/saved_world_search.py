"""Search stored competitions and currencies in a named, checked saved file."""
from functools import partial

from . import saved_club_records, saved_competition_records, saved_currency_records
from . import saved_database, snapshot_catalog, saved_competition_state


def find_competitions(filename, *, native_id=None, type_code=None, gender=None, is_extinct=None,
                      offset=0, limit=50, expected_snapshot_id=None, directory=None,
                      include_saved_state=False):
    snapshot_catalog._page(offset, limit)
    if type(include_saved_state) is not bool:
        raise ValueError('Invalid saved competition state selection')
    saved_database.check_native_id(native_id)
    if type_code is not None and (type(type_code) is not int or not -128 <= type_code <= 127):
        raise ValueError('Invalid signed competition type')
    if gender not in (None, 'male', 'female'):
        raise ValueError('Invalid competition gender')
    if is_extinct is not None and type(is_extinct) is not bool:
        raise ValueError('Invalid competition extinct flag')
    gender_code = {'male': 0, 'female': 1}.get(gender)

    def matches(row):
        return ((native_id is None or row['native_id'] == native_id) and
                (type_code is None or row['type_code'] == type_code) and
                (gender_code is None or row['gender_code'] == gender_code) and
                (is_extinct is None or row['is_extinct'] == is_extinct))

    with saved_database.open_archive_at_clubs(filename, expected_snapshot_id, directory) as (reader, source, handle, entries):
        states = None
        if include_saved_state:
            by_path = {entry.path: entry for entry in entries}
            states = saved_competition_state.StateReader(handle, by_path, entries[0].path.split('/')[0])
        saved_database.skip_table(reader, 'CLUB', saved_club_records.read_club)
        rows = saved_database.table(reader, 'COMP', saved_competition_records.read_competition)
        count, competitions, paging = saved_database.page(rows, matches, offset, limit)
        if states is not None:
            for row in competitions:
                row['saved_state'] = states.read(row['native_id'])
        return {**source, **paging, 'total_competition_slots': count, 'competitions': competitions}


def find_currencies(filename, *, name=None, native_id=None, include_history=False,
                    offset=0, limit=50, expected_snapshot_id=None, directory=None):
    snapshot_catalog._page(offset, limit)
    saved_database.check_native_id(native_id)
    needle = saved_database.name_filter(name)
    if type(include_history) is not bool:
        raise ValueError('Invalid currency history selection')

    def matches(row):
        return ((native_id is None or native_id == row['native_id']) and
                (needle is None or needle in (row['name'] or '').casefold()))

    history_rows = 0

    def check_response_size(row):
        nonlocal history_rows
        history_rows += row['history_count']
        if history_rows > 16_384:
            raise ValueError('Selected currency histories exceed the page budget. Reduce limit.')

    with saved_database.open_at_clubs(filename, expected_snapshot_id, directory) as (reader, source):
        saved_database.skip_table(reader, 'CLUB', saved_club_records.read_club)
        saved_database.skip_table(reader, 'COMP', saved_competition_records.read_competition)
        saved_database.skip_table(reader, 'CONTINENT', saved_currency_records.skip_continent)
        decode = partial(saved_currency_records.read_currency, include_history=include_history)
        rows = saved_database.table(reader, 'CURRENCY', decode)
        count, currencies, paging = saved_database.page(
            rows, matches, offset, limit, on_select=check_response_size if include_history else None)
        return {**source, **paging, 'total_currency_slots': count, 'currencies': currencies}
