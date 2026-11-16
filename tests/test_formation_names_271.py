"""27.0.1: formation names (prepared_tactic_formations, the optional section `formation_names`).

The patch re-laid out the renderer (0x4967B80 -> 0x4A7AC4C), its number-line builder (0x496AA7C ->
0x4A7D8C0) and the renderer's jump table (0x54060BA -> 0x54A129C). These tests run each build's own
naming route from the preserved plugin files in the reader's VM: the wrapper the game calls with a
formation id (0x496D478 -> 0x4A88D08: template lookup with its static initialiser, the sort, the
renderer). One call is modelled, the same way on both builds: the text lookup by id (0x43DB8B8 ->
0x43F4458) returns the English text of the 27.0.1 example.ltf for the id asked, and the text
object's resolve and destructor do nothing. The names 27.0.1's code returns are the reader's table
for that build (`_ENGLISH_PROJECTIONS_BY_BUILD`); 27.0.0's code returns the same names."""
from __future__ import annotations

import random
import struct

import pytest
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as A

from fm_live_mcp import address_book, prepared_tactic_formations as ptf
from prepared_tactic_formation_fixture import IDENTIFIERS, POSITIONS, add_formation_context
from prepared_tactics_fixture import prepared_tactics_memory  # noqa: F401
from test_database import database_memory  # noqa: F401
from test_match_rating_builds import NEW, OLD, _static_vm, needs_builds
from test_players import memory  # noqa: F401
from test_teams import team_memory  # noqa: F401
from test_world import world_memory  # noqa: F401

SHA_27_0_1 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
ROUTE = {
    'old': dict(path=OLD, wrapper=0x496D478, template=0x495FC78, sort=0x496AE3C, renderer=0x4967B80,
                lookup=0x43DB8B8, resolve=0x43D2E64, text_dtor=0x43D1ACC, localization=0x56A4C20,
                jump_table=0x54060BA, jump_use=0x4968800, jump_base=0x4968824, number_line=0x496AA7C),
    'new': dict(path=NEW, wrapper=0x4A88D08, template=0x4A71DC0, sort=0x4A7E074, renderer=0x4A7AC4C,
                lookup=0x43F4458, resolve=0x43EBA04, text_dtor=0x43EA66C, localization=0x5740C20,
                jump_table=0x54A129C, jump_use=0x4A7B63C, jump_base=0x4A7B660, number_line=0x4A7D8C0),
}
# example.ltf of 27.0.1 (KEY-<id>): the ids the route asks for
TEXTS = {0x57C16: 'Diamond', 0x4D9B9: 'DM', 0x4D9BE: 'AM', 0x57D54: 'Wide', 0x57CD3: 'Narrow', 0x3F552: 'WB',
         0x57BEB: 'Asymmetric', 0x788EA: '[%formation_mentality#1] [%string#1]', 0x3E20D: 'Custom'}
ASYMMETRIC = (50, 53)        # their route enters the text engine for a position token: not run
IP = (-15, -13, -12, -10, -9, -7, -5, 2, 4, 6, 9)
OOP = (-15, -13, -12, -10, -9, -7, -5, -3, 1, 4, 9)
CANONICAL = [1, 0, 4, 0x200010, 0x10, 0x100010, 8, 0x20, 0x200080, 0x80, 0x100080, 0x40, 0x100, 0x200400, 0x400,
             0x100400, 0x200, 0x800, 0x202000, 0x2000, 0x102000, 0x1000, 0x8000, 0x204000, 0x4000, 0x104000,
             0x10000]


def _projection(record):
    return tuple(sorted(((word & 63) ^ 32) - 32 for word in struct.unpack('<11H', record[:22])))


class _Route:
    """One build's naming route in a VM over its plugin file."""

    def __init__(self, build):
        self.fn = ROUTE[build]
        self.v, self.base, self.binary = _static_vm(self.fn['path'])
        v = self.v
        self.asked = []
        inner = v._static(bytes(0x400))
        localization = v._static(struct.pack('<QQ', 0, inner) + bytes(0x30))
        v.set_overlay(self.base + self.fn['localization'], struct.pack('<Q', localization))
        self.out, self.rec = v._static(bytes(16)), v._static(bytes(64))
        for name, model in (('lookup', self._lookup), ('resolve', None), ('text_dtor', None)):
            at = self.base + self.fn[name]
            v.uc.hook_add(UC_HOOK_CODE, self._returning(model), begin=at, end=at)

    @staticmethod
    def _returning(model):
        def run(uc, address, size, user):
            if model is not None:
                model(uc)
            uc.reg_write(A.UC_ARM64_REG_PC, uc.reg_read(A.UC_ARM64_REG_LR))
        return run

    def _lookup(self, uc):
        """(translator, id; x8 = text object): +8 the text, +0x18 = -1 so the caller resolves it."""
        ident = uc.reg_read(A.UC_ARM64_REG_X1) & 0xFFFFFFFF
        self.asked.append(ident)
        raw = TEXTS[ident].encode()
        block = self.v.alloc(len(raw) + 16)
        uc.mem_write(block, struct.pack('<II', 1, len(raw)) + raw + b'\0')
        uc.mem_write(uc.reg_read(A.UC_ARM64_REG_X8), struct.pack('<QQQiI', 0, block + 4, 0, -1, 0))

    def _text(self):
        pointer = struct.unpack('<Q', self.v.read(self.out, 8))[0]
        if not pointer:
            return None
        return bytes(self.v.read(pointer + 4, struct.unpack('<I', self.v.read(pointer, 4))[0])).decode()

    def template(self, ident):
        return bytes(self.v.read(self.v.call(self.base + self.fn['template'], (ident,))[0], 24))

    def name_of_id(self, ident):
        self.asked = []
        self.v.uc.mem_write(self.out, bytes(16))
        self.v.call(self.base + self.fn['wrapper'], (ident, self.out))
        return self._text(), tuple(self.asked)

    def name_of_record(self, record):
        """The build's sort, then its renderer, as the wrapper applies them to a template."""
        self.asked = []
        self.v.uc.mem_write(self.rec, bytes(record) + bytes(64 - len(record)))
        self.v.call(self.base + self.fn['sort'], (self.rec, self.rec + 0x16, self.rec + 0x30, 6, 1))
        self.v.uc.mem_write(self.out, bytes(16))
        self.v.call(self.base + self.fn['renderer'], [self.rec] + [0] * 7 + [self.out])
        return self._text(), tuple(self.asked)


@pytest.fixture(scope='module')
def routes():
    """Both builds' routes. The static initialisers they run create mutexes with a condition
    attribute, which the VM does not model; here those two calls do nothing."""
    from fm_live_mcp.fmdb import vm as vmmod
    added = [n for n in ('_pthread_condattr_init', '_pthread_condattr_destroy') if n not in vmmod.EXTERNALS]
    for name in added:
        vmmod.EXTERNALS[name] = vmmod._noop
    try:
        yield {build: _Route(build) for build in ROUTE}
    finally:
        for name in added:
            del vmmod.EXTERNALS[name]


@pytest.mark.slow
@needs_builds
def test_both_builds_name_every_template_alike_and_the_readers_table_is_what_27_0_1_returns(routes):
    """Ids 0..70 through each build's wrapper: the same template bytes, the same text and the same
    ids asked. 27.0.1's names, keyed by the template's sorted low6 tokens, are exactly the reader's
    table for that build. The two asymmetric templates stop on both builds after asking for the
    same ids (the text engine is not modelled) and are not in the table."""
    table = ptf._ENGLISH_PROJECTIONS_BY_BUILD[SHA_27_0_1]
    produced, named_ids = {}, 0
    for ident in range(0, 71):
        got = {}
        for build, route in routes.items():
            record = route.template(ident) if 1 <= ident <= 69 else None
            try:
                got[build] = (record, *route.name_of_id(ident))
            except Exception as exc:  # noqa: BLE001 - the VM's stop
                got[build] = (record, None, tuple(route.asked), getattr(exc, 'reason', repr(exc)))
        assert got['old'] == got['new'], ident
        record, name, asked = got['new'][:3]
        if ident in (0, 70):
            assert (name, asked) == ('Custom', (0x3E20D,))
            continue
        assert record[22:] == b'\x04\x02'
        if ident in ASYMMETRIC:
            assert name is None and asked[-1] == 0x57BEB and _projection(record) not in table
            continue
        assert name and 0x788EA not in asked
        assert produced.setdefault(_projection(record), name) == name
        named_ids += 1
    assert named_ids == 67 and produced == table and len(table) == 61
    assert table[IP] == '4-2-3-1 DM AM Wide' and table[OOP] == '4-4-1-1 2DM'


@pytest.mark.slow
@needs_builds
def test_the_name_follows_the_low6_tokens_and_byte22_only(routes):
    """What the reader keys a name on. Random high bits (6..15) of each word, a random order and a
    random byte 23 leave the text unchanged on both builds; byte 22 other than 4 makes both ask
    for the mentality wrapper text (0x788EA), which the reader leaves unnamed."""
    rng = random.Random(271)
    table = ptf._ENGLISH_PROJECTIONS_BY_BUILD[SHA_27_0_1]
    for ident in (3, 7, 29, 33, 51, 65):
        words = struct.unpack('<11H', routes['new'].template(ident)[:22])
        expected = table[_projection(struct.pack('<11H', *words))]
        for k in range(3):
            mixed = [(w & 63) | (rng.getrandbits(10) << 6 if k else 0) for w in words]
            rng.shuffle(mixed)
            record = struct.pack('<11H', *mixed) + bytes([4, rng.randrange(256)])
            for route in routes.values():
                name, asked = route.name_of_record(record)
                assert name == expected and 0x788EA not in asked, (ident, record.hex())
    plain = struct.pack('<11H', *struct.unpack('<11H', routes['new'].template(29)[:22]))
    for tail in (0, 3, 5, 255):
        asked = []
        for route in routes.values():
            try:                                  # the wrapper text's formatter is not modelled: the run may stop
                route.name_of_record(plain + bytes([tail, 2]))
            except Exception:  # noqa: BLE001 - the VM's stop, after the lookup this checks
                pass
            asked.append(tuple(route.asked))
        assert asked[0] == asked[1] and 0x788EA in asked[0], tail


def _bl_target(binary, at):
    word = struct.unpack('<I', binary.image.file_bytes(at, 4))[0]
    assert word >> 26 == 0x25, hex(at)
    imm = word & 0x3FFFFFF
    return at + 4 * (imm - (1 << 26) if imm & 0x2000000 else imm)


@needs_builds
def test_reviewed_places_are_where_the_unchanged_wrapper_and_the_renderer_point():
    """The wrapper is the same 480 bytes of code up to address fields; its calls name the sort and the
    renderer of each build. The renderer indexes a 15-entry halfword jump table by token + 15 with
    the same instructions on both builds; every entry lands inside the renderer. The reviewed
    spans (the pinned lengths, re-derived at the reviewed addresses) cover the whole functions."""
    from fm_live_mcp.fmdb import address_map, platform_model
    review = address_map.reviews(SHA_27_0_1)
    guards = review['guards']['prepared_tactic_formations.py']
    binaries = {build: platform_model.load_binary(fn['path']) for build, fn in ROUTE.items()}
    words = {}
    for build, fn in ROUTE.items():
        b = binaries[build]
        assert b.function_of(fn['wrapper']) == (fn['wrapper'], fn['wrapper'] + 480)
        assert _bl_target(b, fn['wrapper'] + 0xD0) == fn['sort']
        assert _bl_target(b, fn['wrapper'] + 0xDC) == fn['renderer']
        start, end = b.function_of(fn['renderer'])
        assert start == fn['renderer']
        entries = struct.unpack('<15H', b.image.file_bytes(fn['jump_table'], 30))
        assert len(set(entries)) == 15 and all(start <= fn['jump_base'] + 4 * e < end for e in entries)
        words[build] = struct.unpack('<5I', b.image.file_bytes(fn['jump_use'] + 8, 20))
        callers = [at for at in range(start, end, 4)
                   if struct.unpack('<I', b.image.file_bytes(at, 4))[0] >> 26 == 0x25
                   and _bl_target(b, at) == fn['number_line']]
        assert len(callers) == 2
    # adr x13, base; ldrh w14, [x15, x12, lsl #1]; add x13, x13, x14, lsl #2; mov w12, #0x80; movk w12, #0x20, lsl #16
    assert words['old'] == words['new'] == (0x100000ED, 0x786C79EE, 0x8B0E09AD, 0x5280100C, 0x72A0040C)
    old, new = ROUTE['old'], ROUTE['new']
    for pinned, place in ((old['renderer'], new['renderer']), (old['number_line'], new['number_line']),
                          (old['jump_table'], new['jump_table'])):
        key = f'{pinned:#x}'
        assert int(review['values'][key]['value'], 16) == int(guards[key]['new'], 16) == place
        assert 'length' not in guards[key]                    # the reader's rewrite keeps the pinned length
    lengths = {rva: size for rva, size, _ in ptf.NAME_NATIVE_DIGESTS}
    b = binaries['new']
    assert new['renderer'] + lengths[old['renderer']] >= b.function_of(new['renderer'])[1]
    assert new['number_line'] + lengths[old['number_line']] >= b.function_of(new['number_line'])[1]
    assert lengths[old['jump_table']] == 30


def test_fixture_templates_are_the_templates_the_table_names():
    """The frozen native initialiser layouts of the offline fixture (captured from the game, independent
    of the emulation) are named by the 27.0.1 table, except the two asymmetric ones."""
    table = ptf._ENGLISH_PROJECTIONS_BY_BUILD[SHA_27_0_1]
    unnamed = set()
    for index, identifier in enumerate(IDENTIFIERS):
        codes = tuple(sorted(struct.unpack_from('<11b', POSITIONS, index * 11)))
        if codes not in table:
            unnamed.add(identifier)
    assert unnamed == set(ASYMMETRIC)
    assert all(len(key) == 11 and key[0] == -15 and all(-15 <= c <= 11 and c != -14 for c in key) for key in table)


@pytest.fixture
def formation_memory(prepared_tactics_memory):  # noqa: F811
    return add_formation_context(prepared_tactics_memory)


def test_reader_takes_names_from_the_loaded_builds_table(formation_memory, monkeypatch):
    """The two shapes of the owner's tactics read as the game's code names them on the pinned
    build, on 27.0.1 and on a mapped build without a table of its own (which uses the pinned
    build's): both builds' code returns the same names (the slow test above)."""
    m = formation_memory
    ip, oop = [CANONICAL[c + 15] for c in IP], [CANONICAL[c + 15] for c in OOP]

    def names():
        context = ptf.load(m['read'], m['base'])
        return [ptf.identify(context, masks) for masks in (ip, oop)]
    assert names() == [{'native_id': 29, 'state': 'recognized', 'name': '4-2-3-1 DM AM Wide'},
                       {'native_id': 33, 'state': 'recognized', 'name': '4-4-1-1 2DM'}]
    assert ptf._ENGLISH_PROJECTIONS is ptf._ENGLISH_PROJECTIONS_BY_BUILD[SHA_27_0_1]
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', SHA_27_0_1)
    assert names() == [{'native_id': 29, 'state': 'recognized', 'name': '4-2-3-1 DM AM Wide'},
                       {'native_id': 33, 'state': 'recognized', 'name': '4-4-1-1 2DM'}]
    m['put'](m['formation_templates'] + list(IDENTIFIERS).index(29) * 24 + 22, b'\x03')
    assert names()[0] == {'native_id': 29, 'state': 'recognized', 'name': None}
    monkeypatch.setitem(address_book.ACTIVE, 'sha256', '0' * 64)
    assert names()[1]['name'] == '4-4-1-1 2DM'
