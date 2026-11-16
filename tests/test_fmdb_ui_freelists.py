"""Free-list sites (ui_vm.FREE_LIST_SITES): inlined pops and pushes of game free lists served from
the VM heap, on synthetic code and memory. No game is needed. docs/fmdb/UI_FAST.md."""
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_vm import BASE, RET, words  # noqa: E402
from test_fmdb_ui_fast import make_world  # noqa: E402

from fm_live_mcp.fmdb import ui_fastvm, ui_vm  # noqa: E402
from fm_live_mcp.fmdb.ui_vm import FreeListSite, UiHandlerVM  # noqa: E402
from fm_live_mcp.fmdb.vm import HEAP, HEAP_SIZE  # noqa: E402

PAGE = 4096
POOL = 0x20000                    # pool record RVA (live memory beyond the synthetic text)
NODE, NEXT = 0x30_0000_1000, 0x30_0000_2000
# x0 = pool: ldr x21,[x0,#0x98]; cbz x21,+12; ldr x9,[x21]; str x9,[x0,#0x98]; mov x0,x21; orr x0,x0,x9 ; ret
POP = words(0xF9404C15, 0xB4000075, 0xF94002A9, 0xF9004C09, 0xAA1503E0, 0xAA090000, RET)
# x0 = pool, x1 = node: ldr x8,[x0,#0x98]; str x8,[x1]; str x1,[x0,#0x98]; ret
PUSH = words(0xF9404C08, 0xF9000028, 0xF9004C01, RET)
# x0 = pool: the generic pool function stands in as "ldr x0,[x0,#0x98]; ret" (never run when modelled)
GET = words(0xF9404C00, RET)
POP_SITE = FreeListSite('test_pop', 0x2000, 0x2010, 'pop', POOL, 21, ((9, None),), POP[:16].hex())
PUSH_SITE = FreeListSite('test_push', 0x2100, 0x210C, 'push', None, None, ((8, None),), PUSH[:12].hex())
GET_SITE = FreeListSite('test_get', 0x2200, 0, 'pool_get', None, None, (), GET.hex())
BUILDS = [UiHandlerVM, UiHandlerVM.classic]
IDS = ['fast', 'classic']
pytestmark = pytest.mark.skipif(not ui_fastvm.available(), reason='the UI accelerator library is not built')


def world_with(monkeypatch, build, sites=(POP_SITE, PUSH_SITE, GET_SITE), env='1'):
    monkeypatch.setattr(ui_vm, 'FREE_LIST_SITES', tuple(sites))
    monkeypatch.setattr(ui_vm, 'FREE_LIST_HEADS', (POOL + 0x98,))
    monkeypatch.setenv('FMDB_UI_FREE_LISTS', env)
    original = make_world.__globals__['Image']

    class Image(original):
        def __init__(self, code):
            super().__init__({**code, 0x2000: POP, 0x2100: PUSH, 0x2200: GET})
    monkeypatch.setitem(make_world.__globals__, 'Image', Image)
    world = make_world(build)
    pool = BASE + POOL
    world.m.put(pool, bytes(0x140))
    world.m.put(pool + 0x98, struct.pack('<Q', NODE))
    world.m.put(pool + 0x12C, struct.pack('<I', 24))
    world.m.put(NODE, struct.pack('<QQQ', NEXT, 0xAAAA_AAAA_AAAA_AAAA, 0xBBBB_BBBB_BBBB_BBBB))
    world.m.put(NEXT, bytes(32))
    return world


@pytest.mark.parametrize('build', BUILDS, ids=IDS)
def test_pop_reads_the_game_list_without_the_model(monkeypatch, build):
    world = world_with(monkeypatch, build, env='0')
    vm = world.vm
    assert vm.free_list_sites == []
    vm.reset()
    node, _ = vm.call(BASE + 0x2000, (BASE + POOL,))
    assert node == NODE | NEXT                                    # x21 | x9: the live node and its link
    assert vm.read(BASE + POOL + 0x98, 8) == struct.pack('<Q', NEXT)   # the head moved (in the VM)


@pytest.mark.parametrize('build', BUILDS, ids=IDS)
def test_pop_site_gives_a_zeroed_heap_block_and_never_touches_the_list(monkeypatch, build):
    world = world_with(monkeypatch, build)
    vm = world.vm
    assert [s.name for s in vm.free_list_sites] == ['test_pop', 'test_push', 'test_get']
    vm.reset()
    node, _ = vm.call(BASE + 0x2000, (BASE + POOL,))
    assert HEAP <= node < HEAP + HEAP_SIZE                        # x9 = 0: the block's first word
    assert vm.read(node, 24) == bytes(24)
    assert vm.read(BASE + POOL + 0x98, 8) == struct.pack('<Q', NODE)   # head unchanged
    assert vm.read(NODE, 8) == struct.pack('<Q', NEXT)
    second, _ = vm.call(BASE + 0x2000, (BASE + POOL,))
    assert HEAP <= second < HEAP + HEAP_SIZE and vm.read(second, 24) == bytes(24)   # (the call before was not committed)
    assert vm.intercepted['test_pop'] == 2


@pytest.mark.parametrize('build', BUILDS, ids=IDS)
def test_push_site_and_pool_entry(monkeypatch, build):
    world = world_with(monkeypatch, build)
    vm = world.vm
    vm.reset()
    block = vm.heap_bytes(b'\x11' * 32)
    vm.commit()
    vm.call(BASE + 0x2100, (BASE + POOL, block))
    assert vm.read(block, 8) == b'\x11' * 8                      # the node was not linked in
    assert vm.read(BASE + POOL + 0x98, 8) == struct.pack('<Q', NODE)
    got, _ = vm.call(BASE + 0x2200, (BASE + POOL,))
    assert HEAP <= got < HEAP + HEAP_SIZE and vm.read(got, 24) == bytes(24)
    assert vm.intercepted['test_push'] == 1 and vm.intercepted['test_get'] == 1


@pytest.mark.parametrize('build', BUILDS, ids=IDS)
def test_a_site_whose_bytes_differ_is_not_installed(monkeypatch, build):
    wrong = FreeListSite('test_pop', 0x2000, 0x2010, 'pop', POOL, 21, ((9, None),), '00' * 16)
    world = world_with(monkeypatch, build, sites=(wrong,))
    assert world.vm.free_list_sites == []


def test_head_word_is_left_out_of_the_fingerprint(monkeypatch):
    world = world_with(monkeypatch, UiHandlerVM)
    vm = world.vm
    vm.begin_read()
    vm.watch(set())
    vm.trace_begin()
    vm.call(BASE + 0x2000, (BASE + POOL,))
    head = BASE + POOL + 0x98
    vm.live_read(head - 8, 24)                                    # a direct read of the head itself
    pages, masks = vm.read_set()
    vm.trace_end()
    page, index = head & ~(PAGE - 1), (head & (PAGE - 1)) >> 3
    assert page in pages and page in masks                         # its page is always watched
    assert not (masks[page][index >> 6] >> (index & 63)) & 1      # the head word is not fingerprinted
    neighbour = index - 1
    assert (masks[page][neighbour >> 6] >> (neighbour & 63)) & 1  # the word before it is
    before = vm.fingerprint(pages, masks)
    world.m.put(head, struct.pack('<Q', NEXT))                     # the game pops a node
    vm.begin_read()
    vm.prefetch(pages)
    assert vm.fingerprint(pages, masks) == before
