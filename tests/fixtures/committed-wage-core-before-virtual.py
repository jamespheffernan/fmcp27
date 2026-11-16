"""Private copied-native wage reducer, after the separately proved offer selector.

This is not an installed financial answer. The caller supplies the selector's
ordered addresses (duplicates and null slots retained) and a process/save/image
lifetime reader. All instructions execute in a private Unicorn VM. No process
function or write callback exists. Unknown callees, generation, source stores
outside explicitly owned counters/caches, and incomplete reads are unavailable.
"""
from dataclasses import dataclass
import hashlib
import os
import struct
import time
from functools import lru_cache

import unicorn as uc
from unicorn import arm64_const as arm

from . import assessment_people, database, ffp_projection as ffp, live_transfer_offers as offers
from . import players, teams, world

MAX_INSTRUCTIONS = 300000
MAX_READ_BYTES = 128*1024*1024
MAX_READ_CALLS = 200000
_FULL_FINANCE_ROOT = 0x56d2c68
_FULL_FINANCE_VTABLE = 0x55dfcf8
_FULL_FINANCE_RTTI = 0x55dff18
_FULL_FINANCE_NAME = 0x53b1011
_EAEB_REDUCER_CALL = bytes.fromhex(
    '36410290c03646f9080040f9084540f9e10315aae20313aa030080d200013fd6')

class SourceUnavailable(ffp.UnsupportedProjection):
    """The bounded copied routine cannot establish this result."""


@dataclass(frozen=True)
class WageReduction:
    field_818: int
    field_81c: int
    field_820: int
    field_824: int
    returned_signed32: int
    selected_offer_addresses: tuple[int, ...]
    roster_slots: int


@lru_cache(maxsize=2)
def _verified_image(stamp):
    with open(stamp[0], 'rb') as image:
        if hashlib.file_digest(image, 'sha256').hexdigest() != players.SHA256:
            raise SourceUnavailable('native image fingerprint changed')
        st = os.fstat(image.fileno())
        if (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns) != stamp[1:]:
            raise SourceUnavailable('native image changed while fingerprinting')


# Full function boundaries from the pinned ARM64 LC_FUNCTION_STARTS, not
# instruction-prefix guesses. The selector is deliberately outside this list.
_SPANS = (
    (0xcb43bc, 0xcb4414, "98909b3333920fda07664b887d6ac750fc2077659ffd80ff34ac7845623ce817"),
    (0xcb44b4, 0xcb45dc, "4dabf9e1e712eb526b9c5f23518be8d51304d8b3fd9e2e15213a3c12b44e6010"),
    (0xcb45dc, 0xcb45f0, "9a73fa3d73fb2e7bcff127a63fe56715835cf7f690fd3fa3592013eb3664e188"),
    (0xcb85fc, 0xcb8c68, "671f408e0f459d91457c63d89717b3937b07703b9bdeebfe868c1ad1baa62b62"),
    (0xcb8c68, 0xcb8c7c, "25c942ded4925619f93fb980c3fde293992b8e61aa50588e1f093c2a01e5cabb"),
    (0xcbf0dc, 0xcbf14c, "5b8db0addbfd60543f19bf1306c048942d859031ab370bde6f5524c6b902ad9b"),
    (0xcbfce8, 0xcc0014, "4452f4b82c49ba75a8118aa87c1f8460c408ac5e817a70d145893a630f64cffb"),
    (0xcc0014, 0xcc0450, "4a8269aa5787aa67105737d0a681cfaa6cf7720f6f6c7d996438569789e9a630"),
    (0xd5c5fc, 0xd5c610, "62e50aff752959cc367e0ab72a4ea1286e80d2e70d5a58cc8796f16a3c89568d"),
    (0xd5c610, 0xd5c624, "2d883d700de5b56d2a890e12a2ab812b060f3c7c4a9766e4249a57cc90313472"),
    (0xd87790, 0xd8788c, "d929a519e78cf76c26adb58abdbafaee25d906ed9a8ece40d45cb91568d083ac"),
    (0xd88c6c, 0xd88c74, "2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a"),
    (0xd88c8c, 0xd88c94, "2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a"),
    (0xd8c3c0, 0xd8c3c8, "1f31d5ff0e22c7c2e3b958e4e0186cb71a2e67a614d53dd8d744824fcd4b1d53"),
    (0xd8c3d0, 0xd8c3d8, "94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8"),
    (0xdfa958, 0xdfab34, "5efa33faa39fed2403f419fd5818397a0dbc989a692e9c8410c8d3b0da181af7"),
    (0xff1bd0, 0xff1eac, "19b94b1ade9155ec533025dec9d08e327155b4d9c805ef3f326b22d03c99d19b"),
    (0xff1ed8, 0xff21b4, "551a5a35201aa37ad23be3d0c040693f2e1f6264d03e9819d35d552610b466d4"),
    (0x1002b10, 0x1002ce0, "0dff388ca230f9cfc0a0b08ef34992f46ea133db432b2a8ef4333dee3486728f"),
    (0x1005c60, 0x1005c68, "5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac"),
    (0x1005c70, 0x1005c78, "5a3dbf09a4e8bdcceec86da53e57e6eb7ac66ceb50eedbff297fa2d5d118a7be"),
    (0x1005c78, 0x1005c80, "b1636ea235ffc2d779c1a23a09949d9eb649dc15c0e8815925131acf28ad2abf"),
    (0x1005c90, 0x1005c98, "202b2f20cab67372e4d0f3ce5eaa8cf7cc723ac9dc52103896995f3d35d5016c"),
    (0x1006b44, 0x1006b4c, "0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a"),
    (0x127be34, 0x127be3c, "19754834a98690466ae0cf10916de13cbd57a470a9be644b3efc97399eb2302b"),
    (0x12920f8, 0x1292164, "900da63a273d69f6ef1328bd1bcddb70863a3006d26c24dcbb41180d85dfcd18"),
    (0x129a4b8, 0x129a4c0, "23ba31bca6e99eeaeca35232f284c89f546e52d3ab4cc441902fc17db7fc1dc1"),
    (0x129b5f4, 0x129b804, "b466ba9eea2be8ccf0d61696fbe6fefaaf749f262afe2c3753e78aa2843f11a0"),
    (0x129fffc, 0x12a0004, "2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a"),
    (0x13781b8, 0x13781c0, "5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac"),
    (0x13781c0, 0x13781c8, "5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac"),
    (0x181e16c, 0x181e174, "d3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3"),
    (0x181e174, 0x181e17c, "d3c844a0173107453aa9896cdb7276470625501e7ff067cd764c7a160ece5ca3"),
    (0x181ed88, 0x181ed90, "f2a41acf67c1de0eee5443c8fa2e53019a2650b802e011084b07064fdddf8e82"),
    (0x1831790, 0x1831798, "d5b79016b9fb751da31585e8fe24a684680be6bc5e71460e2422f620bbe78195"),
    (0x1831a1c, 0x1831a24, "6b5eade566e78d8649a397cb7fe17ef26a1b166b9a6810377342a0796be72586"),
    (0x1834944, 0x183494c, "0becf359e148792c5ed24ca79a91209e5f15e0f015d2a0b9f4d69c2e82d59f3a"),
    (0x1838278, 0x1838294, "a43beba5966235da2f8979ab8a3a20690390d4de7c8a248a8df16c7eb216ab21"),
    (0x1838294, 0x18382a4, "2fe2b69dd838e9d32a114066185e0b6343b09faa2947d6a6d19d3808df65afb7"),
    (0x1845ba8, 0x1845bb0, "008816324250c06e66ca174f257c933b0d3a7d05ae19334ddb101a72517eaadd"),
    (0x1855484, 0x185548c, "7cffe687c758bc2cd950a25a5cf0fffb605cc3561d20b4b0a099f830c104365b"),
    (0x185a328, 0x185a58c, "3ea6caa9508446512b6aef17cfa6e8b0beee716260a3d6550f1be2668e9a47d0"),
    (0x185a5a4, 0x185a5b4, "83fee84efcfed8e61bfcf12292329d7660967fa45459709f6c22c92f162ef8e4"),
    (0x1871f18, 0x1871f20, "5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac"),
    (0x18753f8, 0x1875400, "866b82fb6649dcf0f7873c61006d47004b1074ea9b382227c4ab724c93f547f7"),
    (0x1fe8af8, 0x1fe9e18, "80045d37fbf2d970106e68d0bc7b2f4583f3f40de90a4a502409a2431feeaa0b"),
)


def _address(value):
    if type(value) is not int or not 4096 <= value < (1 << 64) - 0x10000 or value % 8:
        raise SourceUnavailable('invalid canonical address')
    return value


def _vector(read, address, stride=8, limit=100000):
    begin, end, capacity = struct.unpack('<QQQ', read(address, 24))
    if (begin, end, capacity) == (0, 0, 0):
        return begin, end
    if (begin < 4096 or any(x % 8 for x in (begin, end, capacity))
            or not begin <= end <= capacity or (end-begin) % stride
            or (capacity-begin) % stride or capacity-begin > limit*stride):
        raise SourceUnavailable('invalid owned vector geometry')
    return begin, end


def _resolved_person(read, base, people, reference):
    if not reference:
        return 0
    _address(reference)
    index, native = struct.unpack('<iI', read(reference+8, 8))
    if native != 0xffffffff:
        return reference
    if index < 0:
        return 0
    start, count = people['start'], people['count']
    if not read(base+teams.LOOKUP_MODE, 1)[0] & 1:
        fast, end = _vector(read, people['root']+0x68, limit=2000000)
        if index < (end-fast)//8:
            start, count = fast, (end-fast)//8
    return players.u64(read(start+8*index, 8)) if index < count else 0


def _full_finance_service(read, base):
    """Bind EAEB44's actual full service, without asserting its refresh context."""
    service = players.u64(read(base+_FULL_FINANCE_ROOT, 8))
    if not service:
        raise SourceUnavailable('full finance service root is unavailable')
    _address(service)
    table = base+_FULL_FINANCE_VTABLE
    if players.u64(read(service, 8)) != table:
        raise SourceUnavailable('full finance service runtime type changed')
    if struct.unpack('<qQ', read(table-16, 16)) != (0, base+_FULL_FINANCE_RTTI):
        raise SourceUnavailable('full finance service RTTI or displacement changed')
    name = players.u64(read(base+_FULL_FINANCE_RTTI+8, 8))
    expected_name = b'17GAME_CLUB_FINANCE\0'
    if name != base+_FULL_FINANCE_NAME or read(name, len(expected_name)) != expected_name:
        raise SourceUnavailable('full finance service RTTI name changed')
    if players.u64(read(table+0x88, 8)) != base+0x1fe8af8:
        raise SourceUnavailable('full finance service reducer dispatch changed')
    if read(base+0xeaec30, len(_EAEB_REDUCER_CALL)) != _EAEB_REDUCER_CALL:
        raise SourceUnavailable('EAEB full-service caller binding changed')
    return service


class _StaticBindings:
    """Read the pinned Mach-O's actual DYLD_CHAINED_PTR_64_OFFSET chains."""
    def __init__(self, image, base):
        self.image, self.base, self.segments, self.cache = image, base, [], {}
        header = self.raw(0, 32)
        if struct.unpack_from('<I', header)[0] != 0xfeedfacf:
            raise SourceUnavailable('invalid pinned ARM64 Mach-O')
        at = 32
        for _ in range(struct.unpack_from('<I', header, 16)[0]):
            command, length = struct.unpack('<II', self.raw(at, 8))
            if length < 8 or length > 0x10000:
                raise SourceUnavailable('invalid native load command')
            if command == 0x80000034:
                offset, count = struct.unpack('<II', self.raw(at+8, 8))
                if not 28 <= count <= 1024*1024:
                    raise SourceUnavailable('native fixup metadata bound')
                blob = self.raw(offset, count)
                if struct.unpack_from('<I', blob)[0] != 0:
                    raise SourceUnavailable('unknown native fixup version')
                start = struct.unpack_from('<I', blob, 4)[0]
                segments = struct.unpack_from('<I', blob, start)[0]
                if segments > 32:
                    raise SourceUnavailable('native fixup segment bound')
                for relative in struct.unpack_from(f'<{segments}I', blob, start+4):
                    if not relative:
                        continue
                    record = start+relative
                    size, page_size, kind, segment, _, pages = struct.unpack_from('<IHHQIH', blob, record)
                    if kind != 6 or page_size != 0x4000 or size < 22+2*pages:
                        raise SourceUnavailable('unknown native fixup layout')
                    starts = struct.unpack_from(f'<{pages}H', blob, record+22)
                    self.segments.append((segment, page_size, starts))
                break
            at += length
        else:
            raise SourceUnavailable('missing native chained fixups')

    def raw(self, offset, size):
        raw = os.pread(self.image.fileno(), size, ffp.ARM_SLICE+offset)
        if len(raw) != size:
            raise SourceUnavailable('incomplete pinned image')
        return raw

    def relocated(self, offset, size, *, leave_imports=False):
        result = bytearray(self.raw(offset, size))
        for segment, page_size, starts in self.segments:
            if offset+size <= segment or offset >= segment+page_size*len(starts):
                continue
            first = max(0, (offset-segment)//page_size)
            last = min(len(starts), (offset+size-1-segment)//page_size+1)
            for page in range(first, last):
                key = segment+page*page_size
                if key not in self.cache:
                    fixups = {}
                    position = starts[page]
                    if position != 0xffff:
                        if position & 0x8000:
                            raise SourceUnavailable('unsupported native multi-start chain')
                        seen = set()
                        while True:
                            if position in seen or position+8 > page_size:
                                raise SourceUnavailable('invalid native fixup chain')
                            seen.add(position)
                            word, = struct.unpack('<Q', self.raw(key+position, 8))
                            fixups[key+position] = word
                            step = (word >> 51) & 0xfff
                            if not step:
                                break
                            position += step*4
                    self.cache[key] = fixups
                for address, word in self.cache[key].items():
                    if address+8 <= offset or address >= offset+size:
                        continue
                    if word >> 63:
                        if leave_imports:
                            continue
                        raise SourceUnavailable('unproved imported static binding')
                    value = self.base+(word & 0xfffffffff)+(((word >> 36) & 255) << 56)
                    packed = struct.pack('<Q', value)
                    lo, hi = max(offset, address), min(offset+size, address+8)
                    result[lo-offset:hi-offset] = packed[lo-address:hi-address]
        return bytes(result)


class _ReducerCPU(ffp.FinanceCPU):
    def __init__(self, read, read_live, base, image, finance, club, selected, people):
        self.snapshot = read
        self.finance, self.club, self.selected = finance, club, selected
        self.team_links = {address+offset for address in set(selected)-{0} for offset in (0x40, 0x50)}
        self.person_links = {address+0x38 for address in set(selected)-{0}}
        self.people = people
        self.team_table = teams.lookup(read, base)
        self.allowed = {}
        self.checked = set()
        self.instructions = 0
        self.source_failure = None
        self.source_writes = [(finance+0x818, finance+0x828)]
        self.roster_common = set()
        self.valid_persons = set()
        self.valid_contracts = set()
        self.valid_teams = set()
        self.static_bindings = _StaticBindings(image, base)
        for start, end, digest in _SPANS:
            raw = os.pread(image.fileno(), end-start, ffp.ARM_SLICE+start)
            if len(raw) != end-start or hashlib.sha256(raw).hexdigest() != digest:
                raise SourceUnavailable(f'pinned native function changed at {start:#x}')
            self.allowed[start] = (end, raw)
        # Page fills are transport only. FinanceCPU rechecks consumed spans;
        # registering whole pages with ReadSet would falsely reject padding.
        for address in set(selected)-{0}:
            self.source_writes.extend(((address+8, address+12), (address+0x38, address+0x40)))
        super().__init__(read_live, base, image)
        self.deadline = time.monotonic()+10
        self._hook(uc.UC_HOOK_CODE, self._instruction)
        self._hook(uc.UC_HOOK_MEM_WRITE, self._store)
        self.selection_vector = ffp.SCRATCH+0x1000
        if selected:
            self.vm.mem_write(self.selection_vector, struct.pack(f'<{len(selected)}Q', *selected))
        self.allocations[self.selection_vector] = len(selected)*8

    def _page(self, page):
        if page not in self.pages and len(self.pages) >= 1024:
            raise SourceUnavailable('reducer input page bound')
        return super()._page(page)

    def _fault(self, vm, access, address, size, value, user):
        try:
            return super()._fault(vm, access, address, size, value, user)
        except Exception as exc:
            # Unicorn can replace a fault-hook exception with UC_ERR_*. Keep
            # the actual unavailable input boundary alongside its guest PC.
            self.source_failure = str(exc)
            raise

    def _store(self, vm, access, address, size, value, user):
        if ffp.SCRATCH <= address and address+size <= ffp.SCRATCH+ffp.SCRATCH_SIZE:
            return
        if not any(first <= address and address+size <= last for first, last in self.source_writes):
            raise SourceUnavailable(f'unproved local source store at {address:#x}')

    def _person(self, person):
        if person in self.valid_persons:
            return
        primary, offset, public, _, _ = assessment_people._person(
            self.snapshot, self.base, self.people, _address(person))
        if public['record_kind'] not in ('actual', 'player_staff'):
            raise SourceUnavailable('cold or non-player PERSON specialization')
        common_offset = 0x370 if public['record_kind'] == 'player_staff' else 0x278
        common_table = 0x558fbf0 if public['record_kind'] == 'player_staff' else 0x5589a90
        if world.pointer(self.snapshot, primary+common_offset) != self.base+common_table:
            raise SourceUnavailable('COMMON primary backlink changed')
        self.roster_common.add(primary+common_offset)
        self.valid_persons.add(person)

    def _common(self, address):
        vt = world.pointer(self.snapshot, _address(address))
        common = {0x5589a90: (0x278, 0x388), 0x558fbf0: (0x370, 0x480)}.get(vt-self.base)
        if common is None:
            raise SourceUnavailable('unproved COMMON specialization')
        self._person(address-common[0]+common[1])
        if address not in self.roster_common:
            raise SourceUnavailable('COMMON canonical relation changed')

    def _contract(self, address, expected_person=None):
        if expected_person is not None and players.u64(self.snapshot(address+8, 8)) != expected_person:
            raise SourceUnavailable('retained contract PERSON owner changed')
        if address in self.valid_contracts:
            return
        table = world.pointer(self.snapshot, _address(address))
        kind = next((kind for kind in ('basic_contract', 'full_contract', 'loan_contract', 'trial_contract')
                     if table == self.base+world.TYPES[kind][0]), None)
        if kind is None:
            raise SourceUnavailable('unproved contract runtime type')
        world.typed(self.snapshot, self.base, address, kind)
        owner = players.u64(self.snapshot(address+8, 8))
        if owner:
            self._person(owner)
        team = players.u64(self.snapshot(address+0x10, 8))
        if team:
            self._team(team)
        self.valid_contracts.add(address)

    def _team(self, address):
        if address in self.valid_teams:
            return
        offers._canonical_team(self.snapshot, self.base, self.team_table, _address(address))
        if self.snapshot(address+0x2f, 1) != b'\0':
            raise SourceUnavailable('compact TEAM is unproved')
        self.valid_teams.add(address)

    def _static_read(self, address, size):
        """Bind static vtable/thunk geometry to the pinned image, before use."""
        offset = address-self.base
        if not ffp.TEXT_END <= offset < 0x56a4000:
            return
        start, end = offset & -8, (offset+size+7) & -8
        expected = self.static_bindings.relocated(start, end-start)
        current = self.snapshot(self.base+start, len(expected))
        if current != expected:
            raise SourceUnavailable('native static table binding changed')

    def _observe(self, vm, access, address, size, value, user):
        self._static_read(address, size)
        if vm is not None:
            for field in range((address+7) & -8, address+size-7, 8):
                if field in self.team_links:
                    team, = struct.unpack('<Q', bytes(vm.mem_read(field, 8)))
                    if team:
                        self._team(team)
                if field in self.person_links:
                    person, = struct.unpack('<Q', bytes(vm.mem_read(field, 8)))
                    if person and struct.unpack('<I', self.snapshot(person+0xc, 4))[0] != 0xffffffff:
                        self._person(person)
        return super()._observe(vm, access, address, size, value, user)

    def _instruction(self, vm, pc, size, user):
        self.instructions += 1
        if self.instructions > MAX_INSTRUCTIONS or time.monotonic() >= self.deadline:
            raise SourceUnavailable('reducer execution bound')
        at = pc-self.base
        if at == 0x1826544:
            args = [vm.reg_read(arm.UC_ARM64_REG_X0+i) for i in range(6)]
            manager = players.u64(self.snapshot(self.base+offers.ROOT, 8))
            begin, end = _vector(self.snapshot, self.club+0x18, limit=256)
            first = players.u64(self.snapshot(begin, 8)) if begin != end else 0
            if args[:2] != [manager+0x18, first] or args[3:] != [1, 0, 2]:
                raise SourceUnavailable('selector input boundary changed')
            if not ffp.SCRATCH <= args[2] <= ffp.SCRATCH+ffp.SCRATCH_SIZE-24:
                raise SourceUnavailable('selector output is not host-owned')
            start = self.selection_vector if self.selected else 0
            finish = start+len(self.selected)*8
            vm.mem_write(args[2], struct.pack('<QQQ', start, finish, finish))
            # Native selector output owns one intrusive reference per non-null
            # slot. Preserve that local ownership, including duplicate slots.
            for address in self.selected:
                if address:
                    counter, = struct.unpack('<I', self.local_read(address+8, 4))
                    if not 1 <= counter < 0x7fffffff:
                        raise SourceUnavailable('invalid selected offer reference count')
                    vm.mem_write(address+8, struct.pack('<I', counter+1))
            vm.reg_write(arm.UC_ARM64_REG_PC, vm.reg_read(arm.UC_ARM64_REG_LR))
            return
        if at == 0x4355ed4:
            # Only the vector which this input boundary allocated may be freed.
            if (vm.reg_read(arm.UC_ARM64_REG_X1), vm.reg_read(arm.UC_ARM64_REG_X2)) != (
                    self.selection_vector, len(self.selected)*8):
                raise SourceUnavailable('unproved native deallocation')
            vm.reg_write(arm.UC_ARM64_REG_PC, vm.reg_read(arm.UC_ARM64_REG_LR))
            return
        entry = next((start for start, (end, _) in self.allowed.items() if start <= at < end), None)
        if entry is None:
            raise SourceUnavailable(f'unproved native callee at {at:#x}')
        if entry not in self.checked:
            end, expected = self.allowed[entry]
            if self.snapshot(self.base+entry, end-entry) != expected:
                raise SourceUnavailable('native reducer code binding changed')
            self.checked.add(entry)
        x0 = vm.reg_read(arm.UC_ARM64_REG_X0)
        if at in (0xcc0014, 0xcbfce8, 0xcb85fc, 0xcb44b4):
            self._common(x0)
        if at in (0xcb8c68, 0xcb43bc, 0xcb45dc, 0xcbf0dc, 0xd5c5fc, 0xd5c610):
            self._person(x0)
        contract_entries = {0x129b5f4, 0xff1bd0, 0xff1ed8, 0xd87790,
                            0xd8c3c0, 0xd8c3d0, 0xd88c6c, 0xd88c8c,
                            0x129a4b8, 0x129fffc, 0x127be34, 0x12920f8,
                            0x13781b8, 0x13781c0, 0x1005c60, 0x1005c70,
                            0x1005c78, 0x1005c90, 0x1006b44}
        if at in contract_entries:
            self._contract(x0)
        if at == 0xcb8c50:
            chosen = vm.reg_read(arm.UC_ARM64_REG_X20)
            common = vm.reg_read(arm.UC_ARM64_REG_X19)
            self._contract(chosen, common+0x110)
        if at == 0xcbfd24:
            self._contract(vm.reg_read(arm.UC_ARM64_REG_X24),
                           vm.reg_read(arm.UC_ARM64_REG_X20)+0x110)
        if at == 0xcbfd68:
            self._contract(vm.reg_read(arm.UC_ARM64_REG_X23),
                           vm.reg_read(arm.UC_ARM64_REG_X20)+0x110)
        if at == 0xcbf13c:
            wrapper = vm.reg_read(arm.UC_ARM64_REG_X11)
            _address(wrapper)
            self.source_writes.append((wrapper, wrapper+4))
        if at == 0xcbf0fc:
            _vector(self.snapshot, vm.reg_read(arm.UC_ARM64_REG_X10), limit=4096)
        if at in (0x1fe8f00, 0x1fe90dc):
            offer = vm.reg_read(arm.UC_ARM64_REG_X21)
            if offer not in self.selected:
                raise SourceUnavailable('trade vector owner changed')
            start, end = _vector(self.snapshot, offer+(0x90 if at == 0x1fe8f00 else 0xf0), 16, 4096)
            self.source_writes.extend((p, p+8) for p in range(start, end, 16))
        # Only retained wrappers are supported. Releasing the last reference
        # would enter destructor/generation/cache management outside this core.

    def _block(self, vm, address, size, user):
        # Every instruction, including imports, is checked by _instruction.
        # Do not inherit FinanceCPU's wider allocator/import implementation.
        if time.monotonic() >= self.deadline:
            raise SourceUnavailable('reducer time bound')


def calculate(read, base, image_stamp, *, club, selected_offers, lifetime, exclude_person=0,
              selected_persons=None):
    """Return the four reducer fields, conditional on the supplied selection.

    ``selected_offers`` must be the exact ordered selector output. This helper
    verifies its objects, not whether the caller ran that selector. ``lifetime``
    reads the caller's process/save/plugin identity before and after the graph;
    equality and byte rechecks do not make the input an atomic snapshot.
    The full EAEB finance-service identity and reducer dispatch are checked;
    EAEB's refresh/admission and final total are not replayed here. X3 exclusion
    follows the native selected-offer branch only, not roster exclusion.
    """
    _address(base)
    _address(club)
    if type(exclude_person) is not int or (exclude_person and not _address(exclude_person)):
        raise SourceUnavailable('invalid excluded PERSON')
    if type(selected_offers) is not tuple or len(selected_offers) > 100000:
        raise SourceUnavailable('require bounded ordered offer tuple')
    for address in selected_offers:
        if address:
            _address(address)
        elif type(address) is not int:
            raise SourceUnavailable('invalid null offer slot')
    if selected_persons is not None and (type(selected_persons) is not tuple
                                        or len(selected_persons) != len(selected_offers)):
        raise SourceUnavailable('selected PERSON overlay shape changed')
    if not callable(lifetime):
        raise SourceUnavailable('caller lifetime reader required')
    before = lifetime()
    if before is None:
        raise SourceUnavailable('caller lifetime is unavailable')
    remaining = [MAX_READ_BYTES, MAX_READ_CALLS]
    deadline = time.monotonic()+20
    def bounded_read(address, size):
        if type(address) is not int or type(size) is not int:
            raise SourceUnavailable('invalid source read arguments')
        remaining[0] -= size
        remaining[1] -= 1
        if (address < 4096
                or not 0 <= size <= 2*1024*1024 or min(remaining) < 0
                or time.monotonic() >= deadline):
            raise SourceUnavailable('reducer source read bound')
        return read(address, size)
    snapshot = world.ReadSet(bounded_read)
    _verified_image(tuple(image_stamp))
    world.typed(snapshot, base, club, 'club')
    clubs = database.table(snapshot, base, 'clubs')
    identity = struct.unpack('<III', snapshot(club+8, 12))
    if not identity[1]:
        raise SourceUnavailable('invalid CLUB native identity')
    database.club_membership(snapshot, base, clubs, identity[0], club)
    finance = _address(players.u64(snapshot(club+0x150, 8)))
    world.typed(snapshot, base, finance, 'club_finance')
    service = _full_finance_service(snapshot, base)
    offers._manager(snapshot, base)
    people = database.table(snapshot, base, 'people')
    team_table = teams.lookup(snapshot, base)
    begin, end = _vector(snapshot, club+0x18, limit=256)
    roster_slots = 0
    for (team,) in struct.iter_unpack('<Q', snapshot(begin, end-begin) if begin != end else b''):
        offers._canonical_team(snapshot, base, team_table, _address(team))
        if players.u64(snapshot(team+0x30, 8)) != club or snapshot(team+0x2f, 1) != b'\0':
            raise SourceUnavailable('roster TEAM owner or compact discriminator changed')
        start, stop = _vector(snapshot, team+0x38, limit=10000)
        roster_slots += (stop-start)//8
        for (primary,) in struct.iter_unpack('<Q', snapshot(start, stop-start) if start != stop else b''):
            vt = world.pointer(snapshot, _address(primary))
            kind = next((fields for fields in assessment_people._PERSON_TYPES.values()
                         if base+fields[1] == vt and fields[0] in ('actual', 'player_staff')), None)
            if kind is None:
                raise SourceUnavailable('unproved roster primary specialization')
            assessment_people._person(snapshot, base, people, primary+kind[2])
    for address in set(selected_offers)-{0}:
        offers._type(snapshot, base, world.pointer(snapshot, address))
    overlays = {}
    if selected_persons is not None:
        for address, supplied in zip(selected_offers, selected_persons):
            if type(supplied) is not int or (supplied and not _address(supplied)):
                raise SourceUnavailable('invalid selected PERSON overlay')
            if not address:
                if supplied:
                    raise SourceUnavailable('non-null PERSON for null offer')
                continue
            raw = players.u64(snapshot(address+0x38, 8))
            resolved = _resolved_person(snapshot, base, people, raw)
            if supplied != resolved or address in overlays and overlays[address] != supplied:
                raise SourceUnavailable('selector PERSON overlay disagrees with native reference')
            if supplied:
                assessment_people._person(snapshot, base, people, supplied)
            overlays[address] = supplied
    with open(image_stamp[0], 'rb') as image:
        st = os.fstat(image.fileno())
        stamp = (st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns)
        if tuple(image_stamp[1:]) != stamp:
            raise SourceUnavailable('pinned image changed')
        cpu = _ReducerCPU(snapshot, bounded_read, base, image, finance, club, selected_offers, people)
        try:
            for address, person in overlays.items():
                cpu.local_read(address+0x38, 8)
                cpu.vm.mem_write(address+0x38, struct.pack('<Q', person))
            if exclude_person:
                cpu._person(exclude_person)
            returned = cpu.run(0x1fe8af8, service, finance, club, exclude_person)
            fields = struct.unpack('<4i', cpu.local_read(finance+0x818, 16))
            result = WageReduction(*fields, struct.unpack('<i', struct.pack('<I', returned & 0xffffffff))[0],
                                   selected_offers, roster_slots)
            # Callbacks can change the source, so recheck after the final one.
            after = lifetime()
            if after != before:
                raise SourceUnavailable('caller process/save/plugin lifetime changed')
            cpu.verify()
            snapshot.verify()
            final_stat = os.fstat(image.fileno())
            if (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns) != stamp:
                raise SourceUnavailable('pinned image changed during reduction')
            return result
        except uc.UcError as exc:
            pc = cpu.vm.reg_read(arm.UC_ARM64_REG_PC)-base
            reason = cpu.source_failure or str(exc)
            raise SourceUnavailable(f'unsupported bounded CPU operation at {pc:#x}: {reason}') from exc
        finally:
            cpu.close()
