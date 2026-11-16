"""The live-match readers on 27.0.1.2503222: what a paused live match showed that the code
comparison had not (12 November 2026, Newcastle v Bournemouth, playback tick 6332)."""
from __future__ import annotations

import ast
import struct
from pathlib import Path

from fm_live_mcp.fmdb import address_census, address_map, platform_model
from tests.test_function_match import NEW, OLD, SHA_27_0_1, needs_builds

PACKAGE = Path(__file__).resolve().parents[1] / 'fm_live_mcp'
# pinned address -> 27.0.1 address of the static initialiser code the two readers guard
LOW_GUARDS = {0xD6C4: 0xD790, 0xDB74: 0xDC40, 0xDBB8: 0xDC84, 0xE204: 0xE2D0}


def _spans(rel):
    """NATIVE_SPANS of a module as written in the source (the pinned build's)."""
    tree = ast.parse((PACKAGE / rel).read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], 'id', '') == 'NATIVE_SPANS':
            return dict(eval(compile(ast.Expression(node.value), rel, 'eval')))    # noqa: S307
    raise AssertionError(rel)


def _masked(raw):
    """Instruction words with BL displacements, ADRP pages and ADD page offsets cleared."""
    out = []
    for (w,) in struct.iter_unpack('<I', raw):
        if w & 0xFC000000 == 0x94000000:
            w = 0x94000000
        elif w & 0x9F000000 == 0x90000000:
            w &= 0x9F00001F
        elif w & 0xFFC00000 == 0x91000000:
            w &= 0xFFC003FF
        out.append(w)
    return out


def test_the_static_initialiser_guards_are_reviewed():
    values = address_map.reviewed_values(SHA_27_0_1)
    for old, new in LOW_GUARDS.items():
        assert values[old][0] == new and 'operator<<' in values[old][1]


@needs_builds
def test_the_static_initialiser_guards_are_the_same_code_on_27_0_1():
    """The entity setup row (size 0x160, teamIndex +0x3A, uniqueID +0x3C) and the playback event
    row (0x2C bytes, PlayerID1..6, PlayerTeams, CommentaryEvent, TimeSlice ...) are written out by
    the game itself; the code that writes them moved 0xCC bytes and is otherwise the same."""
    old, new = platform_model.load_binary(OLD), platform_model.load_binary(NEW)
    assert old.text_start == new.text_start == address_census.CODE_START
    spans = {**_spans('active_match_entity_identity.py'), **_spans('playback_event_source.py')}
    for a, b in LOW_GUARDS.items():
        span = spans[a]
        assert old.image.file_bytes(a, len(span)) == span
        assert _masked(new.image.file_bytes(b, len(span))) == _masked(span), hex(a)
    # the three immediates the frame reader depends on
    assert [new.u32(b) for b in (0xD790, 0xDC40, 0xDC84)] == \
        [0x52800001 | v << 5 for v in (0x160, 0x3A, 0x3C)]


def test_team_statistics_default_to_the_object_the_match_screen_reads():
    """fm_get_current_match defaulted to the client's copy, which held 3 shots on the paused match
    while the engine's object, the one MATCH_UI_HANDLER reads (fmdb/sources/match_state.py), held
    8, as many as the shot events before the playback cursor."""
    import inspect

    from fm_live_mcp import current_match_report, current_match_tools
    assert inspect.signature(current_match_report.current_match_report).parameters['statistics_scope'].default == 'simulation'
    assert "statistics_scope: Literal['client_snapshot', 'simulation'] = 'simulation'" in inspect.getsource(current_match_tools)
