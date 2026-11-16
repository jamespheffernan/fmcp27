"""Prospective terminal tracking/period witness. No storage or game writes."""
from copy import deepcopy
import hashlib

from . import active_match_half_boundaries, active_match_people, active_match_tracking
from . import active_match_shot_timeline, current_spatial_axes
from .live_average_positions import decode_tracking_average_positions
from .match_period_observations import digest, career_identity, fixture_identity

POLICY = 'terminal_width_raw_pairs_phase_prefix_actor_identity_v1'
WITNESS_KEY = 'spatial_period_witness'


def tracking_fingerprint(tracking, actors, cursor):
    """Every observed raw pair/phase byte and canonical stream identity.

    Full raw XY is required because zero-pair/tail coverage consumes both axes.
    Phase presence/length is retained: native end-byte clamping is not this
    width report's actual-byte selection policy. Future points are not bound.
    """
    prefix = active_match_tracking.clip_tracking(tracking, cursor)
    if any(row['start_tick'] % 24 for row in prefix['players']):
        raise ValueError('Unproved off-grid tracking start for the native24-tick trim')
    decode_tracking_average_positions(prefix, actors)
    by_slot = {(row['side_index'], row['stored_player_slot']): row for row in actors}
    rows = []
    for stream in sorted(prefix['players'], key=lambda row: (row['side_index'], row['stored_player_slot'])):
        actor = by_slot[stream['side_index'], stream['stored_player_slot']]
        ordinal = actor.get('person_index_word')
        if type(ordinal) is not int or ordinal < 0:
            raise ValueError('Spatial period stream needs its canonical PERSON ordinal')
        rows.append(dict(side_index=stream['side_index'], stored_player_slot=stream['stored_player_slot'],
                         canonical_person_id=actor['canonical_person_id'], person_index_word=ordinal,
                         person_name=actor['person_name'], start_tick=stream['start_tick'],
                         sample_count=len(stream['samples']) // 4,
                         raw_pairs_sha256=hashlib.sha256(stream['samples']).hexdigest()))
    phases = prefix.get('possession_samples')
    semantic = dict(rows=rows, phase_bytes=None if phases is None else phases.hex(),
                    orientation_profile=prefix['orientation_profile'].hex())
    return dict(policy=POLICY, cutoff_inclusive=cursor, stream_count=len(rows),
                position_sample_count=sum(row['sample_count'] for row in rows),
                phase_byte_count=None if phases is None else len(phases), semantic_sha256=digest(semantic))


def _parent(observation):
    return {key: value for key, value in observation.items() if key != WITNESS_KEY}


def validate_context(parent):
    """Validate spatial native-clock context independently of shot witnesses."""
    if (type(parent) is not dict or type(parent.get('schema_version')) is not int
            or parent['schema_version'] != 1
            or parent.get('capture_method') != 'normal_current_match_query_single_verified_readset'
            or parent.get('clock_domain') != 'native_playback_time_slice'):
        raise ValueError('Spatial period evidence must be captured prospectively')
    if career_identity(parent['career']) != parent['career'] or fixture_identity(parent['fixture']) != parent['fixture']:
        raise ValueError('Noncanonical spatial period career or fixture identity')
    uid, cursor, epoch = (parent.get(name) for name in (
        'official_match_unique_id', 'fingerprint_cursor', 'process_load_epoch'))
    if type(uid) is not int or not 0 < uid < 1 << 64:
        raise ValueError('Invalid spatial period native match identity')
    if type(cursor) is not int or not 0 < cursor < 65536:
        raise ValueError('Invalid spatial period terminal clock')
    if type(epoch) is not str or len(epoch) != 64 or any(c not in '0123456789abcdef' for c in epoch):
        raise ValueError('Invalid spatial period process/load epoch')
    markers = parent.get('period_markers')
    if (type(markers) is not list or len(markers) != 4
            or markers[0].get('next_stop_reason') not in ('StartOfGame', 'StartOfPeriod')
            or [row.get('next_stop_reason') for row in markers[1:]] != ['EndOfPeriod', 'StartOfPeriod', 'EndOfGame']):
        raise ValueError('Closed terminal native spatial period markers required')
    ticks = [row.get('stop_time_slice') for row in markers]
    if (any(type(tick) is not int or not 0 <= tick <= cursor for tick in ticks)
            or any(a >= b for a, b in zip(ticks, ticks[1:])) or ticks[-1] != cursor):
        raise ValueError('Invalid spatial period native marker clocks')
    intervals = parent.get('intervals')
    if type(intervals) is not list or len(intervals) != 2:
        raise ValueError('Two closed native spatial half intervals required')
    expected = {'FirstHalf': (ticks[0], ticks[1], 'verified_first_half_boundary'),
                'SecondHalf': (ticks[2], ticks[3], 'verified_second_half_start')}
    seen = set()
    for interval in intervals:
        label = interval.get('period')
        if label not in expected or label in seen:
            raise ValueError('Ambiguous native spatial half intervals')
        seen.add(label)
        start, end, state = expected[label]
        if (type(interval.get('start_tick')) is not int or type(interval.get('end_tick')) is not int
                or (interval['start_tick'], interval['end_tick']) != (start, end)
                or type(interval.get('official_match_unique_id')) is not int
                or interval['official_match_unique_id'] != uid
                or interval.get('time_slice_domain') != 'native_playback_time_slice'
                or interval.get('state') != state):
            raise ValueError('Spatial half interval differs from native stops, match or domain')
    return parent


def validate_witness(observation):
    parent = _parent(observation)
    witness = observation.get(WITNESS_KEY)
    if witness is None:
        return None
    validate_context(parent)
    if (type(witness) is not dict or type(witness.get('schema')) is not int or witness.get('schema') != 1
            or witness.get('source_kind') != 'same_readset_terminal_native_stops_and_tracking'
            or witness.get('parent_sha256') != digest(parent)
            or witness.get('process_load_epoch') != parent['process_load_epoch']
            or witness.get('official_match_unique_id') != parent['official_match_unique_id']):
        raise ValueError('Spatial period witness parent, epoch or native match differs')
    fingerprint = witness.get('tracking_fingerprint')
    if (type(fingerprint) is not dict or set(fingerprint) != {
            'policy', 'cutoff_inclusive', 'stream_count', 'position_sample_count', 'phase_byte_count', 'semantic_sha256'}
            or fingerprint['policy'] != POLICY
            or fingerprint['cutoff_inclusive'] != parent['fingerprint_cursor']
            or type(fingerprint['stream_count']) is not int or not 0 < fingerprint['stream_count'] <= 52
            or type(fingerprint['position_sample_count']) is not int
            or not 0 < fingerprint['position_sample_count'] <= 150000
            or (fingerprint['phase_byte_count'] is not None and
                (type(fingerprint['phase_byte_count']) is not int or not 0 <= fingerprint['phase_byte_count'] <= 100000))
            or type(fingerprint['semantic_sha256']) is not str
            or len(fingerprint['semantic_sha256']) != 64
            or any(c not in '0123456789abcdef' for c in fingerprint['semantic_sha256'])):
        raise ValueError('Invalid complete spatial period tracking fingerprint')
    return witness


def make_witness(observation, captured):
    """Called only after the owning collector verifies its full read-set/epoch.

    Unlike a possession attestation, this cannot be built from an old terminal
    event vector: capture_terminal_source must have collected tracking together
    with the native stops. This helper neither persists nor imports evidence.
    """
    parent = _parent(observation)
    validate_context(parent)
    if (captured.get('state') != 'checked_terminal_spatial_period_source'
            or captured['official_match_unique_id'] != parent['official_match_unique_id']
            or captured['cursor'] != parent['fingerprint_cursor']
            or captured['period_markers'] != parent['period_markers']
            or captured['fixture_identity'] != parent['fixture']):
        raise ValueError('Spatial period capture does not belong to the period observation')
    value = dict(schema=1, source_kind='same_readset_terminal_native_stops_and_tracking',
                 parent_sha256=digest(parent), process_load_epoch=parent['process_load_epoch'],
                 official_match_unique_id=parent['official_match_unique_id'],
                 tracking_fingerprint=deepcopy(captured['tracking_fingerprint']))
    validate_witness({**parent, WITNESS_KEY: value})
    return value


def make_observation(save, fixture, candidate, captured, epoch, observed_at):
    """Build a spatial-only record after the outer read-set/epoch checks.

    No attempt-prefix entries are synthesized or required. The native stop
    markers and independently captured tracking are the source family here.
    """
    bound, split = candidate['bound'], candidate['split']
    uid, cursor = bound['official_match_unique_id'], bound['current_time_slice']
    markers = deepcopy(split['period_markers'])
    if type(observed_at) is not str or not observed_at:
        raise ValueError('Spatial period capture timestamp is required')
    if len(markers) != 4:
        raise ValueError('Closed terminal spatial marker sequence required')
    intervals = [dict(period=label, start_tick=markers[a]['stop_time_slice'], end_tick=markers[b]['stop_time_slice'],
                      official_match_unique_id=uid, time_slice_domain='native_playback_time_slice', state=state)
                 for label, a, b, state in (('FirstHalf', 0, 1, 'verified_first_half_boundary'),
                                            ('SecondHalf', 2, 3, 'verified_second_half_start'))]
    parent = dict(schema_version=1, source_kind='host_captured_native_spatial_period_observation',
                  capture_method='normal_current_match_query_single_verified_readset',
                  career=career_identity(save), fixture=fixture_identity(fixture),
                  official_match_unique_id=uid, process_load_epoch=epoch, observed_at=observed_at,
                  fingerprint_cursor=cursor, clock_domain='native_playback_time_slice',
                  period_markers=markers, intervals=intervals)
    return dict(parent, spatial_period_witness=make_witness(parent, captured))


def capture_terminal_source(read, base, candidate):
    """Optional current-report hook under its existing checked read-set.

    Normal FullTime only: an exact EndOfGame marker must equal current and
    buffered maximum. The outer current report still owns process/save/epoch
    checks and publication. No normal store is read or written here.
    """
    bound, split = candidate['bound'], candidate['split']
    cursor = bound['current_time_slice']
    if (split.get('state') != 'available'
            or split.get('period_source', {}).get('simulation_period') != 'FullTime'
            or cursor != bound['buffered_max_time_slice']
            or not split.get('period_markers')
            or split['period_markers'][-1]['next_stop_reason'] != 'EndOfGame'
            or split['period_markers'][-1]['stop_time_slice'] != cursor):
        raise ValueError('Terminal native stops and tracking must coexist; no inferred spatial halves')
    client, engine = candidate['client'], candidate['engine']
    verify_period_clock(read, base)
    active_match_shot_timeline._verify_bound(read, base, client, engine, bound)
    current_spatial_axes.verify_native(read, base)
    actors = active_match_people.inspect_actor_bindings(
        read, base, engine, expected_match_unique_id=bound['official_match_unique_id'])
    source = active_match_tracking.capture_source(read, base, client, engine, current_time_slice=cursor)
    canonical_fixture = fixture_identity(candidate['fixture'])
    expected_fixture = (canonical_fixture['date'], canonical_fixture['competition']['native_id'],
                        *((canonical_fixture[name]['database_index'], canonical_fixture[name]['native_id'])
                          for name in ('home_team', 'away_team')))
    source_fixture = source.get('fixture_identity', ())
    source_fixture = tuple(tuple(value) if isinstance(value, (list, tuple)) else value for value in source_fixture)
    if (source.get('state') != 'available_engine_tracking_source'
            or source_fixture != expected_fixture
            or source.get('source_identity', ())[:2] != (client, engine)
            or source['match_unique_id'] != bound['official_match_unique_id']
            or actors.get('state') != 'validated_native_stored_slots'
            or actors.get('official_match_unique_id') != bound['official_match_unique_id']):
        raise ValueError('Terminal spatial engine, actors or fixture differs')
    fingerprint = tracking_fingerprint(source['tracking'], actors['players'], cursor)
    if not fingerprint['position_sample_count']:
        raise ValueError('Terminal spatial source contains no observed points')
    fresh = read.read
    checked = active_match_tracking.capture_source(fresh, base, client, engine, current_time_slice=cursor)
    checked_actors = active_match_people.inspect_actor_bindings(
        fresh, base, engine, expected_match_unique_id=bound['official_match_unique_id'])
    if (checked.get('state') != source['state']
            or checked.get('source_identity') != source.get('source_identity')
            or checked.get('cbe_address') != source.get('cbe_address')
            or tracking_fingerprint(checked['tracking'], checked_actors['players'], cursor) != fingerprint):
        raise ValueError('Complete terminal tracking semantics changed')
    active_match_tracking.verify_prefix(fresh, base, client, engine, bound, source)
    end_split = active_match_half_boundaries.inspect(fresh, base, bound)
    if end_split.get('state') != 'available' or end_split.get('period_markers') != split['period_markers']:
        raise ValueError('Terminal spatial native period markers changed')
    read.verify()
    return dict(state='checked_terminal_spatial_period_source', cursor=cursor,
                official_match_unique_id=bound['official_match_unique_id'],
                fixture_identity=fixture_identity(candidate['fixture']),
                period_markers=deepcopy(split['period_markers']), tracking_fingerprint=fingerprint)


def verify_period_clock(read, base):
    for rva, expected in PERIOD_CLOCK_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Spatial native stop-marker/tracking clock bridge changed')


# One saved tick feeds provider+1A0 StopTimeInfo trimming and CBE tracking
# trimming. Stop rows compare that tick against their first word, stride20.
PERIOD_CLOCK_SPANS = (
    (0x781e40, bytes.fromhex('f40301aaf30300aa00e000910103f837e10314aae3cd049560820691e10314aaac18059560e20691e10314aab50d0595600e41f9e10314aa1e520495600e41f9e10314aa19520495600e41f9e10314aaff510495600e41f9e10314aa29520495')),
    (0x48c8120, bytes.fromhex('3f0400714b020054082440a92b0108eb800400540a0080d26cfd4293ede702b2ad9999f28c7d0d9b9f0500f18c859f9a0d696ab8bf01016bec0000544a5100918c0500f161ffff5416000014')),
)
