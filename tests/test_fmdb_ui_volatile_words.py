"""The volatile-word rule of the screen cache (ui_tools.ignored_words, ui_cache words). No game needed."""
import struct

from fm_live_mcp.fmdb import ui_cache, ui_tools

PAGE = 4096
P = 0x7A_0000_0000


def mask_of(*indexes):
    groups = [0] * 8
    for i in indexes:
        groups[i >> 6] |= 1 << (i & 63)
    return tuple(groups)


def page_with(**words):
    data = bytearray(PAGE)
    for index, value in words.items():
        struct.pack_into('<Q', data, 8 * int(index[1:]), value)
    return bytes(data)


def test_changed_words_names_exactly_the_masked_words_that_moved():
    mask = mask_of(3, 70, 500)
    before = ui_cache.masked_words(page_with(w3=1, w70=2, w500=3, w4=9), mask)
    assert len(before) == 24
    after = page_with(w3=1, w70=5, w500=3, w4=10)             # w4 is not read
    assert ui_cache.changed_words(P, mask, before, after) == [P + 8 * 70]
    masks = {P: mask}
    assert ui_cache.clear_words(masks, [P + 8 * 70, P + 8 * 4]) == 1
    assert masks[P] == mask_of(3, 500)


def test_read_set_keeps_the_words_and_the_check_reports_them():
    mask = mask_of(3, 70)
    data = page_with(w3=1, w70=2)
    whole = P + PAGE
    rs = ui_cache.ReadSet([1, 'x'], [P, whole], [0, 0], {P: mask}, [], {P: ui_cache.masked_words(data, mask)})
    rs = ui_cache.ReadSet.from_bytes(rs.to_bytes())
    assert rs.words == {P: ui_cache.masked_words(data, mask)}
    now = {P: page_with(w3=1, w70=7), whole: bytes(PAGE)}

    def read_many(runs):
        return [(0, b''.join(now[a + k] for k in range(0, n, PAGE))) for a, n in runs]

    def hashes(blob, masks):                # page 0 differs, page 1 equal to what was stored
        return [2, 0]
    check = ui_cache.check_read_set(rs, read_many, hashes, [1, 'x'])
    assert not check['ok'] and check['changed'] == [P] and check['changed_words'] == [P + 8 * 70]

    def all_changed(blob, masks):
        return [2, 3]
    check = ui_cache.check_read_set(rs, read_many, all_changed, [1, 'x'])
    assert check['changed_words'] is None   # a whole page changed: the words are not known


def test_ignored_words_only_when_the_answer_is_equal():
    previous = {'value': 5, 'seconds': 1.0, 'validity': {'mode': 'read_set', 'ignored_words': [P]},
                'computed_at': 'x', 'read_set': {'pages': 3}}
    check = {'changed_words': [P + 8]}
    assert ui_tools.ignored_words(previous, check, {'value': 5, 'seconds': 2.0}) == {P, P + 8}
    assert ui_tools.ignored_words(previous, check, {'value': 6}) == set()
    assert ui_tools.ignored_words(previous, {'changed_words': None}, {'value': 5}) == {P}
    assert ui_tools.ignored_words(None, check, {'value': 5}) == set()
    assert ui_tools.ignored_words(dict(previous, stored=False), check, {'value': 5}) == set()
    many = {'changed_words': [P + 8 * i for i in range(ui_tools.IGNORED_WORDS_LIMIT + 1)]}
    assert ui_tools.ignored_words(previous, many, {'value': 5}) == set()
