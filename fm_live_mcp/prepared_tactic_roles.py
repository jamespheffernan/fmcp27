"""Source-qualified compiled English names and flags from prepared base role words.

The caller establishes creator ownership with prepared_tactics_source.inspect,
calls verify_native once, and verifies its ReadSet before publication. Names
follow the native phase filter and ordered long-label branches. English labels
are frozen from the accepted installed resource; custom PLAYER_TYPE, selected
localized display names and effective per-player overrides are separate sources.
"""
import struct


PHASE_OFFSETS = {'in_possession': 0x120, 'out_of_possession': 0x440}
PHASE_NAME_MASKS = {
    'in_possession': 0x03FB7B49A90FDEFF,
    'out_of_possession': 0x00003FFBF81FFFFF,
}
ROLE_NAME_MASK = 0xFFFFFFFBF91FFFFF
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'

# Tuple order is native branch priority, not ascending bit number.
ROLE_BRANCHES = {
    'in_possession': (
        (0, 688068, 'Goalkeeper'),
        (1, 688071, 'Centre-Back'),
        (2, 688077, 'Full-Back'),
        (52, 688107, 'Inside Full-Back'),
        (3, 688080, 'Wing-Back'),
        (4, 688083, 'Defensive Midfielder'),
        (5, 688088, 'Central Midfielder'),
        (6, 688108, 'Wide Midfielder'),
        (7, 688102, 'Winger'),
        (27, 688109, 'Inside Forward'),
        (49, 688110, 'Inside Winger'),
        (9, 688095, 'Attacking Midfielder'),
        (56, 688111, 'Channel Midfielder'),
        (10, 688112, 'Deep-Lying Forward'),
        (11, 688103, 'Centre Forward'),
        (12, 688113, 'Ball-Playing Goalkeeper'),
        (53, 688114, 'No-Nonsense Goalkeeper'),
        (14, 688115, 'Advanced Centre-Back'),
        (24, 688116, 'Ball-Playing Centre-Back'),
        (51, 688117, 'Wide Centre-Back'),
        (54, 688118, 'Overlapping Centre-Back'),
        (15, 688119, 'Deep-Lying Playmaker'),
        (28, 688120, 'Ball Winning Midfielder'),
        (16, 688121, 'Box-To-Box Midfielder'),
        (47, 688122, 'Mezzala'),
        (48, 688123, 'Wide Central Midfielder'),
        (50, 688124, 'Segundo Volante'),
        (17, 688125, 'Advanced Playmaker'),
        (18, 688126, 'Target Forward'),
        (19, 688127, 'Poacher'),
        (20, 688128, 'Complete Forward'),
        (29, 688129, 'No-Nonsense Centre-Back'),
        (30, 688130, 'Defensive Winger'),
        (31, 688635, 'Channel Forward'),
        (32, 688131, 'Free Role'),
        (33, 688132, 'Anchor'),
        (35, 688133, 'Half Back'),
        (39, 688134, 'Regista'),
        (36, 688135, 'No-Nonsense Full-Back'),
        (38, 688136, 'Advanced Wing-Back'),
        (37, 688137, 'Enganche'),
        (42, 688138, 'Wide Target Forward'),
        (40, 688139, 'False Nine'),
        (41, 688140, 'Second Striker'),
        (43, 688141, 'Playmaking Winger'),
        (44, 688142, 'Inside Wing-Back'),
        (55, 688143, 'Playmaking Wing-Back'),
        (45, 696156, 'Wide Forward'),
        (46, 688145, 'Box-To-Box Playmaker'),
        (57, 688146, 'Midfield Playmaker'),
    ),
    'out_of_possession': (
        (0, 688068, 'Goalkeeper'),
        (2, 688069, 'Line-Holding Goalkeeper'),
        (1, 688070, 'Sweeper Keeper'),
        (3, 688071, 'Centre-Back'),
        (5, 688072, 'Covering Centre-Back'),
        (4, 688073, 'Stopping Centre-Back'),
        (8, 688074, 'Covering Wide Centre-Back'),
        (7, 688075, 'Stopping Wide Centre-Back'),
        (6, 688076, 'Wide Centre-Back'),
        (9, 688077, 'Full-Back'),
        (11, 688078, 'Holding Full-Back'),
        (10, 688079, 'Pressing Full-Back'),
        (12, 688080, 'Wing-Back'),
        (14, 688081, 'Holding Wing-Back'),
        (13, 688082, 'Pressing Wing-Back'),
        (15, 688083, 'Defensive Midfielder'),
        (16, 688084, 'Dropping Defensive Midfielder'),
        (17, 688085, 'Pressing Defensive Midfielder'),
        (18, 688086, 'Screening Defensive Midfielder'),
        (19, 688087, 'Wide Covering Defensive Midfielder'),
        (20, 688088, 'Central Midfielder'),
        (27, 688089, 'Pressing Central Midfielder'),
        (28, 688090, 'Screening Central Midfielder'),
        (29, 688091, 'Wide Covering Central Midfielder'),
        (36, 688092, 'Tracking Wide Midfielder'),
        (35, 688093, 'Wide Midfielder'),
        (37, 688094, 'Wide Outlet Wide Midfielder'),
        (30, 688095, 'Attacking Midfielder'),
        (32, 688096, 'Central Outlet Attacking Midfielder'),
        (33, 688097, 'Splitting Outlet Attacking Midfielder'),
        (31, 688098, 'Tracking Attacking Midfielder'),
        (40, 696138, 'Inside Outlet Winger'),
        (39, 688100, 'Tracking Winger'),
        (41, 688101, 'Wide Outlet Winger'),
        (38, 688102, 'Winger'),
        (42, 688103, 'Centre Forward'),
        (43, 688104, 'Tracking Centre Forward'),
        (44, 688105, 'Central Outlet Centre Forward'),
        (45, 688106, 'Splitting Outlet Centre Forward'),
    ),
}

# Internal flag bits of the stored role word, with the text key and English text the game's
# naming code holds for each. The flag is fixed by the role: every role has one flag value and
# one stored word, the game offers no such choice and shows none, so decode_word() does not
# publish it. A role in Football Manager 27 has no duty; each phase has its own role. The table
# stays under this name because the tactic writer's game-update check reads it
# (fmdb/adviser_update.py).
DUTY_BRANCHES = (
    (21, 297461, 'Defend'),
    (25, 297462, 'Stopper'),
    (26, 297463, 'Cover'),
    (22, 297464, 'Support'),
    (23, 297465, 'Attack'),
    (34, 300963, 'Automatic'),
)


def _address(value, size):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid prepared tactic role address')


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete prepared tactic role read')
    return raw


def verify_native(read, base):
    """Pin phase/getter/masks, branch priority and exact native English KEY routes."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Prepared tactic role native layout changed at RVA {rva:#x}')


def decode(read, creator, phase, index):
    """Decode a stored base word; no effective player override is applied.

    Native null creators are handled by source slot accounting, before this
    decoder. Unknown bits are preserved exactly in raw_encoding. Multiple role
    bits follow the native first matching branch, without guessing a
    combination. The word's internal flag bits are fixed by the role and are
    returned only inside raw_encoding.
    """
    _address(creator, 0x7C0)
    if type(phase) is not str or phase not in PHASE_OFFSETS:
        raise ValueError('Invalid prepared tactic role phase')
    if type(index) is not int or not 0 <= index <= 10:
        raise ValueError('Invalid prepared tactic role position index')
    address = creator + PHASE_OFFSETS[phase] + index * 0x48 + 0x40
    raw = struct.unpack('<Q', _read(read, address, 8))[0]
    return decode_word(raw, phase)


def decode_word(raw, phase):
    """Label one stored role word, without inferring any effective override."""
    if type(raw) is not int or not 0 <= raw < 1 << 64:
        raise ValueError('Invalid stored tactic role word')
    if type(phase) is not str or phase not in PHASE_OFFSETS:
        raise ValueError('Invalid prepared tactic role phase')
    name_word = raw & PHASE_NAME_MASKS[phase] & ROLE_NAME_MASK
    role = next((row for row in ROLE_BRANCHES[phase] if name_word & (1 << row[0])), None)
    return {
        'raw_encoding': f'0x{raw:016x}',
        'compiled_english_name': role[2] if role else None,
        'native_resource_key': role[1] if role else None,
        'name_state': 'named' if role else 'no_matching_native_branch',
    }


# Batches12/13/14: static instruction bytes only; no native code is executed.
NATIVE_SPANS = (
    (0x508604, bytes.fromhex(
        'a00302d15eedfb94418e02b021a02291a20302d1e00317aa2300805202d70994a00302d1f3f0fb94f60300aae0c30e91'
        '53edfb94418e02b021a02491e2c30e91e00317aa23008052f7d60994e0c30e91edf0fb94f30300aa880240f9088140f9'
        'e00314aa00013fd6e20300aae00315aae10313aa4a21a594f30300aae88c0290001146f9e8c31691610094524101a072'
        '894cfb9476860434e00315aae10313aae921a594e80300aae9df9bd2e921b5f22969cff2697fe0f2e017409100601d91'
        '0101098a2d3e1795e0c31691e217409142601d9121008052030080529f510094'
    )),
    (0x511764, bytes.fromhex(
        'e00315aae10313aad3fda494e80300aae9ff9fd2e903bff269ffc7f2e017409100601d910101098aed191795e0c31691'
        'e217409142601d9121008052030080526e2d0094'
    )),
    (0x653e28, bytes.fromhex(
        'f34f02f073be2191e0230091e10313aa020080122fd4f494e023009120910494e88302d008a12291004d00a9'
    )),
    (0x2e50e48, bytes.fromhex(
        '08048252086868381f0900f1e80100540a0848f9090448f94a0109cb1f0d8aeb42010054000080d23f28007108010054'
        '287968f8c80000b4090980522820299b00b140f9c0035fd6000080d2c0035fd6000080d23f280071a8000054820000b4'
        '080980522808289b00b140f9c0035fd608048252086868381f0900f1e80100540a0848f9090448f94a0109cb1f0d8aeb'
        '42010054000080d23f28007108010054287968f8c80000b4090980522820299b004142f9c0035fd6000080d2c0035fd6'
        '000080d23f280071a8000054820000b4080980522808289b004142f9c0035fd6'
    )),
    (0x495ea7c, bytes.fromhex(
        'f50303aaf40302aaf30301aaf60300aa280040f9'
    )),
    (0x495eb90, bytes.fromhex(
        '83b0e8971f040031e8079f1a396a00d0201346f9b604a8373608c837760fd037d619b0377624b837d63f10b6ff020071'
        'e9b79f1a2801082a88350036e8030091a1d78b52a100a072'
    )),
    (0x495ee7c, bytes.fromhex(
        'e8030091a13e91528100a0728cf2e997'
    )),
    (0x495efd0, bytes.fromhex(
        'a93e91528900a072e80300912105001136f2e997'
    )),
    (0x495f128, bytes.fromhex(
        'a93e91528900a072e803009121011f32e0f1e997'
    )),
    (0x495f208, bytes.fromhex(
        'a93e91528900a072e8030091210d0011a8f1e997'
    )),
    (0x495f278, bytes.fromhex(
        'a93e91528900a072e803009121b936118cf1e997'
    )),
    (0x495f2ec, bytes.fromhex(
        'a93e91528900a072e8030091211100116ff1e997'
    )),
    (0x495f3b0, bytes.fromhex(
        '680240f9a80000b4080140b91f010071e0079f1a0200001400008052fd7b48a9f44f47a9f65746a9f85f45a9fa6744a9'
        'fc6f43a9ff430291c0035fd6f4fdffb4'
    )),
    (0x4ad7f40, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091f30300aa1f0800b9084f009008c12991080000f9010800f91f60003915000094e00313aa'
        'fd7b41a9f44fc2a8c0035fd6f44fbea9fd7b01a9fd430091f30300aa1f0800b9084f009008c12991080000f9010800f9'
        '280080520860003905000094e00313aafd7b41a9f44fc2a8c0035fd6'
    )),
    (0x4ad8094, bytes.fromhex(
        'ff4302d1f85f05a9f65706a9f44f07a9fd7b08a9fd030291f60303aaf40302aaf30301aaf70300aae0c30091fee2e397'
        '685e0090151146f9b7060037f7091037171108373714183757172837771a2037971d4037b7203837d7233037f7264837'
        '172a5837372d5037573060377733703797366837b7397837d73c8037f73f883717439037374698375749a037774cd837'
        '974fe037b752e837d75520b7f75818b7175c28b7375ff037576200b7776508b79768f837b76b40b7d76e38b7f77148b7'
        '177530b7377850b7577b58b7777e60b7570868b6f6820034'
    )),
    (0x4ad81a0, bytes.fromhex(
        '36050034'
    )),
    (0x4ad820c, bytes.fromhex(
        '16090034'
    )),
    (0x4ad8244, bytes.fromhex(
        'e8430091e00315aa81f88f524101a072990de497e0c30091e1430091a0e6e397e043009119e6e397e0c30091e10314aa'
    )),
    (0x4ad82f4, bytes.fromhex(
        '16050034'
    )),
    (0x4ad832c, bytes.fromhex(
        'e8430091e00315aaa1f88f524101a0725f0de497c6ffff17e8430091e00315aa613990524101a072590de497c0ffff17'
        '16050034'
    )),
    (0x4ad8394, bytes.fromhex(
        'e8430091e00315aac1f88f524101a072450de497acffff17e8430091e00315aa813990524101a0723f0de497a6ffff17'
        '16050034'
    )),
    (0x4ad83fc, bytes.fromhex(
        'e8430091e00315aae1f88f524101a0722b0de49792ffff17e8430091e00315aa61bc9f528100a072250de4978cffff17'
        '16050034'
    )),
    (0x4ad8464, bytes.fromhex(
        'e8430091e00315aa01f98f524101a072110de49778ffff17e8430091e00315aaa13990524101a0720b0de49772ffff17'
        '16050034'
    )),
    (0x4ad84cc, bytes.fromhex(
        'e8430091e00315aa21f98f524101a072f70ce4975effff17e8430091e00315aac13990524101a072f10ce49758ffff17'
        '16050034'
    )),
    (0x4ad8534, bytes.fromhex(
        'e8430091e00315aa41f98f524101a072dd0ce49744ffff17e8430091e00315aae13990524101a072d70ce4973effff17'
        '16050034'
    )),
    (0x4ad859c, bytes.fromhex(
        'e8430091e00315aa61f98f524101a072c30ce4972affff17e8430091e00315aa013a90524101a072bd0ce49724ffff17'
        '16050034'
    )),
    (0x4ad8604, bytes.fromhex(
        'e8430091e00315aa81f98f524101a072a90ce49710ffff17e8430091e00315aa213a90524101a072a30ce4970affff17'
        '16050034'
    )),
    (0x4ad866c, bytes.fromhex(
        'e8430091e00315aaa1f98f524101a0728f0ce497f6feff17e8430091e00315aa413a90524101a072890ce497f0feff17'
        '16050034'
    )),
    (0x4ad86d4, bytes.fromhex(
        'e8430091e00315aac1f98f524101a072750ce497dcfeff17e8430091e00315aa613a90524101a0726f0ce497d6feff17'
        '16050034'
    )),
    (0x4ad873c, bytes.fromhex(
        'e8430091e00315aae1f98f524101a0725b0ce497c2feff17e8430091e00315aa813a90524101a072550ce497bcfeff17'
        '16050034'
    )),
    (0x4ad87a4, bytes.fromhex(
        'e8430091e00315aa01fa8f524101a072410ce497a8feff17e8430091e00315aaa13a90524101a0723b0ce497a2feff17'
        '16050034'
    )),
    (0x4ad880c, bytes.fromhex(
        'e8430091e00315aa21fa8f524101a072270ce4978efeff17e8430091e00315aac13a90524101a072210ce49788feff17'
        '16050034'
    )),
    (0x4ad8874, bytes.fromhex(
        'e8430091e00315aa41fa8f524101a0720d0ce49774feff17e8430091e00315aae13a90524101a072070ce4976efeff17'
        '16050034'
    )),
    (0x4ad88dc, bytes.fromhex(
        'e8430091e00315aa61fa8f524101a072f30be4975afeff17e8430091e00315aa013b90524101a072ed0be49754feff17'
        '16050034'
    )),
    (0x4ad8944, bytes.fromhex(
        'e8430091e00315aa81fa8f524101a072d90be49740feff17e8430091e00315aa213b90524101a072d30be4973afeff17'
        '16050034'
    )),
    (0x4ad89ac, bytes.fromhex(
        'e8430091e00315aaa1fa8f524101a072bf0be49726feff17e8430091e00315aa413b90524101a072b90be49720feff17'
        '16050034'
    )),
    (0x4ad8a14, bytes.fromhex(
        'e8430091e00315aac1fa8f524101a072a50be4970cfeff17e8430091e00315aa613b90524101a0729f0be49706feff17'
        '16050034'
    )),
    (0x4ad8a7c, bytes.fromhex(
        'e8430091e00315aae1fa8f524101a0728b0be497f2fdff17e8430091e00315aa813b90524101a072850be497ecfdff17'
        '16050034'
    )),
    (0x4ad8ae4, bytes.fromhex(
        'e8430091e00315aa01fb8f524101a072710be497d8fdff17e8430091e00315aaa13b90524101a0726b0be497d2fdff17'
        '16050034'
    )),
    (0x4ad8b4c, bytes.fromhex(
        'e8430091e00315aa21fb8f524101a072570be497befdff17e8430091e00315aac13b90524101a072510be497b8fdff17'
        '16050034'
    )),
    (0x4ad8bb4, bytes.fromhex(
        'e8430091e00315aa41fb8f524101a0723d0be497a4fdff17e8430091e00315aae13b90524101a072370be4979efdff17'
        '16050034'
    )),
    (0x4ad8c1c, bytes.fromhex(
        'e8430091e00315aa61fb8f524101a072230be4978afdff17e8430091e00315aa013c90524101a0721d0be49784fdff17'
        '16050034'
    )),
    (0x4ad8c84, bytes.fromhex(
        'e8430091e00315aa81fb8f524101a072090be49770fdff17e8430091e00315aa213c90524101a072030be4976afdff17'
        '16050034'
    )),
    (0x4ad8cec, bytes.fromhex(
        'e8430091e00315aaa1fb8f524101a072ef0ae49756fdff17e8430091e00315aa413c90524101a072e90ae49750fdff17'
        '16050034'
    )),
    (0x4ad8d54, bytes.fromhex(
        'e8430091e00315aac1fb8f524101a072d50ae4973cfdff17e8430091e00315aa613c90524101a072cf0ae49736fdff17'
        '16050034'
    )),
    (0x4ad8dbc, bytes.fromhex(
        'e8430091e00315aae1fb8f524101a072bb0ae49722fdff17e8430091e00315aa813c90524101a072b50ae4971cfdff17'
        '16050034'
    )),
    (0x4ad8e24, bytes.fromhex(
        'e8430091e00315aa01fc8f524101a072a10ae49708fdff17e8430091e00315aaa13c90524101a0729b0ae49702fdff17'
        '16050034'
    )),
    (0x4ad8e8c, bytes.fromhex(
        'e8430091e00315aa21fc8f524101a072870ae497eefcff17e8430091e00315aac13c90524101a072810ae497e8fcff17'
        '16050034'
    )),
    (0x4ad8ef4, bytes.fromhex(
        'e8430091e00315aa41fc8f524101a0726d0ae497d4fcff17e8430091e00315aae13c90524101a072670ae497cefcff17'
        '16050034'
    )),
    (0x4ad8f5c, bytes.fromhex(
        'e8430091e00315aa41e993524101a072530ae497bafcff17e8430091e00315aa013d90524101a0724d0ae497b4fcff17'
        '16050034'
    )),
    (0x4ad8fc4, bytes.fromhex(
        'e8430091e00315aa81fc8f524101a072390ae497a0fcff17e8430091e00315aa21e993524101a072330ae4979afcff17'
        '16050034'
    )),
    (0x4ad902c, bytes.fromhex(
        'e8430091e00315aaa1fc8f524101a0721f0ae49786fcff17e8430091e00315aa413d90524101a072190ae49780fcff17'
        '16050034'
    )),
    (0x4ad9094, bytes.fromhex(
        'e8430091e00315aac1fc8f524101a072050ae4976cfcff17e8430091e00315aa613d90524101a072ff09e49766fcff17'
        '16050034'
    )),
    (0x4ad90fc, bytes.fromhex(
        'e8430091e00315aae1fc8f524101a072eb09e49752fcff17e8430091e00315aa81379b528100a072e509e4974cfcff17'
        '56030034'
    )),
    (0x4ad9164, bytes.fromhex(
        'e8430091e00315aa01fd8f524101a072d109e49738fcff17e8430091e00315aa813d90524101a072cb09e49732fcff17'
        'e8430091e00315aa21fd8f524101a072c509e4972cfcff17e8430091e00315aaa13d90524101a072bf09e49726fcff17'
        'e8430091e00315aa41fd8f524101a072b909e49720fcff17e8430091e00315aac13d90524101a072b309e4971afcff17'
    )),
    (0x4ad94b8, bytes.fromhex(
        'ff4302d1f85f05a9f65706a9f44f07a9fd7b08a9fd030291f60303aaf40302aaf30301aaf70300aae0c30091f5dde397'
        '485e00f0151146f917080037570b0837771210379715a0b7b7181837d71b2037f71e283717223037372538375728d837'
        '772b88b7972e4837b731c0b7d7345037f7375837173b6037373ea8b7574170377744c037974798b7b74ab0b7d74d7837'
        'f750e03717548037375778b7575a80b7775d90b797608837b7639037d7669837f769a037176de8373770f0375773f837'
        '777600b7977908b7b77c18b7d77f38b7f78220b7178630b7378928b7578c50b7778f40b7979248b7b79558b7d79860b7'
        'f79bb8b7179f68b737a270b75708c8b6b6a60034'
    )),
    (0x4ad95f0, bytes.fromhex(
        '36050034'
    )),
    (0x4ad965c, bytes.fromhex(
        '16090034'
    )),
    (0x4ad9694, bytes.fromhex(
        'e8430091e00315aa81f88f524101a0728508e497e0c30091e14300918ce1e397e043009105e1e397e0c30091e10314aa'
    )),
    (0x4ad9744, bytes.fromhex(
        '16050034'
    )),
    (0x4ad977c, bytes.fromhex(
        'e8430091e00315aae1f88f524101a0724b08e497c6ffff17e8430091e00315aa613990524101a0724508e497c0ffff17'
        '16050034'
    )),
    (0x4ad97e4, bytes.fromhex(
        'e8430091e00315aaa1f98f524101a0723108e497acffff17e8430091e00315aa013e90524101a0722b08e497a6ffff17'
        '16050034'
    )),
    (0x4ad984c, bytes.fromhex(
        'e8430091e00315aa61fd8f524101a0721708e49792ffff17e8430091e00315aae1369b528100a0721108e4978cffff17'
        '16050034'
    )),
    (0x4ad98b4, bytes.fromhex(
        'e8430091e00315aa01fa8f524101a072fd07e49778ffff17e8430091e00315aa213e90524101a072f707e49772ffff17'
        '16050034'
    )),
    (0x4ad991c, bytes.fromhex(
        'e8430091e00315aa61fa8f524101a072e307e4975effff17e8430091e00315aa01379b528100a072dd07e49758ffff17'
        '16050034'
    )),
    (0x4ad9984, bytes.fromhex(
        'e8430091e00315aa01fb8f524101a072c907e49744ffff17e8430091e00315aa21379b528100a072c307e4973effff17'
        '16050034'
    )),
    (0x4ad99ec, bytes.fromhex(
        'e8430091e00315aa81fd8f524101a072af07e4972affff17e8430091e00315aa41379b528100a072a907e49724ffff17'
        '16050034'
    )),
    (0x4ad9a54, bytes.fromhex(
        'e8430091e00315aac1fc8f524101a0729507e49710ffff17e8430091e00315aa61379b528100a0728f07e4970affff17'
        '16050034'
    )),
    (0x4ad9abc, bytes.fromhex(
        'e8430091e00315aaa1fd8f524101a0727b07e497f6feff17e8430091e00315aa81379b528100a0727507e497f0feff17'
        '16050034'
    )),
    (0x4ad9b24, bytes.fromhex(
        'e8430091e00315aac1fd8f524101a0726107e497dcfeff17e8430091e00315aaa1379b528100a0725b07e497d6feff17'
        '16050034'
    )),
    (0x4ad9b8c, bytes.fromhex(
        'e8430091e00315aae1fb8f524101a0724707e497c2feff17e8430091e00315aa413e90524101a0724107e497bcfeff17'
        '16050034'
    )),
    (0x4ad9bf4, bytes.fromhex(
        'e8430091e00315aae1fd8f524101a0722d07e497a8feff17e8430091e00315aac1379b528100a0722707e497a2feff17'
        '16050034'
    )),
    (0x4ad9c5c, bytes.fromhex(
        'e8430091e00315aa01fe8f524101a0721307e4978efeff17e8430091e00315aa613e90524101a0720d07e49788feff17'
        '16050034'
    )),
    (0x4ad9cc4, bytes.fromhex(
        'e8430091e00315aae1fc8f524101a072f906e49774feff17e8430091e00315aae1379b528100a072f306e4976efeff17'
        '16050034'
    )),
    (0x4ad9d2c, bytes.fromhex(
        'e8430091e00315aa21fe8f524101a072df06e4975afeff17e8430091e00315aa813d90524101a072d906e49754feff17'
        '16050034'
    )),
    (0x4ad9d94, bytes.fromhex(
        'e8430091e00315aa41fe8f524101a072c506e49740feff17e8430091e00315aa813e90524101a072bf06e4973afeff17'
        '16050034'
    )),
    (0x4ad9dfc, bytes.fromhex(
        'e8430091e00315aa61fe8f524101a072ab06e49726feff17e8430091e00315aaa13e90524101a072a506e49720feff17'
        '16050034'
    )),
    (0x4ad9e64, bytes.fromhex(
        'e8430091e00315aa81fe8f524101a0729106e4970cfeff17e8430091e00315aac13e90524101a0728b06e49706feff17'
        '16050034'
    )),
    (0x4ad9ecc, bytes.fromhex(
        'e8430091e00315aaa1fe8f524101a0727706e497f2fdff17e8430091e00315aae13e90524101a0727106e497ecfdff17'
        '16050034'
    )),
    (0x4ad9f34, bytes.fromhex(
        'e8430091e00315aac1fe8f524101a0725d06e497d8fdff17e8430091e00315aaa1af87520101a0725706e497d2fdff17'
        '16050034'
    )),
    (0x4ad9f9c, bytes.fromhex(
        'e8430091e00315aae1fe8f524101a0724306e497befdff17e8430091e00315aa013f90524101a0723d06e497b8fdff17'
        '16050034'
    )),
    (0x4ada004, bytes.fromhex(
        'e8430091e00315aa01ff8f524101a0722906e497a4fdff17e8430091e00315aaa1389b528100a0722306e4979efdff17'
        '16050034'
    )),
    (0x4ada06c, bytes.fromhex(
        'e8430091e00315aa21ff8f524101a0720f06e4978afdff17e8430091e00315aac1389b528100a0720906e49784fdff17'
        '16050034'
    )),
    (0x4ada0d4, bytes.fromhex(
        'e8430091e00315aa41ff8f524101a072f505e49770fdff17e8430091e00315aae1389b528100a072ef05e4976afdff17'
        '16050034'
    )),
    (0x4ada13c, bytes.fromhex(
        'e8430091e00315aa61ff8f524101a072db05e49756fdff17e8430091e00315aa610d9652c100a072d505e49750fdff17'
        '16050034'
    )),
    (0x4ada1a4, bytes.fromhex(
        'e8430091e00315aa81ff8f524101a072c105e4973cfdff17e8430091e00315aa213f90524101a072bb05e49736fdff17'
        '16050034'
    )),
    (0x4ada20c, bytes.fromhex(
        'e8430091e00315aaa1ff8f524101a072a705e49722fdff17e8430091e00315aae10d9652c100a072a105e4971cfdff17'
        '16050034'
    )),
    (0x4ada274, bytes.fromhex(
        'e8430091e00315aac1ff8f524101a0728d05e49708fdff17e8430091e00315aa01399b528100a0728705e49702fdff17'
        '16050034'
    )),
    (0x4ada2dc, bytes.fromhex(
        'e8430091e00315aae1ff8f524101a0727305e497eefcff17e8430091e00315aae1af87520101a0726d05e497e8fcff17'
        '16050034'
    )),
    (0x4ada344, bytes.fromhex(
        'e8430091e00315aa010090524101a0725905e497d4fcff17e8430091e00315aa41399b528100a0725305e497cefcff17'
        '16050034'
    )),
    (0x4ada3ac, bytes.fromhex(
        'e8430091e00315aa210090524101a0723f05e497bafcff17e8430091e00315aa61399b528100a0723905e497b4fcff17'
        '16050034'
    )),
    (0x4ada414, bytes.fromhex(
        'e8430091e00315aa410090524101a0722505e497a0fcff17e8430091e00315aac1d08452e100a0721f05e4979afcff17'
        '16050034'
    )),
    (0x4ada47c, bytes.fromhex(
        'e8430091e00315aa613f90524101a0720b05e49786fcff17e8430091e00315aaa1399b528100a0720505e49780fcff17'
        '16050034'
    )),
    (0x4ada4e4, bytes.fromhex(
        'e8430091e00315aa610090524101a072f104e4976cfcff17e8430091e00315aa413f90524101a072eb04e49766fcff17'
        '16050034'
    )),
    (0x4ada54c, bytes.fromhex(
        'e8430091e00315aa810090524101a072d704e49752fcff17e8430091e00315aa813f90524101a072d104e4974cfcff17'
        '16050034'
    )),
    (0x4ada5b4, bytes.fromhex(
        'e8430091e00315aaa10090524101a072bd04e49738fcff17e8430091e00315aa81bc9f528100a072b704e49732fcff17'
        '16050034'
    )),
    (0x4ada61c, bytes.fromhex(
        'e8430091e00315aac10090524101a072a304e4971efcff17e8430091e00315aae1868d52a100a0729d04e49718fcff17'
        '16050034'
    )),
    (0x4ada684, bytes.fromhex(
        'e8430091e00315aae10090524101a0728904e49704fcff17e8430091e00315aa21a68d52a100a0728304e497fefbff17'
        '16050034'
    )),
    (0x4ada6ec, bytes.fromhex(
        'e8430091e00315aa010190524101a0726f04e497eafbff17e8430091e00315aa41d18452e100a0726904e497e4fbff17'
        '16050034'
    )),
    (0x4ada754, bytes.fromhex(
        'e8430091e00315aa210190524101a0725504e497d0fbff17e8430091e00315aaa13f90524101a0724f04e497cafbff17'
        'd6050034'
    )),
    (0x4ada7bc, bytes.fromhex(
        'e8430091e00315aa410190524101a0723b04e497b6fbff17e8430091e00315aae17e8d52a100a0723504e497b0fbff17'
        'd6050034'
    )),
    (0x4ada83c, bytes.fromhex(
        'e8430091e00315aa610190524101a0721b04e49796fbff17d605003446d4ff9700080034ff0700f9412c009021541591'
    )),
    (0x4ada8a4, bytes.fromhex(
        'e8430091e00315aa810190524101a0720104e4977cfbff17d60500342cd4ff9700080034ff0700f9014000b021581c91'
    )),
    (0x4ada90c, bytes.fromhex(
        'e8430091e00315aaa10190524101a072e703e49762fbff17d605003412d4ff9700080034ff0700f9014000b021d41991'
    )),
    (0x4ada974, bytes.fromhex(
        'e8430091e00315aac10190524101a072cd03e49748fbff17d6050034f8d3ff9740060034ff0700f9014000b021681c91'
    )),
    (0x4ada9dc, bytes.fromhex(
        'e8430091e00315aae10190524101a072b303e4972efbff1716040034ded3ff9740050034ff0700f9014000b021781c91'
    )),
    (0x4adaa44, bytes.fromhex(
        'e8430091e00315aa81eb93524101a0729903e49714fbff17e8430091e00315aa214090524101a0729303e4970efbff17'
        'e8430091e00315aa210290524101a0728d03e49708fbff17e8430091e00315aa410290524101a0728703e49702fbff17'
        'e8430091e00315aa414090524101a0728103e497fcfaff17'
    )),
    (0x4adae88, bytes.fromhex(
        'f30303aaf40302aa370040f96d54f997000e00b4f50300aa16dca09276ffdff2e86240391f050071e1020054f70a40f9'
        'e8030091e00314aafb52e497286200f0084945f9010140f9a10400b4201000d128008052080028b8224440b808008012'
        '0800e8b81f05007101040054f80301aaf90302aacfa3e297e20319aae10318aa1a000014f70a40f9e8030091e00314aa'
        'e552e497286200f0084945f9010140f9c10400b4201000d128008052080028b8224440b8080080120800e8b81f050071'
        '21040054f80301aaf90302aab9a3e297e20319aae10318aa1b00001402008052e13f009021142a91e003009103008052'
        '0400805288bfe2971f040031e3079f1aa80240f9096541f9e8230091e102168ae00315aae20314aa20013fd6e00313aa'
        '0180805207a8e297e1230091e00313aa09a6e2971700001402008052e13f009021142a91e00300910300805204008052'
        '71bfe2971f040031e3079f1aa80240f9096141f9e8230091e102168ae00315aae20314aa20013fd6e00313aa01808052'
        'f0a7e297e1230091e00313aaf2a5e297'
    )),
    (0x505286f, bytes.fromhex(
        '696e706f7373657373696f6e00'
    )),
)
