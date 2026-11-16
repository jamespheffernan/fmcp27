"""27.0.1 and the current-match frame tool.

* The native goal area is an optional section of the frame report: on a build where its sites do
  not resolve, the report answers without it (`current_frame_report._goal_area_*`).
* The cached player motion getter 0x47D46C4 -> 0x486A34C (rewritten: the generation path is
  inlined) reads the same fields on every path `native_motion_cache.capture` mirrors: start +0x180,
  end +0x188, the 32-byte ring at +0x100 indexed by tick & 3, the buffer pointer +0xF0 indexed by
  tick - start, 25 bytes copied. Proven by running both builds' getter in the VM over the same
  synthetic motion objects and comparing with the mirror.
"""
from __future__ import annotations

import random
import struct
from pathlib import Path

import pytest

BUILDS = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds')
OLD, NEW = BUILDS / '27.0.0.2493426/game_plugin', BUILDS / '27.0.1.2503222/game_plugin'
GETTER = {'old': (0x47D46C4, 0x47D4898), 'new': (0x486A34C, 0x486A8EC)}
needs_builds = pytest.mark.skipif(not (OLD.is_file() and NEW.is_file()),
                                  reason='preserved 27.0.0 and 27.0.1 plugins not present')


def test_frame_report_goal_area_is_an_optional_section(monkeypatch):
    from fm_live_mcp import address_book, current_frame_report as report
    monkeypatch.setattr(address_book, 'MAP', {'values': {}})
    monkeypatch.setattr(address_book, 'unresolved_sites', lambda: {
        ('fm_live_mcp.frame_attacked_goal_basis', 'module:NATIVE_SPANS'): [(0x4ABD804, 'no counterpart')]})
    for section in (report._goal_area_capture, report._goal_area_result):
        section._blocked = None
    out = report._goal_area_capture(None, 0, {}, 1)
    assert out['state'] == 'unavailable' and '0x4abd804' in out['native_sites'][0]
    assert '_captured' not in out
    tools = {'frame': report.current_frame_report}
    assert not address_book.unavailable_tools(tools)
    assert address_book.partial_tools(tools) == {'frame': {'native_goal_area': out['native_sites'][:3]}}


def _run(build, cases):
    from test_match_rating_builds import _static_vm
    from fm_live_mcp import native_motion_cache as nmc
    path = OLD if build == 'old' else NEW
    v, base, b = _static_vm(path)
    start_fn, end_fn = GETTER[build]
    motion = v._static(bytes(0x200))
    buffer = v._static(bytes(32 * 1200))
    out = v._static(bytes(32))
    player = motion - 0x80
    guard = (start_fn, b.image.file_bytes(start_fn, end_fn - start_fn)) if build == 'new' else nmc.NATIVE_GETTER
    results = []
    saved = nmc.NATIVE_GETTER
    nmc.NATIVE_GETTER = guard
    try:
        for start, end, tick, alt, pointer, seed in cases:
            rng = random.Random(seed)
            body = bytearray(rng.randbytes(0x200))
            struct.pack_into('<iQ', body, 0x180, start, 0)
            struct.pack_into('<i', body, 0x188, end)
            struct.pack_into('<i', body, 0x54, alt)
            struct.pack_into('<Q', body, 0xF0, buffer if pointer else 0)
            v.uc.mem_write(motion, bytes(body))
            v.uc.mem_write(buffer, rng.randbytes(32 * 1200))
            v.uc.mem_write(out, b'\xaa' * 32)
            v.call(base + start_fn, (motion, 0, 0, out, tick & 0xFFFFFFFF, 0))
            native = bytes(v.read(out, 32))
            mirror = nmc.capture(v.read, base, player, fixed_tick=tick)
            results.append((native, mirror))
    finally:
        nmc.NATIVE_GETTER = saved
    return results


def _cases(seed, n):
    rng = random.Random(seed)
    cases = []
    for k in range(n):
        tick = rng.randint(0, 200000)
        kind = k % 3
        if kind == 0:                         # resident ring: start after the tick
            start = tick + rng.randint(1, 5000)
            end = rng.choice([-1, start + rng.randint(0, 1000)])
        elif kind == 1:                       # bounded buffer: start <= tick <= end
            start = tick - rng.randint(0, 1199)
            end = tick + rng.randint(0, 2000)
        else:                                 # negative end with the +0x54 clock at or after the tick
            start = tick - rng.randint(0, 1199)
            end = -rng.randint(1, 50)
        cases.append((start, end, tick, tick + rng.randint(0, 100), True, rng.random()))
    return cases


@pytest.mark.slow
@needs_builds
@pytest.mark.parametrize('seed', [1, 2])
def test_motion_getter_paths_are_unchanged_and_equal_the_mirror(seed):
    cases = _cases(seed, 600)
    old, new = _run('old', cases), _run('new', cases)
    mirrored = 0
    for (no, mo), (nn, mn), case in zip(old, new, cases):
        assert no == nn, case                                    # both builds copy the same bytes
        assert mo == mn                                          # the mirror is build-independent
        if mo['native_xyz'] is not None or mo['state'].startswith('unavailable_nonfinite'):
            raw = mo['_selection'][-1]
            assert raw == no[:25], case                          # the mirror reads what the getter copies
            mirrored += 1
        else:
            assert mo['state'] in ('unavailable_requires_generation_or_secondary_clock',
                                   'unavailable_bounded_motion_buffer_range')
    assert mirrored >= 350
