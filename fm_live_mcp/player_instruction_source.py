"""Stored player-instruction selections; role rules and match effects stay separate."""
from datetime import datetime, timezone
import struct

from . import (live_in_possession_source as ip, live_personal_overrides as personal,
               live_tactical_assignments_source as assignments, players)

ROLE_KEY_MASK = 0xFFFBFFFFF91FFFFF
MAX_SELECTION_ROWS = 128
OPTION_SYMBOLS = (
    'PI_NONE',
    'PI_PASS_SHORTER',
    'PI_PASS_MORE_DIRECT',
    'PI_TAKE_MORE_RISKS',
    'PI_TAKE_FEWER_RISKS',
    'PI_CROSS_OFTEN',
    'PI_CROSS_LESS_OFTEN',
    'PI_CROSS_FROM_DEEP',
    'PI_CROSS_FROM_BYLINE',
    'PI_CROSS_TO_NEAR_POST',
    'PI_CROSS_TO_FAR_POST',
    'PI_CROSS_TO_CENTRE',
    'PI_CROSS_TO_TARGET_MAN',
    'PI_DRIBBLE_MORE',
    'PI_DRIBBLE_LESS',
    'PI_RUN_WIDE_WITH_BALL',
    'PI_CUT_INSIDE_WITH_BALL',
    'PI_HOLD_UP_BALL',
    'PI_SHOOT_MORE',
    'PI_SHOOT_LESS',
    'PI_BE_MORE_EXPRESSIVE',
    'PI_BE_MORE_DISCIPLINED',
    'PI_GET_FORWARD_OFTEN',
    'PI_HOLD_POSITION',
    'PI_ROAM_FROM_POSITION',
    'PI_STAY_WIDER',
    'PI_PLAY_NARROW',
    'PI_MOVE_INTO_CHANNELS',
    'PI_SWITCH_POSITION',
    'PI_HIGHER_PRESSING_INTENSITY',
    'PI_LOWER_PRESSING_INTENSITY',
    'PI_GET_STUCK_IN',
    'PI_STAY_ON_FEET',
    'PI_MARK_TIGHTER',
    'PI_MARK_SPECIFIC_PLAYER',
    'PI_MARK_SPECIFIC_POSITION',
    'PI_ATTACK_BOX_SIDE_CENTRE',
    'PI_ATTACK_BOX_SIDE_LEFT',
    'PI_ATTACK_BOX_SIDE_RIGHT',
    'PI_ATTACK_BOX_SIDE_NEAR_POST',
    'PI_ATTACK_BOX_SIDE_FAR_POST',
    'PI_ATTACK_FRONT_ZONE',
    'PI_ATTACK_BACK_ZONE',
)

ROLE_RULE_CASES = {(4, 0x400008): 3, (8, 0x400008): 3,
                   (4, 0x400004): 0, (8, 0x400004): 0}


def verify_native(read, base):
    for at, expected in NATIVE_SPANS + ROLE_RULE_SPANS:
        if read(base + at, len(expected)) != expected:
            raise ValueError('Stored player instruction native binding changed')
    # The actual native ForwardRuns group used by the instruction exporter.
    start, count = struct.unpack('<QQ', read(base + 0x56A0C60 + 3 * 24, 16))
    if start < 4096 or count > 16 or count == 0:
        raise ValueError('Native forward-runs option group changed')
    options = struct.unpack('<' + 'I' * count, read(start, count * 4))
    if options != (22, 0, 23):
        raise ValueError('Native forward-runs option IDs changed')


def _vector(read, raw, offset, width):
    start, end, cap = struct.unpack_from('<QQQ', raw, offset)
    if (start, end, cap) == (0, 0, 0):
        return b''
    if (start < 4096 or any(v % 8 for v in (start, end, cap)) or not start <= end <= cap
            or (end - start) % width or (cap - start) % width or cap - start > MAX_SELECTION_ROWS * width):
        raise ValueError('Unsupported stored player instruction vector')
    data = read(start, end - start) if end > start else b''
    if len(data) != end - start:
        raise ValueError('Incomplete stored player instruction vector')
    return data


def decode_record(read, raw, phase):
    """Do not call the native getter: its missing-entry branch can allocate."""
    if not isinstance(raw, bytes) or len(raw) != 72 or phase not in assignments.PHASES:
        raise ValueError('One checked phase position record is required')
    position = struct.unpack_from('<I', raw)[0]
    role = struct.unpack_from('<Q', raw, 64)[0]
    wanted = role & ROLE_KEY_MASK
    primary = _vector(read, raw, 8, 24)
    secondary = _vector(read, raw, 40, 16)
    rows = [struct.unpack_from('<QQ', primary, at) for at in range(0, len(primary), 24)]
    if any(rows[i][0] >= rows[i + 1][0] for i in range(len(rows) - 1)):
        raise ValueError('Unordered or duplicate stored role instruction keys')
    matching = [(key, bits) for key, bits in rows if key == wanted]
    bits = matching[0][1] if matching else None
    state = ROLE_RULE_CASES.get((position, role)) if phase == 'in_possession' else None
    return {'state': 'stored_current_role_entry' if matching else 'no_stored_current_role_entry',
            'position_mask': position, 'raw_role_word': f'0x{role:016x}',
            'normalized_role_key': f'0x{wanted:016x}', 'record_activation_raw_u8': raw[32],
            'selected_option_bits_hex': f'0x{bits:016x}' if bits is not None else None,
            'selected_options': [{'native_id': i, 'native_symbol': symbol}
                                 for i, symbol in enumerate(OPTION_SYMBOLS) if bits is not None and bits & (1 << i)],
            'unmapped_selected_bit_indices': [i for i in range(43, 64) if bits is not None and bits & (1 << i)],
            'get_forward_often_explicitly_selected': bool(bits & (1 << 22)) if bits is not None else None,
            'hold_position_explicitly_selected': bool(bits & (1 << 23)) if bits is not None else None,
            'get_forward_often_role_rule': {
                'state': 'supported_native_role_position_case' if state is not None else 'unavailable_unmapped_role_position_case',
                'native_rule_state': state,
                'selected_by_role_rule': state == 3 if state is not None else None,
                'scope': 'Native UI instruction-rule selection for exact supported base position/role; not an effective match instruction.'},
            'secondary_shift_record_count': len(secondary) // 16,
            'secondary_shift_semantics': 'not_decoded',
            'effective_instruction_state': 'not_established',
            'scope': 'Stored selected bits for the normalized current role key; not role defaults, per-player precedence or match execution.'}


def inspect(read, base, coach, phase='both'):
    public = assignments.inspect(read, base, coach, phase, include_personal_overrides=True)
    _, creator = ip._inspect_context(read, base, coach)
    if creator is None:
        reasons = {value.get('unavailable_reason') for value in public['phases'].values()}
        return {**public, 'player_instruction_source_state': 'unavailable_working_assignment_source',
                'player_instruction_source_reasons': sorted(reason for reason in reasons if reason)}
    verify_native(read, base)
    for name, result in public['phases'].items():
        if result.get('assignments') is None:
            continue
        wanted = {r['person']['database_index'] for r in result['assignments'] if r['person'] is not None}
        try:
            entries, _ = personal._map(read, creator + personal.MAP_OFFSETS[name], wanted)
            map_state = 'available'
        except personal.UnsupportedSource:
            entries, map_state = {}, 'unavailable'
        for row in result['assignments']:
            position = row.get('position')
            row['stored_base_player_instructions'] = None
            row['stored_personal_instruction_records'] = None
            if position is None:
                continue
            address = creator + (0x120 if name == 'in_possession' else 0x440) + position['position_index'] * 72
            raw = read(address, 72)
            if (struct.unpack_from('<I', raw)[0] != position['native_mask']
                    or struct.unpack_from('<Q', raw, 64)[0] != int(row['stored_base_role']['raw_encoding'], 16)):
                raise ValueError('Player instruction position or base role changed')
            row['stored_base_player_instructions'] = decode_record(read, raw, name)
            profiles = {}
            person = row['person']
            records = entries.get(person['database_index']) if person is not None else None
            override = row['personal_override']
            for key in ('exact_position_lookup', 'strict_ip_role_lookup'):
                lookup = override.get(key)
                if lookup is None:
                    continue
                index = lookup.get('record_index')
                selected = (decode_record(read, records[index], name)
                            if map_state == 'available' and records is not None and index is not None else None)
                profiles[key] = {'lookup_state': lookup['state'], 'reason': lookup['reason'],
                                 'stored_selection': selected, 'effective_override_state': 'not_established'}
            row['stored_personal_instruction_records'] = profiles
    return {**public, 'player_instruction_source_state': 'available',
            'instruction_scope': 'Existing working edit payload; base position selections, personal records and narrowly supported native role-rule selections are separate.',
            'effective_match_instructions': None, 'observed_screen_instructions': None,
            'limitations': ['No new edit session, native getter invocation, game refresh or write.',
                           'Empty personal maps prove no stored per-person records in this working creator, not an absence of base selections or role rules.',
                           'A clear stored bit is not evidence that a role does not instruct that behavior.',
                           'Secondary shifts and effective personal/base/role precedence are not fully resolved.',
                           'No applied-match, movement, submission or observed-screen claim.']}


def capture(bridge, session_id, coach_name=None, phase='both'):
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        layout = bridge._player_layout(process)
        read, save, _ = bridge._world_state(process, layout)
        coach = bridge._select_coach(save, coach_name)
        result = inspect(read, layout[0] - players.RVA[0], coach, phase)
        read.verify()
        bridge._current(session_id)
        return {**result, 'save': bridge._public_save(save), 'coach': coach['name'],
                'observed_at': datetime.now(timezone.utc).isoformat(),
                'readset_verified': True, 'atomic': False, 'saved_file_fallback': False}


NATIVE_SPANS = (
    (0x4975820, bytes.fromhex(
        'ffc300d1fd7b02a9fd830091e90300aac20900b5222140f920210091a20600b408dca09268ffdff24a00088a28a540a9'
        '2b0108ebe00100546bfd4393ecf301b26c5595f26b7d0c9b6cfd41d30d0380528d210d9bae8541f8ef032caa6b010f8b'
        'df010aeb6b318c9aa831889a8b0100b51f0109eb00050054090140f95f0109eba3040054080540f90825c19a00010012'
    )),
    (0x4975910, bytes.fromhex(
        '28a540a93f0108eb60000054090140f929fcffb4ff7f0039'
    )),
    (0x52e768, bytes.fromhex(
        'd50240b9880240b9e80f00b9822240f9f80700b9e1330091e3130091e4230091e00315aaf5121195e00314aae10315aa'
        '020080d2211c119520020037e80b40b91f0d0071c0010054d6120091f71200f1'
    )),
    (0x52e738, bytes.fromhex(
        '3f40007108040054888b02d008813191090380522920299b280540f9480300b4f40300aa360140f917f57ed31860a352'
        'd50240b9880240b9e80f00b9822240f9f80700b9e1330091e3130091e4230091e00315aaf5121195e00314aae10315aa'
        '020080d2211c119520020037e80b40b91f0d0071c0010054d6120091f71200f1'
    )),
    (0x48e139c, bytes.fromhex(
        '081c0012082d00511f110071e0279f1ac0035fd6'
    )),
)
ROLE_RULE_SPANS = (
    (0x4972ac4, bytes.fromhex(
        '080040b9080a003760008052a10930b7090180520908a0722a00098a5f0109eb000900540a0088520a10a0722b000a8a'
        '7f010aeb600800540a0480520a10a0724b8100912c000b8a9f010beba0070054000080528b0080d20b00b0f20b10c2f2'
        '0b02e0f23f000beac1060054'
    )),
    (0x4972c04, bytes.fromhex(
        'c0035fd6'
    )),
    (0x4973360, bytes.fromhex(
        'ffc300d1f44f01a9fd7b02a9fd830091e80300aa0b10a0d20b00d0f20a0980520a00a272090180520910a0729f0000b9'
        '400c084e8c5400f08159c13d021c214e8c5400f0835dc13d041c234e8c5400f08561c13d051c254e8c5400f08665c13d'
        '061c264e8c5400f08769c13d071c274e8c5400f0906dc13d101c304e8c5400f09171c13d111c314e8c5400f09275c13d'
        '001c324e5f006bf2ec179f1a5f000aea8c159f1a8d5400f0b279c13d008cf26e1328a14e8d5400f0b47dc13d318ef26e'
        '108ef46e101a914e111a534ee798e04e8d5400f0b281c13dc68cf26ec718874e8d5400f0b285c13da58cf26eb228a10e'
        '471a474e311a074e838ce36e6018804e001a404e0058206e418ce16ea118814e2158206ec258206e4228a10e2118424e'
        '1218014e8d5400f0a089c13d2022004e00540f4f00a8204e00a8316e0d00261e6d3300364d000b8abf010beb00330054'
        '2de101914e000d8adf010deb803200540d04a8524d000d8a0e04a852bf010eebe03100544d82c0d20d20e0f24d000d8a'
        '6d3100b50d04b0524d000d8a0e04b052bf010eebc0300054ac30003420008052080500511fa50071a81b00548a5400f0'
        '4a111a918b0000104c7968786b090c8b60011fd6'
    )),
    (0x497387c, bytes.fromhex(
        '800000b91f000071e0179f1afd7b42a9f44f41a9ffc30091c0035fd6'
    )),
    (0x49743c4, bytes.fromhex(
        'e00301aae10302aae40700f9bdf9ff97e40740f929fdff17'
    )),
    (0x5406560, bytes.fromhex(
        '004080000000000000002040000000000000208000000000004080000000000000002080000000000010000002000000'
        '000000000000200000004040000000000000000000800000000000000048010000000000102000000040800000000000'
        '000000000200000000002010000000000000000010000000000020100000000000000000000000000000201000000000'
        '000000000000000000408000000000000000000000000000000040400000000000002080000000000000000000000000'
        '001102131415061718091a1b0c1d0e0f'
    )),
    (0x54066ae, bytes.fromhex(
        'a803'
    )),
)
