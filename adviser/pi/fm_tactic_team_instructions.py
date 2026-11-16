"""Named shared stored team selections through original owned-memory commands.

No live process or game calls. A caller supplies NativeCreator. Exact replacement
clears every stored option through the original kind1 command, then executes kind0
selection with the compiled exclusion table. Defaults mean no explicit stored
selection, not a proven effective UI default or match-engine instruction.
"""
from pathlib import Path
import hashlib
import struct

CREATOR = 0x100400000
COMMAND = 0x100900000
DISPATCH = 0x4469400
ENGLISH_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
OPTION_NAMES = {1: 'Much More Direct Passing', 2: 'More Direct Passing', 3: 'Shorter Passing', 4: 'Much Shorter Passing', 5: 'Pass Into Space', 6: 'Pass Into Feet', 7: 'Play Through Press', 8: 'Bypass Press', 9: 'Hit Early Crosses', 10: 'Floated Crosses', 11: 'Whipped Crosses', 12: 'Low Crosses', 13: 'Run At Defence', 14: 'Dribble Less', 15: 'Shoot On Sight', 16: 'Discourage Long Shots', 17: 'Work Ball Into Box', 18: 'Play For Set Pieces', 19: 'Be More Expressive', 20: 'Be More Disciplined', 21: 'Focus Play Down The Left', 22: 'Focus Play Down The Right', 23: 'Focus Play Through The Middle', 24: 'Focus Play Down Both Flanks', 25: 'Look For Overlap', 26: 'Overlap Left', 27: 'Overlap Right', 28: 'Look For Underlap', 29: 'Underlap Left', 30: 'Underlap Right', 31: 'Roll It Out', 32: 'Throw It Long', 33: 'Take Short Kicks', 34: 'Take Long Kicks', 35: 'Distribute To Centre-Backs', 36: 'Distribute To Full-Backs', 37: 'Distribute To Flanks', 38: 'Distribute Over Opposition Defence', 39: 'Distribute To Playmaker', 40: 'Distribute to Target Forward', 41: 'Distribute To Specific Team-Mate', 42: 'Distribute Quickly', 43: 'Slow Pace Down', 44: 'Short Goal Kicks', 45: 'Long Goal Kicks', 46: 'Much Higher Tempo', 47: 'Higher Tempo', 48: 'Lower Tempo', 49: 'Much Lower Tempo', 50: 'Much Wider', 51: 'Wider', 52: 'Narrower', 53: 'Much Narrower', 54: 'Counter', 55: 'Hold Shape', 56: 'Much Higher Defensive Line', 57: 'Higher Defensive Line', 58: 'Lower Defensive Line', 59: 'Much Lower Defensive Line', 60: 'Goalkeeper Up For Set Pieces', 61: 'High Press', 62: 'Mid Block', 63: 'Low Block', 65: 'Trigger Press Much More Often', 66: 'Trigger Press More Often', 67: 'Trigger Press Less Often', 68: 'Trigger Press Much Less Often', 69: 'Prevent Short GK Distribution', 70: 'Counter-Press', 71: 'Regroup', 72: 'Get Stuck In', 73: 'Stay On Feet', 76: 'Step Up More', 77: 'Drop Off More', 78: 'Waste Much More Time', 79: 'Waste Time', 80: 'Trap Inside', 81: 'Trap Outside', 82: 'Stop Crosses', 83: 'Invite Crosses'}

NATIVE_SPANS = ((71734272, 524, 'bf7b38538f2dd8589f3043d8a3374efc1f88e30f27c9598d132ae4504bba5711'), (88059706, 16, 'f9ff4df512caa6e98d03968de4761e499384bf557fcf626c0c5a994baa5ec4ea'), (88084708, 792, 'dc072c6bed505968347c2e8f5c83d4db7187231c97f9ad57f02d27099aa1d10a'), (75914488, 48, '5fd7334bc6823a0d0f7b3c242b905ac8df8d00302bbe5c6d5f6a348a445b9a7e'), (88084344, 166, 'ef4bc6e25987d48d93f27c642998b4b9bb2176347cc62718cbb721ebea222bfd'), (75923536, 20, 'e44e23b22cf126ae609cf898218ced7778658d4af9df24e752baba6eef1ddde9'), (75914536, 20, '9643ead7547d7891c7567c77270695fb20ecea3c4def9701e4d25aaabf5f663c'), (75918772, 20, 'b35fe279a7d1c5a6e236f37211c6f520b9a30bd4f59027c03357351bb135f031'), (75917884, 20, 'b93db158ad2bdc0d38865bed90fd4d31fef8040fe94bb63fbbd0f6cdf86d1357'), (75919672, 20, '2b6f620f7c2ef793fce2264910edfb8254310ae1bbfac6e08455d4bc233f7280'), (75919892, 16, 'a7c3a76d46fa258622a796feaed4c98fa21b7416a543a1c8c59cd8a3dbb4161e'), (75918220, 16, 'b291d7346e5e0ce0b0cb147725a0d0feb02b64069311fe06f75af0a182697c1a'), (75918884, 20, '650204e4dc4150a3474ac247a2030e88faf060cc7571c537f62f09a5a0d2aa1e'), (75918996, 20, '17f4dcef224ee921ad3ca4230b1a0615125851c191fdbe158fce3d3fad689f20'), (75920448, 20, '96cf9c7248d417a80a34d52b21eb85362c095727c66180ef4bb55edb877b2863'), (75920112, 20, '4337c74913e729e3a1d448a0fe37ba4a8c52a77fb6d34f630054f9718b01f719'), (75916996, 20, 'd3c703e07bdcd21e9ad32fef77dc000826fc5feac9dd77f3dee00e3a2528e6dd'), (75918328, 16, 'cce75e24f7e3ab08570e728fad282d6e90272956bb9ed69bf166dc41c8c0d154'), (75917668, 16, 'a33b57a5f28d770fa205a7294b0bb4e654dd852f65bbfee886548461e2e69008'), (75916552, 16, 'e542686e02982df4f79b18efbef574e3f0856c53c875d938a366557ecab0269c'), (75919224, 20, '95f491b5cf7b61e18301b3a29a1e9ad7cb8bae56042bd8ded0f4897e820023c5'), (75919336, 20, '52ebe8af0bd99177245565613453c14f16420d986622c696a965e9f9e17f63d7'), (75920784, 20, '2626dd3852f27671820e12e2f39eef2b22ef4715d775bd92a415e0dadc9577dc'), (75920560, 20, 'ad4f70a7f8fdbd7914bc7fa296ed7cba7138ae67f8f4c589d061f49eb3d0bb11'), (75916328, 20, '5386101676b7a3a8121b0004908a5cf936cc06183f51f9ef968efa695899411e'), (75917776, 16, '7ebd13398889ec72d34965ff400b6c470d61dfa4adc98c59d77aec690f592260'), (75921120, 16, '5c66365fbc3b9113e7807a6c41d2e91a9dc13e04c7391d9fc09a0162cc7bd2a3'), (75916440, 20, 'f154b1b019002a3bac8acc3a1de2e464e12b2228f156f3c75ebf87678b5bdc4b'), (75917556, 20, '23070aad7c0e23ac2d9725808a2b1c6d8c8ac6da79d0a6128544d866e6500025'), (75916884, 20, '9cc73da3e76b1b6e801f7a94e3914fd031d75b2e9beeb7667c565cc9b3969a5b'), (75918548, 20, '6461f576aa368d3058d6bb4600b772e64bfbf19e42e81e170c981cc3397d7466'), (75916660, 20, '8ba6ea7b27cf2b95acd1df13a2571a7f26e110d5a96ede4a73f341d315a61d71'), (75921892, 20, 'b779d71ecd307e0f96ee0108d5986e1c5c2adbd0f3d80ce536224b70158a7a17'), (75921784, 16, 'b8ae0d31db3fda2ca8c1ae6f10c41513b13db43b0ad02eedd6e95578e152e939'), (75917332, 20, '170aad7c0ff194cf07a55f436153a5f2df1f66d5d3bce5ce499c514c4a34898f'), (75917996, 20, '325facf14611d00465d0e3cd88dacebe74bbc18094c7c745362b87b87b80e50f'), (75919560, 20, 'adb9db8968648a31e41ed5198ab801e6694ce892fcfc82ce72efb29b4ec2b453'), (75918108, 20, '9fea534c1f3f0947f8369a365300d4de4a6c4f1ee59bc087f681e3965d2de1bf'), (75922340, 20, 'd964dbb69f5e891a620d89e311d8407f533c8bc932927394aa9b2f30fda48314'), (75917108, 20, '0953d4130ded566eebc4eae5c99f6ce9c1f1f000bbecc88f538eeec457cfd1a9'), (75920672, 20, 'cb2e0a0894e5377638e4df37e41b7803a25b34852e22a87467cbd0ddd96dde57'), (75922228, 20, '97cf5a9af2b2713883aa5b68459c02e55dad1a05e99f61e7e77e46c26199482c'), (75915992, 20, 'd12b65518044c68a35d9a6d2263f90264c33c1ef8a0b000e2dee6a91e13cfad4'), (75920000, 20, '52a71baa85b17251d4da8f2310c4237131a1dcf160acf50a69b2dbb7afffffac'), (75915880, 20, '309664985f9cb24ad66d53edefb1fc9a8f22036500717e1945ac770ca78e4ad4'), (75915768, 20, 'f29623bb3adb1748808a3f5cfd65849983f886987778be68c4801f70e28c7aa8'), (75917444, 20, '0c4b5a6ecf5076bea58b145357b8539b69c6224f392ef2ebf4de30a9f8984567'), (75918660, 20, '4d539da5a2838c905654284a6c7c95e0be41e0041ac3ae5f899bf3b6327ed491'), (75921008, 20, 'c1d23fbffe3ea5c5d9d8b7766f3172aae79b58c27250f3a805ea7bbc0f87c7be'), (75915208, 20, '66889992f7d5ee0bbcd0f5da04434337896ab223fa910327d6c4e6b5a0cf3449'), (75916104, 20, '98ae492f65899ae68e1324422513911f8f3ef7eeeec68570c302e5cf701411f9'), (75919108, 24, '52f9315eaa79f657f3cae9f850407670962382a28addce361f1ec10cbcae8824'), (75919784, 16, '61c822b903edae1f35bc642918c236660feafe0a7748586cae35df5726ecaada'), (75922452, 24, '693f2dcbd487dfd0b35b9975bbcc43ee7eda9ab3e2c3ae8f8a7541bd219fa01a'), (75919448, 20, 'bb2f06065228b191a1d79450ec905358d0299ea064c4f3cbc32ab996e3197bac'), (75915656, 20, '7fcea4ed1efde627e6778c93581d2b54343a74cd1f075a5e734c9dfdf1f955b3'), (75915320, 20, '33ac3ab69202262a5b9aa35ac9d6e11b641b03e6144482ec0c52ccb35982cbad'), (75922896, 20, 'c2f3b91c504d6f004f7963efb30f8795993f88c63cb1f47433bcc6066acb740c'), (75922116, 20, '66e142d7efb78e4dc36dd5cf396323483166f3d9728ef4c20b98a522993807ac'), (75915544, 20, 'af4d8d3ee65a61e57a00b5c77f1a4c4ce32fb93fa4b55f0ae8962f0788f4f3dd'), (75920224, 20, '28ff88470b81eb916a642b03d459ac8469056be38c07a3bfc2c48379af7bebcc'), (75920896, 20, 'e6c1a3e02b21bad77eadd6ad87d3e9de78b822e1dd746ed6fc9af7c9b7553c96'), (75915432, 20, 'aaa602a90fc34ba3c139b010d103ab3e2431dc793ed7930dae2b6e000f8500cc'), (75921672, 20, '30b2dfbc723f7cf6734d32e54eafaf662f4291ba1155899040534b2252fbb7d8'), (75921228, 20, '3bd6a92c6109f78533019da52076fe4734622b7cbe054d444b5745927e7bf27f'), (75923232, 16, 'f5bdd62e6367fe9095c4422b6c0669f106d44b1991b663f8f0fe6fb4a4a175b0'), (75922680, 16, '12ab2f24f7b417af7756fefea6b3be41ed27fa434e7926239ef55d8b6dbb01ba'), (75923008, 20, '6893c62a9de4958fdb792fa0c0a84e8a63658f3a6b7fd99dbfb67b347ff59af1'), (75921340, 20, '09f895da9f43c3fc1d1ff09e2386484f3d90f59efa4439603a3528dd9a559355'), (75921452, 16, '1ec33584e458473414bb1a82b34592ec438ab37ee56d0d381c027bbc5c1f941b'), (75916772, 20, '24028a0669a7be915912d0ae4cf9819b0c09a15dbf48cd05f7282d6dc05ab1cc'), (75922004, 20, '621fa0e2fb9485e0a7507c3ed02755452de099dd6be1e23089c729b34f713d71'), (75914872, 20, '5ffc53798ce4825ff6a2cdfd2fa97532e847108595ed625a23a5faf85c85b28e'), (75922568, 20, '9b5ff7093912ab49ad5d79901c5484e75cdce767962bffca92dee202b94817a0'), (75922788, 16, 'a9a39e75e643c1e8f1f38dec5be867f83aa36d5ef9db1c64193291d8a7fe01de'), (75918436, 20, 'e96503e04c9768cea007656789d83fa115a052472425ae21799f1ac7040dbbfc'), (75923120, 20, 'ea6a0f71327100269a7c160df0ae8acd940445567eb2468d6bcf1c66f6971f42'), (75921560, 20, '379b7202b785a3cfd6db9e2ae84771b1e23c4bea2a2e3ab2c2f5fbfde40e3cf0'), (75914984, 20, '8970804eee9df3c069d5b3fa2b08abce334e6a4507844711756d3927eea5ab72'), (75916216, 20, 'bd256fadde4733658cf1ae848e86a45ee67fda540bd449d59a0854107018d339'), (75920336, 20, 'b1205e53ec63182f0b4dc2624598a2cac288a9118c649c540238cb614a3c5255'), (75915096, 20, 'e6732058ef455d65bd853110e04c2287e27725ef7c7f2006f651d4ce80b7e4ec'), (75923340, 20, 'd5cde9aa12ae01331b284202594d6ade09e68fc66c18a9c31e92e53cae062f60'), (75914760, 20, '80dfc57304ca643020eef1ced63e001a339460c617b0d2919917cfd0ad89a81f'), (75917220, 20, 'ac10411557597c21a17db9fa3ac3eefd10ea39ff69aa97812b6b19925927a001'), (75914648, 20, 'e0e16e999246db21c91b4c02b0ce9bb8622978ad7007ad24e61dcfad0f4d9669'))
OPPOSITIONS = ((1, 4), (1, 2), (9, 17), (15, 16), (21, 23), (21, 24), (22, 23), (22, 24), (24, 23), (5, 6), (8, 7), (25, 26), (25, 27), (26, 29), (27, 30), (28, 25), (28, 29), (28, 30), (51, 52), (61, 63), (61, 62), (63, 62), (72, 73), (76, 77), (4, 2), (4, 3), (1, 3), (3, 2), (10, 11), (10, 12), (12, 11), (19, 20), (46, 49), (46, 48), (46, 47), (47, 48), (47, 49), (48, 49), (56, 59), (56, 58), (56, 57), (57, 59), (57, 58), (59, 58), (54, 55), (51, 50), (51, 53), (52, 53), (52, 50), (50, 53), (13, 14), (79, 78), (70, 71), (65, 66), (65, 67), (65, 68), (66, 67), (66, 68), (67, 68), (32, 34), (32, 31), (32, 33), (34, 31), (34, 33), (31, 33), (43, 42), (44, 45), (41, 36), (41, 35), (41, 39), (41, 37), (41, 40), (41, 38), (36, 39), (36, 37), (36, 40), (36, 38), (35, 39), (35, 37), (35, 40), (35, 38), (39, 37), (39, 40), (39, 38), (37, 40), (37, 38), (40, 38), (31, 37), (31, 40), (31, 38), (32, 40), (32, 38), (33, 40), (33, 38), (34, 35), (34, 36), (80, 81), (83, 82))

def _need(condition, reason):
    if not condition:
        raise ValueError(reason)


def _ids(names, *, check_conflicts=True):
    _need(type(names) is list and len(names) <= len(OPTION_NAMES), 'Team selections require a bounded list of exact native English names')
    by_name = {name: native_id for native_id, name in OPTION_NAMES.items()}
    _need(all(type(name) is str and name in by_name for name in names), 'Unknown or unnamed native team instruction')
    _need(len(set(names)) == len(names), 'Duplicate requested team instruction')
    ids = sorted(by_name[name] for name in names)
    for a, b in OPPOSITIONS:
        _need(not check_conflicts or not (a in ids and b in ids), 'Conflicting requested team instructions: '+OPTION_NAMES[a]+' / '+OPTION_NAMES[b])
    return ids


def exclusion_groups():
    """Connected native exclusion components; these are not one-choice UI groups.

    Several components are not cliques. Left+Right focus is legal, and goalkeeper
    distribution method/target constraints form one linked component. The exact
    pair list, rather than a guessed one-choice rule, decides legality.
    """
    remaining = set(OPTION_NAMES); groups = []
    while remaining:
        members = {min(remaining)}
        while True:
            extra = {other for a,b in OPPOSITIONS for own,other in ((a,b),(b,a)) if own in members}
            if extra <= members:
                break
            members |= extra
        remaining -= members
        groups.append({'id': min(members), 'native_option_ids': sorted(members),
                       'names': [OPTION_NAMES[i] for i in sorted(members)],
                       'default_operation': 'clear_all_explicit_selections_in_this_component'})
    return groups


def catalog():
    return {'state': 'complete_compiled_named_shared_team_options',
            'named_count': len(OPTION_NAMES), 'unparameterized_authoring_count': len(OPTION_NAMES)-1,
            'options': [{'native_option_id': i, 'name': name, 'requires_target_binding': i==41,
                         'selectable_without_target': i!=41} for i,name in OPTION_NAMES.items()],
            'unnamed_native_option_ids': [64,74,75], 'unrequestable_reserved_bit': 0,
            'native_exclusion_pairs': [list(pair) for pair in OPPOSITIONS],
            'exclusion_components': exclusion_groups(),
            'effective_defaults_or_phase_applicability_verified': False,
            'specific_team_mate_target_authored': False}


_RESOURCE_IDENTITY = None


def verify_sources(creator):
    global _RESOURCE_IDENTITY
    for at,size,digest in NATIVE_SPANS:
        _need(hashlib.sha256(creator.native(at,size)).hexdigest() == digest, 'Native team selection source changed at '+hex(at))
    # The actual loader verifies the complete original native binary.
    core = getattr(creator,'core',None)
    if core is None:
        from fm_tactic_native_authoring import core
    core.verify_native_binary()
    plugin = core.P
    resource = Path(plugin).parent.parent/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf'
    status = resource.stat()
    identity = (str(resource),status.st_dev,status.st_ino,status.st_size,status.st_mtime_ns,status.st_ctime_ns)
    if identity != _RESOURCE_IDENTITY:
        with resource.open('rb') as source:
            digest = hashlib.file_digest(source,'sha256').hexdigest()
        _need(digest == ENGLISH_SHA256, 'Team instruction English resource changed')
        _RESOURCE_IDENTITY = identity


def selected_ids(creator):
    flags = int.from_bytes(bytes(creator.uc.mem_read(CREATOR+0xE0,16)), 'little')
    _need(flags >> 84 == 0, 'Exact team replacement refuses stored bits outside native clearable0..83')
    return [i for i in range(84) if flags & (1 << i)]


def _command(creator, native_id, kind):
    _need(type(native_id) is int and 0 <= native_id < 84 and kind in (0,1), 'Unsupported owned team command')
    if not getattr(creator,'_team_command_mapped',False):
        creator.uc.mem_map(COMMAND,4096)
        creator._team_command_mapped = True
    # Literal command operands, not a modified tactic bit vector. Kinds0/1 do
    # not consume a vtable or companion pointer. The original dispatcher owns
    # all creator mutation and native exclusion clearing.
    creator.uc.mem_write(COMMAND,struct.pack('<QQB7x',0,native_id,kind))
    _need(creator.call(DISPATCH,[COMMAND,CREATOR,0],instructions=10000) == 1, 'Original native team command refused')
    call = dict(creator.last_call)
    _need(all(write['offset'] in (0xE0,0xE8) and write['size']==8 for write in call['creator_writes']), 'Native team command wrote an unexpected creator field')
    _need(not call['services'], 'Native team command entered an opaque service')
    return {'native_option_id':native_id,'operation':'select' if kind==0 else 'clear',**call}


def apply_team_instructions(creator, names):
    """Replace the complete shared stored selection with exact named choices.

    [] explicitly restores no selected options. Option41 requires a qualified
    teammate target and cannot be selected by this unparameterized API. Clearing
    an inherited41 remains supported. Validation completes before any
    creator mutation. On execution failure the caller must discard this owned
    creator and produce no output. The caller owns parent serialization/reload.
    """
    ids = _ids(names)
    _need(41 not in ids, 'Distribute To Specific Team-Mate requires qualified target binding; unparameterized selection is unsupported')
    verify_sources(creator)
    before_ids = selected_ids(creator)
    before = bytes(creator.uc.mem_read(CREATOR,0x800))
    commands = [_command(creator,native_id,1) for native_id in before_ids]
    commands += [_command(creator,native_id,0) for native_id in ids]
    after_ids = selected_ids(creator)
    _need(after_ids == ids, 'Original team selection did not reproduce the exact request')
    after = bytes(creator.uc.mem_read(CREATOR,0x800))
    _need(before[:0xE0]+before[0xF0:] == after[:0xE0]+after[0xF0:], 'Team selection changed another creator field')
    verify_sources(creator)
    return {'mode':'exact_replacement','selected_native_option_ids':ids,
            'selected_names':[OPTION_NAMES[i] for i in ids], 'removed_source_option_ids':before_ids,
            'native_commands':commands,'creator_other_fields_preserved':True,
            'stored_shared_selections_verified':True,
            'effective_instructions_or_game_import_verified':False,
            'specific_team_mate_target_authored':False,
            'scope':'Original owned creator kind1 clear and kind0 select with compiled exclusions. Parent serialization/reload remains the caller responsibility.'}


def edit_team_instructions(creator, *, select=None, clear=None, default_groups=None):
    """Explicit named patch; defaults clear a whole native exclusion component.

    Selection clears existing native opposites. Group IDs come from catalog(),
    not guessed phase or slider defaults. A clear
    and select of the same name, or select within a requested default component,
    is refused. Existing unnamed selected options cannot silently survive a patch.
    """
    select = [] if select is None else select
    clear = [] if clear is None else clear
    default_groups = [] if default_groups is None else default_groups
    chosen, removed = _ids(select), _ids(clear, check_conflicts=False)
    _need(41 not in chosen, 'Distribute To Specific Team-Mate requires qualified target binding; unparameterized selection is unsupported')
    _need(not set(chosen)&set(removed), 'A team instruction cannot be both selected and cleared')
    groups = {group['id']:group['native_option_ids'] for group in exclusion_groups()}
    _need(type(default_groups) is list and all(type(i) is int and i in groups for i in default_groups)
          and len(set(default_groups))==len(default_groups), 'Unknown or duplicate native exclusion default group')
    defaults = {i for group in default_groups for i in groups[group]}
    _need(not set(chosen)&defaults, 'Selected instruction conflicts with requested default group')
    current = selected_ids(creator)
    _need(all(i in OPTION_NAMES for i in current), 'Named patch refuses unqualified source selections; use exact replacement to clear them')
    wanted = set(current)-set(removed)-defaults
    # Kind0 clears every compiled opposite before setting the choice. Apply
    # this exact existing-state rule; requested choices already passed conflicts.
    for option in chosen:
        opposites = {b if a==option else a for a,b in OPPOSITIONS if option in (a,b)}
        wanted -= opposites
        wanted.add(option)
    result = apply_team_instructions(creator,[OPTION_NAMES[i] for i in sorted(wanted)])
    result['mode'] = 'explicit_named_patch'
    result['explicit_select_names'] = select
    result['explicit_clear_names'] = clear
    result['default_exclusion_groups'] = default_groups
    return result
