"""Native recognition and bounded, source-qualified English formation names."""
from collections import Counter
from dataclasses import dataclass
import struct
import hashlib

from . import address_book


POLICY_RVA = 0x5721A18
METADATA_GUARD_RVA = 0x573CF80
TEMPLATE_GUARD_RVA = 0x573CF78
TEMPLATE_VECTOR_RVA = 0x573CF88
METADATA_RVA = 0x573CFA0
INVERSE_RVA = 0x540644C
TEMPLATE_COUNT = 64
RECORD_BYTES = 24
LOCALIZATION_RVA = 0x56A4C20
NUMERIC_CACHE_RVA = 0x56C1918
# Renderer projections. IDs, packed high bits and byte23 are intentionally absent: the native
# formatter uses low6 tokens and byte22.
# Builds whose own naming route was run: {plugin sha256: {sorted low6 tokens: name}}. Each name is
# what that build's code returned in the reader's static VM (id -> template lookup with its static
# initialiser -> sort -> renderer; only the text lookup by id is modelled, returning the English
# text of the build's example.ltf) for a template of the build, byte22 = 4. The renderer's result
# did not change with the words' high bits, their order or byte23; any other byte22 asks for the
# mentality wrapper text and stays unnamed. The two asymmetric templates (ids 50 and 53) are
# absent: their route enters the text engine for a position token, which was not run.
# tests/test_formation_names_271.py repeats the runs; docs/builds/27.0.1.md has the account.
_ENGLISH_PROJECTIONS_BY_BUILD = {
    '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4': {      # 27.0.1.2503222
        (-15,-13,-12,-10,-9,-3,-2,0,1,8,10): '4-4-2',
        (-15,-12,-11,-10,-8,-4,-2,-1,0,8,10): '5-3-2 WB',
        (-15,-13,-12,-10,-9,-6,-2,0,2,6,9): '4-3-3 DM Wide',
        (-15,-13,-12,-10,-9,-2,0,2,6,8,10): '4-2-4 Wide',
        (-15,-12,-11,-10,-3,-2,-1,0,1,8,10): '3-5-2',
        (-15,-13,-12,-10,-9,-6,-2,0,4,8,10): '4-4-2 Diamond Narrow',
        (-15,-13,-12,-10,-9,-3,-2,-1,0,1,9): '4-5-1',
        (-15,-12,-11,-10,-3,-2,0,1,8,9,10): '3-4-3',
        (-15,-12,-11,-10,-3,-2,0,1,4,8,10): '3-4-1-2',
        (-15,-12,-11,-10,-3,-2,0,1,3,5,9): '3-4-2-1',
        (-15,-13,-12,-10,-9,-2,-1,0,3,5,9): '4-3-2-1 Narrow',
        (-15,-13,-12,-10,-9,-2,-1,0,4,8,10): '4-3-1-2 Narrow',
        (-15,-12,-11,-10,-8,-6,-4,-2,0,4,9): '5-4-1 Diamond WB',
        (-15,-13,-12,-10,-9,-3,-2,0,1,4,9): '4-4-1-1',
        (-15,-13,-12,-10,-9,-2,0,3,4,5,9): '4-2-3-1 Narrow',
        (-15,-13,-12,-10,-9,-6,-2,-1,0,4,9): '4-1-3-1-1 DM AM Narrow',
        (-15,-13,-12,-10,-9,-6,-2,-1,0,8,10): '4-1-3-2 DM Narrow',
        (-15,-13,-12,-10,-9,-2,0,2,4,6,9): '4-2-3-1 Wide',
        (-15,-13,-12,-10,-9,-7,-5,-3,1,8,10): '4-4-2 2DM',
        (-15,-13,-12,-10,-9,-7,-5,-1,2,6,9): '4-3-3 2DM Wide',
        (-15,-13,-12,-10,-9,-7,-5,-2,0,8,10): '4-2-2-2 DM Narrow',
        (-15,-12,-11,-10,-6,-3,-1,1,4,8,10): '3-1-3-1-2 DM',
        (-15,-13,-12,-10,-9,-6,-2,0,8,9,10): '4-3-3 DM Narrow',
        (-15,-13,-12,-10,-9,-6,-2,0,3,5,9): '4-3-2-1 DM AM Narrow',
        (-15,-13,-12,-10,-9,-7,-5,2,6,8,10): '4-2-4 DM Wide',
        (-15,-13,-12,-10,-9,-7,-5,2,4,6,9): '4-2-3-1 DM AM Wide',
        (-15,-12,-11,-10,-8,-6,-4,-2,0,8,10): '5-3-2 DM WB',
        (-15,-12,-11,-10,-8,-7,-5,-4,-2,0,9): '5-2-2-1 DM',
        (-15,-13,-12,-10,-9,-6,-3,-2,0,1,9): '4-1-4-1 DM',
        (-15,-13,-12,-10,-9,-7,-5,-3,1,4,9): '4-4-1-1 2DM',
        (-15,-12,-11,-10,-7,-5,-3,-1,1,8,10): '3-5-2 2DM',
        (-15,-12,-11,-10,-8,-7,-5,-4,2,6,9): '5-2-3 DM Wide',
        (-15,-13,-12,-10,-9,-2,-1,0,8,9,10): '4-3-3 Narrow',
        (-15,-13,-12,-10,-9,-2,0,7,8,10,11): '4-2-4',
        (-15,-13,-12,-11,-10,-9,-3,-2,0,1,9): '5-4-1',
        (-15,-13,-12,-10,-9,-1,3,5,8,9,10): '4-3-3 AM Narrow',
        (-15,-13,-12,-10,-9,-7,-5,3,4,5,9): '4-2-3-1 DM AM Narrow',
        (-15,-12,-11,-10,-8,-4,-2,0,4,8,10): '5-2-1-2 WB',
        (-15,-13,-12,-11,-10,-9,-6,-2,0,8,10): '5-3-2 DM Narrow',
        (-15,-12,-10,-2,-1,0,7,8,9,10,11): '2-3-5',
        (-15,-12,-10,-3,-2,0,1,7,8,10,11): '2-4-4',
        (-15,-12,-11,-10,-2,0,7,8,9,10,11): '3-2-5',
        (-15,-12,-11,-10,-2,-1,0,7,8,10,11): '3-3-4',
        (-15,-13,-12,-11,-10,-9,-2,0,8,9,10): '5-2-3 Narrow',
        (-15,-13,-12,-10,-9,-7,-5,2,3,5,6): '4-2-4-0 DM AM Wide',
        (-15,-13,-12,-10,-9,-6,-3,-1,1,8,10): '4-1-3-2 DM',
        (-15,-13,-12,-10,-9,-7,-5,-3,-1,1,9): '4-5-1 2DM',
        (-15,-13,-12,-10,-9,-7,-5,-3,-1,1,4): '4-5-1-0 2DM',
        (-15,-12,-11,-10,-8,-6,-4,-2,-1,0,9): '5-1-3-1 DM WB',
        (-15,-13,-12,-11,-10,-9,-7,-5,-3,1,9): '5-4-1 2DM',
        (-15,-13,-12,-11,-10,-9,-7,-5,-3,1,4): '5-4-1-0 2DM',
        (-15,-12,-11,-10,-8,-4,-2,0,3,5,9): '5-2-2-1 WB',
        (-15,-12,-11,-10,-6,-3,-2,0,1,8,10): '3-1-4-2 DM',
        (-15,-12,-11,-10,-8,-4,-2,0,2,6,9): '5-2-3 WB Wide',
        (-15,-13,-12,-10,-9,-7,-5,3,5,8,10): '4-2-2-2 DM AM Narrow',
        (-15,-12,-11,-10,-8,-7,-5,-4,3,5,9): '5-2-2-1 DM AM',
        (-15,-12,-11,-10,-8,-7,-5,-4,4,8,10): '5-2-1-2 DM AM',
        (-15,-12,-11,-10,-7,-5,2,3,5,6,9): '3-2-5 DM 2AM Wide',
        (-15,-13,-12,-11,-10,-9,-7,-5,4,8,10): '5-2-1-2 DM AM Narrow',
        (-15,-13,-12,-11,-10,-9,-7,-5,3,5,9): '5-2-2-1 DM AM Narrow',
        (-15,-13,-12,-11,-10,-9,-7,-5,2,6,9): '5-2-3 DM Wide',
    },
}


# The pinned build 27.0.0, and a later build whose route still checks out under
# NAME_NATIVE_DIGESTS: 27.0.0's own code, run the same way, returns the same name as 27.0.1's for
# every template (the same test). Until 14 November 2026 this table held two names from a hand
# trace of 7 November, '4-2-3-1 DM Wide' and '4-4-1-1 2DM AM'; the trace took the branch at
# 0x49698CC the wrong way, and the code returns '4-2-3-1 DM AM Wide' and '4-4-1-1 2DM'.
_ENGLISH_PROJECTIONS = _ENGLISH_PROJECTIONS_BY_BUILD[
    '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4']


def _english_projections():
    """The projection table of the loaded build: its own when its naming route was run, else the
    pinned build's (a later build whose route still checks out under NAME_NATIVE_DIGESTS)."""
    return _ENGLISH_PROJECTIONS_BY_BUILD.get(address_book.ACTIVE.get('sha256'), _ENGLISH_PROJECTIONS)


# Reader budgets below are not asserted native allocation limits.
POLICY_CAPACITY_LIMIT = 4096
TEMPLATE_CAPACITY_LIMIT = 128
# Native mask0x00019C1000011001 applies when(id-1)<49.
STATIC_EXCLUDED = frozenset((1, 13, 17, 37, 43, 44, 45, 48, 49))


@dataclass(frozen=True)
class _Context:
    # Candidate IDs are in the native first-match order, after policy filtering.
    candidates: tuple
    inverse: tuple
    naming: object = None


@dataclass
class _NamingContext:
    # Private to one query/context; no cross-query resource cache.
    read: object
    base: int
    ready: object = None

    def available(self):
        if self.ready is None:
            self.ready = _naming_ready(self.read, self.base)
        return self.ready


# The English naming route (renderer, inputs, numeric cache) is an optional part of a result: on
# a build where any of NAME_NATIVE_DIGESTS is unresolved or its code changed, names are withheld
# with this state and recognition (native_id) still answers. 27.0.1 re-laid out the renderer
# (0x4967B80 -> 0x4A7AC4C), its number-line builder (0x496AA7C -> 0x4A7D8C0) and the renderer's
# 15-entry jump table (0x54060BA -> 0x54A129C); both builds' routes were run in the static VM and
# gave the same text for every template that could be run, so the reviewed entries of
# address_overrides.json re-derive those three digests and names answer on 27.0.1, from that
# build's own table (_ENGLISH_PROJECTIONS_BY_BUILD).
NAMING_UNVERIFIED = 'native_naming_route_unverified_on_this_build'


@address_book.optional_section('formation_names', lambda reasons: NAMING_UNVERIFIED)
def _naming_ready(read, base):
    for rva, size, expected in NAME_NATIVE_DIGESTS:
        if hashlib.sha256(_read(read, base+rva, size)).hexdigest() != expected:
            raise ValueError(f'Prepared formation name native layout changed at RVA {rva:#x}')
    localization = struct.unpack('<Q', _read(read, base+LOCALIZATION_RVA, 8))[0]
    if not localization:
        return False
    _pointer(localization)
    cache = struct.unpack('<Q', _read(read, base+NUMERIC_CACHE_RVA, 8))[0]
    if not cache:
        return False
    _pointer(cache)
    if cache + 0x348 >= 1 << 64:
        raise ValueError('Invalid prepared formation numeric cache bounds')
    for number in range(1,5):
        text = struct.unpack('<Q', _read(read, cache+0x320+number*8, 8))[0]
        if not text:
            return False
        # Strings may be unaligned. Bounds/controls are reader validation.
        if not 4096 <= text < (1 << 64)-517:
            raise ValueError('Invalid prepared formation numeric string pointer')
        length = struct.unpack('<I', _read(read, text, 4))[0]
        if length > 512:
            raise ValueError('Prepared formation numeric string exceeds reader bound')
        raw = _read(read, text+4, length+1)
        if raw[-1]:
            raise ValueError('Prepared formation numeric string lacks terminator')
        value = raw[:-1].decode('utf-8', errors='strict')
        if any(ord(char)<32 or ord(char)==127 for char in value):
            raise ValueError('Invalid prepared formation numeric string')
        # Null/empty or valid alternate numeric-cache strings are legal naming
        # unavailability. Numeric recognition remains independently available.
        if value != str(number):
            return False
    return True


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete prepared formation read')
    return raw


def _pointer(value):
    if type(value) is not int or not 4096 <= value < (1 << 64) or value % 8:
        raise ValueError('Invalid prepared formation pointer')


def verify_native(read, base):
    _pointer(base)
    if base + max(max(rva + len(raw) for rva, raw in NATIVE_SPANS),
                  NUMERIC_CACHE_RVA + 8) >= 1 << 64:
        raise ValueError('Invalid prepared formation base')
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Prepared formation native layout changed at RVA {rva:#x}')


def _policy(read, base):
    start, end, capacity = struct.unpack('<QQQ', _read(read, base + POLICY_RVA, 24))
    if start == end == capacity == 0:
        return None
    if (start < 4096 or not start <= end <= capacity
            or capacity - start > POLICY_CAPACITY_LIMIT):
        raise ValueError('Invalid prepared formation policy bounds')
    # Native policy entries are bytes; data/end/capacity need not be aligned.
    if start == end:
        return None
    return _read(read, start, min(end - start, 70))


def load(read, base):
    """Load one private context through the caller's save-bound ReadSet.

    Known uninitialized guards return None without allocating native templates.
    The caller verifies all consumed bytes before publishing any result.
    Supported initialized storage has 64 records and unique IDs1..69 including3,
    with low6 position tokens in the 26 nonzero canonical inverse-table entries.
    Other initialized encodings reject as unsupported, not natively impossible.
    """
    verify_native(read, base)
    metadata_ready = _read(read, base + METADATA_GUARD_RVA, 1)[0] & 1
    templates_ready = _read(read, base + TEMPLATE_GUARD_RVA, 1)[0] & 1
    if not metadata_ready or not templates_ready:
        return None
    policy = _policy(read, base)
    start, end, capacity = struct.unpack('<QQQ', _read(read, base + TEMPLATE_VECTOR_RVA, 24))
    _pointer(start)
    if (not start <= end <= capacity or end - start != TEMPLATE_COUNT * RECORD_BYTES
            or (capacity - start) % RECORD_BYTES
            or capacity - start > TEMPLATE_CAPACITY_LIMIT * RECORD_BYTES):
        raise ValueError('Unsupported prepared formation template vector representation')
    metadata = _read(read, base + METADATA_RVA, TEMPLATE_COUNT * RECORD_BYTES)
    records = _read(read, start, TEMPLATE_COUNT * RECORD_BYTES)
    identifiers = tuple(metadata[index * RECORD_BYTES] for index in range(TEMPLATE_COUNT))
    if (len(set(identifiers)) != TEMPLATE_COUNT or 3 not in identifiers
            or any(not 1 <= identifier <= 69 for identifier in identifiers)):
        raise ValueError('Unsupported prepared formation metadata identifiers')
    inverse = struct.unpack('<27I', _read(read, base + INVERSE_RVA, 108))
    layouts = {}
    projections = _english_projections()
    for index, identifier in enumerate(identifiers):
        words = struct.unpack_from('<11H', records, index * RECORD_BYTES)
        codes = tuple(((word & 63) ^ 32) - 32 for word in words)
        # Native low6->inverse->converter->inverse round-trips these 26 tokens.
        # Zero/invalid template codes are outside this checked representation.
        if any(not -15 <= code <= 11 or code == -14 for code in codes):
            raise ValueError('Unsupported prepared formation template position encoding')
        signature = tuple(sorted(Counter(inverse[code + 15] for code in codes).items()))
        english = projections.get(tuple(sorted(codes))) if records[index*RECORD_BYTES+22]==4 else None
        layouts[identifier] = (signature, english)
    candidates = []
    for identifier in range(1, 70):
        eligible = (identifier not in STATIC_EXCLUDED if policy is None else
                    identifier < len(policy) and bool(policy[identifier]))
        if eligible:
            candidates.append((identifier, *layouts.get(identifier, layouts[3])))
    naming = _NamingContext(read, base) if any(name is not None for _,_,name in candidates) else None
    return _Context(tuple(candidates), inverse, naming)


def identify(context, masks):
    """Identify eleven u32 masks; raw aliases do not create position names."""
    if not isinstance(masks, (list, tuple)) or len(masks) != 11:
        raise ValueError('Prepared formation requires eleven native masks')
    codes = tuple(_compact_position(mask) for mask in masks)
    if context is None:
        return {'native_id': None, 'state': 'unavailable_uninitialized_templates', 'name': None}
    if not isinstance(context, _Context):
        raise ValueError('Invalid prepared formation context')
    signature = tuple(sorted(Counter(
        context.inverse[code + 15] if -15 <= code <= 11 else 0
        for code in codes).items()))
    for identifier, layout, english in context.candidates:
        if signature == layout:
            ready = context.naming.available() if english is not None else None
            result = {'native_id': identifier, 'state': 'recognized', 'name': english if ready is True else None}
            if ready == NAMING_UNVERIFIED:
                result['name_state'] = NAMING_UNVERIFIED
            return result
    return {'native_id': 0, 'state': 'no_eligible_template_match', 'name': None}


def _compact_position(mask):
    if type(mask) is not int or not 0 <= mask <= 0xFFFFFFFF:
        raise ValueError('Expected u32 native position mask')
    if mask == 0:                              #492B8C8 ->492BB14
        return -16
    if mask & 1:                               #492B8CC ->492BB30
        return -15
    if mask & 0x1C:                            #492B8D0 ->492B930
        if mask & 0x8924:
            return -13
        if mask & 0x200000:
            return -12
        side = bool(mask & 0x6490) and not bool(mask & 0x100000)
        side = side or bool(mask & 0x400000)
        value = -11 if side else -10
        if side or mask & 0x100000:
            return value
        return -9 if mask & 0x11248 else -15
    if mask & 0xE0:                            #492B8D8 ->492B994
        if mask & 0x8920:
            return -8
        if mask & 0x200000:
            return -7
        side = bool(mask & 0x6480) and not bool(mask & 0x100000)
        side = side or bool(mask & 0x400000)
        value = -6 if side else -5
        if side or mask & 0x100000:
            return value
        return -4 if mask & 0x11240 else -15
    if mask & 0x700:                           #492B8E0 ->492BA50
        if mask & 0x8900:
            return -3
        if mask & 0x200000:
            return -2
        side = bool(mask & 0x6400) and not bool(mask & 0x100000)
        side = side or bool(mask & 0x400000)
        if side or mask & 0x100000:
            return -1 if side else 0
        return 1 if mask & 0x11200 else -15
    if mask & 0x3800:                          #492B8E8 ->492B9F8
        if mask & 0x8800:
            return 2
        if mask & 0x200000:
            return 3
        side = bool(mask & 0x6000) and not bool(mask & 0x100000)
        side = side or bool(mask & 0x400000)
        if side or mask & 0x100000:
            return 4 if side else 5
        return 6 if mask & 0x11000 else -15
    if mask & 0x1C000:                         #492B8F0
        if mask & 0x8000:
            return 7
        if mask & 0x200000:
            return 8
        if mask & 0x104000 == 0x4000 or mask & 0x400000:
            return 9
        if mask & 0x100000:
            return 10
        if mask & 0x10000:
            return 11
    return -15                                #492BB30; overloaded fallback


# Accepted native recognition route; no native code is invoked.
NATIVE_SPANS = (
    (0x492b8c8, bytes.fromhex(
        '60120034201300371f081e72e10200541f081b72c10500541f081872610b00541f081572610800541f081272e01100544011'
        '7837e00ea837080082522800a07208cd43110900080a280180523f114071e0100054c010b0376010a03648018052003d0013'
        'c0035fd6882491521f00086ae10b0054600ba83708928c521f00086ae8079f1a09000c72e813881a0a000a120a594a2a5f01'
        '0071480180120815881a6a0e0037490e003508498052090082522900a0722801082a1f00086a600d0054e8fe9f52003d0013'
        'c0035fd6082491521f00086aa10a00540009a83708908c521f00086ae8079f1a09000c72e813881a0a000a120a594a2a5f01'
        '0071a80080120815881a4a0b0037290b003508488052090082522900a0722801082a1f00086a400a005488ff9f52003d0013'
        'c0035fd6080091521f00086a210700542008a8371f041372e8079f1a09000c72e813881a0a000a120a594a2a5f0100718800'
        '80520815881a4a08003729080035080082522800a0721f00086a80070054c8008052003d0013c0035fd6082091521f00086a'
        '210500548003a83708808c521f00086ae8079f1a09000c72e813881a0a000a120a594a2a48010013aa050037890500350800'
        '82522800a072080117321f00086ac004005428008052003d0013c0035fd688fe9f52003d0013c0035fd668fe9f52003d0013'
        'c0035fd628ff9f52003d0013c0035fd6c8ff9f52003d0013c0035fd608018052003d0013c0035fd648008052003d0013c003'
        '5fd608ff9f52003d0013c0035fd6a8ff9f52003d0013c0035fd668008052003d0013c0035fd608fe9f52003d0013c0035fd6'
        'e8008052003d0013c0035fd68000803728fe9f52003d0013c0035fd668018052003d0013c0035fd6'
    )),
    (0x4adddc4, bytes.fromhex(
        '2962009029612891282540a91f0109eb200100540002f837290108cb3fc120eba901005408c960381f010071e0079f1ac003'
        '5fd6080400511fc5007102010054e98300b2290082f20982d3f22925c89a6900003600008052c0035fd61f150171e0279f1a'
        'c0035fd6'
    )),
    (0x4ade244, bytes.fromhex(
        'ff8301d1f65703a9f44f04a9fd7b05a9fd430191f30301aaf40300aa884e00d008d942f9080140f9e81700f936008052d51e'
        '001313010034e00315aad1feff97a0000035d6060091df1a01f121ffff540c000014e0130091e10315aae705fa97e0130091'
        'e17700913212fa97e0770091e10314aa77ffff9760fe07360200001415008052e81740f9894e00d029d942f9290140f93f01'
        '08ebe1000054e00315aafd7b45a9f44f44a9f65743a9ff830191c0035fd6'
    )),
    (0x4ade094, bytes.fromhex(
        'ffc300d1fd7b02a9fd830091090080d2080080d28a4e00d04ad942f94a0140f9aa831ff8fff300b8ff0700f9ea2300914b49'
        '00906b3111912c0080520d0080d24e696d38ae0200370e686d38ce3d0011cf1d0012ff69007188000054ce1d40926e796eb8'
        '020000140e0080522f686938ef3d0011f01d00121f6a007188000054ef1d40926f796fb8020000140f008052df010f6b0001'
        '0054ad050091bf2d00f101fdff54290500913f2d00f181fcff5404000014080500914c692d38faffff171f2d00f1e0179f1a'
        'a8835ff8894e00d029d942f9290140f93f0108eb81000054fd7b42a9ffc30091c0035fd6b9410094'
    )),
    (0x495fc78, bytes.fromhex(
        'ffc302d1fc6f05a9fa6706a9f85f07a9f65708a9f44f09a9fd7b0aa9fd830291885a00b008d942f9080140f9e82700f9e86e'
        '00b008013e9108c1bf3868040036e86e00b008e13d9108c1bf38a84f0036080080d2091c0012ea6e00b04a813e914b854138'
        '7f01096be0000054086100d11f0118b161ffff5460008052e1ffff9704000014e96e00b029c547f9200108cbe82740f9895a'
        '00b029d942f9290140f93f0108eba15a0054fd7b4aa9f44f49a9f65748a9f85f47a9fa6746a9fc6f45a9ffc30291c0035fd6'
        'f36e00b073023e91f40300aae00313aa983a0694e80300aae00314aae8faff34'
    )),
    (0x4962b74, bytes.fromhex(
        'f657bda9f44f01a9fd7b02a9fd830091f30301aaf40300aa0800407908150013083d001135550090b57203911f6900716800'
        '0054a2da68b80200001402008052e00313aa010080d2522d00948806407908150013083d00111f69007168000054a2da68b8'
        '0200001402008052e00313aa21008052472d0094880a407908150013083d00111f69007168000054a2da68b8020000140200'
        '8052e00313aa410080523c2d0094880e407908150013083d00111f69007168000054a2da68b80200001402008052e00313aa'
        '61008052312d00948812407908150013083d00111f69007168000054a2da68b80200001402008052e00313aa81008052262d'
        '00948816407908150013083d00111f69007168000054a2da68b80200001402008052e00313aaa10080521b2d0094881a4079'
        '08150013083d00111f69007168000054a2da68b80200001402008052e00313aac1008052102d0094881e407908150013083d'
        '00111f69007168000054a2da68b80200001402008052e00313aae1008052052d00948822407908150013083d00111f690071'
        '68000054a2da68b80200001402008052e00313aa01018052fa2c00948826407908150013083d00111f69007168000054a2da'
        '68b80200001402008052e00313aa21018052ef2c0094882a407908150013083d00111f69007168000054a2da68b802000014'
        '02008052e00313aa41018052fd7b42a9f44f41a9f657c3a8e12c00140800407908150013083d00111f690071a80000542955'
        '00902971039128d968b802000014080080521f01016ba00d00540804407908150013083d00111f690071a800005429550090'
    )),
    (0x496e104, bytes.fromhex(
        'c2100034421100375f081e72e10200545f081b72a10500545f081872010b00545f081572210800545f08127200100054820f'
        '7837e20da837080082522800a07208cd43114900080a280180523f114071800000546200b037820ea0364801805208682138'
        'c0035fd6882491525f00086a410b0054e20aa83708928c525f00086ae8079f1a49000c72e813881a4a000a120a594a2a5f01'
        '0071480180120815881a0afe0737e9fdff3508498052090082522900a0722801082a5f00086a800b0054e81e8052e7ffff17'
        '082491525f00086a810900546208a83708908c525f00086ae8079f1a49000c72e813881a4a000a120a594a2a5f010071a800'
        '80120815881a0afb0737e9faff3508488052090082522900a0722801082a5f00086a80080054881f8052cfffff1708009152'
        '5f00086a41060054e206a8375f041372e8079f1a49000c72e813881a4a000a120a594a2a5f010071880080520815881a2af8'
        '073709f8ff35080082522800a0725f00086ae0050054c8008052baffff17082091525f00086a210400540203a83708808c52'
        '5f00086ae8079f1a49000c72e813881a4a000a120a594a2a48010013aaf5073789f5ff35080082522800a072080117325f00'
        '086a4003005428008052a5ffff17881e8052a3ffff17681e8052a1ffff17281f80529fffff17c81f80529dffff1708018052'
        '9bffff174800805299ffff17081f805297ffff17a81f805295ffff176800805293ffff17081e805291ffff17e80080528fff'
        'ff1762008037281e80528cffff1768018052'
    )),
    (0x4addfd0, bytes.fromhex(
        'ff8300d1fd7b01a9fd430091ff1f0039e81f0091e80700f9012c0091e2230091c3008052240080528f43fa97fd7b41a9ff83'
        '0091c0035fd6'
    )),
    (0x496ee34, bytes.fromhex(
        'ff8302d1fc6f04a9fa6705a9f85f06a9f65707a9f44f08a9fd7b09a9fd430291e41b00b9f70303aaf40302aae11300f9fb03'
        '00aad954009039331191f31340f9690600d1680a00d1e8a700a9680e00d1e80300f9fc031baa6a021bcb480900f1cc000054'
        '237f00545f0900f1f31340f901010054e40100145f0d00f1603d00545f1100f1a03e00545f1500f1003a00545f5d00f1fc1b'
        '00f9'
    )),
    (0x496f6c0, bytes.fromhex(
        '9f0313eb88070091041153fae9179f1aea1b40b9aa340036293d0037130080d2e9031caaf80308aa28054039083d00110a1d'
        '00125f69007188000054081d4092207b68b8020000140000805228014039083d0011091d00123f69007188000054081d4092'
        '367b68b80200001416008052950240f9a20240390100801227d9fe97f70300aaa2024039e00316aa0100801222d9fe97ff02'
        '006b2a0500541a034039483f0011151d4092fb0313aa88031b8b0901403909050039fb0300b4bf6a007168000054207b75b8'
        '020000140000805208f15f38083d0011091d00123f69007188000054081d4092367b68b802000014160080529c0240f98203'
        '40390100801206d9fe97f70300aa82034039e00316aa0100801201d9fe977b0700d1ff02006bfc1b40f94bfcff5488031b8b'
        '0805009102000014e8031caa1a0100390807009173060091e90318aaea1340f91f010aeba1f6ff549a010014'
    )),
    (0x540644c, bytes.fromhex(
        '0100000000000000040000001000200010000000100010000800000020000000800020008000000080001000400000000001'
        '0000000420000004000000041000000200000008000000202000002000000020100000100000008000000040200000400000'
        '0040100000000100'
    )),
)

# Complete bounded renderer/input/cache route, stored as concise digests.
NAME_NATIVE_DIGESTS = (
    (0x4967b80, 12028, '15079e2ac17cade497aeedfa8ce8de6a78815cebe5a961cb8a520f80e4bf4f48'),
    (0x496d478, 480, '858a9bbbdf6a484454633c8af77b8f6f1393cd020316e5f351262c63bc483ce5'),
    (0x496ae3c, 768, '741e3bf9edcc2e06276369c6fe1db73700c2c35c08b3c7c9db54631f5b74082f'),
    (0x49257e0, 192, '33aedb0772cb32321019f30eac767c64c55ec34f366f7a59ccbd9232ec11882d'),
    (0x5404324, 100, '1c70ca6dca209e91615b355f2691e6b71bc264a6f97485cfc210e3cba0013aab'),
    (0x54060ba, 30, 'b32236178fb45d87e628ab6d4f58affd3ffaa1a06d306931cc3cb74726e833e8'),
    (0x4388224, 336, '98836022e7e262ad5b03fe9f9b8a391c6c98b57a0ba3d41b422fa18133c79ca0'),
    (0x43886b4, 368, '4a8c6a89eb68b3bbfed511970aafde453f02ccf232b086d018e759e77cdfd8ce'),
    (0x496aa7c, 968, 'c861de27b54e034913f692739470846b4527db27939584d00861f31a47cc2a63'),
    (0x4972520, 204, '0c98a817a995ffd387469b6990f7984a65c9066206edaed77d4f6879f03c1067'),
)
