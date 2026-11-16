"""Save-wide match data: every resident fixture result, its stored goal events, and the
archived match-statistics frames the game keeps for recent matches.

Routes (all read-only; nothing runs in the game process):

* Results: the fixture manager's year managers (`fixtures.catalog`) hold FIXTURE_RESULT
  records (vtable 0x5672E00) in day buckets. Each record is decoded by the hand-built
  `fixtures.record` (typed teams, fixture name -> competition, stadium) plus the virtual
  getters of FIXTURE_RESULT read directly: slot 3 `+0x58` match key, slots 6/7 `+0x64` score
  block (5 bytes per side), slot 13 `+0x5c` and slot 14 `+0x60` (attendance; see below),
  slot 20 `+0x78` scoring-event vector.
* Attendance: MATCH_STATS_UI_HANDLER::get_property (0x26A17C) answers `AnnouncedAttendance`
  ('02WP') with MATCH_STATS +0x8 + +0x14 and `AwayAttendance` ('iOYC') with +0x10. The same
  values are stored on the result at +0x5c / +0x60; `validate_attendance` checks the equality
  on every archived frame.
* Goal events: 16-byte records `<i person, i second person, u32 word, u8 side, u8 kind,
  u8 minute, u8 added>` (hand-built reader `live_match_backing`; scoring kinds 0,1,2 and
  player credit kinds 0,2 from the B129 policy, native producer 0x2E552AC).
* Archived match statistics: MATCH_STATS_MANAGER (global 0x56B5570) +0x20 lists the banks
  (OBJECT_STORAGE<ARCHIVED_MATCH_STATS>, one per `Temporary/pks_N.obs` file). Each index entry
  is `(offset, length, key)`; the frame is a zstd MATCH_STATS60/FIXTURE31 stream decoded by the
  hand-built wire readers (`live_match_players`, `live_match_team_totals`, `saved_match_player_*`).
"""
from __future__ import annotations

from collections import defaultdict
from .._os_compat import O_CLOEXEC, open_fd, pread
from datetime import date, timedelta
import os
import struct
import time

from .. import fixtures, players, world

RESULT_VTABLE = 0x5672E00
FIXTURE_VTABLE = 0x5672C88
STATS_MANAGER = 0x56B5570
RECORD_BYTES = 0x88
MAX_FRAME_PACKED = 2_000_000
MAX_FRAME_RAW = 10_000_000

# Result event kind codes. Scoring kinds 0,1,2 and player-credit kinds 0,2 come from the B129
# policy (native producer 0x2E552AC); every label is inferred from the save (2026-11-11):
# kinds 0+1+2 per side equal the stored score in 74,862 of 74,864 results with a vector; kind 1
# is the scoring kind not credited to the player; kind 2 is followed by no assist; kinds 4 and 5
# occur only in matches with a shoot-out, at minute 120, and kind 4 per side equals the stored
# shoot-out score in 1,144 of 1,157 shoot-outs; kind 3 is a penalty taken in play that did not
# score (same taker scores with kind 2 elsewhere; never counted in the score).
EVENT_KINDS = {0: 'goal (inferred)', 1: 'own goal (inferred)', 2: 'penalty goal (inferred)',
               3: 'penalty missed (inferred)', 4: 'shoot-out penalty scored (inferred)',
               5: 'shoot-out penalty missed (inferred)'}


class _BlockReader:
    """`read(address, n)` served from prefetched record blocks, else from the engine.

    Other reads are memoised for the life of the reader (one decoding pass): the hand-built
    `fixtures.record` re-proves the record type, re-reads the database table headers and the
    RTTI strings for every record, which cost 665,000 single reads (43 of 53 s) for 134,105
    results. Every check still runs; it reads the same bytes from the memo."""

    def __init__(self, engine, memo=True):
        self.engine = engine
        self.blocks = {}
        self.memo = {} if memo else None

    def load(self, addresses, length=RECORD_BYTES, chunk=4096):
        self.load_ranges([(a, length) for a in addresses], chunk)

    def load_ranges(self, requests, chunk=4096):
        requests = [r for r in dict.fromkeys(requests) if r[0] not in self.blocks]
        for at in range(0, len(requests), chunk):
            part = requests[at:at + chunk]
            for (a, _), data in zip(part, self.engine.read_many(part)):
                if data is not None:
                    self.blocks[a] = data

    def __call__(self, address, length):
        data = self.blocks.get(address)
        if data is not None and length <= len(data):
            return data[:length]
        if self.memo is None:
            return self.engine.read(address, length)
        key = (address, length)
        got = self.memo.get(key)
        if got is None:
            got = self.memo[key] = self.engine.read(address, length)
        return got


def _u64s(data):
    return struct.unpack(f'<{len(data) // 8}Q', data)


def result_addresses(engine):
    """[(year, day, group, slot, address)] for every FIXTURE_RESULT in a materialized group, and
    the year coverage rows from `fixtures.catalog`."""
    read, base = engine.read, engine.base
    info, years, _ = fixtures.catalog(read, base)
    found = []
    for year, binding in years.items():
        heads = []
        for g, group in enumerate(binding['groups']):
            if not binding['flags'][g] & 1:
                continue
            for day, header in enumerate(_u64s(read(group, 366 * 8)), start=1):
                if header:
                    heads.append((day, g, header))
        vecs = engine.read_many([(h, 24) for _, _, h in heads])
        spans = []
        for (day, g, _), v in zip(heads, vecs):
            start, end, _cap = struct.unpack('<QQQ', v)
            if end > start:
                spans.append((day, g, start, (end - start) // 8))
        datas = engine.read_many([(s, n * 8) for _, _, s, n in spans])
        candidates = []
        for (day, g, _, n), data in zip(spans, datas):
            for slot, a in enumerate(_u64s(data)):
                candidates.append((year, day, g, slot, a))
        vts = engine.read_many([(c[4], 8) for c in candidates])
        for c, vt in zip(candidates, vts):
            if struct.unpack('<Q', vt)[0] == base + RESULT_VTABLE:
                found.append(c)
    return found, info


def _score(raw, offset):
    return None if raw[offset] == 255 else raw[offset]


def iso_date(year, day):
    return (date(year, 1, 1) + timedelta(days=day - 1)).isoformat()


def result_index(engine, addresses=None):
    """Light index of every resident result, without the record decode: [{address, year_bucket,
    day, group, slot, date, native_match_key, home/away team address, index word and native id,
    events_pointer}]. The team index words are read from the team records (+8) and are proved
    by `results` (fixtures.record checks table membership) before any row is published.

    About 2.5 s for 134,105 results (one batched read of the records and of each distinct team)."""
    if addresses is None:
        addresses, _ = result_addresses(engine)
    raws = []
    for at in range(0, len(addresses), 4096):
        raws += engine.read_many([(a[4], RECORD_BYTES) for a in addresses[at:at + 4096]])
    teams = sorted({t for raw in raws if raw for t in struct.unpack_from('<QQ', raw, 8)} - {0})
    words = {}
    for at in range(0, len(teams), 4096):
        part = teams[at:at + 4096]
        for t, data in zip(part, engine.read_many([(t, 16) for t in part])):
            if data:
                words[t] = struct.unpack_from('<II', data, 8)
    out = []
    for (year, day, group, slot, address), raw in zip(addresses, raws):
        if not raw:
            continue
        home, away = struct.unpack_from('<QQ', raw, 8)
        h, a = words.get(home, (None, None)), words.get(away, (None, None))
        out.append({'address': address, 'year_bucket': year, 'day': day, 'group': group, 'slot': slot,
                    'date': iso_date(year, day), 'native_match_key': struct.unpack_from('<i', raw, 0x58)[0],
                    'home_team_address': home, 'away_team_address': away,
                    'home_team_idx': h[0] if home else None, 'home_team_id': h[1] if home else None,
                    'away_team_idx': a[0] if away else None, 'away_team_id': a[1] if away else None,
                    'events_pointer': struct.unpack_from('<Q', raw, 0x78)[0]})
    return out


def results(engine, log=None, addresses=None):
    """Decoded rows for every resident fixture result (see module docstring), or for the
    `addresses` given ((year, day, group, slot, address) tuples, e.g. from `result_index`)."""
    log = log or (lambda m: None)
    started = time.time()
    if addresses is None:
        addresses, coverage = result_addresses(engine)
    else:
        coverage = None
    reader = _BlockReader(engine)
    reader.load([a for *_, a in addresses])
    links = set()
    for *_, a in addresses:
        raw = reader.blocks.get(a)
        if raw:
            home, away, name, stadium = struct.unpack_from('<QQQQ', raw, 8)
            links.update(((home, 20), (away, 20), (name, 8), (name + 8, 64), (stadium, 8), (stadium + 8, 12)))
    reader.load_ranges(sorted(r for r in links if r[0] >= 4096))
    cache, rows = {}, []
    base = engine.base
    for year, day, group, slot, address in addresses:
        decoded = fixtures.record(reader, base, address, year, day, cache)
        raw = reader(address, RECORD_BYTES)
        key, attendance, away_attendance = struct.unpack_from('<iii', raw, 0x58)
        block = raw[0x64:0x6e]
        team_ids = decoded['team_ids']
        comp = decoded['competition'] or {}
        stadium = decoded['stadium_binding'] or {}
        name = decoded['name_identity']
        kick = decoded['kickoff_time']
        scores = {label: (_score(block, i), _score(block, 5 + i))
                  for i, label in enumerate(('normal', 'extra', 'penalties', 'aggregate'))}
        final = tuple(scores['extra'][s] if scores['extra'][s] is not None else scores['normal'][s] for s in (0, 1))
        rows.append({
            'year_bucket': year, 'day': day, 'group': group, 'slot': slot, 'address': address,
            'date': (date(year, 1, 1) + timedelta(days=day - 1)).isoformat(),
            'kickoff_time': kick['time'], 'native_match_key': key,
            'competition_idx': comp.get('database_index'), 'competition_id': comp.get('native_id'),
            'competition_name': comp.get('name'),
            'fixture_name_idx': name[1] if name else None,
            'season_code': decoded['season_code'], 'stage_index': decoded['stage_index'],
            'home_team_idx': team_ids[0][0] if team_ids[0] else None,
            'home_team_id': team_ids[0][1] if team_ids[0] else None,
            'away_team_idx': team_ids[1][0] if team_ids[1] else None,
            'away_team_id': team_ids[1][1] if team_ids[1] else None,
            'stadium_idx': stadium.get('database_index'),
            'home_goals': final[0], 'away_goals': final[1],
            'home_goals_normal': scores['normal'][0], 'away_goals_normal': scores['normal'][1],
            'home_goals_extra': scores['extra'][0], 'away_goals_extra': scores['extra'][1],
            'home_penalties': scores['penalties'][0], 'away_penalties': scores['penalties'][1],
            'home_aggregate': scores['aggregate'][0], 'away_aggregate': scores['aggregate'][1],
            'attendance': attendance, 'away_attendance': away_attendance,
            'events_pointer': struct.unpack_from('<Q', raw, 0x78)[0],
        })
    log(f'match results: {len(rows)} in {time.time() - started:.1f}s')
    return rows, coverage


def goal_events(engine, rows):
    """{row index: (state, [event dicts])} from each result's +0x78 vector."""
    out = {}
    with_ptr = [(i, r['events_pointer']) for i, r in enumerate(rows) if r['events_pointer']]
    for i, r in enumerate(rows):
        if not r['events_pointer']:
            out[i] = ('absent', [])
    heads = engine.read_many([(p, 24) for _, p in with_ptr])
    spans = []
    for (i, _), h in zip(with_ptr, heads):
        start, end, cap = struct.unpack('<QQQ', h)
        if start == end:
            out[i] = ('empty', [])
        elif start < 4096 or end < start or (end - start) % 16 or end - start > 512 * 16:
            out[i] = ('invalid', [])
        else:
            spans.append((i, start, end - start))
    datas = engine.read_many([(s, n) for _, s, n in spans])
    for (i, _, _), data in zip(spans, datas):
        events = []
        for seq, (person, second, word, side, kind, minute, added) in enumerate(struct.iter_unpack('<iiIBBBB', data)):
            events.append({'seq': seq, 'person_idx': person, 'second_person_idx': second, 'word8': word,
                           'side': side, 'kind': kind, 'minute': minute, 'added_minute': added})
        out[i] = ('present', events)
    return out


# --------------------------------------------------------------------------- archived frames
def _type_name(read, address):
    table = world.pointer(read, address)
    _disp, info = struct.unpack('<qQ', read(table - 16, 16))
    text = players.u64(read(info + 8, 8))
    return read(text, 96).split(b'\0', 1)[0]


def _unflushed(engine, fp):
    """((file offset, bytes) | None, why not) of what the game has written to a bank's FILE and
    libc has not flushed (stdio_file.unflushed_write: the game's own FILE and buffer, read twice,
    and the kernel's offset of the game's descriptor). The readers here pread the disk file from
    a descriptor of their own, so those bytes are missing there or stand over older ones; the
    game itself would read the disk file with them laid over at that offset."""
    from . import stdio_file
    from .memory import MemoryReadError
    pid = getattr(engine, 'pid', None)
    if pid is None:
        return None, None
    try:
        return stdio_file.unflushed_write(engine.read, engine.read, stdio_file.fd_position(pid), fp), None
    except stdio_file.NotPlaced as refused:
        return None, refused.reason
    except (stdio_file.Moved, MemoryReadError):
        return None, stdio_file.FILE_MOVED


def _frame_bytes(fd, bank, offset, length):
    """The packed bytes of one index entry as the game would read them, or None when they do not
    lie inside the file (the disk file with the bank's unflushed write laid over it)."""
    from . import stdio_file
    unflushed = bank.get('unflushed')
    disk = os.fstat(fd).st_size
    at = bank['origin'] + offset
    if offset < 0 or not 0 < length <= MAX_FRAME_PACKED or at + length > stdio_file.size_with(disk, unflushed):
        return None
    packed = stdio_file.lay_over(pread(fd, length, at), at, length, disk, unflushed)
    return packed if len(packed) == length and packed[:4] == bytes.fromhex('28b52ffd') else None


def _unreadable(bank):
    """Why a frame of this bank could not be read."""
    why = bank.get('unflushed_refused')
    return f'frame bounds or header invalid ({why})' if why else 'frame bounds or header invalid'


def banks(engine):
    """[{ordinal, path, origin, segment_length, entries: [(key, offset, length)], unflushed,
    unflushed_refused}]: `unflushed` is the bank FILE's unflushed write data ((file offset, bytes)
    or None), `unflushed_refused` why such data could not be placed (`_unflushed`)."""
    from ..live_match_backing import _binding
    read, base = engine.read, engine.base
    manager = world.pointer(read, base + STATS_MANAGER)
    if _type_name(read, manager) != b'19MATCH_STATS_MANAGER':
        raise ValueError('MATCH_STATS_MANAGER type changed')
    wrappers = world.vector(read, world.pointer(read, manager + 0x20), 32)
    out = []
    for ordinal, wrapper in enumerate(wrappers):
        store = world.pointer(read, wrapper)
        if _type_name(read, store) != b'N2db14OBJECT_STORAGEI20ARCHIVED_MATCH_STATSiEE':
            raise ValueError('Archived match bank type changed')
        start, end, cap = struct.unpack('<QQQ', read(store + 0x30, 24))
        if not 4096 <= start <= end <= cap or (end - start) % 8 or end - start > 20000 * 8:
            raise ValueError('Invalid archived match index bounds')
        ptrs = _u64s(read(start, end - start)) if end > start else ()
        entries = []
        for data in engine.read_many([(p, 20) for p in ptrs]):
            offset, length, key = struct.unpack_from('<iii', data, 8)
            entries.append((key, offset, length))
        stream = world.pointer(read, store + 0x18)
        origin, seglen = struct.unpack('<Qq', read(stream + 0x20, 16))
        underlying = world.pointer(read, stream + 0x18)
        owner = world.pointer(read, underlying + 0x18)
        fp = world.pointer(read, owner + 8)
        fd = struct.unpack('<h', read(fp + 0x12, 2))[0]
        path = _binding(engine.pid, fd, ordinal)[0] if fd >= 0 else None
        unflushed, refused = _unflushed(engine, fp) if path else (None, None)
        out.append({'ordinal': ordinal, 'path': path, 'origin': origin, 'segment_length': seglen,
                    'entries': entries, 'unflushed': unflushed, 'unflushed_refused': refused})
    return out


def read_frames(bank, keys=None):
    """Yield (key, raw frame) for a bank's entries (optionally only `keys`)."""
    from ..snapshot_catalog import _decompress
    if not bank['path']:
        return
    fd = open_fd(bank['path'], os.O_RDONLY | O_CLOEXEC)
    try:
        for key, offset, length in bank['entries']:
            if keys is not None and key not in keys:
                continue
            packed = _frame_bytes(fd, bank, offset, length)
            if packed is None:
                yield key, None
                continue
            try:
                yield key, _decompress(packed, MAX_FRAME_RAW)
            except ValueError:          # one frame the game is still writing must not fail the table
                yield key, None
    finally:
        os.close(fd)


def _decoders():
    from .. import (saved_match_player_actions as a, saved_match_player_defensive as d,
                    saved_match_player_crosses as c, saved_match_player_keeper as k,
                    saved_match_player_recoveries as r, saved_match_player_progression as p,
                    saved_match_player_dribbling as dr, saved_match_player_running as ru,
                    saved_match_player_sprinting as sp, saved_match_player_final_third as ft,
                    saved_match_player_free_kicks as fk)
    return ((a.decode_player_actions, a.field_registry), (d.decode_player_defensive, d.field_registry),
            (c.decode_player_crosses, c.cross_field_registry), (k.decode_player_keeper, k.field_registry),
            (r.decode_player_recoveries, r.recovery_field_registry),
            (p.decode_player_progression, p.progression_field_registry),
            (dr.decode_player_dribbling, dr.dribbling_field_registry),
            (ru.decode_player_running, ru.running_field_registry),
            (sp.decode_player_sprinting, sp.sprinting_field_registry),
            (ft.decode_player_final_third, ft.final_third_field_registry),
            (fk.decode_player_free_kicks, fk.free_kick_field_registry))


def stat_registry():
    """{field: registry entry} for every per-player statistic the hand-built decoders produce."""
    out = {}
    for _, registry in _decoders():
        out.update(registry())
    return out


# Decode levels of a frame, cheapest first (measured on 4,771 frames, load ~20: about 18 ms a
# frame in full, 87 s in all; the 11 counter decoders are 55 % of it, the player projection 35 %,
# the team totals 15 %; decompressing 6 %).
#   header    teams, stadium, referee, end clock (binding a frame to its result; `match`)
#   players   + the player projection (minutes, rating, on/off, cards; `match_event`)
#   totals    + the team totals (`match_team_stats`, `match_shot`)
#   full      + the 11 per-player counter decoders (`match_player_stats`, `match_pass`)
LEVELS = ('header', 'players', 'totals', 'full')


def decode_header(raw):
    from .. import saved_match_statistics_wire as wire
    prefix = wire.fixture_prefix(raw)
    fixture = wire.continue_fixture(raw, prefix['end'], wire.parse_person, wire.fixture_extra)
    stats = wire.stats_prefix(raw, fixture['end'])
    official = fixture['fields'].get('first_person') or {}
    refs = official.get('references_in_wire_order') or []
    names = official.get('stored_strings_in_wire_order') or []
    return {
        'stats_8_18': stats['fields']['stats_8_18_u32'], 'end_clock': stats['fields']['ac'],
        'teams': [t['index_word'] for t in prefix['fixture_fields8_10_team_references']],
        'stadium_idx': prefix['fixture_field28_stadium_reference']['index_word'],
        'official_person_idx': refs[0]['raw_word'] if refs else None,
        'official_name': ' '.join(n for n in names[:2] if n) or None,
    }


def decode_frame(raw, key, level='full'):
    """(frame header, team totals, player rows) of one MATCH_STATS60/FIXTURE31 frame, decoded to
    `level` (LEVELS); parts below the level are None."""
    rank = LEVELS.index(level)
    header = decode_header(raw)
    totals = rows = None
    if rank >= 2:
        from ..live_match_team_totals import decode_team_totals
        totals = decode_team_totals(raw)
    if rank >= 1:
        from ..live_match_players import decode_retained_players
        rows = decode_retained_players(raw, key)
    if rank >= 3:
        decoders = _decoders()
        for row in rows:
            child = bytes.fromhex(row['raw_child_hex'])
            for decode, _ in decoders:
                row.update(decode(child))
    return header, totals, rows


def decode_entries(bank_list, entries, level='full'):
    """Yield ((bank ordinal, key, offset, length), header, totals, rows, error) for the given
    index entries of the banks, decoded to `level`."""
    from ..snapshot_catalog import _decompress
    by_bank = defaultdict(list)
    for entry in entries:
        by_bank[entry[0]].append(entry)
    for bank in bank_list:
        wanted = by_bank.get(bank['ordinal'])
        if not wanted:
            continue
        if not bank['path']:
            for entry in wanted:
                yield entry, None, None, None, 'bank file not bound'
            continue
        fd = open_fd(bank['path'], os.O_RDONLY | O_CLOEXEC)
        try:
            for entry in sorted(wanted, key=lambda e: e[2]):
                _, key, offset, length = entry
                packed = _frame_bytes(fd, bank, offset, length)
                if packed is None:
                    yield entry, None, None, None, _unreadable(bank)
                    continue
                try:
                    raw = _decompress(packed, MAX_FRAME_RAW)
                except ValueError:      # e.g. the newest frame while the game has not flushed it
                    raw = None
                if raw is None:
                    yield entry, None, None, None, _unreadable(bank)
                    continue
                try:
                    header, totals, rows = decode_frame(raw, key, level)
                except (ValueError, IndexError, KeyError, struct.error) as exc:
                    yield entry, None, None, None, f'{type(exc).__name__}: {exc}'
                    continue
                yield entry, header, totals, rows, None
        finally:
            os.close(fd)


def frame_records(engine, log=None, keys=None, level='full', bank_list=None, entries=None):
    """Yield (key, bank ordinal, header, totals, rows | None, error) for every archived frame (or
    those whose key is in `keys`, or the (bank ordinal, key, offset, length) `entries`), decoded
    to `level`."""
    log = log or (lambda m: None)
    started, count = time.time(), 0
    for bank in (bank_list if bank_list is not None else banks(engine)):
        if entries is not None:
            wanted = {(k, o, n) for b, k, o, n in entries if b == bank['ordinal']}
            if not wanted:
                continue
            bank = {**bank, 'entries': [e for e in bank['entries'] if e in wanted]}
        for key, raw in read_frames(bank, keys):
            count += 1
            if raw is None:
                yield key, bank['ordinal'], None, None, None, _unreadable(bank)
                continue
            try:
                header, totals, rows = decode_frame(raw, key, level)
            except (ValueError, IndexError, KeyError, struct.error) as exc:
                yield key, bank['ordinal'], None, None, None, f'{type(exc).__name__}: {exc}'
                continue
            yield key, bank['ordinal'], header, totals, rows, None
    log(f'archived frames: {count} in {time.time() - started:.1f}s')


# --------------------------------------------------------------------------- retained event streams
# Each human manager keeps full-detail records ("CBE") for a few matches in four owner-date
# vectors (hand-built route of `live_retained_shots.capture_source`): 24-byte headers
# `<u32 ?, u32 packed date (year << 16 | day of year), u64 CBE, i32 owner team native id, ...>`.
# A CBE holds the 56-byte event stream at +0x08 and the two per-side 48-byte shot vectors at
# +0x20 / +0x38; +0x100 holds the pitch half width / half length (float32).
RETAINED_LISTS = {0x188: 'own_team', 0x1A0: 'other', 0x170: 'opponent', 0x1B8: 'other_2'}
MAX_EVENTS = 20000
MAX_SHOTS = 256


def retained_sources(engine):
    """[{list, date, owner_team_id, cbe, events (bytes), paths, shot_vectors, geometry}] for every human."""
    from .. import prepared_tactics_source as pts
    from .match_pass_decode import read_paths
    from ..live_retained_shots import _records
    read = world.ReadSet(engine.read)
    base = engine.base
    record, _ = world.loaded(read, base)
    out = []
    for coach in record['coaches']:
        _, human = pts._team_and_human(read, base, coach)
        for offset, label in RETAINED_LISTS.items():
            pointers = _records(read, human + offset, 8, 4096)
            for (pointer,) in struct.iter_unpack('<Q', pointers):
                header = read(pointer, 24)
                packed = struct.unpack_from('<I', header, 4)[0]
                cbe = players.u64(header, 8)
                owner = struct.unpack_from('<i', header, 16)[0]
                day = date(packed >> 16, 1, 1) + timedelta(days=(packed & 511) - 1)
                item = {'list': label, 'coach': coach['name'], 'date': day.isoformat(),
                        'owner_team_id': owner, 'cbe': cbe}
                if cbe:
                    half_width, half_length = struct.unpack('<ff', read(cbe + 0x100, 8))
                    events = _records(read, cbe + 8, 56, MAX_EVENTS)
                    item.update(events=events, paths=read_paths(engine, events),
                                shot_vectors=[_records(read, cbe + o, 48, MAX_SHOTS) for o in (0x20, 0x38)],
                                geometry={'half_width_native': half_width, 'half_length_native': half_length})
                out.append(item)
    return out


def bind_retained(rows, item):
    """Result row index for a retained source: same date and the owner team on either side."""
    cands = [i for i, r in enumerate(rows) if r['date'] == item['date']
             and item['owner_team_id'] in (r['home_team_id'], r['away_team_id'])]
    return cands[0] if len(cands) == 1 else None


def match_keys(rows):
    """native match key -> [row indices] (keys repeat across years)."""
    by_key = defaultdict(list)
    for i, r in enumerate(rows):
        by_key[r['native_match_key']].append(i)
    return by_key


def bind_frame(rows, by_key, key, header):
    """The result row a frame belongs to: same key and same home/away team index; else None."""
    cands = [i for i in by_key.get(key, ()) if [rows[i]['home_team_idx'], rows[i]['away_team_idx']] == header['teams']]
    return cands[0] if len(cands) == 1 else None
