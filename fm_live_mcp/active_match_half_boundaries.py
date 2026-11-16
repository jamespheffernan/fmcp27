"""Resident stop-info history for normal first-half boundaries after the interval.

Caller supplies the same checked playback context and verifies its shared
ReadSet. This module does not decode actions, score or historical tactics.
"""
import struct
from . import active_match_period as period

STOP_REASONS = {0: 'NotStopped', 1: 'EndOfPeriod', 2: 'SetPiece', 3: 'StartOfPeriod',
                4: 'StartOfGame', 5: 'EndOfGame', 6: 'EndOfCelebration', 7: 'PenaltyAwarded'}
MAX_STOP_RECORDS = 100000


def decode(raw, *, current_time_slice, simulation_period):
    """Preserve every observed marker; classify only the verified normal-half sequence."""
    if not isinstance(raw, bytes) or len(raw) % 20 or len(raw) > MAX_STOP_RECORDS * 20:
        raise ValueError('Invalid retained stop-info record extent')
    if type(current_time_slice) is not int or current_time_slice < 0:
        raise ValueError('Invalid current playback time slice')
    rows = []
    previous = -1
    for index in range(len(raw) // 20):
        row = raw[index * 20:(index + 1) * 20]
        tick = struct.unpack_from('<i', row)[0]
        reason = row[8]
        if tick < 0 or tick < previous:
            raise ValueError('Stop-info time slices are negative or unordered')
        previous = tick
        rows.append({'source_index': index, 'stop_time_slice': tick,
                     'next_stop_reason_raw_u8': reason, 'next_stop_reason': STOP_REASONS.get(reason),
                     'set_piece_type_raw_u8': row[9]})
    observed = [row for row in rows if row['stop_time_slice'] <= current_time_slice]
    markers = [row for row in observed if row['next_stop_reason_raw_u8'] in (1, 3, 4, 5)]
    result = {'source': 'official_retained_StopTimeInfo_history', 'state': 'unknown',
              'reason': 'normal_half_sequence_unestablished', 'current_time_slice': current_time_slice,
              'simulation_period': simulation_period, 'retained_stop_info_count': len(rows),
              'observed_stop_info_count': len(observed), 'future_stop_info_count_withheld': len(rows) - len(observed),
              'period_markers': markers, 'first_half_end_time_slice': None,
              'second_half_start_time_slice': None,
              'scope': 'Source-defined stop boundaries, including stoppage time. Not a 45-minute filter, action totals, within-tick event ordering, current/live fixture identity or historical tactical setup.'}
    if simulation_period not in ('HalfTime', 'SecondHalf', 'FullTime'):
        result['reason'] = 'unsupported_current_period_for_normal_first_half_classification'
        return result
    if not observed or observed[0]['source_index'] != 0 or observed[0]['next_stop_reason_raw_u8'] not in (3, 4):
        result['reason'] = 'initial_period_marker_missing'
        return result
    if any(row['next_stop_reason'] is None for row in observed):
        result['reason'] = 'unmapped_stop_reason'
        return result
    # The complete retained prefix must contain one initial period, one end,
    # and (only for SecondHalf) its next start. Extra-time/full-time is separate.
    kinds = [row['next_stop_reason_raw_u8'] for row in markers]
    expected = [markers[0]['next_stop_reason_raw_u8'], 1]
    if simulation_period in ('SecondHalf', 'FullTime'):
        expected.append(3)
    if simulation_period == 'FullTime':
        expected.append(5)
    if kinds != expected:
        result['reason'] = 'incomplete_or_ambiguous_normal_period_sequence'
        return result
    cutoff = markers[1]['stop_time_slice']
    if cutoff <= markers[0]['stop_time_slice']:
        result['reason'] = 'nonpositive_first_period_extent'
        return result
    start = markers[2]['stop_time_slice'] if simulation_period in ('SecondHalf', 'FullTime') else None
    if simulation_period == 'FullTime' and markers[-1]['stop_time_slice'] != current_time_slice:
        result['reason'] = 'end_of_game_marker_not_at_current_cursor'
        return result
    if start is not None and start <= cutoff:
        result['reason'] = 'overlapping_period_markers'
        return result
    result.update(state='available', reason=None, first_half_end_time_slice=cutoff,
                  second_half_start_time_slice=start)
    return result


def inspect(read, base, playback_context):
    """Consume the same private context as active_match_period.inspect."""
    for rva, expected in NATIVE_SPANS:
        if period._read(read, base + rva, len(expected)) != expected:
            raise ValueError('Official retained stop-info native source changed')
    observed_period = period.inspect(read, base, playback_context)
    # The final cursor may extend a few ticks beyond the last decoded frame.
    # FullTime is accepted only with the exact terminal StopTimeInfo prefix and
    # EndOfGame == current == maximum; stale live/interval states stay unknown.
    terminal_period_candidate = (
        observed_period.get('reason') == 'period_state_time_mismatch'
        and observed_period.get('simulation_period') == 'FullTime'
        and type(observed_period.get('period_state_time_slice')) is int
        and observed_period['period_state_time_slice'] <= observed_period['current_time_slice'])
    if observed_period['source_state'] != 'available' and not terminal_period_candidate:
        return {'state': 'unknown', 'reason': 'current_period_source_unavailable',
                'first_half_end_time_slice': None, 'second_half_start_time_slice': None,
                'period_source': observed_period, 'first_half_boundary': None, 'period_intervals': []}
    provider = playback_context['frame_provider_address']
    start, end, capacity = struct.unpack('<QQQ', period._read(read, provider + 0x1A0, 24))
    if (start, end, capacity) != (0, 0, 0):
        period._pointer(start)
        if any(value < 4096 or value % 4 or value >= 1 << 48 for value in (end, capacity)):
            raise ValueError('Invalid retained stop-info extent pointers')
        if (not start <= end <= capacity or (end - start) % 20
                or (capacity - start) % 20 or capacity - start > MAX_STOP_RECORDS * 20):
            raise ValueError('Invalid retained stop-info vector bounds')
    raw = period._read(read, start, end - start) if end > start else b''
    result = decode(raw, current_time_slice=observed_period['current_time_slice'],
                    simulation_period=observed_period['simulation_period'])
    if result['state'] == 'available' and observed_period['simulation_period'] == 'FullTime':
        playback = playback_context['playback_address']
        maximum = struct.unpack('<i', period._read(read, playback + 0x1DC4, 4))[0]
        if maximum != observed_period['current_time_slice'] or maximum != playback_context.get('buffered_max_time_slice'):
            result.update(state='unknown', reason='terminal_cursor_not_at_buffered_maximum',
                          first_half_end_time_slice=None, second_half_start_time_slice=None)
    result['period_source'] = observed_period
    result['first_half_boundary'] = None
    result['period_intervals'] = []
    if result['state'] == 'available':
        source_match = period._pointer(playback_context.get('source_match_address'))
        unique_id = playback_context.get('official_match_unique_id')
        if type(unique_id) is not int or not 0 <= unique_id < 1 << 64:
            raise ValueError('A checked official match identity is required for half boundaries')
        if struct.unpack('<Q', period._read(read, provider + 0x28, 8))[0] != source_match:
            raise ValueError('Boundary frame provider source match changed')
        if struct.unpack('<Q', period._read(read, source_match, 8))[0] != base + 0x55FA258:
            raise ValueError('Unexpected boundary source GAME_MATCH type')
        if struct.unpack('<Q', period._read(read, source_match + 0x20, 8))[0] != unique_id:
            raise ValueError('Boundary official match identity changed')
        binding = {'state': 'verified_first_half_boundary', 'reason': None,
                   'official_match_unique_id': unique_id,
                   'time_slice_domain': 'native_playback_time_slice', 'period': 'FirstHalf',
                   'start_tick': result['period_markers'][0]['stop_time_slice'],
                   'end_tick': result['first_half_end_time_slice'],
                   'time_slice': result['first_half_end_time_slice'],
                   'second_half_start_tick': result['second_half_start_time_slice'],
                   'boundary_semantics': 'Native EndOfPeriod stop marker; equality and overlapping-action classification are consumer-specific.'}
        result['first_half_boundary'] = binding
        result['period_intervals'] = [dict(binding)]
        if result['second_half_start_time_slice'] is not None:
            result['period_intervals'].append({
                'state': 'verified_second_half_start', 'reason': None,
                'official_match_unique_id': unique_id,
                'time_slice_domain': 'native_playback_time_slice', 'period': 'SecondHalf',
                'start_tick': result['second_half_start_time_slice'], 'end_tick': None})
    return result


# Official export/copy, provider vector getter and native append to retained prefix.
NATIVE_SPANS = (
    (0x209d8, bytes.fromhex('680240f9087d40f9e1230091e00313aa00013fd6')),
    (0x73da88, bytes.fromhex('000840f987f8ff17')),
    (0x73bcbc, bytes.fromhex('00044af9e81601940a2040a908010acb08fd4293e9e702b2a99999f2087d099b600a4af9090100eba00100548b0240f98c0280520a280c9b4a2500916b1100914c715fb84df15f786cc11fb86d8500784a510091290500f141ffff54')),
    (0x781860, bytes.fromhex('00800691c0035fd6')),
    (0x781620, bytes.fromhex('080040f9050c41f901e000910280069103e00691e00308aae5020515')),
    (0x48c2214, bytes.fromhex('b90000b4803240f9600000b4e10319aa9a190094')),
    (0x48c89ec, bytes.fromhex('68a640a91f0109ebc2020054ea1b40b9e90f40b90a250029e92b42290a21003909250039e9ab40290a290039182d00391931003909350039e90340b9093900391a3d0039e93b407909110178e97b4039094d00391c5100911b41003944000014')),
    (0x48c8b58, bytes.fromhex('7c0600f9d60600f1fce702b2bc9999f241edff54')),
)
