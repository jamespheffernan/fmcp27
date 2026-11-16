"""Native answers for the contextual-K branches the typed Python sources leave unproved.

Contextual K (original ``0x2386548``) consumes two operands whose typed Python sources refuse on
some players:

* ``relation_mask`` = ``0x20EE608(HUMAN primary, subject primary)`` (K's call at ``0x238679C``).
  The Python reproduction refuses with "Unproved owned CLUB node family" (an unlisted CLUB INFO
  node class in ``_recent_nodes``) and "Reached unproved 17bb4c0 selection; absence is not
  native null" (a relation row or recent node that makes the native code run the staff
  selection ``0x17BB4C0``).
* ``transfer_predicate`` = ``0xCBB9F8(subject COMMON, owner CLUB, 0, 0, 0, 0)`` (K's call at
  ``0x2386DB8``). The Python reproduction refuses with "Unproved transfer predicate contract
  type" (a contract class outside full/basic/loan/trial).

When, and only when, the Python source raises one of those exact refusals, ``NativeOperands``
runs the original function in ``fmdb.vm.PropertyVM`` and returns its result as the operand. Every
other path keeps the Python answer, so rows that were available before are unchanged.

Memory and firewall: the VM faults whole 4 KiB pages from the live process with the attribute
blocks of every primary record (the journal's forbidden intervals) blanked; a read hook stops
the emulation, as a refusal, if the code loads a blanked byte. A second read hook records every
byte range the emulated code loads; after the call each range is read again through the bulk
journal, must equal the bytes the VM used, and is then covered by the journal's final fence like
every other consumed byte. Stores stay in the VM. A refusal keeps the row ``unavailable`` with
the emulator's reason.
"""
from __future__ import annotations

from bisect import bisect_left
import struct

from unicorn import UC_HOOK_MEM_READ

RELATION_MASK_RVA = 0x20EE608
TRANSFER_PREDICATE_RVA = 0xCBB9F8
BUDGET = 20_000_000
REFUSALS = {
    'relation_mask': ('Unproved owned CLUB node family',
                      'Reached unproved 17bb4c0 selection; absence is not native null',
                      'Unproved transfer predicate contract type'),
    'transfer_predicate': ('Unproved transfer predicate contract type',),
}


class NativeRefused(ValueError):
    """The emulator refused the original function; the operand stays unavailable."""


def refusal_matches(name, exc):
    """True when ``exc`` is one of the exact typed-source refusals this module may answer."""
    text = str(exc)
    return any(text == reason or text.startswith(reason) for reason in REFUSALS.get(name, ()))


def blank_forbidden(page, data, ranges, starts):
    """(data with forbidden bytes zeroed, [(start, end)] blanked spans) for one page."""
    end = page + len(data)
    index = max(bisect_left(starts, page) - 1, 0)
    out, spans = bytearray(data), []
    while index < len(ranges) and ranges[index][0] < end:
        low, high = max(ranges[index][0], page), min(ranges[index][1], end)
        if low < high:
            out[low - page:high - page] = bytes(high - low)
            spans.append((low, high))
        index += 1
    return bytes(out), spans


def merge_loads(loads):
    """Merge (address, size) loads into sorted disjoint (start, end) spans."""
    spans = []
    for address, size in sorted(loads):
        if spans and address <= spans[-1][1]:
            spans[-1][1] = max(spans[-1][1], address + size)
        else:
            spans.append([address, address + size])
    return [tuple(s) for s in spans]


class _PageReader:
    """Raw page reader for the VM: forbidden attribute bytes blanked, original pages kept."""

    def __init__(self, physical, forbidden):
        self.physical, self.forbidden = physical, forbidden
        self.pages, self.blanked = {}, []

    def read(self, address, length):
        out = bytearray()
        for page in range(address & ~4095, address + length, 4096):
            if page not in self.pages:
                raw = self.physical(page, 4096)
                if type(raw) is not bytes or len(raw) != 4096:
                    raise ValueError('Incomplete page read')
                data, spans = blank_forbidden(page, raw, self.forbidden.ranges, self.forbidden.starts)
                self.pages[page] = data
                self.blanked.extend(spans)
            out += self.pages[page]
        offset = address & 4095
        return bytes(out[offset:offset + length])


class NativeOperands:
    """One PropertyVM for a bulk call; runs the two original functions on refused branches."""

    def __init__(self, journal, base, image):
        self.journal, self.base, self.image = journal, base, image
        self.reader = None
        self._live = None
        self._vm = None
        self._loads = None
        self.calls = {'relation_mask': 0, 'transfer_predicate': 0}
        self.refusals = {}

    @property
    def vm(self):
        """Created on first use, inside the caller's open native read stream."""
        if self._vm is None:
            from .fmdb.vm import PropertyVM, NULL_LIMIT, PRIVATE
            from .fmdb.memory import LiveMemory
            # Page faults use their own fast reader: a refused read (unmapped page) must not
            # close the bulk call's native stream. Only spans the code loaded reach the journal.
            self._live = LiveMemory(self.journal.bridge.process.pid)
            self.reader = _PageReader(self._live.read, self.journal.forbidden)
            if callable(self.image):          # loaded on the first native call (most calls make none)
                self.image = self.image()
            self._vm = PropertyVM(self.reader, self.base, self.image, budget=BUDGET, timeout_us=30_000_000)
            self._vm.uc.hook_add(UC_HOOK_MEM_READ, self._on_load, begin=NULL_LIMIT, end=PRIVATE - 1)
        return self._vm

    def _on_load(self, uc, access, address, size, value, user):
        if self._loads is not None:
            self._loads.add((address, size))
        if self.reader.forbidden.intersects(address, size):
            self.vm._fail(uc, 'emulated code read a forbidden attribute byte', hex(address))

    def _run(self, name, rva, args):
        from .fmdb.vm import _Stop
        vm = self.vm
        self.reader.pages.clear()
        vm.invalidate()           # fresh pages for every call: what is journalled is what ran
        self._loads = set()
        try:
            value, _ = self.vm.call(self.base + rva, args)
        except _Stop as stop:
            self.refusals[stop.reason] = self.refusals.get(stop.reason, 0) + 1
            raise NativeRefused(f'Native {name} {rva:#x} refused by the emulator: {stop.reason}') from None
        finally:
            loads, self._loads = self._loads, None
        self._journal(loads)
        self.calls[name] += 1
        return value

    def _journal(self, loads):
        """Re-read every loaded span through the journal; it must match the VM's original pages."""
        code_end = self.base + self.vm.image.segment('__TEXT').vmsize
        for start, end in merge_loads(loads):
            if self.base <= start < code_end:
                continue      # shipped code bytes come from the pinned on-disk slice
            address = start
            while address < end:
                size = min(end - address, 4096 - (address & 4095))
                page = address & ~4095
                expected = self.reader.pages[page][address - page:address - page + size]
                if self.journal.read(address, size) != expected:
                    raise ValueError('Native operand bytes changed between VM page and journal')
                address += size

    def close(self):
        if self._live is not None:
            self._live.close()
            self._live = None

    def relation_mask(self, human_primary, subject_primary):
        return self._run('relation_mask', RELATION_MASK_RVA, [human_primary, subject_primary]) & 0xFFFF

    def transfer_predicate(self, subject_primary, owner_club):
        # K passes the subject's COMMON: subject + [vtable - 0x20] (0x2386D98..0x2386DA0).
        vtable = self.vm.read_u64(subject_primary)
        common = subject_primary + struct.unpack('<q', self.vm.read(vtable - 0x20, 8))[0]
        value = self._run('transfer_predicate', TRANSFER_PREDICATE_RVA, [common, owner_club, 0, 0, 0, 0])
        return bool(value & 0xFFFFFFFF)


def source_type(base_type, native, *, verify=None):
    """Subclass of the bulk approved source whose two refused operands come from the game.

    ``verify``: optional dict; when given, the native function also runs where the Python
    source answered, and agreements/disagreements are counted per operand."""

    class NativeSource(base_type):
        def _operand(self, name, *args):
            if name not in REFUSALS:
                return super()._operand(name, *args)
            try:
                result = super()._operand(name, *args)
            except ValueError as exc:
                if not refusal_matches(name, exc):
                    raise
                return self._native(name, args)
            if verify is not None:
                try:
                    native_value = self._native(name, args)
                except NativeRefused:
                    verify[name + '_refused'] = verify.get(name + '_refused', 0) + 1
                else:
                    same = (native_value == result) if name == 'relation_mask' else (native_value == bool(result))
                    key = name + ('_equal' if same else '_different')
                    verify[key] = verify.get(key, 0) + 1
            return result

        def _native(self, name, args):
            if name == 'relation_mask':
                return native.relation_mask(self.owner.primary, self.subject.primary)
            person, club = args
            return native.transfer_predicate(person.primary, club.address)

    return NativeSource


# --------------------------------------------------------------------------- Player Search admission

CLUB_ADMISSION_RVA = 0xE58E5C        # club leaf (club, subject primary, 0) -> bool
SEARCH_REFRESH_RVA = 0x208B238       # the refresh whose per-person decision is reproduced below


class SearchAdmission:
    """The per-person decision of the Player Search refresh ``0x208B238`` (non-show-all branch).

    The refresh decides inline (``0x208BBA4..0x208BFB4``); the glue below follows that code and
    every function it calls runs natively in the VM:

    1. the subject's current team: COMMON = primary + [vtable-0x20]; contract = [COMMON+0x78];
       a contract whose slot 0x90 returns 0 gives [contract+0x18]; otherwise COMMON's slot 0x230
       (through [vtable-0x18]) when it is nonzero and either the contract is null and the
       holder [COMMON+0x80] is null or all-null, else slot 0x3F8;
    2. same club: the team's [+0x30] (0 for a national team, [+0x2F] != 0) equals the viewer
       club -> admitted (``0x208BF0C`` branches to the append at ``0x208BB94``);
    3. club leaf ``0xE58E5C(viewer club, subject primary, 0)`` -> admitted;
    4. FOW leaf (service [0x56D2D08] slot 0x348) only with a non-null search context; the
       manager's search context is null on the live save, so this step is reported, not run.
    """

    def __init__(self, vm, base, viewer_club):
        self.vm, self.base, self.club = vm, base, viewer_club

    def _virtual(self, obj, slot):
        target = self.vm.read_u64(self.vm.read_u64(obj) + slot)
        value, _ = self.vm.call(target, [obj])
        return value

    def _adjust(self, obj, negative):
        vtable = self.vm.read_u64(obj)
        return obj + struct.unpack('<q', self.vm.read(vtable - negative, 8))[0]

    def current_team(self, primary):
        common = self._adjust(primary, 0x20)
        contract = self.vm.read_u64(common + 0x78)
        if contract and self._virtual(contract, 0x90) & 0xFFFFFFFF == 0:
            return self.vm.read_u64(contract + 0x18)
        person = self._adjust(common, 0x18)
        team = self._virtual(person, 0x230)
        if team and not self.vm.read_u64(common + 0x78):
            holder = self.vm.read_u64(common + 0x80)
            if not holder or not any(self.vm.read_u64(holder + off) for off in (0, 8, 0x10, 0x18)):
                return team
        return self._virtual(person, 0x3F8)

    def decide(self, primary):
        from .fmdb.vm import _Stop
        try:
            team = self.current_team(primary)
            club = 0 if not team or self.vm.read(team + 0x2F, 1)[0] else self.vm.read_u64(team + 0x30)
            same = bool(club) and club == self.club
            leaf = None
            if not same:
                value, _ = self.vm.call(self.base + CLUB_ADMISSION_RVA, [self.club, primary, 0])
                leaf = bool(value & 0xFF)
        except _Stop as stop:
            return dict(state='unavailable', reason='emulation_refused', detail=stop.reason)
        return dict(state='available', admitted=same or bool(leaf), same_club=same, club_leaf=leaf,
                    fow_leaf='not_reached_null_search_context' if not (same or leaf) else 'not_needed')


def search_admission(bridge_or_session, player_keys, *, coach_name=None):
    """Whether each player passes the selected manager's Player Search admission (not show-all)."""
    from . import knowledge_stars as stars
    from .fmdb.image import PluginImage
    from .fmdb.fastvm import vm_class
    from .bridge import BridgeError
    bridge, session_id = stars.kb._bridge_and_session(bridge_or_session)
    keys = stars.kb._validate_keys(player_keys)
    try:
        base, save, coach, viewer, rows = stars._setup(bridge, session_id, keys, coach_name)
        reader = stars._reader(bridge)
        try:
            vm = vm_class()(reader, base, PluginImage.load(bridge.plugin_identity[0][0]), budget=BUDGET)
            club = vm.read_u64(viewer.team + 0x30)
            decider = SearchAdmission(vm, base, club)
            out = []
            for row in rows:
                if row['primary'] is None:
                    out.append(dict(key=row['key'], state='unavailable', reason=row['reason']))
                else:
                    out.append(dict(key=row['key'], **decider.decide(row['primary'])))
        finally:
            close = getattr(reader, 'close', None)
            if close:
                close()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise BridgeError(f'Search admission query rejected: {exc}') from exc
    return dict(session_id=session_id, save=dict(name=save.get('name'), current_date=save.get('current_date')),
                coach=coach.get('name'), club=coach.get('club'), game_writes=False,
                branch='non_show_all_null_search_context', players=out)
