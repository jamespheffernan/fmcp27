"""Archived-statistics API acceptance with synthetic memory and disposable files."""
import asyncio
import struct

import pytest

from fm_live_mcp.bridge import BridgeError
from test_bridge import bridge
from test_database import bind, database_memory, receipt
from test_player_staff import staff_memory
from test_players import memory
from test_teams import team_memory
from test_virtual import virtual_memory
from test_world import world_memory


def checked_reference(bridge, monkeypatch, m):
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *args: receipt())
    return bridge.find_save_players(bridge.session, 'Test')['players'][0]['player_ref']


@pytest.mark.parametrize('reference', [None, '', 1, True, [], {}])
def test_history_invalid_reference_rejects_before_native_reads(bridge, monkeypatch, reference):
    def forbidden(*args, **kwargs):
        pytest.fail('Malformed reference reached native layout discovery')
    monkeypatch.setattr(bridge, '_player_layout', forbidden)
    with pytest.raises(BridgeError, match='player_ref|reference'):
        bridge.get_player_statistics_history(bridge.session, reference)


def test_history_unknown_and_detached_reference_reject(bridge):
    with pytest.raises(BridgeError, match='Unknown|expired'):
        bridge.get_player_statistics_history(bridge.session, 'missing')
    session = bridge.session
    bridge.detach()
    with pytest.raises(BridgeError):
        bridge.get_player_statistics_history(session, 'missing')


@pytest.mark.parametrize('kind', ['virtual', 'player_staff'])
def test_history_unsupported_subtypes_reject_and_invalidate(bridge, monkeypatch, request, kind):
    m = request.getfixturevalue('virtual_memory' if kind == 'virtual' else 'staff_memory')
    bind(bridge, monkeypatch, m)
    row = next(p for p in bridge.get_managed_squad(bridge.session)['players']
               if p.get('record_kind') == kind)
    reference = row['player_ref']
    with pytest.raises(BridgeError, match='unsupported|Unsupported|only'):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert reference not in bridge.player_refs


@pytest.mark.parametrize('fault', ['identity', 'membership', 'save'])
def test_history_stale_reference_rejects_before_archive_access(bridge, monkeypatch, database_memory, fault):
    m = database_memory
    reference = checked_reference(bridge, monkeypatch, m)
    if fault == 'identity':
        m['put'](0x1394, struct.pack('<I', 54321))
    elif fault == 'membership':
        m['vec'](m['headers']['people'], [m['club']])
    else:
        m['q'](m['save'] + 0x28, m['text']('Different career'))
    with pytest.raises(BridgeError, match='changed|identity|membership|live table index'):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert reference not in bridge.player_refs


def test_history_memory_scan_retained_object_cannot_claim_current_save(bridge, monkeypatch, database_memory):
    m = database_memory
    bind(bridge, monkeypatch, m)
    m['vec'](m['headers']['people'], [m['club']])
    monkeypatch.setattr(bridge, '_run', lambda *args: {
        'matches': [{'address': '0x1000'}], 'stop_reason': 'address_space_end'})
    search = bridge.find_players(bridge.session, 'Test')
    reference = search['players'][0]['player_ref']
    assert search['save_identity'] == 'unverified'
    assert 'database_index' not in bridge.player_refs[reference]
    with pytest.raises(BridgeError, match='membership|live table index'):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert reference not in bridge.player_refs


def test_history_mcp_schema_and_read_only_annotations():
    from fm_live_mcp.server import mcp
    tool = next(t for t in asyncio.run(mcp.list_tools())
                if t.name == 'fm_get_player_statistics_history')
    assert set(tool.inputSchema['required']) == {'session_id', 'player_ref'}
    assert tool.inputSchema['properties']['player_ref']['type'] == 'string'
    assert tool.annotations.readOnlyHint is True
    assert tool.annotations.destructiveHint is False
    assert tool.annotations.openWorldHint is False


def archive_record(team_index=0, competition_index=0, *, year=2030, category=1, goals=2):
    """Independent native scalar layout; production codecs supply no expected values."""
    scalar = bytearray(25)
    struct.pack_into('<iHhh', scalar, 0, -99, year, 350, 400)
    scalar[10:17] = bytes([4, 1, 1, 0, 2, 3, 9])
    scalar[17:23] = bytes([5, 1, 6, goals, 1, 0])
    scalar[23:25] = bytes([37, category])
    signed = [0] * 68
    signed[4], signed[47], signed[55] = 51, -5, -13
    return (b'\0' + struct.pack('<ih', team_index, competition_index)
            + scalar + struct.pack('<68h', *signed))


@pytest.fixture
def history_memory(team_memory, tmp_path, monkeypatch):
    from fm_live_mcp import archive_stat_references as refs, archived_player_statistics as codec
    from fm_live_mcp import player_statistics, stats_archive as source
    m = team_memory
    for module in (refs, source):
        for rva, encoded in module.NATIVE_SPANS.items():
            m['put'](m['base'] + rva, bytes.fromhex(encoded))
    for module in (codec, player_statistics):
        for rva, expected in module.NATIVE_SPANS:
            m['put'](m['base'] + rva, expected)
    m['q'](m['tables'][2] + 0x2B0, m['base'] + 0xCA4794)
    m['put'](m['tables'][2] - 0x2C0, struct.pack('<q', -0x110))
    history_index = 0x1000 + 0x388 - 0x110 + 0xBC
    m['put'](history_index, struct.pack('<i', 0))
    manager = m['allocate'](0x28)
    table_rva, name = source.MANAGER_TYPE
    info, text = m['allocate'](16), m['allocate'](len(name) + 1)
    m['put'](text, name + b'\0')
    m['q'](info + 8, text)
    m['put'](m['base'] + table_rva - 16, struct.pack('<qQ', 0, info))
    m['q'](manager, m['base'] + table_rva)
    m['q'](m['base'] + source.MANAGER_ROOT, manager)
    pair, disk = m['allocate'](24), m['allocate'](0xA8)
    m['q'](manager + 0x20, pair)
    m['q'](pair, disk)
    for at, tag in ((8, 'player_stats_hist_id'), (16, 'player_stats_hist_dt'), (24, 'player_stats_hist_ls')):
        m['q'](disk + at, m['text'](tag))
    m['put'](disk + 0x98, struct.pack('<i', 336))
    m['put'](disk + 0x9C, struct.pack('<iH', 168, 7))
    m['put'](disk + 0xA5, b'\x01')
    index_header = m['allocate'](24)
    m['put'](disk + 0x78, struct.pack('<QQQ', index_header, index_header + 24, index_header + 24))
    stream, underlying, owner, file_pointer = [m['allocate'](size) for size in (0x38, 0x20, 16, 0x18)]
    m['q'](disk + 0x50, stream)
    m['q'](stream, m['base'] + source.STREAM_TABLE)
    m['q'](m['base'] + source.STREAM_TABLE + 0x10, m['base'] + 0x437F014)
    m['q'](m['base'] + source.STREAM_TABLE + 0x20, m['base'] + 0x437F078)
    m['put'](stream + 12, b'\x02')
    m['q'](stream + 0x18, underlying)
    m['q'](stream + 0x20, len(source.HEADER))
    m['put'](stream + 0x28, struct.pack('<q', 336))
    m['q'](underlying, m['base'] + source.FILE_STREAM_TABLE)
    m['q'](underlying + 0x18, owner)
    m['q'](owner + 8, file_pointer)
    m['put'](file_pointer + 0x12, struct.pack('<h', 62))
    m['put'](m['base'] + refs.REFERENCE_MODE, b'\0')
    m['put'](m['base'] + refs.REFERENCE_SWITCHES, b'\0\0')
    path = tmp_path / 'player_stats_hist_dt.cmt'
    path.write_bytes(source.HEADER + archive_record() + archive_record(1, 1, category=2, goals=3))
    def active_file(pid, descriptor):
        assert pid == 42 and descriptor == 62
        value = path.stat()
        return path, value.st_dev, value.st_ino
    monkeypatch.setattr(source, '_active_file', active_file)
    def offsets(values):
        address = m['allocate'](max(8, len(values)*4))
        m['put'](address, struct.pack(f'<{len(values)}i', *values))
        m['put'](index_header, struct.pack('<QQQ', address, address + len(values)*4, address + len(values)*4))
    offsets([0, 168])
    m.update(archive_path=path, history_manager=manager, history_pair=pair, history_disk=disk,
             history_stream=stream, history_file_pointer=file_pointer, history_index=history_index,
             history_index_header=index_header, set_history_offsets=offsets)
    return m


def assert_no_published_partial(bridge, reference, team_refs, competition_refs):
    assert reference not in bridge.player_refs
    assert bridge.team_refs == team_refs
    assert bridge.competition_refs == competition_refs


def test_history_real_source_codec_links_scope_and_duplicate_accounting(bridge, monkeypatch, history_memory):
    from fm_live_mcp import server
    m = history_memory
    # Preserve native order, repeated offsets and negative native skips.
    m['set_history_offsets']([168, -1, 0, 168, -2])
    reference = checked_reference(bridge, monkeypatch, m)
    monkeypatch.setattr(server, 'bridge', bridge)
    result = server.fm_get_player_statistics_history(bridge.session, reference)
    assert result['player'] == {'name': 'Test Müller', 'birth_date': '2000-02-29', 'record_kind': 'actual'}
    assert result['save_identity'] == 'native_binding_rechecked'
    assert result['save']['name'] == 'Synthetic career' and result['observed_at']
    history = result['history']
    assert history['state'] == 'decoded' and history['reason'] is None
    assert history['source_coverage'] == 'indexed_disk_stats_archive_only_no_current_or_starting_history'
    assert history['native_entry_count'] == 5 and history['returned_row_count'] == 3
    assert history['skipped_entries'] == [
        {'entry_index': 1, 'native_offset': -1, 'reason': 'native_negative_offset_skipped'},
        {'entry_index': 4, 'native_offset': -2, 'reason': 'native_negative_offset_skipped'}]
    assert history['native_entry_count'] == history['returned_row_count'] + len(history['skipped_entries'])
    assert [r['native_offset'] for r in history['rows']] == [168, 0, 168]
    rows = history['rows']
    assert [r['native_year'] for r in rows] == [2030]*3
    assert [r['category_name'] for r in rows] == ['Cup', 'League', 'Cup']
    assert [r['statistics']['goals'] for r in rows] == [3, 2, 3]
    assert rows[0]['statistics']['total_appearances'] == 6
    assert rows[0]['statistics']['minutes'] == 400
    assert rows[0]['statistics']['advanced']['named_raw_values']['expected_goals_prevented'] == -5
    assert rows[0]['raw_metadata'] == {'native_0x18_signed32': -99, 'native_0x2f_u8': 37}
    assert rows[0]['team']['native_id'] == 51 and rows[0]['team']['random_id'] == 901
    assert rows[0]['competition']['name'] == 'Test Continental Cup'
    assert rows[1]['team']['owner']['name'] == 'Test United'
    assert rows[1]['competition']['name'] == 'Test Premier Division'
    for row in rows:
        assert row['team']['team_ref'] in bridge.team_refs
        assert row['competition']['competition_ref'] in bridge.competition_refs
        assert '_bindings' not in row
    assert 'current' in history['source_coverage'] and 'starting_history' in history['source_coverage']
    assert 'do not establish that each category was played in that competition' in history['limitations']
    def assert_public(value):
        if isinstance(value, dict):
            assert not {'address', '_bindings', 'raw', 'file_path', 'descriptor'} & value.keys()
            for child in value.values():
                assert_public(child)
        elif isinstance(value, list):
            for child in value:
                assert_public(child)
    assert_public(history)


@pytest.mark.parametrize('state', ['empty', 'no_index', 'no_source', 'resident', 'stride'])
def test_history_empty_and_unavailable_sources_stay_distinct(bridge, monkeypatch, history_memory, state):
    m = history_memory
    if state == 'empty':
        m['set_history_offsets']([])
    elif state == 'no_index':
        m['put'](m['history_index'], struct.pack('<i', -1))
    elif state == 'no_source':
        m['q'](m['history_pair'], 0)
    elif state == 'resident':
        m['q'](m['history_pair'] + 8, m['allocate'](24))
    else:
        m['put'](m['history_disk'] + 0xA5, b'\0')
    reference = checked_reference(bridge, monkeypatch, m)
    history = bridge.get_player_statistics_history(bridge.session, reference)['history']
    assert history['rows'] == [] and history['returned_row_count'] == 0
    assert history['skipped_entries'] == []
    if state == 'empty':
        assert history['state'] == 'decoded' and history['native_entry_count'] == 0
    elif state == 'no_index':
        assert history['state'] == 'no_history_index' and history['native_entry_count'] == 0
    else:
        assert history['state'] == 'unavailable' and history['native_entry_count'] is None
        assert history['reason']
    assert reference in bridge.player_refs


@pytest.mark.parametrize('fault', ['header', 'truncated', 'bad_later_prefix', 'misaligned', 'extended_prefix'])
def test_history_corrupt_source_never_returns_partial_or_leaks_refs(bridge, monkeypatch, history_memory, fault):
    from fm_live_mcp import stats_archive as source
    m = history_memory
    reference = checked_reference(bridge, monkeypatch, m)
    if fault == 'header':
        raw = bytearray(m['archive_path'].read_bytes());raw[0] ^= 1
        m['archive_path'].write_bytes(raw)
    elif fault == 'truncated':
        m['archive_path'].write_bytes(m['archive_path'].read_bytes()[:-1])
    elif fault == 'bad_later_prefix':
        raw = bytearray(m['archive_path'].read_bytes());raw[len(source.HEADER) + 168] = 1
        m['archive_path'].write_bytes(raw)
    elif fault == 'misaligned':
        m['set_history_offsets']([0, 1])
    else:
        raw = bytearray(m['archive_path'].read_bytes())
        struct.pack_into('<h', raw, len(source.HEADER) + 168 + 5, -2)
        m['archive_path'].write_bytes(raw)
    teams_before, comps_before = dict(bridge.team_refs), dict(bridge.competition_refs)
    with pytest.raises(BridgeError):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert_no_published_partial(bridge, reference, teams_before, comps_before)


@pytest.mark.parametrize('fault', ['bytes', 'path', 'fd', 'fd_binding', 'source', 'membership'])
def test_history_post_yield_failure_invalidates_without_published_partial(
        bridge, monkeypatch, history_memory, fault):
    from contextlib import contextmanager
    from fm_live_mcp import stats_archive as source
    m = history_memory
    reference = checked_reference(bridge, monkeypatch, m)
    original = source.open_player_archive
    @contextmanager
    def mutate_after_consumption(*args, **kwargs):
        with original(*args, **kwargs) as archived:
            yield archived
            # The real source context performs its own final verification after mutation.
            if fault == 'bytes':
                with m['archive_path'].open('r+b') as file:
                    file.seek(len(source.HEADER) + 27);file.write(b'\x09')
            elif fault == 'path':
                replacement = m['archive_path'].with_suffix('.replacement')
                replacement.write_bytes(m['archive_path'].read_bytes())
                replacement.replace(m['archive_path'])
            elif fault == 'fd':
                m['put'](m['history_file_pointer'] + 0x12, struct.pack('<h', 63))
            elif fault == 'fd_binding':
                replacement = m['archive_path'].with_suffix('.other')
                replacement.write_bytes(m['archive_path'].read_bytes())
                value = replacement.stat()
                monkeypatch.setattr(source, '_active_file', lambda *args: (
                    replacement, value.st_dev, value.st_ino))
            elif fault == 'source':
                m['q'](m['history_pair'], 0)
            else:
                m['vec'](m['headers']['people'], [m['club']])
    monkeypatch.setattr(source, 'open_player_archive', mutate_after_consumption)
    teams_before, comps_before = dict(bridge.team_refs), dict(bridge.competition_refs)
    with pytest.raises(BridgeError):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert_no_published_partial(bridge, reference, teams_before, comps_before)



def test_history_valid_memory_search_reference_is_rebound_to_canonical_person(bridge, monkeypatch, history_memory):
    m = history_memory
    bind(bridge, monkeypatch, m)
    monkeypatch.setattr(bridge, '_run', lambda *args: {
        'matches': [{'address': '0x1000'}], 'stop_reason': 'address_space_end'})
    reference = bridge.find_players(bridge.session, 'Test')['players'][0]['player_ref']
    assert 'database_index' not in bridge.player_refs[reference]
    result = bridge.get_player_statistics_history(bridge.session, reference)
    assert result['save_identity'] == 'native_binding_rechecked'
    assert result['history']['returned_row_count'] == 2


def test_history_null_links_zero_values_and_independent_ids_are_preserved(bridge, monkeypatch, history_memory):
    from fm_live_mcp import stats_archive as source
    m = history_memory
    # Null transport remains null; the second row retains secondary ID zero.
    m['archive_path'].write_bytes(source.HEADER + archive_record(-1, -1, goals=0) + archive_record(1, 1, goals=3))
    m['put'](m['competitions'][1] + 16, struct.pack('<I', 0))
    reference = checked_reference(bridge, monkeypatch, m)
    rows = bridge.get_player_statistics_history(bridge.session, reference)['history']['rows']
    assert rows[0]['team'] is None and rows[0]['competition'] is None
    assert rows[0]['statistics']['goals'] == 0
    assert rows[1]['team']['random_id'] == 901
    assert rows[1]['competition']['native_id'] == 101 and rows[1]['competition']['random_id'] == 0
    assert bridge.get_team_squad(bridge.session, rows[1]['team']['team_ref'])['team']['native_id'] == 51
    assert bridge.get_competition(bridge.session, rows[1]['competition']['competition_ref'])['competition']['random_id'] == 0


def test_history_later_link_failure_publishes_no_earlier_row_refs(bridge, monkeypatch, history_memory):
    from fm_live_mcp import stats_archive as source
    m = history_memory
    m['archive_path'].write_bytes(source.HEADER + archive_record() + archive_record(999, 1))
    reference = checked_reference(bridge, monkeypatch, m)
    teams_before, comps_before = dict(bridge.team_refs), dict(bridge.competition_refs)
    with pytest.raises(BridgeError):
        bridge.get_player_statistics_history(bridge.session, reference)
    assert_no_published_partial(bridge, reference, teams_before, comps_before)
