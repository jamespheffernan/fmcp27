"""Optional resident statistics observations over ordered host row intervals.

The strict combined match report is deliberately separate. Only the exact
proved scalar bytes may move; fixture, career, code and canonical ownership
remain strict. A contiguous read is not claimed atomic or a native tick.
"""
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
import struct
import time

from . import active_match_source, database, players, world
from . import current_player_match_statistic_groups as groups


BLOCK_SIZE = 0x10C
# Exact operands consumed by the unchanged33-field projector. Padding and
# identity bytes are never exempted from the strict semantic-static manifest.
VALUE_SPANS = ((0x1C, 4), (0x24, 4), (0x68, 4), (0x90, 2), (0x99, 3),
               (0xA0, 2), (0xA3, 1), (0xA6, 2), (0xB5, 2), (0xBC, 2),
               (0xC6, 2), (0xCA, 2), (0xCF, 1), (0xD7, 3), (0xDF, 4),
               (0xEC, 2), (0xF1, 1), (0xF5, 1), (0x10A, 2))
LIMITATIONS = (
    'Ordered host monotonic intervals are not native clocks or displayed minutes. '
    'Rows and fields need not share an instant; even one memory copy is not asserted atomic. '
    'Dynamic values may change after observation and are not current-at-response-time values. '
    'Strict static bookends cannot exclude change-and-restore ABA inside the interval. '
    'Resident slots do not establish current on-pitch participation, halftime/full-match totals, '
    'counter reset policy, deltas, tactical cause or live-versus-replay state.'
)


def _segments(cells):
    addresses = sorted(cells)
    if not addresses:
        return
    start = previous = addresses[0]
    for address in addresses[1:]:
        if address != previous + 1 or address - start >= 4096:
            yield start, bytes(cells[at] for at in range(start, previous + 1))
            start = address
        previous = address
    yield start, bytes(cells[at] for at in range(start, previous + 1))


def _exact(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete statistics observation source')
    return raw


@dataclass(frozen=True)
class RowBinding:
    side: int
    slot: int
    stats: int
    guards: tuple


def _validate_row_blocks(rows):
    """Shared or overlapping stats storage has no proved per-row semantics."""
    previous_end = 0
    for row in sorted(rows, key=lambda row: row.stats):
        if (type(row.stats) is not int or row.stats < 4096 or row.stats % 8
                or row.stats >= (1 << 64) - BLOCK_SIZE):
            raise ValueError('Invalid statistics observation block range')
        if row.stats < previous_end:
            raise ValueError('Overlapping statistics observation block ranges')
        previous_end = row.stats + BLOCK_SIZE


class BindingReadSet(world.ReadSet):
    """Query-local preflight cache; every static byte is physically fenced later.

    Repeated native identity walks reuse exact semantic requests. This is never
    used for final dynamic blocks or static/owner fences. Provisional numbers
    establish permitted operands only and cannot appear in the response.
    """

    def __call__(self, address, size):
        key = address, size
        if key in self.observed:
            return self.observed[key]
        return super().__call__(address, size)


class PreparedObservation:
    """Private query-local binding, discarded provisional values and strict manifest."""

    def __init__(self, read, base):
        if sum(len(fields) for _, _, fields in groups.GROUPS) != 33:
            raise ValueError('Statistics observation field manifest requires33 proved fields')
        self.read, self.base = read, base
        self.save, self.world_identity = world.loaded(read, base)
        self.context, self.binding = active_match_source.inspect_context(
            read, base, expected_current_date=self.save['current_date'])
        self.rows = ()
        self.dynamic = set()
        self.official = None
        if self.binding is not None:
            engine = self.binding['engine']
            self.official = struct.unpack('<Q', read(engine + 0x20, 8))[0]
            provisional = groups.inspect(read, base, engine,
                                         expected_match_unique_id=self.official)
            self.rows = self._bind_rows(provisional)
            _validate_row_blocks(self.rows)
            self.dynamic = {row.stats + offset + i for row in self.rows
                            for offset, size in VALUE_SPANS for i in range(size)}
        self.static = {}
        for (address, size), raw in read.observed.items():
            for i, value in enumerate(raw):
                at = address + i
                if at in self.dynamic:
                    continue
                if at in self.static and self.static[at] != value:
                    raise ValueError('Inconsistent static statistics source')
                self.static[at] = value
        self.static_spans = tuple(_segments(self.static))

    def _bind_rows(self, provisional):
        read, base, engine = self.read, self.base, self.binding['engine']
        people = database.table(read, base, 'people')
        bound = []
        for row in provisional['rows']:
            if row['state'] != groups.AVAILABLE:
                continue
            side = struct.unpack('<Q', read(engine + 0x15370 + row['side_index'] * 8, 8))[0]
            player = struct.unpack('<Q', read(side + 0x140 + row['engine_array_index'] * 8, 8))[0]
            stats = struct.unpack('<Q', read(player + 0x1880, 8))[0]
            person = struct.unpack('<Q', read(player + 0x20, 8))[0]
            team = struct.unpack('<Q', read(side + 0xB8, 8))[0]
            displacement = {'actual': 0x388, 'player_staff': 0x480, 'virtual': 0x20}[row['person']['record_kind']]
            primary = person - displacement
            roster = world.vector(read, team + 0x38, 256)
            roster_start = struct.unpack('<Q', read(team + 0x38, 8))[0]
            operands = ((engine + 0x20, 8), (engine + 0x15370 + row['side_index'] * 8, 8),
                        (side + 0x140 + row['engine_array_index'] * 8, 8), (side + 0xB8, 8),
                        (player, 8), (player + 0x20, 8), (player + 0x280, 16),
                        (player + 0x1E27, 1), (player + 0x1880, 8), (stats, 8),
                        (stats + 0x18, 4), (person, 20), (primary, 8),
                        (people['start'] + row['person']['native_identity']['database_index'] * 8, 8),
                        (team + 0x38, 24), (roster_start + roster.index(primary) * 8, 8))
            bound.append(RowBinding(row['side_index'], row['engine_array_index'], stats,
                                    tuple((at, read(at, size)) for at, size in operands)))
        return tuple(bound)

    @staticmethod
    def _verify(read, spans):
        for address, expected in spans:
            if _exact(read, address, len(expected)) != expected:
                raise ValueError('Static statistics identity/context/code source changed')

    def capture(self, physical, *, clock=time.monotonic_ns, evidence=None):
        """Run after every lifetime callback; physical MUST bypass all caches.

        Evidence is an optional in-memory private ledger, never an MCP field
        or host-file write. It can retain failed source facts only as rejected.
        """
        if evidence is not None:
            evidence.update(accepted=False, static_regions=[
                {'address': hex(at), 'size': len(raw), 'rawhex': raw.hex()}
                for at, raw in self.static_spans], dynamic_rows=[])
        self._verify(physical, self.static_spans)
        values, observations = {}, []
        started = clock()
        previous_end = started
        for row in self.rows:
            self._verify(physical, row.guards)
            before = clock()
            if before < previous_end:
                raise ValueError('Host observation clock moved backwards')
            raw = _exact(physical, row.stats, BLOCK_SIZE)
            after = clock()
            if after < before:
                raise ValueError('Host observation clock moved backwards')
            previous_end = after
            # Identity bytes within the physical block must agree too; a
            # changed-then-restored owner cannot sneak through its bookends.
            for i, value in enumerate(raw):
                at = row.stats + i
                if at in self.static and self.static[at] != value:
                    raise ValueError('Static statistics source changed inside observed block')
            self._verify(physical, row.guards)
            observation = dict(side_index=row.side, engine_array_index=row.slot,
                               started_monotonic_ns=before, ended_monotonic_ns=after,
                               identity_guard_bookends_equal=True)
            observations.append(observation)
            for offset, size in VALUE_SPANS:
                for i, value in enumerate(raw[offset:offset + size]):
                    values[row.stats + offset + i] = value
            if evidence is not None:
                evidence['dynamic_rows'].append(dict(observation, address=hex(row.stats),
                    size=BLOCK_SIZE, rawhex=raw.hex(), guard_regions=[
                        {'address': hex(at), 'size': len(value), 'rawhex': value.hex()}
                        for at, value in row.guards]))
        ended = clock()
        if ended < previous_end:
            raise ValueError('Host observation clock moved backwards')
        self._verify(physical, self.static_spans)

        def replay(address, size):
            try:
                return bytes(values[at] if at in self.dynamic else self.static[at]
                             for at in range(address, address + size))
            except KeyError as exc:
                raise ValueError('Unclassified or missing final statistics operand') from exc

        projection = (groups.inspect(replay, self.base, self.binding['engine'],
                                     expected_match_unique_id=self.official)
                      if self.binding is not None else None)
        result = dict(state='unavailable' if projection is None else projection['state'],
            source='typed_owned_resident_statistics_observed_over_host_window',
            consistency_policy='explicit_per_row_observation_window',
            current_match=self.context, player_statistics=projection,
            host_observation_window=dict(started_monotonic_ns=started, ended_monotonic_ns=ended,
                                         clock='host_monotonic_ns'),
            row_observations=observations, static_source_bytes_rechecked=True,
            slow_callbacks_finished_before_dynamic_observations=True,
            dynamic_values_rechecked_unchanged=False, all_rows_same_instant_verified=False,
            all_fields_same_instant_verified=False, current_at_response_time_verified=False,
            **{flag: False for flag in groups.FALSE_FLAGS}, limitations=LIMITATIONS)
        if projection is not None:
            projection['source'] = result['source']
            projection['scope'] = LIMITATIONS
        if evidence is not None:
            evidence.update(accepted=True, static_bookends_equal=True,
                            final_static_fence_after_all_dynamic_reads=True,
                            host_observation_window=deepcopy(result['host_observation_window']))
        return result


def current_match_statistic_observations(bridge, session_id, *, _evidence=None):
    """Collect optional player-only windows on the bridge's same open stream."""
    from .bridge import BridgeError
    from .reader import ReaderError
    result = None
    completed = False
    if _evidence is not None:
        _evidence['accepted'] = False
    with bridge.lock:
        try:
            def finish():
                nonlocal result
                if bridge._reader is not reader or reader.pid != process.pid:
                    raise ValueError('Statistics observation stream changed')
                if bridge.plugin_identity != plugin or bridge.world_identity != identity:
                    raise ValueError('Statistics final lifetime binding changed')
                result = prepared.capture(reader.read, evidence=_evidence)

            with bridge._read_scope(session_id, final_verify=finish):
                process = bridge._current(session_id)
                reader = bridge._reader
                if reader is None or reader.pid != process.pid:
                    raise ValueError('Pinned statistics observation stream absent')
                tables = bridge._player_layout(process)
                plugin = deepcopy(bridge.plugin_identity)
                base = tables[0] - players.RVA[0]
                initial, save, identity = bridge._world_state(process, tables)
                # Use the original stream directly for semantic source reads;
                # an evidence bridge's old immutable journal is not freshness.
                read = BindingReadSet(reader.read)
                read.observed.update(initial.observed)
                if players.verify_runtime(read, base, plugin[1]) != tables:
                    raise ValueError('Statistics runtime layout disagrees')
                prepared = PreparedObservation(read, base)
                if prepared.save != save or prepared.world_identity != identity:
                    raise ValueError('Statistics career source changed')
                current = bridge._current(session_id)
                final_tables = bridge._player_layout(current)
                _, final_save, final_identity = bridge._world_state(current, final_tables)
                if (current != process or final_tables != tables or bridge.plugin_identity != plugin
                        or final_save != save or final_identity != identity):
                    raise ValueError('Statistics process/layout/career source changed')
                public_save = deepcopy(bridge._public_save(final_save))
                observed_at = datetime.now(timezone.utc).isoformat()
                # _read_scope invokes its final _current before finish(). No
                # layout/world/public callback may follow final row capture.
            result.update(session_id=session_id, observed_at=observed_at, save=public_save)
            completed = True
            return result
        except (ValueError, IndexError, KeyError, TypeError, ReaderError) as exc:
            if _evidence is not None:
                _evidence['accepted'] = False
            raise BridgeError(f'Player statistic observation window rejected: {exc}') from exc
        finally:
            if _evidence is not None and not completed:
                _evidence['accepted'] = False
