"""Exact page images for tests that copy a sparse {address: byte} map into a fresh Unicorn.

Several knowledge-lane helpers rebuild every 4 KiB page of a ~55,000-cell memory before each
emulated call (`bytes(cells.get(at, 0) for at in range(page, page + 4096))` for ~124 pages) and
map each page separately: most of each call's cost, repeated for every parametrised case although
a case changes a few bytes. `page_images` returns the same bytes for every page and rebuilds only
the pages whose cells changed since the previous call with the same dict (or, for a dict it has not seen, since the
most recent call): it keeps a copy of the dict, and the symmetric difference of the two item sets
names every address added, removed or changed. `map_pages` maps the same pages as one region per run of adjacent pages.
"""
from collections import OrderedDict
from itertools import repeat

PAGE = 4096
_MASK = ~(PAGE - 1)
_CACHE: OrderedDict = OrderedDict()  # id(cells) -> (copy of cells, {page: image})
_CACHE_SIZE = 4


def page_set(addresses) -> set[int]:
    """`{at & ~4095 for at in addresses}`, computed in C."""
    return set(map(_MASK.__and__, addresses))


def page_image(cells: dict, page: int) -> bytes:
    """`bytes(cells.get(at, 0) for at in range(page, page + 4096))`, computed in C."""
    return bytes(map(cells.get, range(page, page + PAGE), repeat(0, PAGE)))


def _page_has_cells(cells: dict, page: int) -> bool:
    return any(map(cells.__contains__, range(page, page + PAGE)))


def page_images(cells: dict) -> dict[int, bytes]:
    """{page: page_image(cells, page)} for exactly the pages in page_set(cells). Reuses the images
    of the last call with this dict for pages whose cells are unchanged. Do not modify the result."""
    key = id(cells)
    entry = _CACHE.pop(key, None)
    if entry is None and _CACHE:
        # A new dict (a case that builds its memory again) usually differs from the last one in a
        # few pages; the difference below is exact whichever copy it starts from.
        entry = next(reversed(_CACHE.values()))
    if entry is None:
        copy, images = dict(cells), {page: page_image(cells, page) for page in page_set(cells)}
    else:
        copy, images = entry
        if cells != copy:
            touched = page_set(address for address, _ in cells.items() ^ copy.items())
            images = {page: image for page, image in images.items() if page not in touched}
            for page in touched:
                if _page_has_cells(cells, page):
                    images[page] = page_image(cells, page)
            copy = dict(cells)
    _CACHE[key] = (copy, images)
    while len(_CACHE) > _CACHE_SIZE:
        _CACHE.popitem(last=False)
    return images


def map_pages(uc, pages) -> None:
    """`for page in pages: uc.mem_map(page, 4096)`, as one mapping per run of adjacent pages."""
    run_start = run_end = None
    for page in sorted(pages):
        if page == run_end:
            run_end += PAGE
            continue
        if run_start is not None:
            uc.mem_map(run_start, run_end - run_start)
        run_start, run_end = page, page + PAGE
    if run_start is not None:
        uc.mem_map(run_start, run_end - run_start)
