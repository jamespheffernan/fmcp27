"""Perceived current/potential ability stars, as the game computes them for the selected manager.

The game answers "how many stars does this manager see for player R" through two methods of
GAME_ACTUAL_PLAYER (vtable RVA 0x55DEF88): slot 40, RVA 0x1F8660C (current ability) and slot 41,
RVA 0x1F86BC0 (potential ability). Each takes the player primary in x1 (x0 is not read) and returns
a u16 star range: low byte = lowest bin, high byte = highest bin, 0xFFFF = no stars shown. Bins are
half-star units 11..20 (0.5 to 5 stars). Their branches, from the ARM64 slice:

* viewer context 0x1F82DEC: the current HUMAN and current TEAM, looked up in the UI context
  registry (global vector 0x56D38C0 of {FourCC, sicore typed*}) under 'Hhum' and 'Ttea'
  (0x11B5510); the observer staff comes from 0x12C1578(human)+0xD8;
* a stored scout report for the viewer (0x12D9E40(human, R, 0, 1); national teams 0x12DA3D0):
  current = report+0x3D (u16), potential = report+0x30 -> +0x82;
* else an observer from the player's stored team relation (0x17800DC, 0x1096BD0, slot 0x658):
  the value chain 0x14EA848 (observer-adjusted ability) -> 0x14EB040 (current) and 0x14FDFB4
  (potential) with the viewer's team as the comparison squad (the star baseline is
  0xE0327C(team club, position, 8) capped at 35,000) and the fog gate H (0x23871F0, slots
  0x62/0x63) for the HUMAN found through that team;
* else, when the game service 0x56D2CA0 slot 0x1A0 or 0x20EE608 says the human's club knows
  the player, slot 42 (0x1F86898) / slot 43 (0x1F86ED8): staff assessments of the current team's
  club (0x1F85D2C, 0x20BA2C8), which also needs the current TEAM ('Ttea');
* else 0xFFFF.

This module runs those two methods unmodified in ``fmdb.vm.PropertyVM`` on copied live pages.
The UI context registry is empty while no screen is being built, so the VM is given a private
copy holding exactly two entries, built the way the game stores them: a RECORD typed value with
one 'dref' entry whose int32 is ``table << 24 | database index`` (people table 1 for the HUMAN's
PERSON, teams table 24 for the coach's team). This is the one modelling choice: the viewer is the
selected coach looking at the game with his managed team selected.

Firewall: hidden ability values (CA/PA) are read only by emulated game code inside the VM; only
the star bins leave it. Nothing is written to the game.
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

from . import database, players, prepared_tactics_source
from . import knowledge_bulk as kb
from .bridge import BridgeError

GAME_ACTUAL_PLAYER_VTABLE = 0x55DEF88
CURRENT_SLOT, POTENTIAL_SLOT = 40, 41
CURRENT_RVA, POTENTIAL_RVA = 0x1F8660C, 0x1F86BC0
REPORT_RVA = 0x12D9E40                 # (human, player primary, 0, 1) -> stored scout report or 0
CONTEXT_RVA = 0x1F82DEC                # viewer context builder (human, team, observer, ok)
UI_CONTEXT_REGISTRY = 0x56D38C0        # std::vector<{u32 FourCC, typed*}>
HUMAN_KEY, TEAM_KEY, DREF_KEY = 0x4868756D, 0x54746561, 0x64726566   # 'Hhum', 'Ttea', 'dref'
PEOPLE_TABLE, TEAMS_TABLE = 1, 24      # 0x111344C table ids (verified by resolving the handles)
INT32_TRAITS, RECORD_TRAITS = 0x28, 0xB8   # offsets in the sicore typed-traits registry
UNKNOWN = 0xFFFF
BUDGET = 5_000_000


@dataclass(frozen=True)
class Viewer:
    human: int          # HUMAN primary
    person_index: int   # [HUMAN+0x548+8]
    team: int           # managed TEAM
    team_index: int     # [TEAM+8]


def handle(table, index):
    """The packed database handle 0x111344C resolves: signed table byte, 23-bit record index."""
    if not 0 <= table < 0x7F or not 0 <= index < 0x7FFFFF:
        raise ValueError('Database handle out of range')
    return table << 24 | index


def dref_record(at, registry, table, index):
    """Bytes of a sicore RECORD typed value {'dref': int32 handle} laid out at address ``at``.

    Layout (0x48 bytes): int32 typed {traits, handle} at +0x00; one 16-byte record entry
    {'dref', typed*} at +0x10; the entry vector {begin, end, cap} at +0x20; the RECORD typed
    {traits, vector*} at +0x38 (the value the registry points at)."""
    return (struct.pack('<QQ', registry + INT32_TRAITS, handle(table, index))
            + struct.pack('<IIQ', DREF_KEY, 0, at)
            + struct.pack('<QQQ', at + 0x10, at + 0x20, at + 0x20)
            + struct.pack('<QQ', registry + RECORD_TRAITS, at + 0x20))


def context_blob(at, registry, viewer):
    """(bytes, begin, end): two dref records and the two registry entries, placed at ``at``."""
    human = dref_record(at, registry, PEOPLE_TABLE, viewer.person_index)
    team = dref_record(at + 0x48, registry, TEAMS_TABLE, viewer.team_index)
    entries = (struct.pack('<IIQ', HUMAN_KEY, 0, at + 0x38)
               + struct.pack('<IIQ', TEAM_KEY, 0, at + 0x48 + 0x38))
    return human + team + entries, at + 0x90, at + 0x90 + len(entries)


def decode_stars(value):
    """u16 star range from slot 40/41 -> the public shape (half-star units and stars)."""
    value &= 0xFFFF
    if value == UNKNOWN:
        return dict(state='unknown', min_half_stars=None, max_half_stars=None,
                    min_stars=None, max_stars=None)
    low, high = value & 0xFF, value >> 8
    if not (11 <= low <= high <= 20):
        return dict(state='unavailable', reason='unexpected_star_bins', raw=value)
    return dict(state='exact' if low == high else 'range', min_half_stars=low - 10, max_half_stars=high - 10,
                min_stars=(low - 10) / 2, max_stars=(high - 10) / 2)


class StarEngine:
    """One PropertyVM over live pages with the viewer context installed."""

    def __init__(self, reader, base, image, viewer, *, budget=BUDGET):
        from .fmdb.fastvm import vm_class
        from .fmdb.vm import STACK
        self.vm = vm_class()(reader, base, image, budget=budget, timeout_us=20_000_000)
        self.base, self.viewer = base, viewer
        vm = self.vm
        for slot, rva in ((CURRENT_SLOT, CURRENT_RVA), (POTENTIAL_SLOT, POTENTIAL_RVA)):
            if vm.read_u64(base + GAME_ACTUAL_PLAYER_VTABLE + 8 * slot) != base + rva:
                raise ValueError('GAME_ACTUAL_PLAYER star slot moved')
        if vm.read_u64(viewer.human + 0x548 + 8) & 0xFFFFFFFF != viewer.person_index:
            raise ValueError('HUMAN PERSON index changed')
        self._at = vm._static(b'\0' * 0xB0)
        blob, begin, end = context_blob(self._at, vm.registry, viewer)
        self._blob = blob
        vm.uc.mem_write(self._at, blob)
        vm.set_overlay(base + UI_CONTEXT_REGISTRY, struct.pack('<QQ', begin, end))
        self._ctx = STACK + 0x200
        context = self.context()
        if context[:2] != (viewer.human, viewer.team) or not context[3]:
            raise ValueError('Emulated viewer context did not resolve to the selected coach and team')

    def _call(self, rva, args):
        # The context records are VM-private; rewrite them so no call sees another call's stores.
        self.vm.uc.mem_write(self._at, self._blob)
        return self.vm.call(self.base + rva, args)

    def context(self):
        self.vm.uc.mem_write(self._ctx, b'\0' * 0x20)
        self._call(CONTEXT_RVA, [self._ctx])
        raw = bytes(self.vm.uc.mem_read(self._ctx, 0x20))
        human, team, observer = struct.unpack_from('<QQQ', raw)
        return human, team, observer, raw[0x18] == 1

    def stars(self, primary):
        """{'current', 'potential', 'report_present', 'instructions'} for one player primary."""
        from .fmdb.vm import _Stop
        out, instructions = {}, 0
        for name, rva in (('current', CURRENT_RVA), ('potential', POTENTIAL_RVA)):
            try:
                value, stats = self._call(rva, [0, primary])
                instructions += stats.instructions
                out[name] = decode_stars(value)
            except _Stop as stop:
                out[name] = dict(state='unavailable', reason='emulation_refused', detail=stop.reason)
        try:
            report, _ = self._call(REPORT_RVA, [self.viewer.human, primary, 0, 1])
            out['report_present'] = bool(report)
        except _Stop as stop:
            out['report_present'] = None
        out['instructions'] = instructions
        return out


def _reader(bridge):
    try:
        from .fmdb.memory import LiveMemory
        return LiveMemory(bridge.process.pid)
    except Exception:  # noqa: BLE001 - fall back to the bridge's own helper stream
        from .fmdb.live import StreamReader
        return StreamReader(bridge.helper, bridge.process.pid)


def _setup(bridge, session_id, keys, coach_name):
    with bridge.lock, bridge._read_scope(session_id):
        process = bridge._current(session_id)
        tables = bridge._player_layout(process)
        base = tables[0] - players.RVA[0]
        read, save, _ = bridge._world_state(process, tables)
        coach = bridge._select_coach(save, coach_name)
        prepared_tactics_source._team_and_human(read, base, coach)   # validates the coach binding
        team, human = coach['team_address'], coach['manager_address']
        people = database.table(read, base, 'people')
        cache = []

        def ordinals():
            if not cache:
                cache.append(kb.all_actual_primaries(read, base))
            return cache[0]
        rows = []
        for key in keys:
            row = dict(key=key, primary=None)
            try:
                if type(key) is str:
                    binding = bridge.player_refs.get(key)
                    if type(binding) is not dict:
                        raise BridgeError('Unknown or expired player reference')
                    row['primary'] = binding['address']
                else:
                    row['primary'], _ = kb._primary_for_key(read, base, people, key, ordinals)
                if row['primary']:
                    table = players.u64(read(row['primary'], 8))
                    if table not in (base + players.RVA[0], base + players.STAFF_RVA[0]):
                        row.update(primary=None, reason='not_a_player_record')
                else:
                    row['reason'] = 'not_a_player_record'
            except IndexError:
                row['reason'] = 'key_outside_native_vector'
            rows.append(row)
        person_index = struct.unpack('<I', read(human + 0x548 + 8, 4))[0]
        team_index = struct.unpack('<I', read(team + 8, 4))[0]
        read.verify()
    viewer = Viewer(human, person_index, team, team_index)
    return base, save, coach, viewer, rows


def perceived_ability(bridge_or_session, player_keys, *, coach_name=None):
    """Current and potential ability stars the selected manager sees, per player.

    Keys as in ``knowledge_bulk`` (PERSON index, ('ordinal', n), ('address', primary), player_ref).
    Per player: ``current`` and ``potential`` = {state: exact|range|unknown|unavailable,
    min_half_stars, max_half_stars (1..10), min_stars, max_stars (0.5..5.0)}, ``report_present``.
    ``unknown`` is the game's 0xFFFF: no stars shown for this manager."""
    from .fmdb.image import PluginImage
    bridge, session_id = kb._bridge_and_session(bridge_or_session)
    keys = kb._validate_keys(player_keys)
    try:
        base, save, coach, viewer, rows = _setup(bridge, session_id, keys, coach_name)
        reader = _reader(bridge)
        try:
            image = PluginImage.load(bridge.plugin_identity[0][0])
            engine = StarEngine(reader, base, image, viewer)
            players_out = []
            for row in rows:
                if row['primary'] is None:
                    players_out.append(dict(key=row['key'], state='unavailable', reason=row['reason']))
                    continue
                players_out.append(dict(key=row['key'], **engine.stars(row['primary'])))
        finally:
            close = getattr(reader, 'close', None)
            if close:
                close()
    except (ValueError, KeyError, TypeError, OSError) as exc:
        raise BridgeError(f'Perceived ability query rejected: {exc}') from exc
    return dict(session_id=session_id, save=dict(name=save.get('name'), current_date=save.get('current_date')),
                coach=coach.get('name'), club=coach.get('club'), game_writes=False,
                hidden_values_returned=False, method='emulated GAME_ACTUAL_PLAYER slots 40/41',
                players=players_out)


def perceived_ability_squad(bridge_or_session, *, coach_name=None):
    """``perceived_ability`` for the selected manager's own squad (player_refs from the squad tool)."""
    bridge, session_id = kb._bridge_and_session(bridge_or_session)
    squad = bridge.get_managed_squad(session_id, coach_name)['players']
    result = perceived_ability((bridge, session_id), [p['player_ref'] for p in squad], coach_name=coach_name)
    for row, player in zip(result['players'], squad):
        row['name'] = player.get('name')
    return result
