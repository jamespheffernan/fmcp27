"""Version-7 archived statistics records, without archive reads or source merging."""
import struct

from . import player_statistics
from .current_player_statistics import CATEGORY_LABELS


SCALAR_BYTES = 25
BODY_BYTES = SCALAR_BYTES + player_statistics.ARRAY_BYTES
SUPPORTED_PREFIX_BYTES = (7, 11)
LIMITATIONS = (
    'Archived version-7 statistics only. Native year remains a stored unsigned value; '
    'its season-start or season-end convention is unverified. Native categories remain '
    'separate and overlapping totals must not be summed. Unmapped metadata remains raw; '
    'no transfer fee, direction or current-statistics merge is inferred.'
)


def decode_record(raw: bytes, prefix: dict) -> dict:
    """Copy the native archive scalar/array layout into the shared compact codec."""
    if not isinstance(raw, bytes):
        raise ValueError('Archived player statistics must be bytes')
    if not isinstance(prefix, dict) or not all(
            key in prefix for key in ('consumed_bytes', 'team_reference', 'competition_reference')):
        raise ValueError('Archived player statistics require a decoded reference prefix')
    consumed = prefix['consumed_bytes']
    if type(consumed) is not int or consumed not in SUPPORTED_PREFIX_BYTES:
        raise ValueError('Unsupported archived player statistics prefix length')
    if len(raw) != consumed + BODY_BYTES:
        raise ValueError('Unsupported or corrupt archived player statistics encoding: invalid body length')
    scalar = raw[consumed:consumed + SCALAR_BYTES]
    category = scalar[24]
    if category >= len(CATEGORY_LABELS):
        raise ValueError('Unsupported archived player statistics category')

    compact = bytearray(player_statistics.COMPACT_BYTES)
    # Internal nonzero marker: the archive contains array bytes, not a game pointer.
    struct.pack_into('<Q', compact, 0, 1)
    compact[8:10] = scalar[6:8]
    compact[10:12] = scalar[8:10]
    compact[12:16] = scalar[17:21]
    compact[16] = scalar[21]
    compact[17] = scalar[10]
    compact[18:20] = scalar[11:13]
    compact[20] = scalar[22]
    compact[21:25] = scalar[13:17]
    return {
        'native_year': struct.unpack_from('<H', scalar, 4)[0],
        'native_category_code': category,
        'category_name': CATEGORY_LABELS[category],
        'statistics': player_statistics.decode_compact(
            bytes(compact), raw[consumed + SCALAR_BYTES:]),
        'raw_metadata': {
            'native_0x18_signed32': struct.unpack_from('<i', scalar)[0],
            'native_0x2f_u8': scalar[23],
        },
    }


def verify_native(read, base):
    """Check native archive deserialization, scalar copying and category routing."""
    player_statistics.verify_native(read, base)
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Archived player statistics native layout changed at RVA {rva:#x}')


# Selected ARM64 spans from accepted history-01/02 layout and category evidence.
NATIVE_SPANS = (
    (0xf857b0, bytes.fromhex(
        '753a02b0a86272391f010071680080520205881a77f00594a0180034a86272396022009102010052e10314aa08f10594'
        'e0170034'
    )),
    (0xf85810, bytes.fromhex(
        'df0e0071c20000541a048052c83a1f121f110071600200541c000014610000545a06805219000014df16007162000054'
        '1a0780520b000014610000547a07805208000014df1e007188088052890780523a31889ac83a1f121f11007161010054'
        '883a029000e943f9080040f908ed42f900013fd668b590526803a0721f00086b880780521ac19a9a'
    )),
    (0xf85898, bytes.fromhex(
        'f40000b4880240f9081940f9e00314aae10315aa2203805200013fd6fb2300917fff00a97f8301f842fb7fd3880240f9'
        '081940f9e1a30091e00314aa00013fd6'
    )),
    (0xf8592c, bytes.fromhex(
        '680a40f914793c789c0700919f1301f1e00900549f031aeb22010054d47a7c78680a40f91f0100f1800a407ae9426539'
        '2419427aa0feff5408000014'
    )),
    (0xf83b28, bytes.fromhex(
        'fa0301aaf50300aa282440a9087c00a9090800f9680000b4090d40b902000014090080124a1b40b9a92a0329493b4079'
        'a9420079'
    )),
    (0xf83b78, bytes.fromhex(
        '49bf4039a992003909208052a9520278'
    )),
    (0xf83c00, bytes.fromhex(
        '48c340391f15007188120054f9df01a9f6ff02a9f4cf00a9ffff03a9ff230139e1c30091e0031aaae6000094170080d2'
        '48c380397616088b'
    )),
    (0xf84050, bytes.fromhex(
        '680240f915693b787b0b00917f2302f180090054880a40f9280100b415697b78'
    )),
    (0xf88c88, bytes.fromhex(
        '3f0900712c040054290800343f050071c00e00543f09007161180054'
    )),
    (0xf88d10, bytes.fromhex(
        '3f0d0071800700543f110071200e00543f15007141140054e823009121f98d52a100a072'
    )),
    (0xf88d94, bytes.fromhex(
        '09e796526900a072e823009121393f11c54ad194941246f9'
    )),
    (0xf88e70, bytes.fromhex(
        '09e796526900a072e8230091210100328e4ad194941246f9'
    )),
    (0xf88ca4, bytes.fromhex(
        'e823009101e796526100a072024bd194941246f9'
    )),
    (0xf88e04, bytes.fromhex(
        'e823009141338f526100a072aa4ad194941246f9'
    )),
    (0xf88ee0, bytes.fromhex(
        '49338f526900a072e823009121490111724ad194941246f9'
    )),
)
