"""One pinned competition's retained ordinary league C0 table, not current standings."""
from functools import partial
from collections import Counter
import hashlib
import json

from . import (saved_club_records, saved_competition_records, saved_database,
               saved_squad_tables, saved_team_records)
from ._saved_league import wire
from .saved_component_stream import open_component
from .saved_competition_state import HEADER
from .saved_form_rows import _date

MAX_COMPONENT_BYTES = 2 * 1024 * 1024
MAX_PACKED_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024
MAX_CLUB_CONTEXT_BYTES = 16 * 1024 * 1024


def _validate(competition_index, stage_ordinal, expected_snapshot_id):
    if type(competition_index) is not int or not 0 <= competition_index < 2**31:
        raise ValueError('Invalid original saved COMP index')
    if type(stage_ordinal) is not int or not 0 <= stage_ordinal < 1024:
        raise ValueError('Invalid original stage ordinal')
    if not isinstance(expected_snapshot_id, str) or not expected_snapshot_id:
        raise ValueError('Supply the snapshot ID that issued the COMP reference')


def _member(handle, entry):
    if entry.uncompressed_size > MAX_COMPONENT_BYTES or entry.compressed_size > MAX_PACKED_BYTES:
        return dict(state='budget_exceeded', reason='Competition member exceeds bounded decoding budget')
    if entry.uncompressed_size == 0:
        return dict(state='unsupported_layout', reason='Empty competition member')
    handle.seek(26 + entry.start)
    packed = handle.read(entry.compressed_size)
    if len(packed) != entry.compressed_size:
        raise ValueError('Truncated competition member packed extent')
    packed_hash = hashlib.sha256(packed).hexdigest()
    with open_component(handle, entry) as reader:
        data = reader.take(reader.size)
        if reader.source.read(1) or not reader.source.finished:
            raise ValueError('Competition frame did not end at its declared extent')
    handle.seek(26 + entry.start)
    if handle.read(entry.compressed_size) != packed:
        raise ValueError('Competition member changed during read')
    if data[:8] != HEADER:
        return dict(state='unsupported_layout', reason='Unsupported competition stream header',
                    stream_version=(int.from_bytes(data[6:8], 'little')
                                    if len(data) >= 8 and data[:6] == HEADER[:6] else None))
    if len(data) < 49:
        raise ValueError('Truncated supported competition fixed prefix')
    return dict(state='ready', data=data, stream_version=521,
                member_raw_sha256=hashlib.sha256(data).hexdigest(),
                member_packed_sha256=packed_hash)


def _project_table(decoded, source, competition, path, raw_hash, teams, clubs):
    table = decoded['table']
    view = table['native_order_view_code']
    agrees = all(r['native_row_index'] == i and r['value']['stored_position_u8'] == i
                 for i, r in enumerate(table['rows']))
    date_field = next(p for p in table['parts'] if p.get('native_field') == '1c0')
    calendar = _date(bytes.fromhex(date_field['raw_hex']))
    # This is the same date encoding, with a different unproved field meaning.
    if calendar['value'] is not None:
        calendar['state'] = 'stored_stage_calendar_value'
    saved_date = source['saved_metadata'].get('saved_simulation_date')
    relation = None
    if calendar['value'] is not None and saved_date is not None:
        relation = ('future' if calendar['value'] > saved_date else
                    'past' if calendar['value'] < saved_date else 'equal')
    rows = []
    for ordinal, item in enumerate(table['rows']):
        value = item['value']
        index = value['team_reference']['stored_team_index']
        team = teams.get(index)
        club = None
        if team is not None and team['owner_kind'] == 'club':
            club = clubs.get(team['owner_index'])
        reference_state = ('resolved' if team is not None else 'null' if index == -1 else
                           'invalid_negative_index' if index < -1 else 'out_of_range')
        rows.append(dict(
            row_index=ordinal, start=item['start'], end=item['end'],
            team_reference_word=index, team_reference_state=reference_state,
            team=team, owner_club=club, stored_position_u8=value['stored_position_u8'],
            stored_overall_position=ordinal + 1 if view == 0 and agrees else None,
            overall=value['overall'], home=value['home'], away=value['away'],
            unmapped_stat_blocks=value['unmapped_stat_blocks']))
    return dict(state='decoded', competition=competition, component_path=path,
        stream_version=521, native_season_code=decoded['native_season_code'],
        season_date_range=None, table_effective_date=None, currentness='unproved',
        stage_ordinal=decoded['stage_ordinal'], stage_kind=1,
        stored_stage_count=decoded['stage_count'],
        stage_body_start=decoded['stage_body_start'], C0_table_end=decoded['consumed_end'],
        member_raw_sha256=raw_hash, native_order_view_code=view,
        all_position_bytes_match_original_order=agrees,
        stage_calendar=calendar, stage_calendar_relation_to_save=relation,
        row_count=len(rows), rows=rows, complete_C0_table=True, complete_stage=False,
        next_native_reader=decoded['next_native_reader'],
        canonical_team_joins=sum(r['team_reference_state'] == 'resolved' for r in rows))


def _canonical_teams(filename, pin, wanted, directory):
    """A second forward game_db pass, re-opened under the identical checked pin."""
    clubs, teams = {}, {}
    context_bytes = 0
    with saved_database.open_archive_at_clubs(filename, pin, directory) as (reader, source, _, _):
        for row in saved_database.table(reader, 'CLUB', saved_club_records.read_club):
            context_bytes += 128 + (len(row['name'].encode('utf-8'))
                                    if row['name'] is not None else 0)
            if context_bytes > MAX_CLUB_CONTEXT_BYTES:
                raise ValueError('Canonical CLUB context exceeds saved league table work budget')
            clubs[row['database_index']] = {key: row[key] for key in
                ('database_index', 'native_id', 'secondary_id', 'name')}
        saved_squad_tables.reach_teams_after_clubs(reader)
        decode = partial(saved_team_records.read_team, include_roster=False)
        for row in saved_database.table(reader, 'TEAM', decode):
            if row['database_index'] in wanted:
                teams[row['database_index']] = row
    return teams, clubs


def get_league_table(filename, competition_index, expected_snapshot_id, *, stage_ordinal=0, directory=None):
    """Resolve original COMP to its member; never use per-file offsets or fitting."""
    _validate(competition_index, stage_ordinal, expected_snapshot_id)
    with saved_database.open_archive_at_clubs(
            filename, expected_snapshot_id, directory) as (reader, source, handle, entries):
        saved_database.skip_table(reader, 'CLUB', saved_club_records.read_club)
        competition = None
        native_counts = Counter()
        for row in saved_database.table(reader, 'COMP', saved_competition_records.read_competition):
            native_counts[row['native_id']] += 1
            if row['database_index'] == competition_index:
                competition = row
        if competition is None:
            result = dict(state='competition_unavailable', reason='Original COMP index is outside the stored table')
        elif native_counts[competition['native_id']] != 1:
            result = dict(state='competition_identity_ambiguous', competition=competition,
                          reason='Canonical COMP primary ID does not uniquely select an archive member owner')
        else:
            native = competition['native_id']
            signed = native if native < 2**31 else native - 2**32
            path = f"{entries[0].path.split('/')[0]}/rgman/comp_{signed}.dat"
            matching = [entry for entry in entries if entry.path == path]
            if len(matching) > 1:
                raise ValueError('Saved competition member path is ambiguous')
            if not matching:
                result = dict(state='absent', competition=competition, component_path=path,
                              reason='Competition runtime member is not stored')
            else:
                member = _member(handle, matching[0])
                if member['state'] != 'ready':
                    result = {**member, 'competition': competition, 'component_path': path}
                else:
                    raw_hash = member['member_raw_sha256']
                    result = wire.decode(member['data'], stage_ordinal)
                    result.update(competition=competition, component_path=path,
                                  stream_version=521, member_raw_sha256=raw_hash)
                    # Re-read the packed member before leaving the checked archive.
                    # The enclosing source identity is also verified on context exit.
                    entry = matching[0]
                    handle.seek(26 + entry.start)
                    packed_hash = hashlib.sha256(handle.read(entry.compressed_size)).hexdigest()
                    if packed_hash != member['member_packed_sha256']:
                        raise ValueError('Competition member changed during decoding')
                    result['member_packed_sha256'] = packed_hash
        first_source = source
    if result['state'] == 'decoded':
        wanted = {r['value']['team_reference']['stored_team_index']
                  for r in result['table']['rows']
                  if r['value']['team_reference']['stored_team_index'] >= 0}
        teams, clubs = (_canonical_teams(filename, expected_snapshot_id, wanted, directory)
                        if wanted else ({}, {}))
        packed_hash = result['member_packed_sha256']
        result = _project_table(result, first_source, competition, path, raw_hash, teams, clubs)
        result['member_packed_sha256'] = packed_hash
    if result['state'] != 'decoded':
        for key, value in dict(rows=None, row_count=None, complete_C0_table=False,
                               complete_stage=False, table_effective_date=None,
                               season_date_range=None, currentness='unproved',
                               native_season_code=None).items():
            result.setdefault(key, value)
    reply = {**first_source, 'competition_index': competition_index,
        'requested_stage_ordinal': stage_ordinal, 'table': result,
        'evidence_scope': {**wire.PROFILE_SCOPE,
            'reference_context': dict(wire.REFERENCE_PROFILE),
            'scope': 'retained ordinary league C0 table only',
            'position': 'stored overall position only with view0 and all original position bytes agreeing; not current rank',
            'stage_calendar': 'date-driven rule processing; not table effective date',
            'season': 'stored discriminator; real season interval unproved',
            'canonical_identity': 'original same-snapshot COMP/TEAM/CLUB ordinals; empty TEAM names preserved',
            'complete_stage': False, 'whole_competition_state': False,
            'native_competition_id_filename': 'signed32 formatting of canonical COMP primary ID'},
        'resource_limits': dict(max_component_bytes=MAX_COMPONENT_BYTES,
                               max_packed_bytes=MAX_PACKED_BYTES,
                               max_response_bytes=MAX_RESPONSE_BYTES,
                               max_club_context_bytes=MAX_CLUB_CONTEXT_BYTES)}
    if len(json.dumps(reply, ensure_ascii=True).encode('ascii')) > MAX_RESPONSE_BYTES:
        raise ValueError('Saved league table exceeds response budget')
    return reply
