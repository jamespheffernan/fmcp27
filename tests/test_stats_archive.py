import os
import struct
import subprocess

import pytest

from fm_live_mcp import stats_archive as archive
from test_database import database_memory
from test_players import memory
from test_world import world_memory


def raw_archive_record(value=0):
    return b'\0'+struct.pack('<ih', 0, 0)+bytes([value])*25+bytes(136)


@pytest.fixture
def archive_memory(database_memory, tmp_path, monkeypatch):
    m = database_memory
    base = m['base']
    for rva, data in archive.NATIVE_SPANS.items():
        m['put'](base+rva, bytes.fromhex(data))
    m['q'](m['tables'][2]+0x2B0, base+0xCA4794)
    m['put'](m['tables'][2]-0x2C0, struct.pack('<q', -0x110))
    history_index_address = 0x1000+0x388-0x110+0xBC
    m['put'](history_index_address, struct.pack('<i', 0))
    manager, info = m['allocate'](0x28), m['allocate'](16)
    rva, name = archive.MANAGER_TYPE
    text = m['allocate'](len(name)+1)
    m['put'](text, name+b'\0')
    m['q'](info+8, text)
    m['put'](base+rva-16, struct.pack('<qQ', 0, info))
    m['q'](manager, base+rva)
    m['q'](base+archive.MANAGER_ROOT, manager)
    pair, disk = m['allocate'](24), m['allocate'](0xA8)
    m['q'](manager+0x20, pair)
    m['q'](pair, disk)
    for offset, tag in ((8, 'player_stats_hist_id'), (16, 'player_stats_hist_dt'), (24, 'player_stats_hist_ls')):
        m['q'](disk+offset, m['text'](tag))
    m['put'](disk+0x9C, struct.pack('<iH', archive.RECORD_WIDTH, archive.VERSION))
    m['put'](disk+0x98, struct.pack('<i', 336))
    m['put'](disk+0xA5, b'\1')
    stream, underlying, owner, darwin_file = (m['allocate'](0x38), m['allocate'](0x20),
                                            m['allocate'](0x20), m['allocate'](0x20))
    m['q'](disk+0x50, stream)
    m['q'](stream, base+archive.STREAM_TABLE)
    m['q'](base+archive.STREAM_TABLE+0x10, base+0x437F014)
    m['q'](base+archive.STREAM_TABLE+0x20, base+0x437F078)
    m['put'](stream+12, b'\2')
    m['q'](stream+0x18, underlying)
    m['q'](stream+0x20, 8)
    m['put'](stream+0x28, struct.pack('<q', -1))
    m['q'](underlying, base+archive.FILE_STREAM_TABLE)
    m['q'](underlying+0x18, owner)
    m['q'](owner+8, darwin_file)
    m['put'](darwin_file+0x12, struct.pack('<h', 62))
    m['put'](base+0x56D2C98, b'\0')
    m['put'](base+0x56D3522, b'\0\0')
    index_header = m['allocate'](24)
    m['put'](disk+0x78, struct.pack('<QQQ', index_header, index_header+24, index_header+24))
    offsets = [0, 168, -1, -2, 0]
    offsets_address = m['allocate'](len(offsets)*4)
    m['put'](offsets_address, struct.pack('<5i', *offsets))
    m['put'](index_header, struct.pack('<QQQ', offsets_address, offsets_address+20, offsets_address+20))
    archive_file = tmp_path/'player_stats_hist_dt.cmt'
    archive_file.write_bytes(archive.HEADER+raw_archive_record()+raw_archive_record(1))
    original_stat = archive_file.stat()
    binding = (archive_file, original_stat.st_dev, original_stat.st_ino)
    monkeypatch.setattr(archive, '_active_file', lambda pid, descriptor: binding)
    m.update(archive_file=archive_file, archive_disk=disk, archive_stream=stream,
             archive_offset_header=index_header, archive_offsets=offsets_address,
             source_pair=pair, darwin_file=darwin_file, game_descriptor=62,
             history_index_address=history_index_address, archive_manager=manager,
             descriptor_binding=binding)
    return m


def open_archive(m):
    return archive.open_player_archive(m['read'], m['base'], 0x1000, m['tables'], 99)


def test_complete_index_order_duplicates_and_all_negative_skips(archive_memory):
    m = archive_memory
    with open_archive(m) as result:
        assert result['state'] == 'decoded' and result['native_entry_count'] == 5
        assert [r['native_offset'] for r in result['records']] == [0, 168, 0]
        assert [r['native_offset'] for r in result['skipped_entries']] == [-1, -2]
        assert [r['entry_index'] for r in result['skipped_entries']] == [2, 3]
        assert all(r['reason'] == 'native_negative_offset_skipped' for r in result['skipped_entries'])
        assert all(len(r['raw']) == 168 for r in result['records'])
        assert 'path' not in result and 'address' not in result


def test_empty_index_is_decoded_with_validated_file(archive_memory):
    m = archive_memory
    m['put'](m['archive_offset_header'], bytes(24))
    with open_archive(m) as result:
        assert result['state'] == 'decoded' and result['native_entry_count'] == 0
        assert result['records'] == [] and result['skipped_entries'] == []


def test_supplementary_cache_does_not_change_native_disk_selection(archive_memory):
    m = archive_memory
    m['q'](m['source_pair']+16, m['allocate'](0x70))
    with open_archive(m) as result:
        assert result['state'] == 'decoded'
        assert result['encoding']['supplementary_cache_present'] is True
        assert len(result['records']) == 3


@pytest.mark.parametrize('index', [-1, -2, -2147483648])
def test_native_negative_history_index_is_explicit_no_index(archive_memory, index):
    m = archive_memory
    m['put'](m['history_index_address'], struct.pack('<i', index))
    with open_archive(m) as result:
        assert result['state'] == 'no_history_index' and result['native_entry_count'] == 0


@pytest.mark.parametrize('fault,reason', [
    ('manager', 'no_player_statistics_manager'), ('pair', 'no_archive_source_pair'),
    ('disk', 'no_disk_archive_source'), ('resident', 'native_resident_source_not_decoded'),
    ('stream', 'disk_stream_not_resident'), ('version', 'unsupported_archive_width_or_version'),
    ('width', 'unsupported_archive_width_or_version'),
    ('flags', 'unsupported_archive_reference_or_stride_encoding'),
    ('mode', 'unsupported_archive_reference_or_stride_encoding'),
    ('switch', 'unsupported_archive_reference_or_stride_encoding'),
    ('stride', 'unsupported_archive_reference_or_stride_encoding')])
def test_unavailable_sources_never_look_empty(archive_memory, fault, reason):
    m = archive_memory
    if fault == 'manager': m['q'](m['base']+archive.MANAGER_ROOT, 0)
    elif fault == 'pair': m['q'](m['archive_manager']+0x20, 0)
    elif fault == 'disk': m['q'](m['source_pair'], 0)
    elif fault == 'resident': m['q'](m['source_pair']+8, m['allocate'](24))
    elif fault == 'stream': m['q'](m['archive_disk']+0x50, 0)
    elif fault == 'version': m['put'](m['archive_disk']+0xA0, struct.pack('<H', 8))
    elif fault == 'width': m['put'](m['archive_disk']+0x9C, struct.pack('<i', 172))
    elif fault == 'flags': m['put'](m['archive_stream']+12, b'\0')
    elif fault == 'mode': m['put'](m['base']+0x56D2C98, b'\1')
    elif fault == 'switch': m['put'](m['base']+0x56D3522, b'\1')
    elif fault == 'stride': m['put'](m['archive_disk']+0xA5, b'\0')
    with open_archive(m) as result:
        assert result['state'] == 'unavailable' and result['reason'] == reason
        assert result['native_entry_count'] is None and result['records'] == []


@pytest.mark.parametrize('fault', ['virtual', 'person', 'getter', 'common', 'owner_index',
    'manager_type', 'tag', 'stream_type', 'origin', 'closed', 'index_bounds',
    'offset_bounds', 'index_outside', 'unaligned', 'truncation', 'header', 'team_tag', 'extension', 'native'])
def test_bad_binding_or_record_never_yields_partial_data(archive_memory, fault):
    m = archive_memory
    if fault == 'virtual': m['q'](0x1000, 0)
    elif fault == 'person': m['q'](0x1388, 0)
    elif fault == 'getter': m['q'](m['tables'][2]+0x2B0, 0)
    elif fault == 'common': m['put'](m['tables'][2]-0x2C0, struct.pack('<q', 0))
    elif fault == 'owner_index': m['put'](0x1390, bytes.fromhex('ffffffff'))
    elif fault == 'manager_type': m['q'](m['archive_manager'], 0)
    elif fault == 'tag': m['q'](m['archive_disk']+8, m['text']('wrong'))
    elif fault == 'stream_type': m['q'](m['archive_stream'], 0)
    elif fault == 'origin': m['q'](m['archive_stream']+0x20, 0)
    elif fault == 'closed': m['put'](m['darwin_file']+0x12, struct.pack('<h', -1))
    elif fault == 'index_bounds': m['q'](m['archive_disk']+0x80, 1)
    elif fault == 'offset_bounds': m['q'](m['archive_offset_header']+16, m['archive_offsets']+4*4097)
    elif fault == 'index_outside': m['put'](m['history_index_address'], struct.pack('<i', 1))
    elif fault == 'unaligned': m['put'](m['archive_offsets'], struct.pack('<i', 1))
    elif fault == 'truncation': m['archive_file'].write_bytes(archive.HEADER+bytes(167))
    elif fault in ('header', 'team_tag', 'extension'):
        data = bytearray(m['archive_file'].read_bytes())
        if fault == 'header': data[0] = 9
        elif fault == 'team_tag': data[8] = 1
        else: data[13:15] = struct.pack('<h', -2)
        m['archive_file'].write_bytes(data)
    elif fault == 'native': m['put'](m['base']+0x11EE748, bytes(4))
    with pytest.raises(ValueError):
        with open_archive(m): pytest.fail('Yielded partial data')


@pytest.mark.parametrize('mutation', ['bytes', 'truncate', 'path', 'memory', 'fd'])
def test_post_yield_revalidation_rejects_changes(archive_memory, mutation, monkeypatch):
    m = archive_memory
    with pytest.raises(ValueError):
        with open_archive(m):
            if mutation == 'bytes':
                with m['archive_file'].open('r+b') as stream:
                    stream.seek(20)
                    stream.write(b'\x07')
            elif mutation == 'truncate': m['archive_file'].write_bytes(archive.HEADER)
            elif mutation == 'path':
                m['archive_file'].rename(m['archive_file'].with_suffix('.old'))
                m['archive_file'].write_bytes(archive.HEADER+bytes(336))
            elif mutation == 'memory': m['q'](m['source_pair'], 0)
            else: monkeypatch.setattr(archive, '_active_file', lambda *a: (m['archive_file'], 99, 99))


def test_decoder_exception_preserved_and_owned_descriptor_closed(archive_memory, monkeypatch):
    closed = []
    original = os.close
    def close(fd):
        closed.append(fd)
        original(fd)
    monkeypatch.setattr(archive.os, 'close', close)
    error = OSError('decoder failure')
    with pytest.raises(OSError) as caught:
        with open_archive(archive_memory): raise error
    assert caught.value is error and len(closed) == 1
    with pytest.raises(OSError): os.fstat(closed[0])


def test_consumed_bytes_rechecked_even_if_metadata_is_stable(archive_memory, monkeypatch):
    m = archive_memory
    real = os.pread
    reads = 0
    def pread(fd, count, offset):
        nonlocal reads
        reads += 1
        raw = real(fd, count, offset)
        return bytes([raw[0]^1])+raw[1:] if reads > 4 and raw else raw
    monkeypatch.setattr(archive.os, 'pread', pread)
    with pytest.raises(ValueError, match='Consumed'):
        with open_archive(m): pass


def test_native_stream_bound_precedes_larger_file_extent(archive_memory):
    m = archive_memory
    m['put'](m['archive_disk']+0x98, struct.pack('<i', 1))
    with pytest.raises(ValueError):
        with open_archive(m): pytest.fail('Accepted a row beyond native size bound')
    m['put'](m['archive_disk']+0x98, bytes(4))
    with open_archive(m) as result:
        assert result['state'] == 'unavailable' and result['native_entry_count'] is None
        assert result['reason'] == 'native_stream_size_not_materialized'


def test_native_segment_limit_precedes_larger_file_extent(archive_memory):
    m = archive_memory
    m['put'](m['archive_stream']+0x28, struct.pack('<q', 168))
    with pytest.raises(ValueError):
        with open_archive(m): pytest.fail('Accepted data outside native segment')


@pytest.mark.parametrize('output', [
    'p99\nf62\nD0x1\ni42\nn/tmp/player_stats_hist_dt.cmt\n',
    'p99\nf62\nD0x1\ni42\nn/tmp/other.cmt\n',
    'p99\nf62\nD0x1\ni42\nn/tmp/player_stats_hist_dt.cmt\nn/duplicate\n'])
def test_bounded_descriptor_resolver(monkeypatch, output):
    def run(args, **kwargs):
        assert args == ['lsof', '-a', '-p', '99', '-d', '62', '-FpfDin']
        assert kwargs['timeout'] == 3
        return subprocess.CompletedProcess(args, 0, output, '')
    monkeypatch.setattr(archive.subprocess, 'run', run)
    if output.count('\nn') == 1 and output.rstrip().endswith('player_stats_hist_dt.cmt'):
        assert archive._active_file(99, 62)[1:] == (1, 42)
    else:
        with pytest.raises(ValueError): archive._active_file(99, 62)
