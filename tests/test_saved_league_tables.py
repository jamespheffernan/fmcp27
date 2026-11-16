"""Packaged sequential framing, real compressed snapshots and qualified joins."""
import asyncio
from contextlib import contextmanager
import hashlib
import io
import json
import os
from pathlib import Path
import struct
from types import SimpleNamespace

import pytest

from fm_live_mcp import saved_league_tables as query, snapshot_catalog
from fm_live_mcp._saved_league import comp390, embedded, row, settings, wire
from test_saved_club_search import database
from test_saved_competition_state import prefix
from test_saved_database_header import text
from test_saved_squad_search import club, team
from test_saved_world_search import competition, framed
from test_snapshot_catalog_public import compress


def settings_packet():
    return (b'\xff\xff' + bytes(sum(n for _, n in settings.FIRST)) + bytes(4 + 12 + 15)
            + bytes(sum(n for _, n in settings.SECOND)) + bytes(8 * 4) + b'\0'
            + bytes(4) + b'\0' + bytes(4 + 1 + 4 + 3 + 1)
            + b'\xff\xff' * 2 + bytes(5) + b'\xff\xff' + bytes(3 + 4))


def row_packet(index=0, position=0):
    ref = b'\0' + struct.pack('<i', index)
    block = b'\0' + struct.pack('<i6b3h', -1, 8, 8, 6, 1, 1, 0, 21, 6, 19)
    opaque = bytes([position]) + bytes(13)
    return ref + opaque + bytes(4) + block * 5 + bytes(1 + 13 + 2 + 1 + 1 + 10 + 1)


def member(*, rows=(), kinds=(1,), settings_present=True, view=0):
    # Independent native writer sequence; there are no source-file offsets here.
    fixed = bytes(11) + b'\0' + b'\xff\xff' + bytes(4) + bytes(7 * 4)
    scalars = bytes(1 + 6 * 2 + 4 + 6 * 2 + 4)
    lead = prefix() + bytes(4) + b'\0' + fixed + scalars + bytes(6 + 4 + 4 + 1 + 1)
    lead += struct.pack('<I', len(kinds))
    for kind in kinds:
        lead += bytes([kind])
        if kind == 1:
            lead += bytes([view, 1]) + bytes.fromhex('3601ee07') + bytes(2) + b'\1' + bytes(4) + b'\0'
            lead += bytes([settings_present]) + (settings_packet() if settings_present else b'')
            lead += b'\0' + struct.pack('<b', len(rows)) + b''.join(rows)
            # Full stage continuation is deliberately not implemented.
            break
    return lead


def archive(path, *, members, competitions=None, clubs=None, teams=None):
    if competitions is None: competitions = [competition(0, 11)]
    if clubs is None: clubs = [club(0, 688)]
    if teams is None: teams = [team(0, 900)]
    db = database(clubs) + framed(competitions) + framed([]) * 7 + bytes(12) + framed([]) * 5 + framed(teams)
    payload = bytearray(); folders = {}
    for filename, raw in [('game_db.dat', db)] + list(members.items()):
        parent, _, leaf = filename.rpartition('/'); packed = compress(raw)
        folders.setdefault(parent, []).append((leaf, len(payload), len(packed), len(raw)))
        payload.extend(packed)
    def directory(name, entries, children=()):
        raw = text(name) + struct.pack('<I', len(entries))
        for leaf, start, packed, size in entries:
            stem, extension = leaf.rsplit('.', 1)
            raw += text(stem) + text('.' + extension) + struct.pack('<5Q', start, packed, size, 0, 0)
        return raw + struct.pack('<I', len(children)) + b''.join(children)
    children = [directory(name, entries) for name, entries in folders.items() if name]
    table = directory('career', folders[''], children)
    offset = 26 + len(payload) + 9
    path.write_bytes(snapshot_catalog.MAGIC + struct.pack('<Q', offset - 18) + bytes(9)
                     + payload + snapshot_catalog.MAGIC + compress(table))
    return path


def get(path, **kwargs):
    pin = snapshot_catalog.inspect_snapshot(path.name, directory=path.parent)['snapshot_id']
    return query.get_league_table(path.name, 0, pin, directory=path.parent, **kwargs)


def test_settings_and_row_every_truncation():
    data = settings_packet()
    assert settings.parse(data, 0)['end'] == len(data)
    for end in range(len(data)):
        with pytest.raises(ValueError): settings.parse(data, 0, limit=end)
    data = row_packet()
    result = row.parse(data, 0, reference_context=wire.REFERENCE_PROFILE)
    assert result['end'] == len(data) and result['overall']['points'] == 19
    for end in range(len(data)):
        with pytest.raises(ValueError): row.parse(data, 0, limit=end, reference_context=wire.REFERENCE_PROFILE)


def test_portable_wire_stops_before_unread_stage_suffix():
    data = member(rows=[row_packet()])
    result = wire.decode(data + b'not a parsed stage suffix', 0)
    assert result['state'] == 'decoded' and result['consumed_end'] == len(data)
    assert result['table']['row_count'] == 1
    for end in range(len(data)):
        with pytest.raises(ValueError): wire.decode(data[:end], 0)
    assert wire.decode(member(kinds=(7, 7)), 1)['state'] == 'stage_absent'
    assert wire.decode(member(), 1)['state'] == 'stage_absent'
    assert wire.decode(member(kinds=(0, 1)), 1)['state'] == 'stopped'
    assert wire.decode(member(kinds=(0,)), 0)['state'] == 'unsupported_stage'


def test_real_archive_original_COMP_and_canonical_TEAM_CLUB_join(tmp_path):
    path = archive(tmp_path/'league.fm', members={'rgman/comp_11.dat': member(rows=[row_packet()])})
    result = get(path); table = result['table']; first = table['rows'][0]
    assert table['state'] == 'decoded' and table['row_count'] == 1
    assert first['team']['database_index'] == 0 and first['team']['native_id'] == 900
    assert first['team']['name'] == '' and first['owner_club']['native_id'] == 688
    assert first['owner_club']['name'] == 'Newcastle United'
    assert first['stored_overall_position'] == 1 and first['overall']['points'] == 19
    assert table['table_effective_date'] is None and table['currentness'] == 'unproved'
    assert table['season_date_range'] is None and not table['complete_stage']
    assert table['stage_calendar']['value'] == '2030-11-06'
    assert not result['evidence_scope']['native_runtime_selectors_observed']


def test_positions_empty_tables_invalid_refs_and_names_preserved(tmp_path):
    for view, position in [(1, 0), (0, 2)]:
        path = archive(tmp_path/f'view{view}{position}.fm', members={'rgman/comp_11.dat': member(rows=[row_packet(position=position)], view=view)})
        assert get(path)['table']['rows'][0]['stored_overall_position'] is None
    path = archive(tmp_path/'empty.fm', members={'rgman/comp_11.dat': member()})
    assert get(path)['table']['row_count'] == 0
    for index, state in [(-1, 'null'), (-2, 'invalid_negative_index'), (50, 'out_of_range')]:
        path = archive(tmp_path/f'ref{index}.fm', members={'rgman/comp_11.dat': member(rows=[row_packet(index)])})
        r = get(path)['table']['rows'][0]
        assert r['team'] is None and r['team_reference_state'] == state


def test_absent_unknown_header_supported_truncation_pin_and_primary_id(tmp_path):
    path = archive(tmp_path/'absent.fm', members={})
    assert get(path)['table']['state'] == 'absent'
    path = archive(tmp_path/'unknown.fm', members={'rgman/comp_11.dat': b'no'})
    assert get(path)['table']['state'] == 'unsupported_layout'
    path = archive(tmp_path/'truncated.fm', members={'rgman/comp_11.dat': prefix()})
    with pytest.raises(ValueError, match='Truncated'): get(path)
    with pytest.raises(ValueError, match='Snapshot identity'): query.get_league_table(path.name, 0, 'wrong', directory=tmp_path)
    path = archive(tmp_path/'ambiguous.fm', competitions=[competition(0, 11), competition(1, 11)], members={})
    assert get(path)['table']['state'] == 'competition_identity_ambiguous'
    path = archive(tmp_path/'signed.fm', competitions=[competition(0, 0xffffffff)], members={'rgman/comp_-1.dat': member()})
    assert get(path)['table']['component_path'] == 'career/rgman/comp_-1.dat'


def test_explicit_unknown_settings_child_and_bad_versions():
    data = member()
    actual = settings.parse(settings_packet(), 0)
    point = next(p['start'] for p in actual['parts'] if p.get('native_field') == '0x1f8')
    settings_start = data.find(settings_packet())
    mutated = bytearray(data); mutated[settings_start + point:settings_start + point + 4] = struct.pack('<I', 1)
    result = wire.decode(bytes(mutated), 0)
    assert result['state'] == 'stopped' and result['next_native_reader'] == '0x3E25728'
    # Unknown packed child layouts are explicit alternatives, not absent tables.
    with pytest.raises(ValueError): settings.parse(settings_packet(), 0, file_version=520)


@pytest.mark.parametrize('arguments', [dict(competition_index=True), dict(competition_index=-1),
    dict(stage_ordinal=True), dict(stage_ordinal=1024), dict(expected_snapshot_id='')])
def test_validation_before_source(arguments):
    args = dict(filename='missing.fm', competition_index=0, expected_snapshot_id='pin'); args.update(arguments)
    with pytest.raises(ValueError): query.get_league_table(**args)


def test_packaged_code_has_no_runtime_research_loading():
    package = Path(query.__file__).with_name('_saved_league')
    for path in package.glob('*.py'):
        source = path.read_text()
        assert 'importlib' not in source and 'sys.path' not in source and '__file__' not in source
        assert 'evidence/' not in source and '8ff7b705' not in source and '120901' not in source


def test_public_schema_and_dispatch(monkeypatch):
    from fm_live_mcp import server
    tool = next(t for t in asyncio.run(server.mcp.list_tools()) if t.name == 'fm_get_saved_league_table')
    assert tool.annotations.readOnlyHint
    assert set(tool.inputSchema['required']) == {'filename', 'competition_index', 'expected_snapshot_id'}
    monkeypatch.setattr(query, 'get_league_table', lambda *args, **kw: dict(args=args, kwargs=kw))
    assert server.fm_get_saved_league_table('a.fm', 7, 'pin', 0)['kwargs'] == {'stage_ordinal': 0}


def test_member_budget_and_postdecode_source_change(monkeypatch):
    entry = SimpleNamespace(uncompressed_size=query.MAX_COMPONENT_BYTES + 1,
                            compressed_size=1, start=0)
    assert query._member(None, entry)['state'] == 'budget_exceeded'
    handle = io.BytesIO(bytes(26) + b'original')
    entry = SimpleNamespace(uncompressed_size=49, compressed_size=8, start=0)
    @contextmanager
    def changing(source, selected):
        yield SimpleNamespace(size=49, take=lambda n: prefix(),
                              source=SimpleNamespace(read=lambda n: b'', finished=True))
        source.seek(26); source.write(b'modified')
    monkeypatch.setattr(query, 'open_component', changing)
    with pytest.raises(ValueError, match='changed during read'): query._member(handle, entry)


def test_second_pass_pin_failure_and_response_budget(tmp_path, monkeypatch):
    path = archive(tmp_path/'pin.fm', members={'rgman/comp_11.dat': member(rows=[row_packet()])})
    def changed(filename, pin, wanted, directory):
        assert pin and wanted == {0}
        raise ValueError('Snapshot changed before canonical TEAM pass')
    monkeypatch.setattr(query, '_canonical_teams', changed)
    with pytest.raises(ValueError, match='Snapshot changed'): get(path)
    path = archive(tmp_path/'budget.fm', members={'rgman/comp_11.dat': member()})
    monkeypatch.setattr(query, 'MAX_RESPONSE_BYTES', 1)
    with pytest.raises(ValueError, match='response budget'): get(path)


def test_optional_eight_pinned_independent_tables():
    path = os.environ.get('FM_SAVED_LEAGUE_TABLE_ORACLE')
    if not path:
        pytest.skip('Set FM_SAVED_LEAGUE_TABLE_ORACLE to the frozen independent eight-table oracle')
    expected = json.loads(Path(path).read_text())
    for prior in expected['tables']:
        reply = query.get_league_table(prior['filename'], prior['competition_index'], prior['snapshot_id'],
            directory=os.environ.get('FM_SAVED_CAREER_DIRECTORY'))
        table = reply['table']
        assert table['state'] == 'decoded' and table['row_count'] == prior['table_count']
        assert table['C0_table_end'] == prior['table_end']
        assert table['member_raw_sha256'] == prior['source_component_raw_sha256']
        assert table['table_effective_date'] is None and table['season_date_range'] is None
        assert table['native_season_code'] == prior['native_season_code']
        for actual, row_expected in zip(table['rows'], prior['rows'], strict=True):
            assert actual['stored_overall_position'] == row_expected['stored_overall_position']
            assert actual['start'] == row_expected['source_row_start']
            assert actual['end'] == row_expected['source_row_end']
            for side in ('overall', 'home', 'away'):
                for field, value in row_expected[side].items():
                    assert actual[side][field] == value
            canonical = row_expected['team']
            assert actual['owner_club'] == canonical.get('canonical_owner_club')
            assert actual['team'] == {k: v for k, v in canonical.items() if k != 'canonical_owner_club'}


def test_unknown_header_never_invents_stream_version(tmp_path):
    for raw, version in [(b'wrong123456', None), (query.HEADER[:6] + b'\x0a\x02', 522)]:
        path = archive(tmp_path/f'header{version}.fm', members={'rgman/comp_11.dat': raw})
        table = get(path)['table']
        assert table['state'] == 'unsupported_layout' and table['stream_version'] == version
        assert table['rows'] is None and table['row_count'] is None
        assert not table['complete_C0_table'] and not table['complete_stage']


def test_club_context_budget_and_unavailable_original_COMP(tmp_path, monkeypatch):
    path = archive(tmp_path/'context.fm', members={'rgman/comp_11.dat': member(rows=[row_packet()])})
    monkeypatch.setattr(query, 'MAX_CLUB_CONTEXT_BYTES', 0)
    with pytest.raises(ValueError, match='CLUB context exceeds'): get(path)
    pin = snapshot_catalog.inspect_snapshot(path.name, directory=tmp_path)['snapshot_id']
    result = query.get_league_table(path.name, 1, pin, directory=tmp_path)
    assert result['table']['state'] == 'competition_unavailable' and result['table']['rows'] is None


def test_absent_canonical_CLUB_name_is_preserved_and_budgeted(tmp_path):
    path = archive(tmp_path/'nullname.fm', clubs=[club(0, 688, name='')],
        members={'rgman/comp_11.dat': member(rows=[row_packet()])})
    result = get(path)['table']['rows'][0]
    assert result['owner_club']['native_id'] == 688
    assert result['owner_club']['name'] is None and result['team']['name'] == ''
