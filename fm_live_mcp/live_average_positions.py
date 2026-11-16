"""Native retained tracking means and distinct pass-origin network nodes."""
import ctypes
import struct
import sys

MAX_TRACKING_SAMPLES = 100_000
MAX_TRACKING_PLAYERS = 52


def _f32(value):
    return struct.unpack('<f', struct.pack('<f', value))[0]


# The renderer uses FMADD, so retain its single float32 rounding step. fmaf is correctly rounded
# by definition, so the C library it comes from does not change the result: the process's own
# libm on macOS and Linux, the Universal C Runtime on Windows (where CDLL(None) is an error).
_fmaf = (ctypes.CDLL('ucrtbase') if sys.platform == 'win32' else ctypes.CDLL(None)).fmaf
_fmaf.argtypes = (ctypes.c_float, ctypes.c_float, ctypes.c_float)
_fmaf.restype = ctypes.c_float


def tracking_positive_orientation(profile, side, tick):
    """Exact native4895a60 branch; tick and period boundaries remain native units."""
    if not isinstance(profile, bytes) or len(profile) != 16:
        raise ValueError('Unsupported tracking orientation profile')
    if type(side) is not int or side not in (0, 1) or type(tick) is not int or tick < 0:
        raise ValueError('Invalid tracking side or tick')
    first, second, third = struct.unpack_from('<iii', profile)
    if any(v < -1 for v in (first, second, third)) or profile[13] not in (0, 1) or profile[14] not in (0, 1):
        raise ValueError('Unsupported tracking orientation boundaries')
    expected = int(side == 0)
    if first != -1 and first > tick:
        return profile[13] == expected
    if second != -1 and second > tick:
        return profile[13] != expected
    return (profile[14] == expected) != (third == -1 or third <= tick)


def read_tracking_source(read, cbe):
    """Read bounded CBE streams after the caller verifies its canonical owner."""
    from .live_retained_shots import _records
    entries = _records(read, cbe + 0xd0, 40, MAX_TRACKING_PLAYERS)
    profiles = read(cbe + 0x108, 16)
    rows = []
    seen = set()
    for offset in range(0, len(entries), 40):
        entry = entries[offset:offset + 40]
        key = struct.unpack_from('<b', entry)[0]
        if key < 0 or key >= MAX_TRACKING_PLAYERS or key in seen:
            raise ValueError('Unsupported or duplicate native tracking player key')
        seen.add(key)
        first, last, capacity = struct.unpack_from('<QQQ', entry, 16)
        if not first <= last <= capacity or (last - first) % 4 or capacity - first > MAX_TRACKING_SAMPLES * 4:
            raise ValueError('Unsupported native tracking sample vector')
        if first == 0 and (last or capacity):
            raise ValueError('Invalid null tracking sample vector')
        samples = b''.join(read(pos, min(8192, last - pos)) for pos in range(first, last, 8192))
        rows.append({'side_index': key % 2, 'stored_player_slot': key // 2,
                     'start_tick': struct.unpack_from('<I', entry, 8)[0], 'samples': samples})
    phase_first, phase_last, phase_capacity = struct.unpack('<QQQ', read(cbe + 0xe8, 24))
    if (phase_first, phase_last, phase_capacity) == (0, 0, 0):
        possession_samples = b''
    else:
        if (phase_first < 4096 or phase_first % 8 or not phase_first <= phase_last <= phase_capacity
                or phase_capacity - phase_first > MAX_TRACKING_SAMPLES):
            raise ValueError('Unsupported native possession byte vector')
        possession_samples = b''.join(read(pos, min(8192, phase_last - pos))
                                      for pos in range(phase_first, phase_last, 8192))
    return {'state': 'available' if rows else 'unavailable_no_retained_tracking',
            'orientation_profile': profiles, 'possession_samples': possession_samples, 'players': rows}


def decode_tracking_average_positions(tracking, players):
    """Reproduce named AveragePositionMap all-samples float32 means.

    Native1a65e8 reads int16 pairs, advances24 native ticks per sample, uses
    float32±0.01 and FMADD, and divides by the count of those position samples.
    This is independent of pass/touch event counts. Axes remain native axes.
    """
    if not isinstance(tracking, dict) or not isinstance(players, list):
        raise ValueError('Unsupported tracking packet')
    profile = tracking.get('orientation_profile')
    phases = tracking.get('possession_samples')
    if phases is not None and (not isinstance(phases, bytes) or len(phases) > MAX_TRACKING_SAMPLES):
        raise ValueError('Unsupported possession sample stream')
    rows = tracking.get('players')
    if not isinstance(rows, list) or len(rows) > MAX_TRACKING_PLAYERS:
        raise ValueError('Unsupported tracking player budget')
    roster = {}
    identities = set()
    for player in players:
        side, slot = player.get('side_index'), player.get('stored_player_slot')
        identity, name = player.get('canonical_person_id'), player.get('person_name')
        if (type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26
                or (side, slot) in roster or type(identity) is not int or identity <= 0 or identity in identities
                or not isinstance(name, str) or not name):
            raise ValueError('Ambiguous tracking player identity')
        roster[side, slot] = player
        identities.add(identity)
    output = []
    seen = set()
    scale = _f32(0.01)
    for row in rows:
        side, slot, tick = row.get('side_index'), row.get('stored_player_slot'), row.get('start_tick')
        samples = row.get('samples')
        if (type(side) is not int or side not in (0, 1) or type(slot) is not int or not 0 <= slot < 26
                or (side, slot) in seen or type(tick) is not int or not 0 <= tick <= 0xffffffff
                or not isinstance(samples, bytes) or len(samples) % 4 or len(samples) // 4 > MAX_TRACKING_SAMPLES):
            raise ValueError('Unsupported tracking row')
        seen.add((side, slot))
        if (side, slot) not in roster:
            raise ValueError('Unresolved tracking player slot')
        count = len(samples) // 4
        sums = [0.0, 0.0]
        phase_sums = {'in_possession': [0.0, 0.0], 'out_of_possession': [0.0, 0.0]}
        phase_counts = {'in_possession': 0, 'out_of_possession': 0}
        unclassified = unmapped = 0
        zero_pairs = trailing_zero_pairs = 0
        first_nonzero_tick = last_nonzero_tick = None
        for index, pair in enumerate(struct.iter_unpack('<hh', samples)):
            at = tick + index * 24
            if at > 0x7fffffff:
                raise ValueError('Unsupported tracking tick overflow')
            multiplier = scale if tracking_positive_orientation(profile, side, at) else -scale
            if pair == (0, 0):
                zero_pairs += 1
                trailing_zero_pairs += 1
            else:
                trailing_zero_pairs = 0
                first_nonzero_tick = at if first_nonzero_tick is None else first_nonzero_tick
                last_nonzero_tick = at
            for axis in (0, 1):
                sums[axis] = float(_fmaf(pair[axis], multiplier, sums[axis]))
            if phases:
                phase = phases[min(at // 24, len(phases) - 1)]
                if phase == 255:
                    unclassified += 1
                else:
                    bucket = 'in_possession' if phase == side else 'out_of_possession'
                    unmapped += phase not in (0, 1)
                    phase_counts[bucket] += 1
                    for axis in (0, 1):
                        phase_sums[bucket][axis] = float(_fmaf(pair[axis], multiplier, phase_sums[bucket][axis]))
        player = roster[side, slot]
        output.append({'side_index': side, 'stored_player_slot': slot,
                       'canonical_person_id': player['canonical_person_id'], 'person_name': player['person_name'],
                       'state': 'available' if count else 'unavailable_no_position_samples',
                       'sample_count': count, 'sample_start_tick': tick, 'sample_step_native_ticks': 24,
                       'coverage': {'zero_pair_sample_count': zero_pairs,
                                    'trailing_zero_pair_sample_count': trailing_zero_pairs,
                                    'nonzero_pair_sample_count': count - zero_pairs,
                                    'first_nonzero_sample_tick': first_nonzero_tick,
                                    'last_nonzero_sample_tick': last_nonzero_tick,
                                    'on_pitch_time_coverage_verified': False,
                                    'zero_pair_meaning': 'unproven; preserved in official denominator'},
                       'native_axis_0': _f32(sums[0] / _f32(count)) if count else None,
                       'native_axis_1': _f32(sums[1] / _f32(count)) if count else None,
                       'possession_means': {
                           'state': ('native_phase_branch_with_unmapped_values' if unmapped else 'available') if phases else 'unavailable_possession_stream',
                           'unclassified_sample_count': unclassified if phases else None,
                           'unmapped_native_phase_sample_count': unmapped if phases else None,
                           **{bucket: {'sample_count': phase_counts[bucket] if phases else None,
                                      'native_axis_0': _f32(phase_sums[bucket][0] / _f32(phase_counts[bucket])) if phase_counts[bucket] else None,
                                      'native_axis_1': _f32(phase_sums[bucket][1] / _f32(phase_counts[bucket])) if phase_counts[bucket] else None}
                              for bucket in phase_counts}}})
    return {'state': 'available' if output else 'unavailable_no_retained_tracking',
            'source_kind': 'official_average_position_map_all_tracking_samples', 'players': output,
            'coverage_policy': 'Official stored-sample means include zero pairs and post-exit zero tails; counts do not measure on-pitch time',
            'possession_policy': 'native tick//24 clamped to byte stream; -1 omitted from subsets; other non-side values follow native out branch',
            'unknown_fields': ['pitch_axis_names', 'physical_units', 'unmapped_native_phase_meaning']}


TRACKING_NATIVE_SPANS = (
    (0x48928b4, bytes.fromhex('685595524855a572287c289b09fd7fd308fd62930801090b090840b90a0040f9eb032a2a087da80a6901090b1f01096b08b1891a40c9e838c0035fd6')),
    (0x4896890, bytes.fromhex('4804010b0a1d001309204da90b0109eb000200546bfd4393ece702b2ac9999f26c7d0c9b0b0580520d0080928efd41d3cf250b9bf085c238b1054cca8c01118b1f020a6b8cb18e9ae9b1899a0cffffb53f0108eb800000542b01c0395f010b6b4a000054e90308aa2a2100913f0108ebe0038a9ac0035fd6')),
    (0x4895a60, bytes.fromhex('3f000071e9179f1a0a5444395f01096be8179f1a0b0841b97f0500316011427a0c020054080c41b91f0500310011427a8d0000545f01096be8079f1a09000014085844391f01096be8179f1a091041b93f0500312011427ae9c79f1a0801094ae00308aac0035fd6')),
    (0x1a67ec, bytes.fromhex('e0031aaae10315aae20318aa9abc1b956003407d00a4100f00d8215e1f00007148e19a526884b7720101271ec202271e411c211e0a28011f6007407d00a4100f00d8215e0b2c011ff7060091186300117b1300917f0314eb41fdff54130080d2190080d20de4002f00e4002fe04f00bd09e4002f08e4002f770200b4e102239e4019211e6119211ea0c302d1a15303d1a26303d1e31f40f988200094')),
    (0x1a69c4, bytes.fromhex('e0a5100f00d8215e0a280e1f80a5100f00d8215e0b2c0e1f186300117b130091f70600917f0314ebc0f3ff54e0031aaae10315aae20318aa19bc1b956f03407d1f00007148e19a526884b7720001271ec102271e2e1c201e6c07407d')),
    (0x1a6a54, bytes.fromhex('6003407d00a4100f00d8215e0d340e1f6007407d00a4100f00d8215ee14f40bd01040e1fe14f00bd73060091d1ffff17')),
    (0x29f798, bytes.fromhex('a0835bf8e8030039c71e0013e8430091e2e30091e10315aae30314aa0400805205008052260080528a1bfc97')),
    (0x1aeaf4, bytes.fromhex('a02301d1a26301d121aa8e52a1a8ad72f8210995a02301d1e2a3019141488f528108a772f3210995')),
)
