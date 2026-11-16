"""Compiled tactic definitions and original native selection checks, offline only.

The caller owns an original-code NativeCreator (.native/.call/.uc), loaded by
its full TAC reader. Queries never write the loaded creator. Proposed words are
examined in a separately owned scratch copy using native flag0 predicates; they
are not emitted as edits. The writer must use original native setters and verify
its whole serialization. Native editor wrappers build availability context.

A role is requested and reported by name only. The stored word for a role at a
position is found through the game's own legality predicate, never supplied.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct

CATALOG_SHA256 = '419adb07966874817beec710364d0902ea566f3f8bd8446ef2c9c388de2259eb'
NATIVE_GUARDS = ((76624896, 232, '4c744bff130d973b48e5eff9acce7b041e6947518db09779f766b76cd7800109'),
 (76666672, 148, '20469ad7db96c81dfd734449346ad8a8871583f40317d35dfd5ec77b04b4ab67'),
 (77034608, 164, 'f646f5eac26bf72dc22147241dedb70e938a817bc5112d52c6f4e1f53754b1f5'),
 (77034760, 140, '362d9d916ce6af350d607c24d1c8ed7293bc735f3694d27800d736b57701b0f4'),
 (5476088, 288, '70d3295d30072ddf40e1987db215a0e68d8da927a6a8e4ee43c5843d318f185e'),
 (5476376, 288, 'b2cc1a5255513c21a4e940db1720bf597c372c2da3b11cafd555534a627a9087'),
 (77017952, 7664, 'a20ecdc7fa5f797b255ffd2d0a53becd97c4dfae0e8455f2084c3b6150c7b1c4'),
 # 0x4975150..0x4976430 (4832 bytes, sha256 ca7d8e49...) guarded one function at a time: the same
 # bytes on the pinned build, and on a later build each function is found where the patch put it
 (77025616, 232, 'be3b1df97a4d179417aa6e84952a076208a3e56ea9b5fc78cbcede02e3e9acc3'),
 (77025848, 16, 'daf656f3d1f1c67144d4655e6a70d11d1c966a413087a78c97b59a474b2436bf'),
 (77025864, 1192, '93becaf0a2f2d57becf790f95d18f5671b565d490ca8f73962aa86242bdc0c2e'),
 (77027056, 16, '033c2c28c96633cc9a10fc9397fcb2a9f21cd911da4b2e34396802f8fd93c9db'),
 (77027072, 16, 'a60f97376a2548828d105a57d2d87d4bf3a04606cc0ef6296df220419a9f377f'),
 (77027088, 272, 'dc000db1c64b09ab3379c7749db3db4b63b65b0bfa9e5422229f91a78a48193f'),
 (77027360, 336, '9427b450d5be64bcdbf2ec3eed3819390454f798f144b41cd5e107e5bb06b305'),
 (77027696, 8, '3ab378d7cdbd91d42ee22110e77f1ccc3c53e529536bf9f659c5127a462bd5b2'),
 (77027704, 344, 'bc7c390f06f5e2d014a539d5184f6fd21f231b178babcdc8fdd74912cb41479e'),
 (77028048, 252, '48ad9eece936cfd5e924923002f09f2688bd6eb53156dd71a2c87ee257911db4'),
 (77028300, 20, 'd0c0ca760025697404ebf3ced1b4da157214f060d5fcbe68147d5eed79d37605'),
 (77028320, 1104, '07a758db648df7118c7d4f21770794191b659ae1cf3fbecdc1b2248b87c051ac'),
 (77029424, 272, 'ec4688a0de5ba32bb0773e0257e6a7f039686f2be0101109e20134a4bb2bc946'),
 (77029696, 20, '7d67461c55b52935c987bc4ebf7af0902699be8041670fd17d5b1764c086c3c2'),
 (77029716, 732, '6f60a0c5fb89093d5de389f9d11240ebf082e1e8f1873aa6012512ad92ae1251'))
CREATOR = 0x100400000
SCRATCH = 0x104000000
PHASES = {'in_possession': (0x120, 0x4913400, 0x4977470, 0x538EF8),
          'out_of_possession': (0x440, 0x491D730, 0x4977508, 0x539018)}


# The build the catalog was compiled from. On another game build whose address map checked the
# catalog's English texts and metadata enums against that build's files, fm_live_mcp/adviser_book.py
# rewrites each verified value here to that build's, and the catalog is bound to it.
CATALOG_BUILD = {'plugin_sha256': '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1',
                 'metadata_sha256': 'ff4780c66f37e088f363d0c4365110dd0d7968204cb36283a6262055badab21d',
                 'english_resource_sha256': '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'}


def catalog():
    raw = Path(__file__).with_suffix('.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError('Compiled tactic catalog source changed')
    data = json.loads(raw)
    data.update(CATALOG_BUILD)
    return data


def verify_native(native):
    for at, size, expected in NATIVE_GUARDS:
        raw = native.native(at, size)
        if type(raw) is not bytes or len(raw) != size or hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f'Original tactic selection source changed at {at:#x}')


def _record(native, phase, slot):
    if type(phase) is not str or phase not in PHASES:
        raise ValueError('Unknown tactic phase')
    if type(slot) is not int or not 0 <= slot < 11:
        raise ValueError('Tactic slot must be an integer from0 through10')
    pointer = CREATOR + PHASES[phase][0] + 72 * slot
    raw = bytes(native.uc.mem_read(pointer, 72))
    data = catalog()
    position = struct.unpack_from('<I', raw)[0]
    if position not in {row['native_mask'] for row in data['positions']}:
        raise ValueError('Position is outside the26 canonical native masks')
    return pointer, raw, data


def _named(rows, name, what):
    if type(name) is not str:
        raise ValueError(f'Explicit compiled {what} name required')
    found = [row for row in rows if name in (row['compiled_english_name'], row['metadata_name'])]
    if len(found) != 1:
        raise ValueError(f'Unknown compiled {what}: {name}')
    return found[0]


# A stored role word is the role's own bit plus one further bit that the game fixes for that
# role at that position. Football Manager 27 shows the player a role and nothing else, so that
# further bit is never an input and never a result here: it is found through the game's own
# legality predicate. The catalog file lists the candidate bits under its key 'duties' (the
# name the game's metadata still carries for them); nothing outside this module reads that key.
def _fixed_bits(data):
    return data['duties']


def resolve_role(phase, role):
    """Resolve an exact compiled role name; this alone does not establish legality."""
    data = catalog()
    if type(phase) is not str or phase not in PHASES:
        raise ValueError('Unknown tactic phase')
    role = _named(data['roles'][phase], role, 'role')
    if not role['survives_native_phase_filter']:
        raise ValueError('Known legacy role is removed by the native phase filter')
    return dict(phase=phase, role=deepcopy(role), legality_evaluated=False)


def _scratch(native):
    if getattr(native, '_tactic_catalog_scratch', None) is not native.uc:
        if any(start <= SCRATCH + 4095 and end >= SCRATCH for start, end, _ in native.uc.mem_regions()):
            raise ValueError('Tactic catalog scratch address already owned')
        native.uc.mem_map(SCRATCH, 4096)
        native._tactic_catalog_scratch = native.uc
    return SCRATCH


def _word_accepted(native, phase, pointer, raw, word):
    """Run the original flag0 predicate over a scratch copy of the record carrying `word`."""
    scratch = _scratch(native)
    proposed = raw[:64] + struct.pack('<Q', word)
    native.uc.mem_write(scratch, proposed)
    result = native.call(PHASES[phase][2], [scratch, 0])
    if bytes(native.uc.mem_read(scratch, 72)) != proposed or bytes(native.uc.mem_read(pointer, 72)) != raw:
        raise ValueError('Pure native selection check unexpectedly mutated a record')
    if result not in (0, 1):
        raise ValueError('Unsupported native role-word predicate result')
    return result == 1


def _legal_words(native, phase, pointer, raw, data, role):
    """Every stored word the game's own predicate accepts for one catalog role at this record."""
    return [role['word'] | bit['word'] for bit in _fixed_bits(data)
            if _word_accepted(native, phase, pointer, raw, role['word'] | bit['word'])]


def validate_role_request(native, phase, slot, role):
    """Find the one stored word the game accepts for a named role at the actual record.

    The position's role mask must offer the role, and the original predicate must accept
    exactly one word for it. No word, or more than one, refuses; nothing is picked.
    """
    verify_native(native)
    pointer, raw, data = _record(native, phase, slot)
    requested = resolve_role(phase, role)
    mask = native.call(PHASES[phase][1], [pointer])
    if not mask & requested['role']['word']:
        raise ValueError('Native position role mask refuses requested role')
    words = _legal_words(native, phase, pointer, raw, data, requested['role'])
    if not words:
        raise ValueError('Native role-word predicate refuses requested role')
    if len(words) != 1:
        raise ValueError('The game offers more than one stored word for this role at this position; none is chosen')
    return requested | dict(native_word=words[0], legality_evaluated=True,
                            position_mask=struct.unpack_from('<I', raw)[0],
                            native_position_role_mask=mask, native_word_valid=True,
                            creator_mutated=False)


def validate_loaded_selection(native, phase, slot):
    """Require the actual loaded word to be one known role's word that the game accepts here."""
    verify_native(native)
    pointer, raw, data = _record(native, phase, slot)
    word = struct.unpack_from('<Q', raw, 64)[0]
    roles = [r for r in data['roles'][phase] if word & r['word']]
    bits = [r for r in _fixed_bits(data) if word & r['word']]
    if len(roles) != 1 or len(bits) != 1 or word != roles[0]['word'] | bits[0]['word']:
        raise ValueError('Loaded role word is not exactly one compiled role with its one fixed bit')
    requested = resolve_role(phase, roles[0]['metadata_name'])
    mask = native.call(PHASES[phase][1], [pointer])
    if not mask & requested['role']['word']:
        raise ValueError('Native position role mask refuses requested role')
    if not _word_accepted(native, phase, pointer, raw, word):
        raise ValueError('Native role-word predicate refuses the loaded role word')
    return requested | dict(native_word=word, legality_evaluated=True,
                            position_mask=struct.unpack_from('<I', raw)[0],
                            native_position_role_mask=mask, native_word_valid=True,
                            creator_mutated=False)


def legal_roles(native, phase, slot):
    """Enumerate the roles the original predicates accept at the actual record, by name.

    A role is listed when the game accepts exactly one stored word for it here. A role with
    more than one accepted word cannot be authored and is listed apart.
    """
    verify_native(native)
    pointer, raw, data = _record(native, phase, slot)
    mask = native.call(PHASES[phase][1], [pointer])
    names, refused = [], []
    for role in data['roles'][phase]:
        if not role['survives_native_phase_filter'] or not mask & role['word']:
            continue
        words = _legal_words(native, phase, pointer, raw, data, role)
        if len(words) == 1:
            names.append(role['compiled_english_name'])
        elif words:
            refused.append(role['compiled_english_name'])
    position_mask = struct.unpack_from('<I', raw)[0]
    position = next(row for row in data['positions'] if row['native_mask'] == position_mask)
    return {'phase': phase, 'position_index': slot, 'position_mask': position_mask,
            'position_name': position['compiled_english_name'] or '+'.join(position['metadata_mask_components']),
            'legal_roles': names, 'roles_refused_for_more_than_one_stored_word': refused}


def instruction_availability(native, phase, slot, option):
    """Execute the real editor wrapper; no manually supplied availability mask."""
    validate_loaded_selection(native, phase, slot)
    pointer, raw, data = _record(native, phase, slot)
    options = data['player_instructions']
    if type(option) is str:
        rows = [row for row in options if row['metadata_name'] == option]
        if len(rows) != 1:
            raise ValueError('Unknown compiled player instruction')
        option = rows[0]['native_option']
    if type(option) is not int or not 1 <= option <= 42:
        raise ValueError('Explicit native player instruction1 through42 required;0 is PI_NONE')
    scratch = _scratch(native) + 128
    native.uc.mem_write(scratch, b'\xff' * 4)
    result = native.call(PHASES[phase][3], [pointer, option, 0, scratch])
    state = struct.unpack('<I', native.uc.mem_read(scratch, 4))[0]
    if result not in (0, 1) or state not in (0, 1, 2, 3):
        raise ValueError('Unsupported native editor availability output')
    if bytes(native.uc.mem_read(pointer, 72)) != raw:
        raise ValueError('Native availability query unexpectedly mutated record')
    return dict(phase=phase, slot=slot, native_option=option,
                metadata_name=next(row['metadata_name'] for row in options if row['native_option'] == option),
                native_available=bool(result), native_state=state,
                original_editor_wrapper=hex(PHASES[phase][3]),
                availability_context='built_by_original_editor_wrapper', creator_mutated=False)
