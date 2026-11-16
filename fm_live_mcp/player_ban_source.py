"""Stored PLAYER_BAN lists for caller-validated regular actual-player bindings.

Call verify_native once per request. The caller owns canonical identity/type
checks and final ReadSet verification. Text is the pinned English main template,
not full UI wording, an active-ban filter or a fixture eligibility verdict.
"""
from datetime import date, timedelta
import struct

MAX_RECORDS = 64
PLUGIN_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
LABELS = {665798: 'International', 314612: 'No ban',
          456215: 'Banned for one international match',
          456216: 'Banned for [%number#1] international matches'}


def _address(value, size=0):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid stored player ban source address')


def _read(read, address, size):
    raw = read(address, size)
    if not isinstance(raw, bytes) or len(raw) != size:
        raise ValueError('Incomplete stored player ban source read')
    return raw


def verify_native(read, base):
    """Pin the owned source, typed fields, date default and English key routes."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Stored player ban native layout changed at RVA {rva:#x}')


def _date(raw):
    day, year = struct.unpack('<HH', raw)
    ordinal = day & 511
    result = {'value': None, 'state': 'unmapped_native_start_date', 'raw_hex': raw.hex()}
    if year == 1900 and ordinal == 1:
        result['state'] = 'native_default_sentinel'
    elif 1850 <= year <= 2200 and 1 <= ordinal <= 366:
        value = date(year, 1, 1) + timedelta(days=ordinal - 1)
        if value.year == year:
            result.update(value=value.isoformat(), state='stored_native_start_date')
    return result


def _record(read, address, slot):
    _address(address, 0x20)
    # The internal pointer at+8 and bytes+14/+1B are not consumed by this stored-record projection.
    raw_scope = _read(read, address, 8)
    raw_date = _read(read, address + 0x10, 4)
    cutoff, number, reason = struct.unpack('<hhb', _read(read, address + 0x16, 5))
    total, subtractor = struct.unpack('<bb', _read(read, address + 0x1C, 2))
    kind = raw_scope[5]
    scope = None
    main = {'state': 'unsupported_native_kind', 'key': None, 'text': None, 'quantity': None}
    if kind in (20, 21):
        scope = {'state': 'mapped_native_english', 'key': 665798, 'text': LABELS[665798]}
        if total < 0:
            main['state'] = 'unsupported_date_renderer_branch'
        elif total == 0:
            main = {'state': 'native_zero_total_input', 'key': 314612,
                    'text': LABELS[314612], 'quantity': None}
        else:
            quantity = total - subtractor
            key = 456215 if quantity == 1 else 456216
            main = {'state': 'native_international_match_main_text', 'key': key,
                    'text': LABELS[key].replace('[%number#1]', str(quantity)),
                    'quantity': quantity}
    return {'native_slot_index': slot, 'native_kind': kind, 'scope': scope,
            'main_text': main, 'stored_start_date': _date(raw_date),
            'native_properties': {'badd': total, 'badm': subtractor, 'adby': cutoff,
                                  'reas': reason, 'numb': number},
            'unmapped_scope_context_word': struct.unpack_from('<i', raw_scope)[0],
            'eligibility_state': 'not_evaluated'}


def project(read, primary_address, record_kind):
    """Project one canonical binding without minting refs or evaluating bans.

    The actual-player primary address is already checked by the caller using the
    same ReadSet. Combined and virtual kinds remain explicitly unsupported.
    Physical order and duplicate pointers are retained. Invalid source fails;
    an absent secondary is distinct from a present, checked empty vector.
    """
    if record_kind not in ('actual', 'player_staff', 'virtual'):
        raise ValueError('Unknown player ban binding kind')
    result = {'source_state': 'unsupported_record_kind',
              'physical_record_count': None, 'records': None}
    if record_kind != 'actual':
        return result
    _address(primary_address, 0xF8)
    secondary = struct.unpack('<Q', _read(read, primary_address + 0xF0, 8))[0]
    if not secondary:
        result['source_state'] = 'secondary_absent'
        return result
    _address(secondary, 0x30)
    start, end, capacity = struct.unpack('<QQQ', _read(read, secondary + 0x18, 24))
    if start == end == capacity == 0:
        count = 0
    else:
        if (start < 4096 or not start <= end <= capacity
                or any(value % 8 for value in (start, end, capacity))):
            raise ValueError('Invalid stored player ban vector bounds')
        count = (end - start) // 8
        if count > MAX_RECORDS:
            raise ValueError('Stored player ban record reader bound exceeded')
        _address(start, end - start)
    pointers = _read(read, start, count * 8) if count else b''
    records = [_record(read, struct.unpack_from('<Q', pointers, slot * 8)[0], slot)
               for slot in range(count)]
    return {'source_state': 'present_records' if count else 'present_empty',
            'physical_record_count': count, 'records': records}


def resolve_competition_scopes(read, base, projection):
    """Enrich only proved kind1 COMP operands; caller verifies the same ReadSet.

    This identifies a stored scope, never activation, carryover or eligibility.
    Other kinds may interpret the same word in a different native table.
    """
    from . import competitions
    for record in projection.get('records') or []:
        if record['native_kind'] != 1:
            continue
        for rva, expected in COMP_SCOPE_SPANS:
            if _read(read, base + rva, len(expected)) != expected:
                raise ValueError('Stored ban competition operand route changed')
        index = record['unmapped_scope_context_word']
        if index < 0:
            record['scope'] = {'state': 'native_competition_sentinel',
                               'competition': None}
        else:
            # Canonical typed lookup rejects aliases, conflicting tables and drift;
            # errors intentionally reject the entire checked request.
            competition = competitions.by_index(read, base, index)
            record['scope'] = {'state': 'stored_native_competition',
                               'competition': competition}
        total = record['native_properties']['badd']
        served = record['native_properties']['badm']
        record['stored_match_balance'] = {
            'state': 'stored_total_minus_served' if total >= 0 and 0 <= served <= total
                     else 'unsupported_native_count_inputs',
            'matches': total - served if total >= 0 and 0 <= served <= total else None,
            'total': total, 'served': served,
            'activation_state': 'not_evaluated'}
    return projection


# Actual kind1 branch resolves record+0 through the COMP table. Pinned separately
# from the international text branch; no other kind is assumed to share it.
COMP_SCOPE_SPANS = (
    (0x3cc6dc8, bytes.fromhex('281440391f7d0071a00500541f05007121dbff54280040b91f050031c0daff54a8daff3769d00090299946f949daffb46ad000b04a8153392a1e00372aad46a96b010acb1f0d8beba21d0054f30302aa480d088bf2000014')),
    (0x3cc71c4, bytes.fromhex('294540f9292940a94a0109eb60bbff541f0d8aeb22bbff54f30302aa280d088b000140f9a0baffb4689e40f91f0100eb20c3ff54085840f91f0113ebc0c2ff5468e643f9a8b9ffb4089d40f91f0100eb41b9ff5410feff17')),
)


# Selected stored-list, property, scope and main-text code from the supported
# build. No runtime evidence-file access and no game functions are invoked.
NATIVE_SPANS = (
    (0xcfdc64, bytes.fromhex(
        'e00318aaa5a01394ff2300f9777a40f9787a00f9170400b4'
    )),
    (0xcfdd00, bytes.fromhex(
        '777a40f9e23340f9e20000b4e02b40f9a00000b4e12f40f9080040f9081940f900013fd69ffe00a99f8201f8e1430191'
        'e00317aac6a71394'
    )),
    (0x11e82d0, bytes.fromhex(
        '00e4006f600300ad08008012680300b9750b0079791300b9784301f8783b0079e0031baae11b40f9a8d4b994c00d0036'
        'fb2300f9882642a91f0109eb820000541b8500f8881200f928000014e1030191e00313aaf50c0094fb2340f9801200f9'
    )),
    (0x11e6f68, bytes.fromhex(
        '602602b000c01091a1f601b021ac2191020880520304805204008052050080520608805207008252e8bec594'
    )),
    (0x50bb86b, bytes.fromhex(
        '504c415945525f42414e00'
    )),
    (0x405fb18, bytes.fromhex(
        '28bc68d31f4d00712c0300541f1500714d0600541f190071e00900541f290071800c00541f3d007101240054bf060031'
        'e01a0054'
    )),
    (0x405fb84, bytes.fromhex(
        '095100513f090071830400541f650071200500541f7d0071'
    )),
    (0x405fc1c, bytes.fromhex(
        'c2010034e8430091e00314aac11885524101a07222ef0d94d400001482060034e8430091e00314aae11885524101a072'
        '1bef0d94cd000014e8430091e00314aaa1668f526100a07215ef0d94'
    )),
    (0x405e060, bytes.fromhex(
        '1bff68d3d603f837d702194bf60f0034681f00121f4d0071cc1800541f150071'
    )),
    (0x405e268, bytes.fromhex(
        'e8230091e00315aa819e99528100a07290f50d94e0e30091'
    )),
    (0x405f260, bytes.fromhex(
        'ff06007141010054e8230091e00315aae1c29e52c100a07290f10d94e0e30091e1230091f7e90d9400fcff17e8230091'
        'e00315aa01c39e52c100a07287f10d94e0e30091e1230091eee90d94'
    )),
    (0x380b44, bytes.fromhex(
        'e00314aa818c8c52214cac7293df0195ad0f0295f60300aae00314aaa18d8c52214cac728ddf0195a70f0295f70300aa'
        'e00314aa612e8c52a14cae7287df0195a10f0295fc0300aae00314aa41ac8d52a1cead7281df0195af0f0295f90300aa'
        'e00314aa412c8f52218cac727bdf0195a90f0295f80300aae00314aa818c8e52614eac7275df0195f40300aaefbdfd94'
        'e10314aa8abefd94'
    )),
    (0x380c44, bytes.fromhex(
        'a10352f8889902b008e13691e80300f9e0431e91e7e31191e2031caae30316aae40317aae50318aae60319aabc74f394'
    )),
    (0x1f848ac, bytes.fromhex(
        'e87a40f9880700b408a541a9290108cb9f0f89eb020700541b797cf8db0600b4e81340b928010034e0031baa2a6f8394'
        '28bf40391f050071e8179f1a0800084a480200362c000014180200b488ba01b008e943f908ad40f9680000b4003940f9'
        '02000014000080d2e1031baae20318aa63b901b063e03691e40319aa05008052f60775948003003468174039b3000034'
        '086900511f3d007182000054160000141fa1007180020054e0fc919408200091e8ff01a9e1630091e0031baaba1fee97'
        'e1630091'
    )),
    (0x1b0c89c, bytes.fromhex(
        '952ac0790ddda39408a00091f53300b9e81700f9e0e30091e2a30091814d8e52618eac7278aea394e01740f9080040f9'
        '080d40f9e1a3009100013fd69572c039fedca39408a00091f53300b9e81700f9e0e30091e2a30091818c8c52214cac72'
        '69aea394e01740f9080040f9080d40f9e1a3009100013fd69576c039efdca39408a00091f53300b9e81700f9e0e30091'
        'e2a30091a18d8c52214cac725aaea394e01740f9080040f9080d40f9e1a3009100013fd6952ec079e0dca39408a00091'
        'f53300b9e81700f9e0e30091e2a30091412c8f52218cac724baea394e01740f9080040f9080d40f9e1a3009100013fd6'
        '956ac039d1dca39408a00091f53300b9e81700f9e0e30091e2a30091612e8c52a14cae723caea394e01740f9080040f9'
        '080d40f9e1a3009100013fd69532c079c2dca39408a00091f53300b9e81700f9e0e30091e2a3009141ac8d52a1cead72'
        '2daea394e01740f9080040f9080d40f9e1a3009100013fd6628e9f9488224079892640790a7d09534945092a09211833'
        'e93300b9e01700f9e0e30091e2a30091818c8e52614eac721baea394e01740f9'
    )),
    (0x1b0ca9c, bytes.fromhex(
        'ff1b00b9e8a30091e2630091e00314aa010080525c010094e0e30091e2a3009101ee8d52616cae72f7ada394e01740f9'
        '080040f9080d40f9e1a3009100013fd6'
    )),
    (0x405e390, bytes.fromhex(
        '095100513f090071437600541f650071607d00541f7d0071817e0054'
    )),
    (0x405e2fc, bytes.fromhex(
        'f70b00b9e8630191e023009187c70d94e0e30091e263019121008052030080526dee0d94'
    )),
    (0x11e823c, bytes.fromhex(
        'f55f81523900805299eda072'
    )),
)
