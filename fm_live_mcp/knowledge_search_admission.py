"""Pure dependencies for a future native search-admission replay.

Only the ordinary actual/combined PERSON age dependency is implemented here:
0x148F4C0 and 0x3D574B0..0x3D57648 in build 27.0.0.2493426. This module does
not enumerate candidates, decide admission, read memory, or execute game code.
Compact virtual getters must not be substituted: their age path can generate
and write a profile cache. See evidence/knowledge-population-20261108.
"""
from dataclasses import dataclass
import struct


@dataclass(frozen=True)
class NativeDate:
    """The native DATE's two stored u16 words; upper day bits are flags."""

    day_word: int
    year: int

    def __post_init__(self):
        for value in (self.day_word, self.year):
            if type(value) is not int or not 0 <= value <= 0xFFFF:
                raise ValueError('Native DATE words must be unsigned 16-bit integers')

    @classmethod
    def from_bytes(cls, raw: bytes):
        if type(raw) is not bytes or len(raw) != 4:
            raise ValueError('Native DATE requires exactly four bytes')
        return cls(*struct.unpack('<HH', raw))

    @property
    def day(self):
        return self.day_word & 0x1FF

    @property
    def default(self):
        return self.year == 1900 and self.day == 1


def _anniversary_leap(year):
    # 0x3D575A8..0x3D575DC: preserve the native u16 multiply and mask.
    mask = 15 if ((year * 0x5C29) & 0xFFFF) < 0xA3E else 3
    return year & mask == 0


def _fallback_leap(year):
    # The synthetic-date branch uses a different, 32-bit multiply sequence.
    mask = 15 if ((year * 0xC28F5C29) & 0xFFFFFFFF) < 0x0A3D70A4 else 3
    return year & mask == 0


def person_age(birth_date: NativeDate, at_date: NativeDate, *,
               mode: int | None = None, current_date: NativeDate | None = None,
               alternate_date: NativeDate | None = None,
               fallback_year: int | None = None) -> int:
    """Replay the ordinary PERSON age adapter and native packed-date arithmetic.

    The caller supplies already-read dates and raw mode byte 0x56D4951. Modes
    1/2 choose 0x56D57D0+0x184 for a default as-of DATE; other modes choose
    0x56B1DB8. A residual year1900 uses the u16 at 0x56B3390, capped at 2026.
    The native global-year write is represented only by a local calculation.

    Missing consumed context raises rather than inventing an age. A 1900
    fallback year would recurse indefinitely in native code and is explicit
    here. Inputs preserve raw word semantics, including native 14..100 clamps
    for future/old DOBs; this is not a general calendar-age API.
    """
    if not isinstance(birth_date, NativeDate) or not isinstance(at_date, NativeDate):
        raise ValueError('Expected stored native birth and as-of DATE values')
    if birth_date.default:
        return 0  # PERSON adapter returns before reading the date context.
    if at_date.default:
        if type(mode) is not int or not 0 <= mode <= 255:
            raise ValueError('Native age mode byte is unavailable or invalid')
        at_date = alternate_date if mode in (1, 2) else current_date
        if not isinstance(at_date, NativeDate):
            raise ValueError('Selected native age context DATE is unavailable')
    if at_date.year == 1900:
        if type(fallback_year) is not int or not 0 <= fallback_year <= 0xFFFF:
            raise ValueError('Native age fallback year is unavailable or invalid')
        year = min(fallback_year, 2026)
        if year == 1900:
            raise ValueError('Native age year1900 fallback would recurse indefinitely')
        at_date = NativeDate(214 if _fallback_leap(year) else 213, year)

    bd, ad = birth_date.day, at_date.day
    difference = bd - ad
    age = at_date.year - birth_date.year
    if difference >= 2:
        age -= 1
    elif difference > -2:
        # 0x3D57598..0x3D57620 adjusts only close day-of-year boundaries.
        # Preserve >60 below: changing it to >=60 changes the native March1
        # birth / leap-year February29 result.
        born_leap = _anniversary_leap(birth_date.year)
        at_leap = _anniversary_leap(at_date.year)
        anniversary = bd
        if born_leap and not at_leap and bd > 59:
            anniversary -= 1
        elif not born_leap and at_leap and bd > 60:
            anniversary += 1
        age -= int(ad < (anniversary & 0x1FF))

    # Native sxth precedes both signed comparisons, even for unusual raw years.
    age = ((age + 0x8000) & 0xFFFF) - 0x8000
    return max(14, min(100, age))
