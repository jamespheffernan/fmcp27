"""Private stored annual stadium-rental cash property, without game calls.

Native GAME_CLUB Csry dispatches CLUB+150 finance vslot380. Its concrete
CLUB_FINANCE leaf reads signed32+7f8; CLUB_FINANCE_BASE returns literal zero.
Installed editor Csry is cash, Stadium Rental Per Year, without pence storage.

Caller must check process/save/plugin before and after in its real read scope.
Local rechecks establish consumed-byte stability, not atomicity or freshness.
This is one recorded annual rent value; no payment timing, legal commitment,
future liability, actual outstanding debt, payroll or offer affordability.
"""
from dataclasses import dataclass
import struct

from . import database, players, wages, world

PLUGIN_SHA256 = players.SHA256
PROPERTY = 'Csry'
FINANCE_OFFSET = 0x150
RENT_OFFSET = 0x7F8
RENT_SLOT = 0x380
GETTERS = {'club_finance': 0xEB8768, 'club_finance_base': 0xE64C1C}


@dataclass(frozen=True)
class ClubBinding:
    """Consumer-selected canonical CLUB identity; not a permission token."""
    address: int
    database_index: int
    native_id: int
    secondary_id: int

    def __post_init__(self):
        if (type(self.address) is not int or not 4096 <= self.address < (1 << 64) - FINANCE_OFFSET - 8
                or self.address % 8):
            raise ValueError('Invalid annual-rent CLUB address')
        for value in (self.database_index, self.native_id, self.secondary_id):
            if type(value) is not int or not 0 <= value < 1 << 32:
                raise ValueError('Invalid annual-rent CLUB identity')
        if self.database_index == 0xFFFFFFFF or not self.native_id:
            raise ValueError('Invalid annual-rent CLUB canonical identity')


def verify_native(read, base):
    last_offset = max(*(rva + len(raw) for rva, raw in NATIVE_SPANS),
                      world.TYPES['game_club'][0] + 22 * 8 + 8,
                      *(world.TYPES[kind][0] + RENT_SLOT + 8 for kind in GETTERS))
    if type(base) is not int or base < 4096 or base % 8 or base >= (1 << 64) - last_offset:
        raise ValueError('Invalid annual-rent native base')
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Annual-rent native property changed at {rva:#x}')
    for rva, slot, getter in ((world.TYPES['game_club'][0], 22 * 8, 0x1FAF4D8),
                              (world.TYPES['club'][0], 3 * 8, 0xE476C4),
                              *((world.TYPES[kind][0], RENT_SLOT, getter) for kind, getter in GETTERS.items())):
        if players.u64(read(base + rva + slot, 8)) != base + getter:
            raise ValueError('Annual-rent native virtual dispatch changed')


def read_annual_rent(read, base, club: ClubBinding):
    """Return the selected club's recorded native cash/year, not a forecast.

    The amount preserves the signed native cash domain. Negative values are
    not reinterpreted as missing, refunds or legal credits. Missing finance is
    unavailable; typed base finance's literal zero is a distinct native result.
    No caller-supplied currency or finance pointer bypasses checked sources.
    """
    if type(club) is not ClubBinding:
        raise ValueError('Require a selected canonical CLUB binding')
    observed = world.ReadSet(read)
    verify_native(observed, base)
    world.typed(observed, base, club.address, 'club')
    actual = struct.unpack('<III', observed(club.address + 8, 12))
    if actual != (club.database_index, club.native_id, club.secondary_id):
        raise ValueError('Annual-rent selected CLUB identity changed')
    table = database.table(observed, base, 'clubs')
    database.club_membership(observed, base, table, club.database_index, club.address)
    finance = players.u64(observed(club.address + FINANCE_OFFSET, 8))
    result = dict(club_native_identity=dict(database_index=club.database_index, native_id=club.native_id,
                      raw_secondary_id=club.secondary_id), amount=None, currency=None, period='year',
                  state='unavailable', reason='no_finance_record', native_property=PROPERTY,
                  freshness='stored_without_refresh', non_atomic_read=True,
                  native_functions_executed=False, game_writes=False)
    if finance:
        if finance < 4096 or finance % 8 or finance >= (1 << 64) - RENT_OFFSET - 4:
            raise ValueError('Invalid annual-rent finance pointer')
        vtable = world.pointer(observed, finance)
        kind = next((kind for kind in GETTERS if vtable == base + world.TYPES[kind][0]), None)
        if kind is None:
            raise ValueError('Unsupported annual-rent finance type')
        world.typed(observed, base, finance, kind)
        if kind == 'club_finance_base':
            amount, reason = 0, 'native_base_finance_literal_zero'
        else:
            amount = struct.unpack('<i', observed(finance + RENT_OFFSET, 4))[0]
            reason = 'native_stored_annual_rent'
        result.update(amount=amount, currency=wages.base_currency(observed, base),
                      state='decoded', reason=reason, finance_kind=kind)
    if database.table(observed, base, 'clubs')['identity'] != table['identity']:
        raise ValueError('Annual-rent CLUB table changed')
    observed.verify()
    return result


# Exact static Csry comparison path, native cash-variant caller and getter
# bodies. Image verification and process/save lifetime remain caller-owned.
NATIVE_SPANS = (
    (0x1faf568, bytes.fromhex('284a8c52')),
    (0x1faf56c, bytes.fromhex('686ea872')),
    (0x1faf570, bytes.fromhex('df02086b')),
    (0x1faf574, bytes.fromhex('fa3b00f9')),
    (0x1faf578, bytes.fromhex('ac120054')),
    (0x1faf7cc, bytes.fromhex('a82c8c52')),
    (0x1faf7d0, bytes.fromhex('688aaa72')),
    (0x1faf7d4, bytes.fromhex('df02086b')),
    (0x1faf7d8, bytes.fromhex('4c150054')),
    (0x1faf7dc, bytes.fromhex('88ce8c52')),
    (0x1faf7e0, bytes.fromhex('886ea872')),
    (0x1faf7e4, bytes.fromhex('df02086b')),
    (0x1faf7e8, bytes.fromhex('8d210054')),
    (0x1fafc18, bytes.fromhex('888d8e52')),
    (0x1fafc1c, bytes.fromhex('686ea872')),
    (0x1fafc20, bytes.fromhex('df02086b')),
    (0x1fafc24, bytes.fromhex('2c260054')),
    (0x1fafc28, bytes.fromhex('682c8e52')),
    (0x1fafc2c, bytes.fromhex('686ea872')),
    (0x1fafc30, bytes.fromhex('df02086b')),
    (0x1fafc34, bytes.fromhex('2c980054')),
    (0x1fb0f38, bytes.fromhex('e84d8e52')),
    (0x1fb0f3c, bytes.fromhex('686ea872')),
    (0x1fb0f40, bytes.fromhex('df02086b')),
    (0x1fb0f44, bytes.fromhex('4dca0054')),
    (0x1fb0f48, bytes.fromhex('084e8e52')),
    (0x1fb0f4c, bytes.fromhex('686ea872')),
    (0x1fb0f50, bytes.fromhex('df02086b')),
    (0x1fb0f54, bytes.fromhex('e07c0354')),
    (0x1fb0f58, bytes.fromhex('284f8e52')),
    (0x1fb0f5c, bytes.fromhex('686ea872')),
    (0x1fb0f60, bytes.fromhex('df02086b')),
    (0x1fb0f64, bytes.fromhex('206c0254')),
    (0x1fb5ce8, bytes.fromhex('40ab40f9')),
    (0x1fb5ce8, bytes.fromhex('40ab40f9080040f908c141f900013fd6f30300aaf637919400a00091f35b01b9e8c30391003100f9e8430591f43740f91f0114eb80010054800240f9080040f9080d40f9e10314aa00013fd6f3c30391601ac03d8002803de537919400200091607e06a9080040f9080d40f9e143059100013fd6')),
    (0xeb8768, bytes.fromhex('00f847b9c0035fd6')),
    (0xe64c1c, bytes.fromhex('00008052c0035fd6')),
)
