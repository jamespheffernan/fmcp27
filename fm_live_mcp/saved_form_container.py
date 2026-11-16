"""Locate the153E56C groups payload from an already reached PLAYER+F0.

This uses the pinned current-writer3754/9 conditional reference profile.
It preserves physical count/order and returns absence only after reading the
actual+58 absence marker. Unsupported branches are explicit measured stops.
"""
from .saved_form_children import (
    BoundedReader, UnsupportedFormChild, skip_optional30, skip_optional38,
    skip_optional40, skip_optional48, skip_optional50, skip_vector00_row,
)

WIRE_PROFILE = 'source3754_minor9_F0_local_reference_profile'
MAX_VECTOR_ROWS = 512  #Both native counts are u8; offline cumulative work bound.


def locate_form_groups(data, start, limit, *, source_major=3754, source_minor=9,
                       reference_profile=WIRE_PROFILE, max_vector_rows=MAX_VECTOR_ROWS):
    """Return present/absent/stopped, with absolute offsets and no form-row scan.

    ``end`` is before the groups when present, after the actual absence marker
    when absent, and the first unparsed byte when stopped. Truncation, malformed
    producer markers/versions and invalid bounds raise ValueError. This does not
    validate a PERSON identity or any bytes following the form groups.
    """
    if (type(source_major) is not int or type(source_minor) is not int
            or (source_major, source_minor) != (3754, 9)):
        raise ValueError('Unsupported saved form container source')
    if reference_profile != WIRE_PROFILE:
        raise ValueError('Unsupported saved form container reference profile')
    if type(max_vector_rows) is not int or not 0 <= max_vector_rows <= 512:
        raise ValueError('Invalid saved form container row budget')
    reader = BoundedReader(data, start, limit)
    counts = {}
    markers = []
    checks = []

    def result(state, *, native=None, reason=None):
        return {
            'state': state, 'start': start, 'end': reader.offset,
            'form_start': reader.offset if state == 'present' else None,
            'form_present': True if state == 'present' else False if state == 'absent' else None,
            'next_native_reader': native, 'stop_reason': reason,
            'counts': counts, 'presence_markers': markers,
            'validated_children': checks, 'wire_profile': WIRE_PROFILE,
            'wire_profile_is_conditional': True,
            'native_reader': '0x11E7C4C', 'native_writer': '0x11E9F30',
            'complete_person': False, 'unread_form_suffix': True,
            'reference_identity_resolution': False,
        }

    total_rows = 0
    try:
        count = reader.u8()
        counts['vector_00'] = count
        total_rows += count
        if total_rows > max_vector_rows:
            return result('stopped', native='0x154E184', reason='offline_vector_row_budget')
        for index in range(count):
            child_start = reader.offset
            skip_vector00_row(reader)
            checks.append({'kind': 'vector_00', 'native_index': index,
                           'start': child_start, 'end': reader.offset})
        count = reader.u8()
        counts['vector_18'] = count
        total_rows += count
        if total_rows > max_vector_rows:
            return result('stopped', native='0x405D598', reason='offline_vector_row_budget')
        if count:
            return result('stopped', native='0x405D598', reason='positive_vector18_unparsed')
        for name, callback in (
            ('optional_30', skip_optional30), ('optional_38', skip_optional38),
            ('optional_40', skip_optional40), ('optional_48', skip_optional48),
            ('optional_50', skip_optional50),
        ):
            marker_offset = reader.offset
            present = reader.presence(name)
            markers.append({'kind': name, 'offset': marker_offset, 'value': present})
            if present:
                child_start = reader.offset
                callback(reader)
                checks.append({'kind': name, 'start': child_start, 'end': reader.offset})
        marker_offset = reader.offset
        present = reader.presence('153E56C form')
        markers.append({'kind': 'optional_58', 'offset': marker_offset, 'value': present})
        return result('present' if present else 'absent')
    except UnsupportedFormChild as error:
        reader.offset = error.offset
        return result('stopped', native=error.native_reader, reason=error.reason)
