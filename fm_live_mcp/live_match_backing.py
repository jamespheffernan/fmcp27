"""Selected current-session archived-match reads without game calls or cursor changes."""
from contextlib import ExitStack
from ._os_compat import change_time_ns, open_fd, pread, O_CLOEXEC, O_NOFOLLOW, O_NONBLOCK
import hashlib
import os
from pathlib import Path
import stat
import struct
import subprocess

from . import fixtures, players, world
from .fmdb import stdio_file
from .snapshot_catalog import _decompress

MAX_MATCHES = 100
MAX_PACKED = 2_000_000
MAX_RAW = 10_000_000


def _type(read, address, name):
    table = world.pointer(read, address)
    displacement, info = struct.unpack('<qQ', read(table-16, 16))
    text = players.u64(read(info+8, 8))
    if displacement or read(text, len(name)+1) != name+b'\0':
        raise ValueError('Unexpected live match backing type')


def _binding(pid, descriptor, ordinal):
    result = subprocess.run(['lsof', '-a', '-p', str(pid), '-d', str(descriptor), '-FpfDin'],
                            check=True, capture_output=True, text=True, timeout=5)
    if len(result.stdout) > 16384:
        raise ValueError('Live match descriptor listing exceeds bound')
    fields = {}
    for line in result.stdout.splitlines():
        if not line or line[0] not in 'pfDin' or line[0] in fields:
            raise ValueError('Ambiguous live match descriptor')
        fields[line[0]] = line[1:]
    path = Path(fields['n'])
    if (int(fields['p']) != pid or int(fields['f']) != descriptor
            or not path.is_absolute() or path.name != f'pks_{ordinal}.obs'):
        raise ValueError('Live match descriptor identity disagrees')
    return str(path), int(fields['D'], 16), int(fields['i'])


def _identity(s):
    return s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, change_time_ns(s)


def read_selected_matches(bridge, session_id, fixture_refs, *, include_players=True):
    """Return private raw bytes only after source, fixture and file rechecks pass."""
    if (not isinstance(fixture_refs, (list, tuple)) or not 1 <= len(fixture_refs) <= MAX_MATCHES
            or any(not isinstance(ref, str) or not ref for ref in fixture_refs)
            or len(set(fixture_refs)) != len(fixture_refs)):
        raise ValueError('Select one to 100 unique fixture references')
    with bridge.lock, bridge._read_scope(session_id), ExitStack() as stack:
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        read, save, _ = bridge._world_state(process, tables)
        base = tables[0]-players.RVA[0]
        if include_players:
            from .saved_match_player_dribbling import verify_native
            verify_native(read, base)
            from .saved_match_player_running import verify_native as verify_running_native
            verify_running_native(read, base)
            from .saved_match_player_sprinting import verify_native as verify_sprinting_native
            verify_sprinting_native(read, base)
            from .saved_match_player_final_third import verify_native as verify_final_third_native
            verify_final_third_native(read, base)
        _, years, catalog_identity = fixtures.catalog(read, base)
        selected = {}
        fixture_rows = {}
        event_arrays = {}
        for ref in fixture_refs:
            saved = bridge.fixture_refs.get(ref)
            if not saved or saved['tables'] != tables or saved['catalog_identity'] != catalog_identity:
                raise ValueError('Fixture reference identity expired')
            entries, route = fixtures.bucket(read, years[saved['year']], saved['day'], saved['group'])
            if (route != saved['route'] or not 0 <= saved['slot'] < len(entries)
                    or entries[saved['slot']] != saved['address']):
                raise ValueError('Fixture bucket membership changed')
            decoded = fixtures.record(read, base, saved['address'], saved['year'], saved['day'], {})
            if decoded['identity'] != saved['identity']:
                raise ValueError('Fixture identity changed')
            fixtures.typed(read, base, saved['address'], 'result')
            key = struct.unpack('<i', read(saved['address']+0x58, 4))[0]
            if key < 0 or key in selected:
                raise ValueError('Invalid or ambiguous match archive key')
            selected[key] = ref
            fixture_rows[key] = fixtures.detail(read, base, saved['address'], saved['year'],
                                                  saved['day'], decoded, {}, False)[0]
            array = players.u64(read(saved['address']+0x78, 8))
            event = dict(state='absent_array', count=None, rows=None)
            if array:
                if array < 4096 or array % 8:
                    raise ValueError('Invalid resident match event array')
                start, end, capacity = struct.unpack('<QQQ', read(array, 24))
                if (start, end, capacity) == (0, 0, 0):
                    event_raw = b''
                else:
                    if (not 4096 <= start <= end <= capacity or (end-start)%16
                            or (capacity-start)%16 or capacity-start > 512*16):
                        raise ValueError('Invalid resident match event bounds')
                    event_raw = read(start, end-start) if end > start else b''
                event_rows = []
                for index, values in enumerate(struct.iter_unpack('<iiIBBBB', event_raw)):
                    first, second, word, side, kind, byte14, byte15 = values
                    event_rows.append(dict(source_index=index, raw16_hex=event_raw[index*16:(index+1)*16].hex(),
                                           person_index=first, second_index_word=second, word8=word,
                                           side12=side, kind13=kind, byte14=byte14, byte15=byte15))
                event = dict(state='present_records' if event_rows else 'present_empty', count=len(event_rows),
                             rows=event_rows, raw_sha256=hashlib.sha256(event_raw).hexdigest())
            event_arrays[key] = event

        manager = world.pointer(read, base+0x56B5570)
        _type(read, manager, b'19MATCH_STATS_MANAGER')
        header = world.pointer(read, manager+0x20)
        wrappers = world.vector(read, header, 32)
        if len(wrappers) > 16:
            raise ValueError('Live match bank count exceeds bound')
        records = {}
        identity_people = {}
        identity_teams = {}
        checks = []
        scanned = 0
        total_raw = 0
        for ordinal, wrapper in enumerate(wrappers):
            store = world.pointer(read, wrapper)
            _type(read, store, b'N2db14OBJECT_STORAGEI20ARCHIVED_MATCH_STATSiEE')
            start, end, capacity = struct.unpack('<QQQ', read(store+0x30, 24))
            if (not 4096 <= start <= end <= capacity or (end-start)%8
                    or (capacity-start)%8 or capacity-start > 20000*8):
                raise ValueError('Invalid live match index bounds')
            hits = []
            for at in range(start, end, 8):
                entry = read(world.pointer(read, at), 20)
                scanned += 1
                if scanned > 40000:
                    raise ValueError('Live match index work budget exceeded')
                offset, length, key = struct.unpack_from('<iii', entry, 8)
                if key in selected:
                    if key in records or any(hit[0] == key for hit in hits):
                        raise ValueError('Duplicate live match archive key')
                    hits.append((key, offset, length))
            if not hits:
                continue
            stream = world.pointer(read, store+0x18)
            _type(read, stream, b'N6sicore20SEGMENT_INPUT_STREAME')
            origin, segment_length = struct.unpack('<Qq', read(stream+0x20, 16))
            if origin != 8 or segment_length < -1:
                raise ValueError('Unsupported live match segment bounds')
            underlying = world.pointer(read, stream+0x18)
            _type(read, underlying, b'N6sicore26FILE_INPUT_STREAM_TEMPLATEINS_17REFERENCE_COUNTERINS_17FILE_POINTER_LIBCEEEEE')
            owner = world.pointer(read, underlying+0x18)
            file_pointer = world.pointer(read, owner+8)
            descriptor = struct.unpack('<h', read(file_pointer+0x12, 2))[0]
            if descriptor < 0:
                raise ValueError('Live match descriptor is closed')
            binding = _binding(process.pid, descriptor, ordinal)
            path, device, inode = binding
            own = open_fd(path, os.O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOFOLLOW)
            stack.callback(os.close, own)
            initial = os.fstat(own)
            if not stat.S_ISREG(initial.st_mode) or (initial.st_dev, initial.st_ino) != (device, inode):
                raise ValueError('Live match bank file identity disagrees')
            magic = pread(own, 8, 0)
            if magic != bytes.fromhex('030173626f2e0100'):
                raise ValueError('Unsupported live match bank header')
            consumed = [(0, magic)]
            # Bytes the game has written to this bank's FILE and libc has not flushed are not in
            # the disk file this descriptor reads, or stand over older ones. The game would read
            # the disk file with them laid over at its descriptor's file offset (fmdb/stdio_file).
            # The FILE and its buffer are read through `read`, so read.verify() rechecks them;
            # the offset is rechecked below. Data that cannot be placed is left out, as before.
            position = stdio_file.fd_position(process.pid)
            try:
                unflushed = stdio_file.unflushed_write(read, read, position, file_pointer)
            except stdio_file.NotPlaced:
                unflushed = None
            except stdio_file.Moved:
                raise ValueError('Live match bank changed during capture') from None
            where = position(descriptor) if unflushed is not None else None
            for key, offset, length in hits:
                if (offset < 0 or not 0 < length <= MAX_PACKED
                        or origin+offset+length > stdio_file.size_with(initial.st_size, unflushed)
                        or (segment_length != -1 and offset+length > segment_length)):
                    raise ValueError('Invalid live match selected frame bounds')
                packed = stdio_file.lay_over(pread(own, length, origin+offset), origin+offset, length,
                                             initial.st_size, unflushed)
                if len(packed) != length or packed[:4] != bytes.fromhex('28b52ffd'):
                    raise ValueError('Invalid live match compressed frame')
                raw = _decompress(packed, MAX_RAW)
                from .live_match_players import decode_retained_players
                from .live_match_identities import resolve
                identities = None
                if include_players:
                    player_rows = decode_retained_players(raw, key)
                    person_indices = {row['person_index_word'] for row in player_rows if row['person_index_word'] >= 0}
                    team_indices = {row['team_index_word'] for row in player_rows if row['team_index_word'] >= 0}
                    fresh = resolve(read, base, person_indices - identity_people.keys(), team_indices - identity_teams.keys())
                    identity_people.update(fresh['people'])
                    identity_teams.update(fresh['teams'])
                    identities = dict(people={index:identity_people[index] for index in person_indices},
                                      teams={index:identity_teams[index] for index in team_indices})
                total_raw += len(raw)
                if total_raw > 64_000_000:
                    raise ValueError('Live match decoded byte budget exceeded')
                records[key] = dict(fixture_ref=selected[key], fixture_native=fixture_rows[key], event_array=event_arrays[key], identities=identities, key=key, state='available', raw=raw,
                    packed_sha256=hashlib.sha256(packed).hexdigest(), raw_sha256=hashlib.sha256(raw).hexdigest(),
                    source=dict(path=path, device=device, inode=inode, fd=descriptor, bank=ordinal,
                                origin=origin, offset=offset, length=length, raw_length=len(raw)))
                consumed.append((origin+offset, packed))
            checks.append((ordinal, descriptor, binding, own, initial, consumed, unflushed, where, position))
        read.verify()
        bridge._current(session_id)
        for ordinal, descriptor, binding, own, initial, consumed, unflushed, where, position in checks:
            if (_binding(process.pid, descriptor, ordinal) != binding
                    or _identity(os.fstat(own)) != _identity(initial)
                    or _identity(Path(binding[0]).stat(follow_symlinks=False)) != _identity(initial)):
                raise ValueError('Live match bank identity changed during capture')
            if unflushed is not None and position(descriptor) != where:
                raise ValueError('Live match bank changed during capture')
            for offset, raw in consumed:
                if stdio_file.lay_over(pread(own, len(raw), offset), offset, len(raw), initial.st_size,
                                       unflushed) != raw:
                    raise ValueError('Live match selected bytes changed during capture')
            if _identity(os.fstat(own)) != _identity(initial):
                raise ValueError('Live match bank changed during verification')
        read.verify()
        bridge._current(session_id)
        return dict(save=bridge._public_save(save), source_kind='running_session_active_fd',
                    records=[records.get(key, dict(fixture_ref=ref, fixture_native=fixture_rows[key], event_array=event_arrays[key], key=key, state='not_in_active_match_banks', raw=None))
                             for key, ref in selected.items()], scanned_indices=scanned,
                    native_functions_executed=False, game_stream_cursor_modified=False,
                    save_identity='native_binding_rechecked')
