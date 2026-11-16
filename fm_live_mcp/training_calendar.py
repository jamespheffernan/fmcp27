"""Civil-date projection of existing stored TEAM training weeks.

Rows are Monday through Sunday; slots retain native indices, without clock-time
or completion claims. The caller owns TEAM binding and final ReadSet verification.
"""
from datetime import date, timedelta
import re
import struct


MIN_YEAR = 1850
MAX_YEAR = 2200
MAX_DAYS = 366
_ISO_DATE = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}\Z')


def _civil_date(value):
    if type(value) is not str or not _ISO_DATE.fullmatch(value):
        raise ValueError('Training date must be an exact ISO date')
    try:
        result = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError('Invalid training civil date') from error
    if not MIN_YEAR <= result.year <= MAX_YEAR:
        raise ValueError('Training date is outside the supported native range')
    return result


def window(start_date, day_count, current_date):
    """Return every requested civil date, including the first and last dates."""
    if type(day_count) is not int or not 1 <= day_count <= MAX_DAYS:
        raise ValueError('Training day_count must be an integer from 1 through 366')
    start = _civil_date(current_date if start_date is None else start_date)
    end = start + timedelta(days=day_count - 1)
    if not MIN_YEAR <= end.year <= MAX_YEAR:
        raise ValueError('Training end date is outside the supported native range')
    return [start + timedelta(days=index) for index in range(day_count)]


def _address(value, size):
    if (type(value) is not int or value < 4096 or value % 8
            or value + size >= 1 << 64):
        raise ValueError('Invalid training calendar address')


def _read(read, address, size):
    raw = read(address, size)
    if len(raw) != size:
        raise ValueError('Incomplete training calendar read')
    return raw


def verify_native(read, base):
    """Pin accepted DATE normalization, weekday/row and signed slot getters."""
    _address(base, max(rva + len(raw) for rva, raw in NATIVE_SPANS))
    for rva, expected in NATIVE_SPANS:
        if _read(read, base + rva, len(expected)) != expected:
            raise ValueError(f'Training calendar native layout changed at RVA {rva:#x}')


def decode(read, weeks, dates, label):
    """Project ordered resident keys, selecting the first exact native match.

    weeks=None means unavailable source; an empty collection means an available
    source without resident weeks. Invalid native key values remain unmatched;
    no missing week or constructor/default branch is invoked. Only selected
    wrappers' 56-byte bodies are read, at +0x10, and cached for this call.
    """
    if weeks is not None and not isinstance(weeks, (list, tuple)):
        raise ValueError('Invalid training week collection')
    first = {}
    for index, entry in enumerate(weeks or ()):
        if (not isinstance(entry, (list, tuple)) or len(entry) != 3
                or type(entry[0]) is not int or not 0 <= entry[0] <= 65535
                or type(entry[1]) is not int or not 0 <= entry[1] <= 511):
            raise ValueError('Invalid training week key')
        _address(entry[2], 0x48)
        first.setdefault((entry[0], entry[1]), (index, entry[2]))
    if not isinstance(dates, (list, tuple)) or not callable(label):
        raise ValueError('Invalid training calendar projection')
    for value in dates:
        if type(value) is not date or not MIN_YEAR <= value.year <= MAX_YEAR:
            raise ValueError('Invalid training calendar civil date')

    bodies = {}
    result = []
    for value in dates:
        row = value.weekday()
        monday = value - timedelta(days=row)
        day = {
            'date': value.isoformat(), 'week_start': monday.isoformat(),
            'native_weekday': value.isoweekday() % 7 + 1, 'storage_row': row,
            'state': ('unavailable_source' if weeks is None
                      else 'unavailable_resident_week'),
            'native_wrapper_index': None, 'unmapped_row_byte': None,
            'slots': None,
        }
        key = (monday.year, monday.timetuple().tm_yday)
        match = first.get(key)
        if match is not None:
            index, address = match
            if address not in bodies:
                bodies[address] = _read(read, address + 0x10, 56)
            body = bodies[address]
            codes = struct.unpack_from('<hhh', body, row * 8 + 2)
            day.update(
                state='stored_assigned', native_wrapper_index=index,
                unmapped_row_byte=body[row * 8],
                slots=[label(slot, code) for slot, code in enumerate(codes)],
            )
        result.append(day)
    return result


# Batches 15/16, pinned ARM64 build. Native aliases for invalid days are not
# reproduced: window/decode validate civil dates before choosing rows.
NATIVE_SPANS = (
    # weekday_previous_or_same
    (0x42eae28, bytes.fromhex(
        '0804407909011971aa2d80520bf518516bb1891a2c5c8f528cc2b5722c7d2c9b8dfd60d38cfd7fd38c158d0b8b098b0b'
        'eca390526c3daa722c7d2c9b8dfd60d38cfd7fd38c1d8d0b6b010c0b292d0a1b0a0040794a2100122b858b52eb51b872'
        '0b7d0b1b8c148e52ac47a1726d008052ee0180527f010c6bcb318d1a7f01086ae8179f1ae803282a08010a0b0801090b'
        '699284522949b272097d299b29fd60d32901080b2a7d0213497d490b290d094b0801090b08050011091d00123f01216b'
        'c0010054f44fbea9fd7b01a9fd430091081d00130801014b091d00111f01007121b1881af30300aa39bff696600200b9'
        'fd7b41a9f44fc2a8c0035fd6'
    )),
    # subtract_days
    (0x9abf4, bytes.fromhex(
        '6103f83708044079090040792a210012eb03212a4b010b0b6a3d0013eb0178362b858b526c008052ed018052ae2d8052'
        '080500510f7d0b1bef3d0012fff92871af318c1a1f010f6acf158e1a4f010f0bea3d0013effe7f374a05001120191712'
        '40210033003d1033c0035fd6'
    )),
    # wrapper_date_plus_day
    (0x3a09c98, bytes.fromhex(
        '281c409208f17dd309c080d20920a0f24960c0f289a0e0f22825c89a3f20007108319f1a090900120e1c407908184079'
        '0a21001229010a0b290500512a858b526b008052ec01805203000014c901090bae050011cd3d0012ce7d0a1bce3d0012'
        'dff928718f318b1a2e3d0013ff010d6aa0000054dfb50571eb0000546ed29f52f3ffff17dfb905716b0000544ed29f52'
        'efffff1729050011081917122821003300410d2ac0035fd6'
    )),
    # storage_to_weekday
    (0x3a30b50, bytes.fromhex(
        '087c7dd3496080d289a0a0f2c9e0c0f22900e0f22825c89a490080521f1c00710831891a00090012c0035fd6'
    )),
    # week_getter
    (0x3a30644, bytes.fromhex(
        '280400511f19007148010054081d4092c9cd009029411491287968f85f080071e9000054e8ff9f52003d0013c0035fd6'
        '080080d25f08007168ffff54080c088b0845228b08054079003d0013c0035fd6'
    )),
    # day_getter
    (0x3a2ffa4, bytes.fromhex(
        '3f080071a80000540844218b08054079003d0013c0035fd6e8ff9f52003d0013c0035fd6'
    )),
    # raw_index_getter
    (0x3a305f0, bytes.fromhex(
        '084c218b3f1c007100319f9ac0035fd6'
    )),
    # day_pointer_getter
    (0x3a308d0, bytes.fromhex(
        '3f0c00712d020054880080523f1c0071a900805229019f9a3f1800710801899a490080523f1400716a0080524a019f9a'
        '3f10007129018a9a3f14007108c1899a000c088bc0035fd621010034c80080523f0c00712900805229019f9a3f040071'
        '0801899a000c088bc0035fd6000080d2c0035fd6'
    )),
    # weekday_to_row_table
    (0x53e8510, bytes.fromhex(
        '060000000000000000000000000000000100000000000000020000000000000003000000000000000400000000000000'
        '0500000000000000'
    )),
)
