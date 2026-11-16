"""One-pass saved PLAYER_STATS_INFO lookup and primary-category comparison.

Native F1F420/F1D9F8 version15 is separate from archived completed seasons.
The supported current-writer subset is pinned by B67: F7A0F8/F7AD3C,
F756F0/F7588C, F7AA6C,1573FAC and1573858. No native calls are made.
"""
from fractions import Fraction
from hashlib import sha256
import json
import struct

from . import player_statistics, saved_component_stream, saved_person_candidates, snapshot_catalog
from .saved_person_name_search import _source as checked_name_source

CATEGORIES = ('Non Competitive', 'League', 'Cup', 'Continental', 'International', 'Overall (Club)')
MAX_PEOPLE = 32
MAX_RECORDS = 250_000
MAX_COMPONENT_BYTES = 128 * 1024**2
MAX_ADDITIONAL_TEAMS = 1000
MAX_RAW_ITEMS = 4096
MAX_RESPONSE_BYTES = 512 * 1024
MAX_NAME_CANDIDATES = 8
ENVELOPE = bytes.fromhex('03017461642e0f00')
WIRE_PROFILE = 'current_v15_stats_v7_tagged32_TEAM_item_v2_packed16_writer_subset'


class _Wire:
    def __init__(self, reader):
        self.reader = reader
        self.digest = sha256()

    @property
    def offset(self):
        return self.reader.offset

    @property
    def size(self):
        return self.reader.size

    def take(self, n):
        if type(n) is not int or not 0 <= n <= self.size - self.offset:
            raise ValueError('Current statistics read crosses declared component extent')
        raw = self.reader.take(n)
        if not isinstance(raw, bytes) or len(raw) != n:
            raise ValueError('Truncated current statistics source')
        self.digest.update(raw)
        return raw

    def number(self, fmt):
        return struct.unpack('<' + fmt, self.take(struct.calcsize('<' + fmt)))[0]


def _stats(wire, keep):
    start = wire.offset
    if wire.number('B') != 7:
        raise ValueError(f'Unsupported current statistics version at {start}')
    raw = wire.take(153)  # native+08..18, then68 signed16; no pointer serialized.
    if not keep:
        return None
    decoded = player_statistics.decode_compact(struct.pack('<Q', 1) + raw[:17], raw[17:])
    # Null and allocated-all-zero advanced storage have the same serialized bytes.
    # No synthetic decoder pointer or original residency claim escapes this layer.
    return {
        **{key: value for key, value in decoded.items()
           if key not in ('advanced', 'limitations')},
        'source_span': {'start': start, 'end': wire.offset},
        'serialized_stats_sha256': sha256(bytes([7]) + raw).hexdigest(),
        'advanced_values_state': 'serialized_values_original_indirect_pointer_not_recorded',
        'advanced_units': 'unverified_native_units_not_used_for_comparison',
    }


def _nullable(wire, keep):
    at = wire.offset
    present = wire.number('B')
    if present not in (0, 1):
        raise ValueError(f'Unsupported current statistics presence at {at}')
    return present, _stats(wire, keep) if present else None


def _team_reference(wire):
    """Source-qualified F7AA6C→1101440 tagged index32 branch, no identity join."""
    at = wire.offset
    marker = wire.number('B')
    # F7AA6C supplies mode0 or3;1101560..68 converts both to marker0.
    if marker != 0:
        raise ValueError(f'Unsupported current-writer additional TEAM reference marker at {at}')
    index = wire.number('i')
    if index < -1:
        raise ValueError('Invalid additional TEAM reference index')


def read_current(reader, person_indices, person_count, category_code):
    """Fully consume one bounded raw component; retain only requested buckets.

    Returned keys are exact stored PERSON indices. Every physical source record
    is checked, including nonmatches, so absent keys are known only after EOF.
    This helper performs no file I/O, name search, caching or native execution.
    """
    if (type(person_count) is not int or not 0 <= person_count <= 2**31
            or type(category_code) is not int or not 0 <= category_code < 6
            or not isinstance(person_indices, (set, frozenset))
            or not 1 <= len(person_indices) <= MAX_PEOPLE
            or any(type(i) is not int or not 0 <= i < person_count for i in person_indices)):
        raise ValueError('Invalid current statistics PERSON cohort or category')
    if (type(reader.size) is not int or not len(ENVELOPE) + 17 <= reader.size <= MAX_COMPONENT_BYTES
            or reader.offset != 0):
        raise ValueError('Unsupported current statistics component size or incoming offset')
    wire = _Wire(reader)
    if wire.take(8) != ENVELOPE:
        raise ValueError('Unsupported current statistics envelope or component version')
    seen = set()
    selected = {}
    count = additional_total = raw_item_total = 0
    while True:
        marker_at = wire.offset
        marker = wire.number('B')
        if marker == 0:
            break
        if marker != 1 or count >= MAX_RECORDS:
            raise ValueError('Unsupported current record marker or source record work budget')
        start = wire.offset
        owner, = struct.unpack_from('<i', wire.take(20))
        if not 0 <= owner < person_count:
            raise ValueError('Current statistics owner is outside the same-snapshot PERSON table')
        if owner in seen:
            raise ValueError('Duplicate current statistics PERSON owner; single-owner comparison is ambiguous')
        seen.add(owner)
        wanted = owner in person_indices
        primary = None
        presence = []
        for slot in range(8):
            present, decoded = _nullable(wire, wanted and slot == category_code)
            presence.append(bool(present))
            if wanted and slot == category_code:
                primary = decoded
        wire.take(20)  # Transposed raw native+74..87; no interpreted fields.
        n = wire.number('I')
        if n > MAX_ADDITIONAL_TEAMS:
            raise ValueError('Additional-team statistics exceed supported work budget')
        additional_total += n
        for _ in range(n):
            _team_reference(wire)
            for _ in range(6):
                _nullable(wire, False)
        items = wire.number('I')
        if items > MAX_RAW_ITEMS:
            raise ValueError('Current raw-item vector exceeds supported work budget')
        raw_item_total += items
        for _ in range(items):
            if wire.number('B') != 2:
                raise ValueError('Unsupported current raw-item version')
            wire.take(7)
        if wire.number('B') != 16:
            raise ValueError('Unsupported current packed-value count')
        packed = wire.take(48)
        if any(packed[i] > 127 or packed[i + 1] > 31 or packed[i + 2] > 15
               for i in range(0, 48, 3)):
            raise ValueError('Current packed values violate native writer masks')
        if wanted:
            selected[owner] = {
                'state': 'available' if primary is not None else 'serialized_null_category',
                'source_record_ordinal': count,
                'source_span': {'start': marker_at, 'body_start': start, 'end': wire.offset},
                'statistics': primary,
                'primary_slot_presence': presence[:6],
                'unlabelled_slot_presence': presence[6:],
                'additional_team_record_count': n,
            }
        count += 1
    footer_at = wire.offset
    footer = list(struct.unpack('<4I', wire.take(16)))
    if wire.offset != wire.size:
        raise ValueError('Trailing bytes after current statistics manager footer')
    for index in person_indices - selected.keys():
        selected[index] = {'state': 'no_serialized_current_entry', 'statistics': None,
                           'source_record_ordinal': None, 'source_span': None}
    return selected, {
        'state': 'complete_current_component', 'complete_source': True,
        'physical_record_count': count, 'distinct_owner_count': len(seen),
        'duplicate_owner_count': 0, 'all_owner_indices_inside_declared_PERSON_table': True,
        'additional_team_record_count': additional_total, 'raw_item_count': raw_item_total,
        'end': wire.offset, 'raw_sha256': wire.digest.hexdigest(),
        'manager_footer': {'source_offset': footer_at, 'native_08_0c_10_14_u32': footer},
        'wire_profile': WIRE_PROFILE, 'wire_profile_is_conditional': True,
        'native_loader_globals_proved': False,
        'additional_TEAM_reference_identities_resolved': False,
    }


def _names(target):
    """Display witnesses cannot change a numeric statistics lookup or ranking."""
    unique = {}
    for candidate in target['candidates']:
        if candidate['identity']['stored_index'] != target['person_index']:
            raise ValueError('Saved name candidate has a different PERSON index')
        fields = []
        for ns, index, value in zip(('first', 'second', 'common'), candidate['name_indices'],
                                     candidate['names'], strict=True):
            state = ('null_reference' if index == -1 else 'unavailable' if value is None else
                     'budget' if value.get('state') == 'budget' else
                     'stored_text' if value.get('text') is not None else 'unsupported_encoding')
            fields.append({'namespace': ns, 'stored_index': index, 'state': state,
                           'text': None if value is None else value.get('text')})
        item = {
            'identity': candidate['identity'],
            'names': {field['namespace']: field['text'] for field in fields},
            'name_fields': fields, 'name_indices': candidate['name_indices'],
            'source_common_start': candidate.get('common_start'),
            'source_identity_offset': candidate.get('identity_offset'),
            'source_end': candidate.get('end'),
        }
        unique.setdefault(json.dumps(item, sort_keys=True), item)
    complete = target['search_complete']
    state = ('incomplete' if not complete else 'unavailable' if not unique else
             'unique_candidate' if len(unique) == 1 else 'ambiguous_candidates')
    values = list(unique.values())
    return {
        'state': state, 'search_complete': complete,
        'candidate_count': len(values), 'candidate_projection_complete': len(values) <= MAX_NAME_CANDIDATES,
        'candidates': values[:MAX_NAME_CANDIDATES],
        'selected': values[0] if state == 'unique_candidate' else None,
        'budget_reasons': target['budget_reasons'],
        'scope': 'same-snapshot common-PERSON suffix/name witnesses; not complete PERSON certification',
    }


def _classify(person, minimum_minutes):
    state = person['current']['state']
    stats = person['current']['statistics']
    if state != 'available':
        return state
    if stats['minutes'] < 0:
        return 'negative_minutes'
    if stats['minutes'] == 0:
        return 'no_playing_time'
    if stats['minutes'] < minimum_minutes:
        return 'below_minimum_minutes'
    if stats['goals'] is None or stats['assists'] is None:
        return 'missing_goals_or_assists'
    return 'eligible'


def compare_current_statistics(filename, person_indices, expected_snapshot_id, *,
                               category_code=1, minimum_minutes=270, directory=None):
    """Rank one exact numeric cohort by stored primary-category G+A/90.

    The supplied cohort may come from a saved TEAM roster, but the primary
    category is per PERSON and does not establish statistics for that TEAM.
    All source records are examined once; absence never becomes a zero counter.
    """
    if (not isinstance(person_indices, list) or not 1 <= len(person_indices) <= MAX_PEOPLE
            or any(type(i) is not int or not 0 <= i < 2**31 for i in person_indices)):
        raise ValueError('Supply 1 to32 same-snapshot PERSON indices')
    if type(category_code) is not int or not 0 <= category_code < len(CATEGORIES):
        raise ValueError('Supply a native category_code from0 to5')
    if type(minimum_minutes) is not int or not 1 <= minimum_minutes <= 32767:
        raise ValueError('minimum_minutes must be an integer within1..32767')
    if (type(expected_snapshot_id) is not str or len(expected_snapshot_id) != 64
            or any(c not in '0123456789abcdef' for c in expected_snapshot_id)):
        raise ValueError('Supply the exact expected_snapshot_id for the saved PERSON indices')
    unique = list(dict.fromkeys(person_indices))
    with checked_name_source(filename, expected_snapshot_id, directory) as (data, layout, pin, metadata):
        if any(index >= layout.person_count for index in unique):
            raise ValueError('Requested PERSON index is outside the same-snapshot table')
        targets = saved_person_candidates.search_candidates(data, layout, unique)
        named = {target['person_index']: _names(target) for target in targets}
        if len(named) != len(targets) or set(named) != set(unique):
            raise ValueError('Saved name lookup did not return the exact requested cohort')
        with snapshot_catalog.checked_snapshot(filename, directory=directory) as (handle, entries, identity):
            if snapshot_catalog.snapshot_id(identity) != pin:
                raise ValueError('Current statistics snapshot differs from PERSON source')
            root = entries[0].path.split('/')[0]
            source = [entry for entry in entries if entry.path == root + '/rgman/player_stats.dat']
            if len(source) != 1:
                raise ValueError('Saved snapshot requires one root rgman/player_stats.dat')
            with saved_component_stream.open_component(handle, source[0]) as reader:
                selected, coverage = read_current(reader, set(unique), layout.person_count, category_code)
                if reader.source.read(1) != b'' or not reader.source.finished:
                    raise ValueError('Current statistics frame did not end at its declared extent')
            coverage['component_path'] = source[0].path
            coverage['uncompressed_size'] = source[0].uncompressed_size
        people = []
        eligible = []
        for index in unique:
            current = selected[index]
            person = {'person_index': index, 'name_context': named[index], 'current': current,
                      'state': None, 'rank': None, 'goal_contributions': None,
                      'goal_contributions_per90': None, 'per90_exact': None}
            person['state'] = _classify(person, minimum_minutes)
            stats = current['statistics']
            if stats is not None and stats['goals'] is not None and stats['assists'] is not None:
                person['goal_contributions'] = stats['goals'] + stats['assists']
                if stats['minutes'] > 0:
                    rate = Fraction(90 * person['goal_contributions'], stats['minutes'])
                    person['per90_exact'] = {'numerator': rate.numerator, 'denominator': rate.denominator}
                    person['goal_contributions_per90'] = float(rate)
            if person['state'] == 'eligible':
                eligible.append(person)
            people.append(person)
        eligible.sort(key=lambda row: (-Fraction(**row['per90_exact']), row['person_index']))
        previous = None
        rank = 0
        for position, person in enumerate(eligible, 1):
            rate = Fraction(**person['per90_exact'])
            if rate != previous:
                rank, previous = position, rate
            person['rank'] = rank
        result = {
            'source': 'on-disk save snapshot', 'filename': filename, 'snapshot_id': pin,
            'saved_metadata': metadata, 'requested_person_indices': person_indices,
            'evaluated_person_indices': unique, 'people': people,
            'ranking_person_indices': [row['person_index'] for row in eligible],
            'eligible_count': len(eligible), 'evaluated_count': len(people),
            'filters': {'category_code': category_code, 'category_name': CATEGORIES[category_code],
                        'minimum_minutes': minimum_minutes},
            'metric': 'stored_primary_category_goals_plus_assists_per90',
            'coverage': coverage,
            'evidence_scope': {
                'statistics': 'serialized current primary category per PERSON; selected-team attribution not established',
                'cohort': 'supplied exact same-snapshot PERSON indices; duplicate requests evaluated once',
                'ordering': 'exact rational descending; competition ranks; PERSON index orders equal rates',
                'ranking_eligibility': 'eligible means meeting these statistical ranking criteria; not match, registration or transfer eligibility',
                'absence': 'complete source proves no serialized entry only; not zero appearances or eligibility',
                'season_year': None, 'season_year_state': 'not_established_from_this_component',
                'archived_completed_seasons_included': False, 'starting_history_included': False,
                'native_execution': False, 'whole_PERSON_identity_coverage': False,
            },
        }
        if len(json.dumps(result, ensure_ascii=True).encode()) > MAX_RESPONSE_BYTES:
            raise ValueError('Saved current statistics response exceeds output budget')
    return result
