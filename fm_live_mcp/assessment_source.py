"""Paged stored assessment tags in a checked managed HUMAN team context.

The caller supplies and finally verifies a save-bound ReadSet before publishing.
Only pointer pairs are examined for nonmatches. Joining interest is optional. A stored tag or child pointer does not establish a completed report.
"""
from copy import deepcopy
import struct

from . import assessment_interest_labels, assessment_interest_source, prepared_tactics_source, world

PAGE_LIMIT = 4096
POINTER_PAGE_SLOTS = 2048
POPULATION = 'managed_human_team_context_stored_assessment_tags'


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value >= 1 << 64 or value + size > 1 << 64):
        raise ValueError('Invalid assessment source pointer')
    return value


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete assessment source read')
    return raw


def verify_native(read, base):
    """Pin native context selection, record pointers, date and payload meanings."""
    _address(base, max(rva+len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base+rva, len(expected)) != expected:
            raise ValueError(f'Assessment native source changed at RVA {rva:#x}')


def _bounds(raw):
    start, end, capacity = struct.unpack('<QQQ', raw)
    if (start, end, capacity) == (0, 0, 0):
        return 0, 0
    _address(start)
    if (any(value % 8 for value in (end, capacity))
            or not start <= end <= capacity):
        raise ValueError('Invalid assessment source vector bounds')
    # Capacity is storage, not population or a per-request read limit.
    return start, (end-start)//8


def _date(raw):
    """Retain native flags/defaults and qualify this as population time only."""
    day, year = struct.unpack('<HH', raw)
    result = {'value': None, 'state': 'unmapped_packed_value', 'raw_hex': raw.hex()}
    if year == 1900 and day & 511 == 1:
        result['state'] = 'native_default_sentinel'
        return result
    try:
        result['value'] = world.packed_date(raw)
    except ValueError:
        return result
    result['state'] = 'stored_base_population_date'
    return result


def project(read, base, coach, wanted, source_offset, source_limit,
            include_joining_interest=False):
    """Return (public source coverage, private ordered matching tag tuples).

    wanted contains already canonical PERSON addresses. The identity layer owns
    that membership proof. Tuple fields are (physical index, subject PERSON,
    assessor PERSON or0, details). Duplicate records retain every physical slot.
    Offsets at the end return an empty terminal page; offsets beyond it fail.
    """
    if type(source_offset) is not int or source_offset < 0:
        raise ValueError('Invalid assessment source offset')
    if type(source_limit) is not int or not 1 <= source_limit <= PAGE_LIMIT:
        raise ValueError('Invalid assessment source limit')
    if not isinstance(wanted, (set, frozenset)):
        raise ValueError('Assessment subjects must be a set of canonical PERSON addresses')
    for person in wanted:
        _address(person)
    verify_native(read, base)
    if include_joining_interest:
        assessment_interest_source.verify_native(read, base)
        assessment_interest_labels.verify_native(read, base)

    def checked(address, size):
        return _read(read, address, size)

    team, human = prepared_tactics_source._team_and_human(checked, base, coach)
    marker = _read(read, coach['team_address']+0x2F, 1)[0]
    # Exact native selector: zero vs any nonzero. No national label is inferred.
    offset = 0x110 if marker == 0 else 0x128
    header = _read(read, human+offset, 24)
    start, total = _bounds(header)
    if source_offset > total:
        raise IndexError('Assessment source offset is outside the stored vector')
    count = min(source_limit, total-source_offset)
    pointers = []
    for first in range(0, count, POINTER_PAGE_SLOTS):
        size = min(POINTER_PAGE_SLOTS, count-first)
        raw = _read(read, start+(source_offset+first)*8, size*8)
        pointers.extend(struct.unpack(f'<{size}Q', raw))
    rows, pairs, details = [], {}, {}
    for relative, address in enumerate(pointers):
        if not address:
            continue
        _address(address, 0x38)
        if address not in pairs:
            subject, assessor = struct.unpack('<QQ', _read(read, address, 16))
            for person in (subject, assessor):
                if person:
                    _address(person)
            pairs[address] = subject, assessor
        subject, assessor = pairs[address]
        if subject not in wanted:
            continue
        if address not in details:
            raw = _read(read, address+0x18, 0x20)
            child = struct.unpack_from('<Q', raw, 0x18)[0]
            if child:
                _address(child)
            details[address] = {
                'stored_population_date': _date(raw[:4]),
                'assessment_payload_state': ('stored_assessment_extra_data_present' if child
                                             else 'assessment_extra_data_absent'),
            }
            if include_joining_interest:
                inputs = assessment_interest_source.inspect(read, address)
                details[address]['joining_interest'] = assessment_interest_labels.decode(**inputs)
        # Keep independent detail objects for duplicate physical records.
        rows.append((source_offset+relative, subject, assessor, deepcopy(details[address])))
    if _read(read, human+offset, 24) != header:
        raise ValueError('Assessment source changed during read; retry')
    next_offset = source_offset+count
    summary = {
        'source_state': 'available', 'unavailable_reason': None, 'team': team,
        'team_context_marker': marker, 'population': POPULATION,
        'source_total': total, 'source_offset': source_offset, 'scanned_count': count,
        'next_source_offset': next_offset if next_offset < total else None,
        'complete_source': source_offset == 0 and count == total,
    }
    return summary, rows


# Accepted20 context, subject/provider, pool, population date and child-presence
# evidence. Static instructions/data only; no native function is invoked.
NATIVE_SPANS = (
    (0x12d85a8, bytes.fromhex(
        'c10100b428bc40391f01007108258052092280522801889a092680520a2380524901899a096869f8086868f8280108cb'
        '00fd4393c0035fd6000080d2c0035fd6'
    )),
    (0x2102494, bytes.fromhex(
        '281840f908b400b4f40301aa280040f9a8b300b4f60303aaf30302aa18ad01d0151346f9e00314aafd4fd5971f200331'
        '81080054a80303d1e00315aa61318c52a100a072f8648b94800640f9e863079151cfc297a00303d1e263079121008052'
        '23008052a93e8b94e0ef40f9200100b408200091090080120801e9b81f05007181000054080040f9080540f900013fd6'
        '800240f9e86307913fcfc297a00303d1e26307914100805223008052973e8b94e0ef40f9200100b408200091'
    )),
    (0x1635d4c, bytes.fromhex(
        'e003679e1f0800f90004186e0000803d2800805288eda072081800b9e8ea01d0002dc13d00c0813c08008012082c00b9'
        '1f1800f91f3800b9c0e4022f00c003fcc0035fd6'
    )),
    (0x1635e44, bytes.fromhex(
        'e00302d000e01d9141d401b0212c25910220805203368052040080520500805206208052070082523183b494'
    )),
    (0x1636154, bytes.fromhex(
        '800640f9e10313aa7638eb9740fcff34750240f9a80240f9081940f981620091e00315aa4200805200013fd6a81240b9'
        '08fbff35750240f9a80240f9081940f9816a0091e00315aa4200805200013fd6a81240b9e8f9ff35800a40f9e10313aa'
        '62008052a22ceb9760f9ff34881a40f91f0100f1e8079f1ae8ef0039750240f9a80240f9081940f9e1ef0091e00315aa'
        '2200805200013fd6a81240b9a8f7ff35800240f9e10313aa4e38eb9740f7ff34881a40f9081c00b4'
    )),
    (0x2106ad0, bytes.fromhex(
        '181840f9380500b568ad01b008211f9108c1bf380811003668ad01b018d143f9780100b4080340f969ad01b029811e91'
        '280100f9200540fd488f0190014945fd0084a10e200500fd0d00001460ad01b000e01d91092041a90a0880528b078052'
        '1f0109eb68018a9a026868b8013840b930458994f80300aa200100b468ad01b008015f391f050071a100005468ad01b0'
        '01b147b9e00318aa849fa794e00318aa84bad497f81a00f9880240f908015ef88802088be80600f948ad01f008e13691'
        '080140b9e81a00b988b2c039e9cc8c52ca9999520829091b097d1113287d480b1f05007108c59f1a890280521f510071'
        '08b1891a08130239c80240f909815ef8c902098be90200f9'
    )),
    (0x12ca1c4, bytes.fromhex(
        'e01e02d00080179181ef01d0216418910240805203098052040080520500805206408052070082525132c294'
    )),
    (0x50bc619, bytes.fromhex(
        '53434f555445445f504552534f4e5f54414700'
    )),
    (0x50be94b, bytes.fromhex(
        '53434f555445445f504552534f4e5f5441475f45585452415f4441544100'
    )),
    (0x42eae28, bytes.fromhex(
        '0804407909011971aa2d80520bf518516bb1891a2c5c8f528cc2b5722c7d2c9b8dfd60d38cfd7fd38c158d0b8b098b0b'
        'eca390526c3daa722c7d2c9b8dfd60d38cfd7fd38c1d8d0b6b010c0b292d0a1b0a0040794a210012'
    )),
)
