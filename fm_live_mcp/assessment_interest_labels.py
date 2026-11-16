"""Pinned English presentation of stored assessment joining interest.

This module does not evaluate current player willingness or imply a completed
scouting report. English strings are static installed-build resource templates;
the caller verifies the build and canonical stored assessment source separately.
The native surname marker in the already-agreed long template is retained.
"""

SOURCE = 'stored_assessment_native_viewer_english'
PLUGIN_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'

# Installed example.ltf KEYs. Hidden person markers and comments are omitted;
# visible substitution markers remain intact. This is a static English scope.
_LABELS = {227378: 'Unknown',
 242522: 'N/A',
 283690: '[%person#1-surname] has already agreed to move clubs.',
 652317: 'Extremely interested in Senior contract transfer',
 652318: 'Extremely interested in joining our club on Senior contract.',
 652319: 'Extremely Interested',
 652320: 'Extremely interested in joining our club.',
 652321: 'Interested in Senior contract transfer',
 652322: 'Interested in joining our club on a Senior contract.',
 652323: 'Interested',
 652324: 'Interested in joining our club.',
 652325: 'Some interest in Senior contract transfer',
 652326: 'Some interest in joining our club on a Senior contract.',
 652327: 'Slight Interest',
 652328: 'Some interest in joining our club.',
 652329: 'Would need some convincing to join on a Senior contract transfer',
 652330: 'Would need some convincing to join on a Senior contract at this time.',
 652331: 'Dubious',
 652332: 'Would need some convincing to join our club at this time.',
 652333: 'No interest in Senior contract transfer',
 652334: 'Not interested in joining our club on a Senior contract at this time.',
 652335: 'Extremely Doubtful',
 652336: 'Not interested in joining our club at this time.',
 652337: 'Already agreed to move',
 652340: 'None',
 652341: 'No intention of joining our club on a permanent basis.'}


def _uint8(value, name):
    if type(value) is not int or not 0 <= value <= 255:
        raise ValueError(f'Assessment interest {name} must be uint8')
    return value


def _result(state, category, compact, long):
    return {'state': state, 'category': category,
            'compact': {'key': compact, 'text': _LABELS.get(compact)},
            'long': {'key': long, 'text': _LABELS.get(long)},
            'source': SOURCE}


def decode(value, *, field5_present, flag41, child_present, byte79, byte7a):
    """Render both proved English templates without any memory access.

    Only branch-consumed inputs are validated. Missing field5 skips every
    formatter input; N/A skips the value and Senior-wording byte. Unused fields
    may be None, matching the source reader's sparse native projection.
    """
    if type(field5_present) is not bool or type(child_present) is not bool:
        raise ValueError('Assessment interest presence flags must be bool')
    if not field5_present:
        return _result('unknown', None, 227378, 227378)
    _uint8(flag41, 'flag41')
    if flag41 == 1 and (not child_present or not _uint8(byte7a, 'byte7a') & 0x80):
        return _result('not_applicable', None, 242522, 242522)
    if type(value) is not int or not -(1 << 31) <= value < (1 << 31):
        raise ValueError('Assessment interest value must be signed32')
    if value >= 30000:
        category, compact, long = 'extremely_interested', 652319, 652320
    elif value >= 10000:
        category, compact, long = 'interested', 652323, 652324
    elif value >= 5000:
        category, compact, long = 'slight_interest', 652327, 652328
    elif value >= -2000:
        category, compact, long = 'dubious', 652331, 652332
    elif (value & 0xffffffff) >= 0xffff63c0:
        # Native b.lo is unsigned after the preceding signed<-2000 branch.
        category, compact, long = 'extremely_doubtful', 652335, 652336
    elif value == -111111:
        # No resource template selected; final enclosing UI behavior is unproved.
        return _result('native_empty_template', 'native_empty_template', None, None)
    elif value == -100002:
        return _result('available', 'already_agreed_to_move', 652337, 283690)
    else:
        return _result('available', 'none', 652340, 652341)
    if child_present and _uint8(byte79, 'byte79') & 0x20:
        compact -= 2
        long -= 2
    return _result('available', category, compact, long)


def verify_native(read, base):
    """Check pinned formatter bytes; read should be the caller's ReadSet.

    No native function is invoked. Static English resources are tied to the
    accepted installed build, rather than the running UI's selected locale.
    """
    if (type(base) is not int or base < 4096 or base % 8
            or base + max(rva + len(raw) for rva, raw in NATIVE_SPANS) >= 1 << 64):
        raise ValueError('Invalid assessment interest native base')
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Assessment interest native layout changed at RVA {rva:#x}')


# Complete formatter164245C..1642933, including signed/unsigned/special-value
# branches, local N/A and Senior flags, both modes and every English key load.
NATIVE_SPANS = (
    (0x164245c, bytes.fromhex(
        'ff0302d1f65705a9f44f06a9fd7b07a9fdc30191f40300aaf30308aa150302d0a01246f9ffff02a9ff1f00f908008012'
        'e84300b9e81f8052e8130139880641391f05007161040054881a40f9680000b408e94139e8033837e8230091416b9652'
        '6100a072fe64b694b41246f97f0200f9e82340b91f050031e0000054880640f9153d40f9225ca897080840f9bf0208eb'
        'c0090054830402f063c03d91e023009101008052020080125842b694880640f90841483948070034a8a300d1e0230091'
        'c545b694a8835df8e80700b53f000014882240b909a68e521f01096b6b010054881a40f9680000b408e54139c8042837'
        '01040034e8230091e1839e522101a072d764b694af00001409e284521f01096b6b010054881a40f9680000b408e54139'
        'c807283701070034e823009161849e522101a072ca64b694a2000014097182521f01096b8b040054881a40f9680000b4'
        '08e54139c809283701090034e8230091e1849e522101a072bd64b69495000014e823009101849e522101a072b864b694'
        '9000001461050034e8230091a1839e522101a072b264b6948a000014e8230091082100911f0113eb00010054e80b40f9'
        'a80000b4091100d17f0200f92a00805229012ab8680200f9e0230091293db694bb0000141f411f316b030054881a40f9'
        '680000b408e54139e808283721080034e823009161859e522101a0729864b69470000014e823009181849e522101a072'
        '9364b6946b00001461040034e823009121849e522101a0728d64b69465000014e8230091c1839e522101a0728864b694'
        '60000014e98793121f01096b63030054881a40f9680000b408e541390808283781060034e8230091e1859e522101a072'
        '7b64b69453000014e823009101859e522101a0727664b6944e00001481040034e8230091a1849e522101a0727064b694'
        '48000014e823009141849e522101a0726b64b6944300001429bf8952c9ffbf721f01096b80080054c92b8f52c9ffbf72'
        '1f01096b8103005481050034e823009121869e522101a0725d64b69435000014e823009181859e522101a0725864b694'
        '3000001481030034e823009121859e522101a0725264b6942a000014e8230091c1849e522101a0724d64b69425000014'
        'e823009101869e522101a0724864b69420000014c1020034e823009181869e522101a0724264b6941a000014a1020034'
        'e8230091a1859e522101a0723c64b69414000014e823009141859e522101a0723764b6940f000014e823009141858a52'
        '8100a0723264b6940a000014e8230091a1869e522101a0722d64b69405000014e8230091c1859e522101a0722864b694'
        'e0a30091e12300912f3db694e0230091a83cb694800240f9800200b4080040f9095d40f9e823009120013fd6e0a30091'
        'e22300912100805223008052d13db694e00740f9200100b408200091090080120801e9b81f05007181000054080040f9'
        '080540f900013fd6b41246f97f0200f9e84340b91f050031e0000054880640f9153d40f9325ba897080840f9bf0208eb'
        '60030054830402f063c03d91e0a3009101008052020080126841b694880640f908414839e8000034e8230091e0a30091'
        'd544b694e80740f9880100b50c000014e8a30091082100911f0113eb00010054e81b40f9a80000b4091100d17f0200f9'
        '2a00805229012ab8680200f9e0a300916c3cb694fd7b47a9f44f46a9f65745a9ff030291c0035fd6'
    )),
)
