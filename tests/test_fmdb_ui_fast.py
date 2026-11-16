"""FastUiHandlerVM, read-set fingerprints and the list/narrative split, on synthetic memory.

No game is needed: the "process" is test_fmdb_vm.Memory, which the tests mutate to play the
part of the running game. Skipped when build/libfm_ui_accel.dylib is not built
(scripts/build_ui_accel.sh).
"""
import struct
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_fmdb_vm import BASE, GETTER, RET, TRAITS, WRITING_GETTER, Image, Memory, REGISTRY, words  # noqa: E402

from fm_live_mcp.fmdb import ui_cache, ui_fastvm, ui_tools  # noqa: E402
from fm_live_mcp.fmdb.ui_vm import UiHandlerVM  # noqa: E402
from fm_live_mcp.fmdb.vm import HEAP, VARIANT_REGISTRY_RVA  # noqa: E402

pytestmark = pytest.mark.skipif(not ui_fastvm.available(), reason='build/libfm_ui_accel.dylib is not built')
PAGE = 4096
RECORD = 0x30_0000_0000


class Game(Memory):
    """Fake process memory with the batched read of LiveMemory."""
    pid = 4242

    def read_many_status(self, requests):
        out = []
        for address, length in requests:
            try:
                out.append((0, self.read(address, length)))
            except OSError:
                out.append((6, None))
        return out


def make_world(build=UiHandlerVM):
    m = Game()
    m.put(BASE + VARIANT_REGISTRY_RVA, struct.pack('<Q', REGISTRY))
    m.put(REGISTRY, bytes(0xE0))
    for i, (offset, name) in enumerate(TRAITS.items()):
        vtable = 0x20_0001_0000 + i * 0x100
        info, text = vtable + 0x80, vtable + 0xA0
        m.put(vtable - 8, struct.pack('<QQQQQ', info, 0, 0, 0, 0))
        m.put(info + 8, struct.pack('<Q', text))
        m.put(text, name.encode() + b'\0')
        m.put(REGISTRY + offset, struct.pack('<QB', vtable, i))
    code = {0x1000: GETTER, 0x1600: WRITING_GETTER,
            # str x1,[x0,#0x40] ; ret  (a store into live memory, kept by commit)
            0x1700: words(0xF9002001, RET),
            # ldr x0,[x0,#0x40] ; ret
            0x1800: words(0xF9402000, RET)}
    vm = build(m, BASE, Image(code), view='game', thread='reader', budget=100_000, file_resolver=False)
    return SimpleNamespace(m=m, vm=vm)


def put_record(world, address, payload, getter=0x1000):
    vtable = address + 0x800
    world.m.put(vtable, struct.pack('<QQQQ', 0, 0, 0, BASE + getter))
    world.m.put(address, struct.pack('<QQQ', vtable, REGISTRY + 0x28, payload) + bytes(0x100))
    return address


@pytest.fixture
def world():
    return make_world()


def test_constructor_gives_the_accelerated_class_and_classic_stays_available():
    assert type(make_world().vm) is ui_fastvm.FastUiHandlerVM
    classic = make_world(UiHandlerVM.classic).vm
    assert type(classic) is UiHandlerVM and isinstance(make_world().vm, UiHandlerVM)


@pytest.mark.parametrize('build', [UiHandlerVM, UiHandlerVM.classic], ids=['fast', 'classic'])
def test_baseline_commit_restore_and_pin_agree_with_the_reference(build):
    world = make_world(build)
    vm = world.vm
    record = put_record(world, RECORD, 7)
    store, load = BASE + 0x1700, BASE + 0x1800
    vm.reset()
    block = vm.heap_bytes(b'abcdefgh')
    vm.commit()
    vm.call(store, (record, 111))                 # a store without commit is dropped by the next call
    assert vm.call(load, (record,))[0] == 0
    vm.call(store, (record, 222))
    vm.commit()                                   # now part of the baseline
    first = vm._baseline
    assert vm.call(load, (record,))[0] == 222 and vm.read(block, 8) == b'abcdefgh'
    vm.call(store, (record, 333))
    vm.commit()
    second_block = vm.heap_bytes(b'12345678')
    vm.commit()
    assert vm.call(load, (record,))[0] == 333 and vm.read(second_block, 8) == b'12345678'
    vm._baseline = first                          # pin an earlier baseline
    vm._restore()
    assert vm.call(load, (record,))[0] == 222 and vm.heap_top == first.heap_top
    assert vm.read(second_block, 8) == bytes(8)   # the later heap block is gone
    vm.reset()
    assert vm.call(load, (record,))[0] == 0 and vm.heap_top == HEAP
    assert world.m.read(record + 0x40, 8) == bytes(8)          # nothing was written to the "game"


def test_many_written_pages_and_snapshots_share_unchanged_pages(world):
    vm = world.vm
    records = [put_record(world, RECORD + i * 0x10000, i) for i in range(48)]
    vm.reset()
    for i, r in enumerate(records):               # more written pages than stay writable (16)
        vm.call(BASE + 0x1700, (r, 1000 + i))
        vm.commit()
    stats = vm.vm_stats()
    assert stats['nbase'] >= 48 and stats['pages_committed'] <= 2 * 48     # one new page copy per commit
    for i, r in enumerate(records):
        assert vm.call(BASE + 0x1800, (r,))[0] == 1000 + i
    vm.reset()
    assert all(vm.call(BASE + 0x1800, (r,))[0] == 0 for r in records)
    assert vm.vm_stats()['blobs_live'] <= 2 * 48          # snapshots released their pages


def test_generation_rereads_stale_pages_before_use(world):
    vm = world.vm
    record = put_record(world, RECORD, 100)
    assert vm.get_property(record, 'Xxxx').value == 100
    world.m.put(record + 0x10, struct.pack('<Q', 555))            # the game moves on
    assert vm.get_property(record, 'Xxxx').value == 100           # same read: the copied page
    assert vm.reader.read(record + 0x10, 8) == struct.pack('<Q', 100)
    vm.begin_read()
    assert vm.reader.read(record + 0x10, 8) == struct.pack('<Q', 555)   # recipes read the same pages
    assert vm.get_property(record, 'Xxxx').value == 555
    world.m.put(record + 0x10, struct.pack('<Q', 556))
    vm.generation_seconds = 0.0                                   # reset() ends an old generation
    vm.reset()
    assert vm.get_property(record, 'Xxxx').value == 556


def test_stale_page_is_not_served_to_models_or_restores(world):
    vm = world.vm
    record = put_record(world, RECORD, 1)
    vm.reset()
    vm.call(BASE + 0x1700, (record, 9))            # dirty the page, then drop the store
    vm.reset()
    world.m.put(record + 0x40, struct.pack('<Q', 77))
    vm.begin_read()
    assert vm.call(BASE + 0x1800, (record,))[0] == 77             # fresh bytes, not the saved copy
    vm.call(BASE + 0x1700, (record, 5))
    vm.reset()
    assert vm.call(BASE + 0x1800, (record,))[0] == 77             # restore goes back to the fresh copy


def read_set_of(world, record, watch=()):
    vm = world.vm
    vm.begin_read()
    vm.watch(watch)
    vm.trace_begin()
    value = vm.get_property(record, 'Xxxx').value
    pages, masks = vm.read_set()
    vm.trace_end()
    return value, ui_cache.ReadSet([1, 'start'], pages, vm.fingerprint(pages, masks), masks, [])


def check(world, read_set, process=(1, 'start')):
    return ui_cache.check_read_set(read_set, world.m.read_many_status, ui_fastvm.hash_masked, list(process))


def test_read_set_lists_touched_pages_and_detects_any_change_on_them(world):
    record = put_record(world, RECORD, 41)
    other = put_record(world, RECORD + 0x40000, 1)
    value, rs = read_set_of(world, record)
    assert value == 41 and RECORD in rs.pages and RECORD + 0x40000 not in rs.pages and not rs.masks
    assert check(world, rs)['ok']
    world.m.put(other + 0x10, struct.pack('<Q', 2))               # a page it did not read
    assert check(world, rs)['ok']
    world.m.put(record + 0x200, b'x')                             # an unread byte of a page it read
    result = check(world, rs)
    assert not result['ok'] and result['changed'] == [RECORD] and result['data'][RECORD][0x200:0x201] == b'x'
    assert not check(world, rs, process=(2, 'start'))['ok']


def test_watched_page_is_fingerprinted_by_the_words_read(world):
    record = put_record(world, RECORD, 41)
    value, rs = read_set_of(world, record, watch=[RECORD])
    assert value == 41 and RECORD in rs.masks
    mask = rs.masks[RECORD]
    read_words = {w for w in range(512) if (mask[w >> 6] >> (w & 63)) & 1}
    assert {0, 1, 2} <= read_words and 0x200 // 8 not in read_words     # vtable, traits, payload
    world.m.put(record + 0x200, b'counter!')                      # the game changes bytes it never read
    assert check(world, rs)['ok']
    world.m.put(record + 0x10, struct.pack('<Q', 42))             # ... and then a word it did read
    result = check(world, rs)
    assert not result['ok'] and result['changed'] == [RECORD]


def test_watched_page_gives_the_same_values_and_keeps_copy_on_write(world):
    vm = world.vm
    record = put_record(world, RECORD, 3, getter=0x1600)          # this getter also stores into the record
    plain = vm.get_property(record, 'Xxxx').value
    vm.watch([RECORD])
    assert vm.get_property(record, 'Xxxx').value == plain == 3
    assert vm.read(record + 0x20, 4) == struct.pack('<I', 3)      # the store, visible until the next call
    vm.reset()
    assert vm.read(record + 0x20, 4) == bytes(4)
    vm.watch(())
    assert vm.get_property(record, 'Xxxx').value == 3


def test_read_set_roundtrip_and_cache_files(tmp_path):
    rs = ui_cache.ReadSet([7, 'x'], [0x1000, 0x2000, 0x9000], [1, 2, 3], {0x2000: (5,) + (0,) * 7},
                          [['/tmp/none', -1, -1]])
    again = ui_cache.ReadSet.from_bytes(rs.to_bytes())
    assert (again.process, again.pages, again.hashes, again.files) == (rs.process, rs.pages, rs.hashes, rs.files)
    assert again.masks == {0x2000: (5,) + (0,) * 7}
    assert ui_cache.page_runs([0x1000, 0x2000, 0x9000]) == [(0x1000, 0x2000), (0x9000, 0x1000)]
    store = ui_cache.ScreenCache('career-x', build='b1', root=tmp_path)
    store.put('recipe:x', {'a': 1}, {'value': 5}, {'mode': 'read_set'}, rs)
    assert store.get('recipe:x', {'a': 1})['value'] == 5 and store.read_set('recipe:x', {'a': 1}).pages == rs.pages
    assert store.get('recipe:x', {'a': 2}) is None
    assert ui_cache.ScreenCache('career-x', build='b2', root=tmp_path).get('recipe:x', {'a': 1}) is None
    assert store.prune_process([8, 'y']) == 1 and store.get('recipe:x', {'a': 1}) is None
    store.put('news_body', {'unid': 1}, {'row': {}}, {'mode': 'forever'})
    assert store.prune_process([8, 'y']) == 0 and store.get('news_body', {'unid': 1}) is not None


def test_file_change_invalidates(tmp_path, world):
    record = put_record(world, RECORD, 1)
    _, rs = read_set_of(world, record)
    data = tmp_path / 'history_dt.cmt'
    data.write_bytes(b'one')
    rs.files = [ui_cache.file_stamp(data)]
    assert check(world, rs)['ok']
    data.write_bytes(b'longer')
    result = check(world, rs)
    assert not result['ok'] and 'game file changed' in result['reason']


class FakeSession:
    def __init__(self, world, tmp_path):
        self.world, self.memory, self.tmp = world, world.m, tmp_path
        self.process, self.volatile = [world.m.pid, 'start'], set()

    def screen_cache(self, state):
        return ui_cache.ScreenCache('career-x', build='b1', root=self.tmp)

    def note_volatile(self, store, pages):
        self.volatile.update(pages)

    def vm(self, mode, state, fresh=False, max_instructions=None):
        return self.world.vm


def test_tracked_answer_is_recomputed_only_when_bytes_it_read_change(world, tmp_path):
    session = FakeSession(world, tmp_path)
    record = put_record(world, RECORD, 10)
    calls = []

    def compute(vm):
        calls.append(1)
        return {'value': vm.get_property(record, 'Xxxx').value}

    def ask(**kwargs):
        entry, block = ui_tools.tracked(session, {}, 'recipe:test', {'record': record}, compute, **kwargs)
        return entry['value'], block
    value, block = ask()
    assert value == 10 and not block['hit'] and len(calls) == 1
    value, block = ask()
    assert value == 10 and block['hit'] and block['check']['result'] == 'unchanged' and len(calls) == 1
    world.m.put(record + 0x300, b'tick')           # an unread byte: page-level set cannot tell, recompute once
    value, block = ask()
    assert value == 10 and not block['hit'] and len(calls) == 2 and RECORD in session.volatile
    world.m.put(record + 0x300, b'tock')           # the page is now tracked by word: still valid
    value, block = ask()
    assert value == 10 and block['hit'] and len(calls) == 2
    world.m.put(record + 0x10, struct.pack('<Q', 11))             # a byte it read
    value, block = ask()
    assert value == 11 and not block['hit'] and len(calls) == 3
    value, block = ask(fresh=True)
    assert value == 11 and not block['hit'] and len(calls) == 4
    session.process = [world.m.pid, 'restarted']                  # another process: addresses mean nothing
    value, block = ask()
    assert not block['hit'] and len(calls) == 5


def test_tracked_forever_entries_and_incomplete_answers(world, tmp_path):
    session = FakeSession(world, tmp_path)
    record = put_record(world, RECORD, 10)
    calls = []

    def compute(vm):
        calls.append(1)
        return {'value': vm.get_property(record, 'Xxxx').value}
    entry, block = ui_tools.tracked(session, {}, 'news_body', {'unid': 1}, compute, forever=True)
    world.m.put(record + 0x10, struct.pack('<Q', 99))
    entry, block = ui_tools.tracked(session, {}, 'news_body', {'unid': 1}, compute, forever=True)
    assert entry['value'] == 10 and block['hit'] and len(calls) == 1          # never recomputed
    entry, block = ui_tools.tracked(session, {}, 'recipe:budget', {}, compute, complete=lambda p: False)
    assert block['stored'] is False
    ui_tools.tracked(session, {}, 'recipe:budget', {}, compute, complete=lambda p: False)
    assert len(calls) == 3                                                    # an unstored answer is not served


# ---------------------------------------------------------------------- inbox: list and bodies
class FakeNews:
    NEWS_KEYS = ('titl', 'body')
    NEWS_HEAD_KEYS = ('titl',)

    def __init__(self):
        self.rendered = []
        self.flags = {30: 0, 20: 1, 10: 1}

    def viewer(self, vm):
        return SimpleNamespace(human=1, person_index=5)

    def inbox_entries(self, vm, human):
        return [SimpleNamespace(unid=u, news_class='NEWS', date=f'2030-12-{u}', read=bool(f), flags=f)
                for u, f in self.flags.items()]

    def Names(self, vm):
        return lambda ui_id: {'id': ui_id}

    def news_item(self, vm, person_index, unid, keys):
        self.rendered.append((unid, tuple(keys)))
        return SimpleNamespace(unid=unid, keys=keys)

    def shape_news(self, entry, reading, names):
        row = {'subject': f'subject {entry.unid}', 'headline_subtitle': None, 'time_sent': '09:00',
               'input_failures': {}}
        if 'body' in reading.keys:
            row.update(body=f'body {entry.unid}', body_links=[], can_respond=False, sender={'id': 1})
        return row


class FakeUiVM:
    rng_uses = 0

    def begin_read(self):
        pass

    def reset(self):
        pass


def test_inbox_lists_from_stored_objects_and_renders_bodies_on_demand(monkeypatch, tmp_path):
    import threading
    news = FakeNews()
    session = SimpleNamespace(lock=threading.RLock(), memory=None, process=[1, 's'], volatile=set(),
                              save_state=lambda: {'save_key': 'career-x', 'game_date': '2030-12-30'},
                              screen_cache=lambda state: ui_cache.ScreenCache('career-x', build='b', root=tmp_path),
                              vm=lambda mode, state, **kw: FakeUiVM(), note_volatile=lambda store, pages: None)
    monkeypatch.setattr(ui_tools, 'session_for', lambda bridge, sid: session)
    monkeypatch.setattr(ui_tools, 'recipe_module', lambda name: news)
    monkeypatch.setattr(ui_tools, 'fingerprinting', lambda s: True)
    first = ui_tools.inbox(None, 's')
    assert [r['unid'] for r in first['result']] == [30, 20, 10] and first['unread'] == 1
    assert [r['subject'] for r in first['result']] == ['subject 30', 'subject 20', 'subject 10']
    assert all('body' not in r for r in first['result'])
    assert news.rendered == [(30, ('titl',)), (20, ('titl',)), (10, ('titl',))]      # headers only
    news.flags[30] = 1                                             # the manager reads an item in the game
    second = ui_tools.inbox(None, 's')
    assert len(news.rendered) == 3 and second['cache']['hit'] and second['cache']['rendered_now'] == 0
    assert second['result'][0]['read'] is True and second['unread'] == 0
    third = ui_tools.inbox(None, 's', items=[20])
    row = next(r for r in third['result'] if r['unid'] == 20)
    assert row['body'] == 'body 20' and row['as_rendered']['can_respond'] is False
    assert news.rendered[3:] == [(20, ('titl', 'body'))] and all('body' not in r for r in third['result'] if r['unid'] != 20)
    ui_tools.inbox(None, 's', items=[20])
    assert len(news.rendered) == 4                                 # the body is kept
    ui_tools.inbox(None, 's', items=[20], fresh=True)
    assert len(news.rendered) == 5                                 # fresh renders the named items again
    only_unread = ui_tools.inbox(None, 's', unread_only=True, items=[10])
    assert [r['unid'] for r in only_unread['result']] == [10] and only_unread['items_not_in_inbox'] == []
    assert ui_tools.inbox(None, 's', items=[999])['items_not_in_inbox'] == [999]
    budget = ui_tools.inbox(None, 's', limit=1, items=[30], fresh=True, time_budget_s=-1)
    assert budget['result'][0]['pending'] and budget['cache']['pending'] == 1


def test_two_seed_rule_withholds_draw_dependent_leaves_and_reuses_a_clean_result(world, tmp_path):
    from fm_live_mcp.fmdb.ui_vm import GENERATED_AT_READ
    session = FakeSession(world, tmp_path)
    record = put_record(world, RECORD, 10)
    runs = []

    def compute(vm, dependent=True):
        runs.append(getattr(vm, 'rng_salt', 0))
        vm.rng_uses += 2                           # the computation drew twice
        value = vm.get_property(record, 'Xxxx').value
        return {'stable': value, 'drawn': 5 if not (dependent and getattr(vm, 'rng_salt', 0)) else 6}
    entry, _ = ui_tools.tracked(session, {}, 'recipe:dice', {}, compute, fresh=True)
    assert runs == [0, ui_tools_salt()] and entry['stable'] == 10
    assert entry['drawn'] == {'unavailable': GENERATED_AT_READ}               # never stored as a value
    assert entry['rng_rule']['draws'] == 2 and entry['rng_rule']['leaves_withheld'] == ["('drawn',)"]
    ui_tools.tracked(session, {}, 'recipe:dice', {}, compute, fresh=True)
    assert len(runs) == 4                          # a result with withheld leaves is always read twice
    runs.clear()
    clean = lambda vm: compute(vm, dependent=False)                           # noqa: E731
    entry, _ = ui_tools.tracked(session, {}, 'recipe:clean', {}, clean, fresh=True)
    assert len(runs) == 2 and entry['drawn'] == 5 and entry['rng_rule']['leaves_withheld'] == []
    entry, _ = ui_tools.tracked(session, {}, 'recipe:clean', {}, clean, fresh=True)
    assert len(runs) == 3 and entry['rng_rule']['served_without_second_read'] == 1


def ui_tools_salt():
    from fm_live_mcp.fmdb.ui_vm import TWO_SEED_SALT
    return TWO_SEED_SALT
