"""Named pitch setup source controls; no game process access."""
import hashlib
import struct

import pytest
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X8, UC_ARM64_REG_LR, UC_ARM64_REG_SP, UC_ARM64_REG_PC

from fm_live_mcp import frame_pitch_setup as pitch
from test_frame_attack_direction import Source, OriginalNative, native_spans, BASE, PRIMARY, PLAYBACK, MATCH, CACHE, STACK, STOP, TICK, PLUGIN

PITCH=0x36000000
OUTPUT=STACK+0x100


@pytest.fixture
def source(native_spans):
    s=Source(native_spans)
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        for at,expected in pitch.NATIVE_SPANS:
            f.seek(0x5ED4000+at);actual=f.read(len(expected));assert actual==expected
            s.put(BASE+at,actual)
    s.put(BASE+0x54EC0C8+0x48,struct.pack('<Q',BASE+0x734C2C))
    s.put(MATCH+0x153E8,struct.pack('<Q',PITCH))
    s.put(PITCH+0x270,struct.pack('<ff',68,105))
    s.put(PLAYBACK+0x10A0,struct.pack('<ff',105,68))
    return s


def public(s):
    initial=pitch.capture(s.read,BASE,s.bound,fixed_tick=TICK)
    return pitch.project(pitch.verify_capture(s.read,BASE,initial,s.bound))


def test_named_dimensions_match_original_getter_prefix_and_complete_copy_callee(source):
    # Run complete734C2C owner-selection/tail plus736F84 through its first
    # dimension write and the complete741B50 callee. Unrelated stadium fields
    # after736FD0 are explicitly outside this oracle's scope.
    original=OriginalNative(source)
    for reg,value in [(UC_ARM64_REG_X0,PRIMARY),(UC_ARM64_REG_X1,123),
        (UC_ARM64_REG_X8,OUTPUT),(UC_ARM64_REG_SP,STACK+0xFF00),(UC_ARM64_REG_LR,STOP)]:
        original.uc.reg_write(reg,value)
    # OriginalNative allows stack writes; the owned output lies in that stack.
    original.uc.emu_start(BASE+0x734C2C,BASE+0x736FD4,count=100)
    assert original.uc.reg_read(UC_ARM64_REG_PC)==BASE+0x736FD4
    result=public(source)
    assert struct.unpack('<ff',bytes(original.uc.mem_read(OUTPUT,8)))==(result['pitch_length_native'],result['pitch_width_native'])==(105,68)
    assert result['physical_units'] is result['penalty_area_geometry'] is None
    assert result['world_xy_to_pitch_bounds_verified'] is result['on_pitch_population_verified'] is False
    assert not any(k.startswith('_') for k in result)


@pytest.mark.parametrize('span',range(len(pitch.NATIVE_SPANS)))
def test_each_pitch_source_guard_drift_refuses(source,span):
    at,_=pitch.NATIVE_SPANS[span];source.values[BASE+at]^=1
    with pytest.raises(ValueError,match='source changed'):public(source)


def test_named_route_drift_refuses(source):
    source.put(BASE+0x54EC0C8+0x48,struct.pack('<Q',BASE+0x734C30))
    with pytest.raises(ValueError,match='virtual route'):public(source)


@pytest.mark.parametrize('v',[0.0,-1.0,float('inf'),float('nan')])
def test_invalid_pitch_setup_is_unavailable_not_standard_pitch(source,v):
    source.put(PLAYBACK+0x10A0,struct.pack('<ff',v,68))
    result=public(source)
    assert result['state']=='unavailable_native_pitch_dimensions'
    assert result['pitch_length_native'] is result['pitch_width_native'] is None


def test_source_disagreement_has_null_dimensions(source):
    source.put(PITCH+0x274,struct.pack('<f',104))
    result=public(source)
    assert result['state']=='unavailable_pitch_setup_source_disagreement'
    assert result['pitch_length_native'] is result['pitch_width_native'] is None


def test_changed_dimension_refuses_after_lifetime_callbacks(source):
    before=pitch.capture(source.read,BASE,source.bound,fixed_tick=TICK)
    source.put(PITCH+0x274,struct.pack('<f',106))
    with pytest.raises(ValueError,match='changed during'):pitch.verify_capture(source.read,BASE,before,source.bound)


def test_missing_exact_frame_returns_no_setup(source):
    source.put(CACHE+0x38,struct.pack('<I',TICK+10))
    result=public(source)
    assert result['state']=='unavailable_exact_frame' and result['pitch_length_native'] is None


def test_monotonic_cursor_can_advance_with_fixed_frame(source):
    before=pitch.capture(source.read,BASE,source.bound,fixed_tick=TICK)
    result=pitch.project(pitch.verify_capture(source.read,BASE,before,source.bound|{'current_time_slice':TICK+4}))
    assert result['frame_tick']==TICK and result['verification_cursor']==TICK+4


def test_unverified_projection_refuses(source):
    with pytest.raises(ValueError,match='Final named'):pitch.project(pitch.capture(source.read,BASE,source.bound,fixed_tick=TICK))
