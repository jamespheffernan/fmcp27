"""Live regression oracle: the bulk engine against the existing tool path at one game state.

Skipped when the native helper is missing or FM27 cannot be attached. Read-only. Runs the
existing per-cell path, so it takes several minutes (about 0.1 s per cell); set
FM_LIVE_REGRESSION=0 to skip it while FM27 is running.
"""
import os

import pytest

from fm_live_mcp import bridge as bridge_module, knowledge_bulk as kb, knowledge_manager_visible as km

FIXED_ORDINALS = [1, 2, 3, 5, 8, 13, 17, 21, 34, 55, 89, 100, 144, 233, 377, 610, 987, 1000, 1597, 2584,
                  4181, 6765, 10000, 10946, 17711, 28657, 46368, 50000]


@pytest.fixture(scope='module')
def live():
    if os.environ.get('FM_LIVE_REGRESSION') == '0':
        pytest.skip('FM_LIVE_REGRESSION=0')
    bridge = bridge_module.Bridge()
    if not bridge.helper.is_file():
        pytest.skip('native helper not built')
    try:
        session_id = bridge.attach()['session_id']
    except Exception as exc:   # no FM27 process, permission, or unsupported build
        pytest.skip(f'FM27 is not attached: {exc}')
    yield bridge, session_id
    bridge.detach()


def _compare(bridge, session_id, refs, attempts=3):
    """Both paths at one game state. A capture rejected because the running game changed a
    consumed byte (for example the day advanced) is retried; equality is never relaxed."""
    for attempt in range(attempts):
        date = bridge.get_save(session_id)['save']['current_date']
        try:
            with bridge.lock:
                old = km._capture(bridge, session_id, refs, kb.ALL_FIELDS, None)
            new = kb.visible_attributes_bulk((bridge, session_id), refs)
        except (ValueError, bridge_module.BridgeError) as exc:
            if 'changed' not in str(exc) or attempt == attempts - 1:
                raise
            continue
        if bridge.get_save(session_id)['save']['current_date'] == date == new['save']['current_date']:
            break
    old_cells = {row['player_ref']: row['fields'] for row in old['subjects']}
    equal = different = 0
    for player in new['players']:
        for a, b in zip(old_cells[player['key']], player['fields'], strict=True):
            equal += a == b
            different += a != b
    assert old['before']['save']['current_date'] == new['save']['current_date']
    assert different == 0 and equal == len(refs) * 47
    assert new['state_counts'] == old['state_counts']
    assert new['firewall']['attribute_bytes_authorised'] == old['journal']['authorized_attribute_bytes'] \
        == new['state_counts']['exact'] + new['state_counts']['range']
    return new


def test_managed_squad_all_fields_equal_existing_tool(live):
    bridge, session_id = live
    refs = [p['player_ref'] for p in bridge.get_managed_squad(session_id)['players']]
    _compare(bridge, session_id, refs)


def test_fixed_all_actual_ordinals_all_fields_equal_existing_tool(live):
    bridge, session_id = live
    bound = kb.bind_player_refs(bridge, session_id, [('ordinal', o) for o in FIXED_ORDINALS])
    refs = [ref for ref in bound.values() if ref]
    assert len(refs) == 28
    new = _compare(bridge, session_id, refs)
    # Ordinal keys resolve to the same subjects and cells as their player_refs.
    by_ordinal = kb.visible_attributes_bulk((bridge, session_id), [('ordinal', o) for o in FIXED_ORDINALS])
    assert [p['fields'] for p in by_ordinal['players']] == [p['fields'] for p in new['players']]
