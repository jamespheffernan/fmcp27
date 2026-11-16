"""Perceived ability stars: pure parts offline, the emulated game methods when FM27 is attached."""
import os
import struct

import pytest

from fm_live_mcp import knowledge_stars as ks

REG = 0x7000_0000_0000


def test_handle_packs_table_and_index():
    assert ks.handle(1, 109669) == 0x0101AC65
    assert ks.handle(24, 545) == 0x18000221
    for bad in ((-1, 0), (0x7F, 0), (1, 0x7FFFFF)):
        with pytest.raises(ValueError):
            ks.handle(*bad)


def test_dref_record_layout_matches_the_sicore_record_shape():
    at = 0x1000
    blob = ks.dref_record(at, REG, 1, 7)
    assert len(blob) == 0x48
    int_traits, value = struct.unpack_from('<QQ', blob, 0)
    assert (int_traits, value) == (REG + 0x28, 1 << 24 | 7)
    key, _, typed = struct.unpack_from('<IIQ', blob, 0x10)
    assert key == 0x64726566 and typed == at                      # 'dref' -> int32 typed
    assert struct.unpack_from('<QQQ', blob, 0x20) == (at + 0x10, at + 0x20, at + 0x20)
    assert struct.unpack_from('<QQ', blob, 0x38) == (REG + 0xB8, at + 0x20)   # RECORD typed


def test_context_blob_registers_human_then_team():
    viewer = ks.Viewer(human=0x10, person_index=5, team=0x20, team_index=9)
    blob, begin, end = ks.context_blob(0x4000, REG, viewer)
    assert (begin, end) == (0x4090, 0x40B0) and len(blob) == 0xB0
    first = struct.unpack_from('<IIQ', blob, 0x90)
    second = struct.unpack_from('<IIQ', blob, 0xA0)
    assert first == (0x4868756D, 0, 0x4000 + 0x38)               # 'Hhum' -> people handle record
    assert second == (0x54746561, 0, 0x4048 + 0x38)              # 'Ttea' -> teams handle record
    assert struct.unpack_from('<Q', blob, 0x08)[0] == 1 << 24 | 5
    assert struct.unpack_from('<Q', blob, 0x50)[0] == 24 << 24 | 9


@pytest.mark.parametrize('raw,expected', [
    (0xFFFF, dict(state='unknown', min_half_stars=None, max_half_stars=None, min_stars=None, max_stars=None)),
    (0x1010, dict(state='exact', min_half_stars=6, max_half_stars=6, min_stars=3.0, max_stars=3.0)),
    (0x140F, dict(state='range', min_half_stars=5, max_half_stars=10, min_stars=2.5, max_stars=5.0)),
    (0x0B0B, dict(state='exact', min_half_stars=1, max_half_stars=1, min_stars=0.5, max_stars=0.5)),
])
def test_decode_stars(raw, expected):
    assert ks.decode_stars(raw) == expected


@pytest.mark.parametrize('raw', [0x0A0A, 0x1515, 0x0F10, 0x0000])
def test_decode_stars_rejects_impossible_bins(raw):
    assert ks.decode_stars(raw)['state'] == 'unavailable'


# --------------------------------------------------------------------------- live (FM27 attached)

@pytest.fixture(scope='module')
def live():
    if os.environ.get('FM_LIVE_REGRESSION') == '0':
        pytest.skip('FM_LIVE_REGRESSION=0')
    from fm_live_mcp import bridge as bridge_module
    bridge = bridge_module.Bridge()
    if not bridge.helper.is_file():
        pytest.skip('native helper not built')
    try:
        session_id = bridge.attach()['session_id']
    except Exception as exc:
        pytest.skip(f'FM27 is not attached: {exc}')
    yield bridge, session_id
    bridge.detach()


def test_live_own_squad_has_stars_for_every_player(live):
    result = ks.perceived_ability_squad(live)
    assert result['hidden_values_returned'] is False and result['game_writes'] is False
    assert result['players']
    for row in result['players']:
        for side in ('current', 'potential'):
            assert row[side]['state'] in ('exact', 'range'), (row['name'], row[side])


def test_live_unreported_strangers_show_no_stars_and_reported_ones_do(live):
    bridge, session_id = live
    result = ks.perceived_ability(live, [('ordinal', o) for o in (1, 2, 17, 233)])
    states = [row['current']['state'] for row in result['players']]
    reports = [row['report_present'] for row in result['players']]
    for state, report in zip(states, reports):
        assert (state != 'unknown') == bool(report)
