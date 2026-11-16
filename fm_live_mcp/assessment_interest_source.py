"""Build-pinned stored assessment inputs for native joining-interest text.

Call verify_native once per opted-in request. The caller must establish canonical
record ownership and use a ReadSet, then verify all consumed bytes before
publishing. No native typed-value copier or assessment evaluator is executed.
"""
import struct

ENTRY_SIZE = 0x68
TYPE_OFFSET = 0x60
ARRAY_OFFSETS = (0x178, 0x160)
MAX_FIELD_ENTRIES = 256  # External reader bound, not a native enum limit.


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid assessment interest source address')


def _read(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete assessment interest source read')
    return raw


def verify_native(read, base):
    """Pin the exact field-presence, sparse scalar and local renderer routes."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Assessment interest native layout changed at RVA {rva:#x}')


def _vector(read, address):
    start, end, capacity = struct.unpack('<QQQ', _read(read, address, 24))
    if start == end == capacity == 0:
        return 0, 0
    if (start < 4096 or not start <= end <= capacity
            or any(value % 8 for value in (start, end, capacity))):
        raise ValueError('Invalid assessment interest field vector bounds')
    if (end - start) % ENTRY_SIZE:
        raise ValueError('Invalid assessment interest field extent')
    if end - start > MAX_FIELD_ENTRIES * ENTRY_SIZE:
        raise ValueError('Assessment interest field vector exceeds reader bound')
    _address(start, end - start)
    return start, (end - start) // ENTRY_SIZE


def _field5_present(read, child):
    if not child:
        return False
    for offset in ARRAY_OFFSETS:
        start, count = _vector(read, child + offset)
        for index in range(count):
            if _read(read, start + index * ENTRY_SIZE + TYPE_OFFSET, 1)[0] == 5:
                return True
    return False


def inspect(read, record):
    """Return labels.decode kwargs, reading only inputs used by its native branch.

    The Boolean field5 predicate scans type tags only. Variant payloads and
    auxiliary source flags do not affect that predicate and remain uninterpreted.
    Malformed or unsupported source geometry raises; it never becomes Unknown.
    """
    _address(record, 0x48)
    child = struct.unpack('<Q', _read(read, record + 0x30, 8))[0]
    if child:
        _address(child, 0x1B0)
    result = {'value': None, 'field5_present': _field5_present(read, child),
              'flag41': None, 'child_present': bool(child),
              'byte79': None, 'byte7a': None}
    if not result['field5_present']:
        return result
    result['flag41'] = _read(read, record + 0x41, 1)[0]
    if result['flag41'] == 1:
        result['byte7a'] = _read(read, child + 0x7A, 1)[0]
        if not result['byte7a'] & 0x80:
            return result
    result['value'] = struct.unpack('<i', _read(read, record + 0x20, 4))[0]
    if result['value'] >= -40000:
        result['byte79'] = _read(read, child + 0x79, 1)[0]
    return result


# Native163ECD8 field lookup and its exact source/renderer consumers. All spans
# are immutable code bytes from the supported FM27 build, not evidence-file I/O.
NATIVE_SPANS = (
    (0x163ecd8, bytes.fromhex(
        'ff0301d1f65701a9f44f02a9fd7b03a9fdc30091081840f9e80300b413a957a9a9d889d2899db8f2c989ddf289d8e9f2'
        '4a0113eb600100544afd43934a7d099b5f0500f14a859f9a6b8241397f01016b6002005473a201914a0500f161ffff54'
        '132956a9480113eb6001005408fd4393087d099b1f0500f108859f9a698241393f01016b2003005473a20191080500f1'
        '61ffff54000080524d000014494840b9684a40b93f050031800400541f05003181040054f40303aae8fb01f008810791'
        '087969f8e0230091f50302aae10302aa00013fd60800805209008012e20315aaa94a00b913000014494840b9684a40b9'
        '3f050031200400541f05003121040054f40303aae8fb01f008810791087969f8e0230091f50302aae10302aa00013fd6'
        '08008012e20315aaa84a00b928008052e30314aa200000141f050031a0010054e20700f9e9fb01f029010c91287968f8'
        'e0230091e10302aaf40302aae20313aaf50303aa00013fd6e20314aae30315aa08008052100000141f050031a0010054'
        'e20700f9e9fb01f029010c91287968f8e0230091e10302aaf40302aae20313aaf50303aa00013fd6e20314aae30315aa'
        '280080526016c03d69c2407949c000794014803d6800003920008052fd7b43a9f44f42a9f65741a9ff030191c0035fd6'
    )),
    (0x163568c, bytes.fromhex(
        '95030290a88a44f9880000b47f7e16a97fba00f9130000146804029008a11a9108c1bf38c80500366804029008c11991'
        'a88a04f9884a45f97ffe16a97fb200f9080100b56804029008a1199108c1bf38a80600366804029008c11891884a05f9'
        '68e205917faa01b900e4006f008100ad0001803d'
    )),
    (0x1637614, bytes.fromhex(
        '881a40f900810591e10313aa7927fd97c00d0034881a40f900e10591e10313aa7427fd97200d0034'
    )),
    (0x1581454, bytes.fromhex(
        '892240a9080109cb08fd43d3a9d88952899db872087d091be80f00b9750240f9a80240f9081940f9e1330091e00315aa'
        '8200805200013fd6a81240b96801003415008052'
    )),
    (0x1581584, bytes.fromhex(
        '18070091e80f80b9f7a201911f0308eb8bfaff54'
    )),
    (0x4102e8, bytes.fromhex(
        '80820291e2830991e37f0991a100805278ba489400030034e8830791808202912100805254c84894a04303d1e1830791'
        '79e3fd94e083079146e1fd94e883079180820291010080524bc84894a06303d1e183079170e3fd94e08307913de1fd94'
        'e0074b39e17f493939c30094e30300aa15000014e8830791e00315aa41068f526100a072'
    )),
    (0x16361c0, bytes.fromhex(
        '881a40f91f0100f1e8079f1ae8ef0039750240f9a80240f9081940f9e1ef0091e00315aa2200805200013fd6a81240b9'
        'a8f7ff35800240f9e10313aa4e38eb9740f7ff34881a40f9081c00b4'
    )),
    (0x164245c, bytes.fromhex(
        'ff0302d1f65705a9f44f06a9fd7b07a9fdc30191f40300aaf30308aa150302d0a01246f9ffff02a9ff1f00f908008012'
        'e84300b9e81f8052e8130139880641391f05007161040054881a40f9680000b408e94139e8033837e8230091416b9652'
        '6100a072fe64b694'
    )),
    (0x164252c, bytes.fromhex(
        '882240b909a68e521f01096b6b010054881a40f9680000b408e54139c804283701040034e8230091e1839e522101a072'
        'd764b694af00001409e284521f01096b6b010054881a40f9680000b408e54139c807283701070034e823009161849e52'
        '2101a072ca64b694a2000014097182521f01096b8b040054881a40f9680000b408e54139c809283701090034e8230091'
        'e1849e522101a072bd64b69495000014'
    )),
    (0x1642630, bytes.fromhex(
        '1f411f316b030054881a40f9680000b408e54139e808283721080034e823009161859e522101a0729864b69470000014'
        'e823009181849e52'
    )),
    (0x16426a0, bytes.fromhex(
        'e98793121f01096b63030054881a40f9680000b408e541390808283781060034e8230091e1859e522101a0727b64b694'
    )),
)
