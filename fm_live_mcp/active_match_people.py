"""Canonical roster joins for resident engine player objects.

This is an engine snapshot, not a displayed-match participation source. The
caller owns fixture binding, roster decoding, ReadSet verification and epoch.
No historical event actor identity can be inferred from a current array index.
"""
import struct


def _read(read, address, size):
    value = read(address, size)
    if not isinstance(value, bytes) or len(value) != size:
        raise ValueError('Incomplete active-match player read')
    return value


def _u64(read, address):
    return struct.unpack('<Q', _read(read, address, 8))[0]


def _type(read, base, address, table, name):
    if address < 4096 or address % 8 or _u64(read, address) != base + table:
        raise ValueError('Active-match player source type changed')
    displacement, info = struct.unpack('<qQ', _read(read, base + table - 16, 16))
    if displacement != 0 or info < 4096:
        raise ValueError('Active-match player RTTI changed')
    text = _u64(read, info + 8)
    if _read(read, text, len(name) + 1) != name + b'\0':
        raise ValueError('Active-match player RTTI changed')


def inspect(read, base, engine, canonical_rosters, *, identity_only=False):
    """Join +20 only to same-side, caller-verified canonical PERSON subobject pointers.

    canonical_rosters maps side index to {PERSON subobject address: public identity dict}.
    An unmatched pointer stays unknown; a cross-side pointer is never joined.
    """
    _type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    rows = []
    for side_index, offset in enumerate((0x15370, 0x15378)):
        side = _u64(read, engine + offset)
        if side < 4096 or side % 8:
            raise ValueError('Invalid active-match side pointer')
        pointers = struct.unpack('<26Q', _read(read, side + 0x140, 208))
        roster = canonical_rosters.get(side_index, {})
        for index, address in enumerate(pointers):
            row = {'side_index': side_index, 'engine_array_index': index,
                   'identity_state': 'null_object', 'person': None,
                   'on_pitch': None, 'display_time_participation': None,
                   'participation_state': 'unsupported',
                   'scope': 'resident_engine_snapshot_not_display_time'}
            if address:
                _type(read, base, address, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
                if _u64(read, address + 0x280) != engine:
                    raise ValueError('Active-match player engine mismatch')
                owner_side = _u64(read, address + 0x288)
                if owner_side == 0:
                    row['identity_state'] = 'side_owner_absent_unclassified'
                    rows.append(row)
                    continue
                if owner_side != side:
                    raise ValueError('Active-match player side mismatch')
                player = _u64(read, address + 0x20)
                identity = roster.get(player)
                row.update(identity_state='canonical_same_team_roster_pointer_join' if identity is not None else 'unmatched_canonical_roster_pointer',
                           person=dict(identity) if identity is not None else None)
                if not identity_only:
                    row.update(tactics_index_raw=_read(read, address + 0x1E51, 1)[0],
                           with_ball_position_mask=struct.unpack('<I', _read(read, address + 0xCD8, 4))[0],
                           without_ball_position_mask=struct.unpack('<I', _read(read, address + 0xDB0, 4))[0],
                           native_status_unclassified=_read(read, address + 0x1E26, 1)[0])
            rows.append(row)
    return {'source': 'resident_engine_player_to_canonical_roster', 'rows': rows,
            'historical_event_actor_join': 'unsupported',
            'on_pitch_semantics': 'not_established', 'display_time_binding': 'not_established'}


def canonical_rosters(read, base, engine):
    """Build compact PERSON identities in the caller's single ReadSet.

    No Bridge/API calls or attribute/profile cache reads. Only current side TEAM
    membership, typed PERSON table membership and proved name fields are used.
    Virtual PERSON identity remains usable without a generated name/profile.
    """
    from . import database, players, virtual_identity, world
    _type(read, base, engine, 0x55FA258, b'10GAME_MATCH')
    people = database.table(read, base, 'people')
    result = {}
    for side_index, offset in enumerate((0x15370, 0x15378)):
        side = _u64(read, engine + offset)
        team = _u64(read, side + 0xB8)
        world.typed(read, base, team, 'team')
        roster = set(world.vector(read, team + 0x38, 256))
        identities = {}
        for match_player in struct.unpack('<26Q', _read(read, side + 0x140, 208)):
            if not match_player:
                continue
            _type(read, base, match_player, 0x569EE68, b'N7simatch12MATCH_PLAYERE')
            person = _u64(read, match_player + 0x20)
            if not person:
                continue
            header = _read(read, person, 20)
            table, index, native, secondary = struct.unpack('<QIII', header)
            layouts = {base + players.RVA[2]: (0x388, players.RVA[0], 'actual'),
                       base + players.STAFF_RVA[2]: (0x480, players.STAFF_RVA[0], 'player_staff'),
                       base + virtual_identity.PERSON_RVA: (0x20, world.TYPES['virtual_player'][0], 'virtual')}
            layout = layouts.get(table)
            if layout is None or not native or index >= people['count']:
                continue
            displacement, primary_table, kind = layout
            primary = person - displacement
            if primary not in roster or _u64(read, primary) != base + primary_table:
                continue
            metadata_displacement = struct.unpack('<q', _read(read, table - 16, 8))[0]
            if metadata_displacement != -displacement:
                raise ValueError('Canonical match PERSON displacement changed')
            if _u64(read, people['start'] + index * 8) != person:
                continue
            if kind == 'virtual':
                checked = virtual_identity.inspect(read, primary, tuple(base+r for r in players.RVA))
                if checked['stored_team_index'] != struct.unpack('<I', _read(read, team+8,4))[0]:
                    continue
                name = None
                name_state = 'unavailable_without_generated_profile'
            else:
                delta = 0xF8 if kind == 'player_staff' else 0
                first = players.name_part(read, _u64(read, primary + 0x298 + delta))
                last = players.name_part(read, _u64(read, primary + 0x2A0 + delta))
                common = players.common_name(read, _u64(read, primary + 0x2A8 + delta))
                name = common or ' '.join(p for p in (first,last) if p) or None
                name_state = 'stored_direct' if name else 'unavailable'
            identities[person] = {'name': name, 'name_state': name_state,
                'record_kind': kind,
                'native_identity': {'database_index': index, 'native_id': native,
                    'random_id': None if native == secondary else secondary}}
        result[side_index] = identities
    return result


def _inspect_canonical_team(read, base, engine, *, identity_only=False):
    """Original TEAM-only projection for explicitly versioned old evidence."""
    return inspect(read, base, engine, canonical_rosters(read, base, engine), identity_only=identity_only)


def inspect_canonical(read, base, engine, *, identity_only=False):
    """One caller-owned scope, with a native PERSON fallback for unmatched rows."""
    from .native_match_stats_person import add_global_identities
    result = _inspect_canonical_team(read, base, engine, identity_only=identity_only)
    return add_global_identities(read, base, engine, result)


def engine_participation(status, flags, on, off, sent):
    """Classify only pinned native transitions; no displayed-clock inference."""
    if status == 1 and not off and not sent:
        return ('substitute_on_pitch' if flags & 32 and on else 'on_pitch', True)
    if status == 3 and off:
        return ('substituted_off', False)
    if status == 2 and sent:
        return ('sent_off', False)
    if status == 8 and flags & 32 and not on:
        return ('unused_substitute', False)
    return ('unknown', None)


def add_engine_participation(read, base, engine, result):
    """Add engine-frontier state using typed, PERSON-reconciled player stats.

    Native on/off writers and simulation consumer are pinned. A displayed-clock
    lineup reconstruction needs a separate ordered substitution/event source.
    """
    for rva, expected in PARTICIPATION_SPANS:
        if _read(read, base+rva, len(expected)) != expected:
            raise ValueError('Active-match participation native source changed')
    for row in result['rows']:
        row.update(engine_participation='unknown', engine_on_pitch=None,
                   engine_participation_source='unavailable', native_participation=None)
        if not row['person']:
            continue
        side = _u64(read, engine + (0x15370 if row['side_index'] == 0 else 0x15378))
        address = _u64(read, side + 0x140 + row['engine_array_index']*8)
        stats = _u64(read, address + 0x1880)
        if not stats:
            continue
        _type(read, base, stats, 0x55FA800, b'23GAME_MATCH_PLAYER_STATS')
        index = struct.unpack('<I', _read(read, stats+0x18, 4))[0]
        if index != row['person']['native_identity']['database_index']:
            row['engine_participation_source'] = 'stats_person_index_mismatch'
            continue
        flags,on,off,sent = (_read(read,stats+offset,1)[0] for offset in (0x5C,0xAF,0xAA,0xB2))
        state,on_pitch = engine_participation(row['native_status_unclassified'],flags,on,off,sent)
        row.update(engine_participation=state,engine_on_pitch=on_pitch,
                   engine_participation_source='typed_stats_person_index_and_pinned_native_transitions',
                   native_participation={'substitute_flag':bool(flags&32),'on_minute':on,
                                         'off_minute':off,'sent_off_minute':sent})
    result['on_pitch_semantics'] = 'guarded_engine_frontier_only'
    return result


# Entry AF→status1; off AA→status3; sending-off B2→status2;
# status1 simulation phase-position consumer; concrete stats→named form fields.
PARTICIPATION_SPANS = (
    (0x4a79b58, bytes.fromhex('96424cf901074ab9e0031baa53d8e897c0be023988424cf9f82b00f9098f4ab9095500b9e92259b9097100b9e91f8052a9ca383929008052a99a3839f51b00f9bc4639391c61023989ce4bb9')),
    (0x4563764, bytes.fromhex('6a424cf949a902391f81296bac5200540800805248b10239488f4ab9485900b968008052889a3839e81f80528846393948610239')),
    (0x456443c, bytes.fromhex('68424cf900c90239caee8e920a11b1f26a7f2a9b4afd60d34a011b0b4b7d07536a7d4a0b4a0500114a1d00134a01006bac1c00540a0080520ab10239095900b949008052899a3839e9322b91290140f9338901f9e91f80528946393909610239e90240b9')),
    (0x451abec, bytes.fromhex('a86a78f817054091e89a78391f05007121ffff54e846b9391345399b742240f9d41000b489021a8a68aa40a94b0108eb800100546bfd4393')),
    (0x153faf8, bytes.fromhex('aabe42390a470039a8aa4239084b0039acc242390c4f0039abca42390b530039')),
    (0x153f5ac, bytes.fromhex('f50000b4a872413968002836a8be4239080200341c008052')),
)


def inspect_actor_bindings(read, base, engine, *, expected_match_unique_id):
    """Current resident original-roster slots, never current formation indices.

    Caller must bind engine to the same checked fixture/playback and recheck one
    shared ReadSet. This does not establish event time or display participation.
    """
    if type(expected_match_unique_id) is not int or not 0 < expected_match_unique_id < 1 << 64:
        raise ValueError('A checked nonzero official match unique ID is required')
    _type(read,base,engine,0x55FA258,b'10GAME_MATCH')
    if _u64(read,engine+0x20) != expected_match_unique_id:
        raise ValueError('Active actor official match identity changed')
    for rva,expected in ACTOR_SLOT_SPANS:
        if _read(read,base+rva,len(expected)) != expected:
            raise ValueError('Active actor roster-slot native source changed')
    # This public actor/event contract still requires the original TEAM join.
    # Global native-statistics fallback has no separately admitted event scope.
    people=_inspect_canonical_team(read,base,engine,identity_only=True)
    resolved=[];unresolved=[];used=set()
    for row in people['rows']:
        side_index,index=row['side_index'],row['engine_array_index']
        identity=row['person']
        reason=None
        side=_u64(read,engine+0x15370+side_index*8)
        address=_u64(read,side+0x140+index*8)
        if not address or identity is None:
            reason=row['identity_state']
        else:
            slot=_read(read,address+0x1E27,1)[0]
            if slot != index:
                reason='native_original_roster_slot_differs_from_checked_array_index'
            else:
                stats=_u64(read,address+0x1880)
                if not stats:
                    reason='typed_match_player_stats_absent'
                else:
                    _type(read,base,stats,0x55FA800,b'23GAME_MATCH_PLAYER_STATS')
                    person_word=struct.unpack('<I',_read(read,stats+0x18,4))[0]
                    if person_word != identity['native_identity']['database_index']:
                        reason='typed_stats_person_index_mismatch'
        if reason:
            unresolved.append({'side_index':side_index,'engine_array_index':index,'reason':reason})
            continue
        key=side_index,slot
        if key in used:
            raise ValueError('Duplicate active original roster slot')
        used.add(key)
        resolved.append({'side_index':side_index,'stored_player_slot':slot,
            'canonical_person_id':identity['native_identity']['native_id'],
            'person_index_word':identity['native_identity']['database_index'],
            'person_name':identity.get('name'),
            'identity_state':'canonical_PERSON_table_same_team_and_typed_stats',
            'name_state':identity.get('name_state','stored_direct')})
    return {'state':'validated_native_stored_slots',
            'official_match_unique_id':expected_match_unique_id,'players':resolved,
            'unresolved':unresolved,
            'slot_policy':'Native original roster slot +1E27, independently checked against array position and typed stats PERSON; current tactics index +1E51 is never used.',
            'temporal_scope':'Identity binding only; neither actor event time nor displayed participation is inferred.'}


# Original-index setup, matching concrete stats source, official chart
# tracking-key/player-vector consumer, CBE primary actor producer/selector.
ACTOR_SLOT_SPANS = (
    (0x4512c24,bytes.fromhex('884641f9080d138b1ba140f97c074091939f38397f2e00f168329f5a884b393988473939')),
    (0x4512d7c,bytes.fromhex('883e8b39694341f90ad289522a00a07229696af8280d088b083540f9092941f9297973f869430cf9')),
    (0x1a6764,bytes.fromhex('9703c039e0031aaae10317aae20315aa47c01b95f90300aae0feffb428a740a91f0109eb80feff54e87e40936a2e41f9692a41f94a0109cb1f0d8aebc2fdff54377968f897fdffb4')),
    (0x488ab3c,bytes.fromhex('88da40796852027888ae4139689e0039e00314aae73f0394c000003768aa40391f1d0071600000541f31007161000054951a40f9950400b588aa413968a20039')),
    (0x4894fb4,bytes.fromhex('e99e40393f01186be10100547fda007180030054ea6240794a0300371f00196b01020054170000145fff0371a1030054d60600d1f7e200d1df0600f108fdff5430000014eaa640395f01186b00feff54')),
)
