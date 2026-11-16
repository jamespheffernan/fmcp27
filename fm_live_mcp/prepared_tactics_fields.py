"""Stored prepared-tactic name and phase positions from proved native fields."""
import struct


POSITION_NAMES = {
    0x1: 'GK', 0x10: 'D(C)', 0x4: 'D(R)', 0x200010: 'D(CR)', 0x100010: 'D(CL)',
    0x8: 'D(L)', 0x200080: 'DM(CR)', 0x100080: 'DM(CL)',
    0x800: 'AM(R)', 0x2000: 'AM(C)', 0x1000: 'AM(L)',
    0x4000: 'ST(C)', 0x100: 'M(R)', 0x200: 'M(L)',
    0x20: 'WB(R)', 0x40: 'WB(L)', 0x102000: 'AM(CL)', 0x202000: 'AM(CR)',
    0x104000: 'ST(CL)', 0x204000: 'ST(CR)',
    0x80: 'DM(C)', 0x200400: 'M(CR)', 0x100400: 'M(CL)',
}
PHASE_OFFSETS = {'in_possession': 0x120, 'out_of_possession': 0x440}
MAX_NAME_BYTES = 512


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete prepared tactic field read')
    return raw


def _address(value, size=0, alignment=8):
    if (type(value) is not int or value < 4096 or value % alignment
            or value + size >= 1 << 64):
        raise ValueError('Invalid prepared tactic field address')


def verify_native(read, base):
    """Pin name assignment, phase layout and exact position-name routes."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Prepared tactic field native layout changed at RVA {rva:#x}')


def _name(read, creator):
    pointer = struct.unpack('<Q', _read(read, creator + 0x790, 8))[0]
    if not pointer:
        return None, 'null_native_string'
    # Byte bound and control rejection are reader validation, not native limits.
    # Native string data can be unaligned; its byte length precedes UTF-8 data.
    _address(pointer, MAX_NAME_BYTES + 5, alignment=1)
    length = struct.unpack('<I', _read(read, pointer, 4))[0]
    if length > MAX_NAME_BYTES:
        raise ValueError('Prepared tactic name exceeds byte bound')
    raw = _read(read, pointer + 4, length + 1)
    if raw[-1] != 0:
        raise ValueError('Prepared tactic name lacks native terminator')
    value = raw[:-1].decode('utf-8', errors='strict')
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError('Invalid prepared tactic name control character')
    return value, 'stored' if length else 'empty'


def decode(read, base, creator_address):
    """Decode one owned creator; caller verifies its supplied ReadSet before publish.

    Source ownership/lifetime comes from prepared_tactics_source.inspect. Creators
    are nonpolymorphic, so this decoder does not invent an object-start vtable.
    """
    _address(creator_address, 0x7C0)
    verify_native(read, base)
    name, name_state = _name(read, creator_address)
    phases = {}
    for phase, offset in PHASE_OFFSETS.items():
        positions = []
        for index in range(11):
            mask = struct.unpack('<I', _read(
                read, creator_address + offset + index * 0x48, 4))[0]
            position_name = POSITION_NAMES.get(mask)
            positions.append({
                'position_index': index, 'native_mask': mask,
                'name': position_name,
                'state': 'named' if position_name is not None else 'unmapped_native_mask',
            })
        phases[phase] = {'positions': positions, 'formation': None}
    return {'name': name, 'name_state': name_state, 'phases': phases}


# Accepted batches 09/10: no native function is invoked by these checks.
NATIVE_SPANS = (
    (0x438356c, bytes.fromhex(
        '280040f9480200b4001100d128008052090028b8e00700f9'
    )),
    (0x43835a4, bytes.fromhex(
        'f40740f9340100b415008052880640b908000014140080d2ffff00a935008052ff0f00f9030000140800805235008052e807'
        '00b9680240f9081940f9e1130091e00313aa8200805200013fd6e20740b9e89900d0081543f91f0102eba901005442010034'
        '88220091897a00f0'
    )),

    (0x4a7b280, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091f30305aa08388039a80c088b096e8a522900a072146969f8882243f901400091e00308aaafa8'
        'ff97888a8a522800a072686a68b8892243f928f534b9fd7b41a9f44fc2a8'
    )),
    (0x4a6556c, bytes.fromhex(
        'f44fbea9fd7b01a9fd430091f30300aa08f084520000088baa9f0094e00313aafd7b41a9f44fc2a8'
    )),
    (0x4a8d42c, bytes.fromhex(
        '00401e910fefe317'
    )),
    (0x4a8d598, bytes.fromhex(
        'ffc301d1fc6f01a9fa6702a9f85f03a9f65704a9f44f05a9fd7b06a9fd830191f30301aaf40300aa5f000071088880520924'
        '80522801889a026868b808918052092d80523501889a089a8052093680523601889a08a38052093f80523c01889a08ac8052'
        '094880523b01889a08b58052095180523a01889a08be8052095a80523901889a08c78052096380523801889a08d08052096c'
        '80523701889a08d98052097580522a01889a08e28052097e80522801889aea2300a9e00301aa010080d253420194826a75b8'
        'e00313aa210080524f420194826a76b8e00313aa410080524b420194826a7cb8e00313aa6100805247420194826a7bb8e003'
        '13aa8100805243420194826a7ab8e00313aaa10080523f420194826a79b8e00313aac10080523b420194826a78b8e00313aa'
        'e100805237420194826a77b8e00313aa0101805233420194e80340f9826a68b8e00313aa210180522e420194e80740f9826a'
        '68b8e00313aa4101805229420194e00313aafd7b46a9f44f45a9f65744a9f85f43a9fa6742a9fc6f41a9ffc30191'
    )),
    (0x54060dc, bytes.fromhex(
        '0100000000000000040000001000200010000000100010000800000020000000800020008000000080001000400000000001'
        '0000000420000004000000041000000200000008000000202000002000000020100000100000008000000040200000400000'
        '0040100000000100'
    )),
    (0x49272a4, bytes.fromhex(
        'f60000361f040031a1000054e0430191e10313aafc0600941806001496000036e0430191e10313aaf7060094df0a1e72'
    )),
    (0x4927464, bytes.fromhex(
        'e8c30091e01340f9610790526100a07211d1ea97'
    )),
    (0x49273a0, bytes.fromhex(
        '15008052d9061b12ec000014'
    )),
    (0x4927758, bytes.fromhex(
        '39020034a8735a381f05007101020054'
    )),
    (0x49278d4, bytes.fromhex(
        'e8c30091e01340f941aa9e526100a072f5cfea97'
    )),
    (0x4927b50, bytes.fromhex(
        'e81f40b91f05003161020054c11a0653c5160553a6735a38a7635a38a8535a38a9435a38ea1b40b9ea032a2a4a7d1f53ea0b'
        '0039e9070039e8030039e00313aa020080520300805204008052bc050094'
    )),
    (0x492779c, bytes.fromhex(
        'd702191201010014'
    )),
    (0x4927d28, bytes.fromhex(
        'e8c30091e01340f9a10790526100a072e0ceea97'
    )),
    (0x49280e0, bytes.fromhex(
        'e8c30091e01340f9010890526100a072f2cdea97'
    )),
    (0x49284c4, bytes.fromhex(
        'e8c30091e01340f9c10790526100a072f9ccea97'
    )),
    (0x49288e4, bytes.fromhex(
        'e8c30091e01340f9217899526100a072f1cbea97'
    )),
    (0x4928fe4, bytes.fromhex(
        '800a40f9e8430091010790526100a07231caea97'
    )),
    (0x49276dc, bytes.fromhex(
        'c8120453ea1740b95f010071e3a3881ae8b79f1ae9830c323f01366ae213881a090280520904a0723f01366ae413881a8a00'
        'f83776002036df060c72e3179f1ac10e0353c50a0253a6735a38a7635a38a8535a38a9435a38ea1b40b9ea032a2a4a7d1f53'
        'ea0b0039e9070039e8030039e00313aacf060094'
    )),
    (0x4927ed0, bytes.fromhex(
        'e81f40b91f050031a1020054e81740b96802f837c2521453c4561553df060c72e3179f1aa6735a38a7635a38a8535a38a943'
        '5a38ea1b40b9ea032a2a4a7d1f53ea0b0039e9070039e8030039e00313aa0100805205008052d9040094'
    )),
    (0x49282c8, bytes.fromhex(
        'c82a0a53ea1740b95f010071e3a3881ae8b79f1ae9830c3229c10f113f01366ae213881a090280520904a07229c10f113f01'
        '366ae413881a8a00f83776005036df060c72e3179f1ac5220853c1260953a6735a38a7635a38a8535a38a9435a38ea1b40b9'
        'ea032a2a4a7d1f53ea0b0039e9070039e8030039e00313aad2030094'
    )),
    (0x49286d4, bytes.fromhex(
        'e81f40b91f05003101040054c8360d53ea1740b95f010071e3a3881ae8b79f1a090084520902a0723f01366ae213881a0900'
        '84520904a0723f01366ae413881a8a00f83776006836df060c72e3179f1ac1320c53c52e0b53a6735a38a7635a38a8535a38'
        'a9435a38ea1b40b9ea032a2a4a7d1f53ea0b0039e9070039e8030039e00313aacd020094'
    )),
    (0x4928a8c, bytes.fromhex(
        'e81f40b91f05003141040054c83a0e53ea1740b95f010071e3a3881ae8b79f1a090084520902a072290940113f01366ae213'
        '881a090084520904a072290940113f01366ae413881a8a00f83776007036df060c72e3179f1ac1421053c53e0f53a6735a38'
        'a7635a38a8535a38a9435a38ea1b40b9ea032a2a4a7d1f53ea0b0039e9070039e8030039e00313aadd010094'
    )),
    (0x49292ac, bytes.fromhex(
        'f70307aaf60306aaf90305aafa0304aae30b00b9fb0302aaf80301aaf30300aaff7f02a9e083009101808052de6be997a847'
        '4039e80700b9a8434039e80f00b9ff2b00f9c86b00f0151146f93b22003476010034'
    )),
    (0x4929330, bytes.fromhex(
        'e00315aa210990526100a072'
    )),
    (0x49294c0, bytes.fromhex(
        'e8c30091e00315aa410590526100a072'
    )),
    (0x492973c, bytes.fromhex(
        '5a1e003676010034da6f0090484366391f050071c1040054a13900b021102a91e043019102008012e57de9975e000014b707'
        '0034e8c30091e00315aa210990526100a072'
    )),
    (0x4929910, bytes.fromhex(
        'e8c30091e00315aac10890526100a072e6c7ea97'
    )),
    (0x4929b04, bytes.fromhex(
        'f91a003676010034c86f0090084166391f05007141070054814d00d0215c0791e043019102008012f37ce997a8000014370a'
        '0034e82f40b948020034ff1b00f9213900d021880091e0c3009102008012e97ce997e0830091e1c300911f6be997e81b40f9'
        'e80000b4001100d1080080120800e8b81f05007141000054ae68e997e80f40b9080b0036e8c30091e00315aa01939c526100'
        'a072'
    )),
    (0x4929e60, bytes.fromhex(
        'b814003676010034c86f0090084166391f05007141070054013b00f021bc2491e0430191020080121c7ce99797000014170a'
        '0034e82f40b948020034ff1b00f9213900d021880091e0c3009102008012127ce997e0830091e1c30091486ae997e81b40f9'
        'e80000b4001100d1080080120800e8b81f05007141000054d767e997e80f40b9e8090036e8c30091e00315aa21939c526100'
        'a072'
    )),
    (0x492a0f4, bytes.fromhex(
        'e80b40b9e816003476010034a86f00f0084166391f05007161070054a139009021102a91e043019102008012767be997a900'
        '0014570a0034e82f40b948020034ff1b00f9213900b021880091e0c30091020080126c7be997e0830091e1c30091a269e997'
        'e81b40f9e80000b4001100d1080080120800e8b81f050071410000543167e997e80f40b9280b0036e8c30091e00315aa61a3'
        '91528100a072cac5ea97c86b00d0141146f9e84b40b91f050031e0000054880640f9153d40f9eebcdc96080840f9bf0208eb'
        'a0210054436d00f063c03d91e0c30091010080520200801224a3ea97880640f908414839081f0034e8630191e0c3009191a6'
        'ea97f42f40f900010014e8c30091e00315aa010990526100a072acc5ea97'
    )),
)

