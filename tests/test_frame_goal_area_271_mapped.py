"""Through the 27.0.1 address map: the frame's native goal area is not withheld.

Runs in a session that addresses the installed build (`pytest tests/test_frame_goal_area_271_mapped.py`
with the map in `$FMCP_CACHE_DIR`). Skips unless that build is 27.0.1.2503222 and its preserved
plugin is on this machine. No game is read: the guards are compared with the plugin file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fm_live_mcp import address_book as ab

SHA_271 = '68adfde2e0588458c1830cb7e688855d9c61237973a7eb7a105af5ac4ed112a4'
PLUGIN = Path('/Volumes/4TB Private/Offloaded/Agent Work/fmdb-runtime-research/builds/27.0.1.2503222/game_plugin')
MAX_READ = 16384                    # bridge.Bridge._read_memory refuses a longer read
GOAL_AREA_SITES = {0x4ABCE24: 0x498FD30, 0x4AB33FC: 0x498FF64, 0x4ABD804: 0x49901D4, 0x4AB35F4: 0x49902D4,
                   0x4ABD9DC: 0x49B2744, 0x4AB1F78: 0x499D6FC, 0x4AB4DF8: 0x4990B0C}


@pytest.fixture(scope='module')
def mapped():
    if ab.ACTIVE['state'] != 'mapped' or ab.ACTIVE['sha256'] != SHA_271:
        pytest.skip('the session does not address build 27.0.1.2503222 through its map')
    if not PLUGIN.is_file():
        pytest.skip('the preserved 27.0.1 plugin is not on this machine')
    return ab.MAP


def test_map_resolves_the_goal_area_sites(mapped):
    for pinned, new in GOAL_AREA_SITES.items():
        entry = mapped['values'][f'{pinned:#x}']
        assert (entry['value'], entry['method']) == (new, 'reviewed'), hex(pinned)


def test_static_walk_does_not_withhold_the_goal_area(mapped):
    from fm_live_mcp import current_frame_report as report
    assert report._goal_area_capture.blocked() == []
    assert report._goal_area_result.blocked() == []
    tools = {'fm_get_current_match_frame': report.current_frame_report}
    assert not ab.unavailable_tools(tools) and not ab.partial_tools(tools)


def test_rewritten_guards_are_the_plugin_file(mapped):
    """Every span the section's two reviewed modules and the direction module check is, after the
    map's rewrite, the 27.0.1 plugin's bytes at the 27.0.1 address, in one bounded read."""
    from fm_live_mcp import frame_attack_direction as direction, frame_attacked_goal_basis as goal
    from fm_live_mcp import native_motion_world_basis as motion
    from fm_live_mcp.fmdb.image import PluginImage
    image = PluginImage.load(PLUGIN, verify=False)
    base = 0x1_0000_0000
    reads = []

    def read(address, length):
        assert 1 <= length <= MAX_READ
        reads.append(length)
        return image.file_bytes(address - base, length)
    assert motion.verify_native(read, base)['native_motion_xyz_to_frame_endpoint_copy_verified'] is True
    for module in (goal, direction):
        for at, expected in module.NATIVE_SPANS:
            assert read(base + at, len(expected)) == expected, (module.__name__, hex(at))
    addresses = {at for module in (goal, motion) for at, _raw in module.NATIVE_SPANS}
    assert set(GOAL_AREA_SITES.values()) <= addresses
    assert max(reads) == 10704
