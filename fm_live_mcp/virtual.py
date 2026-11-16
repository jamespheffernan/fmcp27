"""Read existing virtual-player profiles without invoking game functions.

The compact record indexes VIRTUAL_MANAGER's generated ACTUAL_PLAYER cache.
Cache identity must match the compact record; missing/evicted profiles fail.
All offsets require the verified plugin fingerprint and runtime layout.
"""
import struct

from . import players, world, player_profile, personality

MANAGER_ROOT = 0x56A68A8
PERSON_RVA = 0x55CB9F8
BASE_PROFILE_FIELDS = ('name', 'display_name', 'birth_date', 'attributes')


class ProfileUnavailableError(ValueError):
    """Expected rich-profile absence from the proved negative cache-index branch."""


def decode(read, address, tables, include_clubs=False, include_profile=False, profile_policy='required'):
    if type(profile_policy) is not str or profile_policy not in ('required', 'available'):
        raise ValueError("profile_policy must be 'required' or 'available'")
    if profile_policy == 'required':
        return _decode_required(read, address, tables, include_clubs, include_profile)

    from . import virtual_identity

    core = virtual_identity.inspect(read, address, tables)
    raw = core['_raw']
    reason = 'negative_cache_index' if core['cache_index'] < 0 else None
    if reason is None:
        try:
            record, _ = _decode_required(read, address, tables, include_clubs, include_profile, expected_raw=raw)
        except players.VirtualCacheIdentityMismatchError:
            # Compact PERSON/table membership was proved above. Reject every cached
            # field, preserving only that independently checked stored identity.
            reason = 'cache_identity_mismatch'
    if reason is not None:
        record = {field: None for field in BASE_PROFILE_FIELDS}
        record.update(record_kind='virtual', native_identity=core['native_identity'],
                      profile_state='identity_only', profile_unavailable_reason=reason,
                      field_sources={'native_identity': 'stored_direct',
                                     **{field: 'unavailable_from_verified_sources' for field in BASE_PROFILE_FIELDS}},
                      unavailable_fields=list(BASE_PROFILE_FIELDS),
                      evidence=('native_virtual_stored_identity_with_negative_cache_index' if reason=='negative_cache_index'
                                else 'native_virtual_stored_identity_with_rejected_profile_cache'))
        for requested, field in ((include_clubs, 'clubs'), (include_profile, 'profile')):
            if requested:
                record[field] = None
                record['unavailable_fields'].append(field)
                record['field_sources'][field] = 'unavailable_from_verified_sources'
    else:
        record.update(native_identity=core['native_identity'], profile_state='cached',
                      field_sources={'native_identity': 'stored_direct',
                                     **{field: 'cached_generated_profile' for field in BASE_PROFILE_FIELDS}},
                      unavailable_fields=[])
        if include_clubs:
            record['field_sources']['clubs'] = 'identity_checked_cached_profile_and_team_links'
        if include_profile:
            record['field_sources']['profile'] = 'cached_generated_profile_with_verified_native_defaults'
    if read(address, 64) != raw:
        raise ValueError('Virtual profile availability changed during read')
    return record, core['identity']


def _decode_required(read, address, tables, include_clubs=False, include_profile=False, expected_raw=None):
    base = tables[0] - players.RVA[0]
    world.typed(read, base, address, "virtual_player")
    raw = read(address, 64)
    if expected_raw is not None and raw != expected_raw:
        raise ValueError('Virtual profile availability changed during read')
    person_table = base + PERSON_RVA
    if players.u64(raw, 0x20) != person_table:
        raise ValueError("Virtual player person type changed")
    metadata = read(person_table - 16, 16)
    if struct.unpack_from('<q', metadata)[0] != -0x20:
        raise ValueError("Virtual player person displacement changed")
    info = players.u64(metadata, 8)
    name = players.u64(read(info + 8, 8))
    expected = b'N2db14VIRTUAL_PLAYERE\0'
    if read(name, len(expected)) != expected:
        raise ValueError("Virtual player person RTTI changed")
    identity, secondary = struct.unpack_from('<II', raw, 0x2C)
    if not identity:
        raise ValueError("Virtual player primary identity is missing")
    index = struct.unpack_from('<h', raw, 0x14)[0]
    if index < 0:
        raise ProfileUnavailableError(
            "Virtual expanded profile is unavailable from the verified cache; "
            "use profile_policy='available' for checked stored identity")
    manager = world.pointer(read, base + MANAGER_ROOT)
    world.typed(read, base, manager, "virtual_manager")
    start, end, capacity = struct.unpack('<QQQ', read(manager + 8, 24))
    if (start < 4096 or any(x % 8 for x in (start, end, capacity))
            or not start <= end <= capacity or capacity - start > 4096 * 8
            or index >= (end - start) // 8):
        raise ValueError("Virtual profile cache bounds rejected")
    cached = world.pointer(read, start + index * 8)
    if include_profile:
        player_profile.verify_getters(read, base, players.u64(raw), player_profile.VIRTUAL_GETTERS)
        personality.verify_virtual_cache(read, base, players.u64(raw, 0x20), cached)
    try:
        record, profile_identity = players._decode_record(read, cached, tables, virtual_identity=identity, include_profile=include_profile)
    except players.VirtualCacheIdentityMismatchError:
        if read(address, 64) != raw or world.pointer(read, start + index * 8) != cached:
            raise ValueError('Virtual profile changed during cache identity rejection')
        raise
    record['record_kind'] = 'virtual'
    record['evidence'] = 'native_virtual_player_with_identity_checked_cached_profile'
    if include_clubs:
        if any(players.u64(read(cached + offset, 8)) for offset in (0x2F0, 0x2F8)):
            raise ValueError("Unexpected contract on a virtual profile")
        team = world.pointer(read, cached + 0x128)
        world.typed(read, base, team, 'team')
        if read(team + 8, 4) != raw[8:12]:
            raise ValueError("Virtual player team identity disagrees")
        club_address = world.pointer(read, team + 0x30)
        club, _ = world.club(read, base, club_address)
        if team not in world.vector(read, club_address + 0x18, 64):
            raise ValueError("Virtual player team is absent from club teams")
        record['clubs'] = {'contract_club': None, 'current_club': None,
                           'roster_club': club, 'on_loan': False,
                           'contract_state': 'virtual_uncontracted',
                           'evidence': 'virtual_profile_without_full_or_loan_contract'}
    # The caller also verifies its whole ReadSet, including all pointer chains.
    if read(address, 64) != raw or world.pointer(read, start + index * 8) != cached:
        raise ValueError("Virtual profile changed during read")
    return record, ('virtual', identity, *profile_identity[1:], secondary)
