"""Saved specialized TEAM/NATIONAL_TEAM records for source3754/minor9.

The caller establishes the specialized factory profile and table ownership.
Reference words are same-file canonical table indices, never native IDs or live
references. Stored roster membership does not establish ownership or eligibility.
"""
import struct

MAX_DATABASE_SLOTS = 2_000_000
MAX_ROSTER_SLOTS = 65_535
MAX_NAME_BYTES = 8192


def _national_prefix(reader):
    # 13CE874: fixed native fields, then a signed-i8 population of ten-byte rows.
    reader.skip(53)
    count = reader.i8()
    reader.skip(max(count, 0) * 10)


def _team_prefix(reader, include_roster, match_person_indices):
    # 175A16C: fields before TEAM+0x38, its u16 count and signed-i32 PERSON keys.
    reader.skip(33)
    count = reader.u16()
    if type(count) is not int or not 0 <= count <= MAX_ROSTER_SLOTS:
        raise ValueError('Saved TEAM roster exceeds native count bounds')
    person_indices = [] if include_roster else None
    unverified = [] if include_roster else None
    matched = [] if match_person_indices is not None else None
    if include_roster or match_person_indices:
        for slot, (word,) in enumerate(struct.iter_unpack('<i', reader.take(count * 4))):
            if include_roster:
                person_indices.append(None if word == -1 else word)
                if word < -1:
                    unverified.append({'native_slot': slot, 'raw_word': word})
            if word >= 0 and match_person_indices is not None and word in match_person_indices:
                matched.append({'slot_index': slot, 'person_index': word})
    else:
        reader.skip(count * 4)
    reader.skip(18)
    return count, person_indices, unverified, matched


def read_team(reader, ordinal, kind, *, include_roster=True, match_person_indices=None):
    """Consume a verified kind10/11 row, preserving stored names and roster order.

    Owner+0x2F selects CLUB for zero and NATIONAL_TEAM_CONTAINER otherwise.
    FFFFFFFF is the proved null reference. Other negative PERSON words remain
    visible and are flagged as unverified; no record is silently dropped.

    The caller validates match_person_indices members once per query as exact
    nonnegative signed-i32 table ordinals. A supplied frozenset adds matching
    native slots in serialized order, preserving duplicates, independently of
    include_roster. No full roster or per-slot dictionaries are built for misses
    when include_roster is False. None preserves the existing output shape.
    """
    if type(ordinal) is not int or not 0 <= ordinal < MAX_DATABASE_SLOTS:
        raise ValueError('Invalid saved TEAM ordinal')
    if type(kind) is not int or kind not in (10, 11):
        raise ValueError('Unsupported saved specialized TEAM subtype')
    if type(include_roster) is not bool:
        raise ValueError('Invalid TEAM roster selection')
    if match_person_indices is not None and type(match_person_indices) is not frozenset:
        raise ValueError('Invalid TEAM person match selection')
    if kind == 11:
        _national_prefix(reader)
    roster_count, person_indices, unverified, matched = _team_prefix(
        reader, include_roster, match_person_indices
    )

    team_type = reader.i8()
    owner_kind_code = reader.u8()
    reader.skip(4)
    owner_word = reader.u32()
    name = reader.text(max_bytes=MAX_NAME_BYTES)
    reader.skip(1)
    short_name = reader.text(max_bytes=MAX_NAME_BYTES)
    reader.skip(1)
    stored_index, native_id, secondary_id = reader.u32(), reader.u32(), reader.u32()
    if stored_index != ordinal:
        raise ValueError('Saved TEAM database ordinal mismatch')
    result = {
        'database_index': ordinal,
        'native_id': native_id,
        'secondary_id': secondary_id,
        'team_type_code': team_type,
        'owner_kind': 'club' if owner_kind_code == 0 else 'national',
        'owner_index': None if owner_word == 0xffffffff else owner_word,
        'name': name,
        'short_name': short_name,
        'roster_count': roster_count,
    }
    if owner_word != 0xffffffff and owner_word & 0x80000000:
        result['owner_index_state'] = 'unverified_negative_word'
    if person_indices is not None:
        result['person_indices'] = person_indices
        if unverified:
            result['unverified_negative_person_indices'] = unverified
    if matched is not None:
        result['matched_person_slots'] = matched
    return result
