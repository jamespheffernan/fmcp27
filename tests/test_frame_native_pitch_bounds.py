"""Original pitch constructor outputs and exact-frame/native guards."""
import struct
import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_S0,UC_ARM64_REG_S1,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from fm_live_mcp import frame_native_pitch_bounds as bounds
from test_frame_pitch_setup import source,native_spans,BASE,PITCH,PLAYBACK,MATCH,TICK,PLUGIN

OUTPUT,STOP=0x70000000,0x71000000


def construct(s,length=105.0,width=68.0):
    spans=(*bounds.NATIVE_SPANS,*bounds.basis.NATIVE_SPANS)
    with PLUGIN.open('rb') as f:
        for at,expected in spans:f.seek(0x5ED4000+at);assert f.read(len(expected))==expected;s.put(BASE+at,expected)
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in {BASE+(at&~4095) for at,_ in bounds.NATIVE_SPANS}|{OUTPUT,STOP}:uc.mem_map(page,4096)
    for at,raw in bounds.NATIVE_SPANS:uc.mem_write(BASE+at,raw)
    for reg,value in [(UC_ARM64_REG_X0,OUTPUT),(UC_ARM64_REG_S0,struct.unpack('<I',struct.pack('<f',length))[0]),(UC_ARM64_REG_S1,struct.unpack('<I',struct.pack('<f',width))[0]),(UC_ARM64_REG_LR,STOP)]:uc.reg_write(reg,value)
    uc.emu_start(BASE+0x4A55180,STOP,count=100);assert uc.reg_read(UC_ARM64_REG_PC)==STOP
    s.put(PITCH+0x1A0,bytes(uc.mem_read(OUTPUT,0xE8)))
    s.put(PLAYBACK+0x10A0,struct.pack('<ff',length,width))


def project(s):
    captured=bounds.capture(s.read,BASE,s.bound,fixed_tick=TICK)
    return bounds.project(bounds.verify_capture(s.read,BASE,captured,s.bound))


@pytest.mark.parametrize('length,width',[(105.0,68.0),(101.25,69.5),(110.0,75.0),(100.1,66.7)])
def test_original_constructor_geometry_maps_exact_frame_xy_axes(source,length,width):
    construct(source,length,width);result=project(source)
    width,length=struct.unpack('<ff',struct.pack('<ff',width,length))
    assert result['native_xy_bounds']=={'x_min':-width/2,'x_max':width/2,'y_min':-length/2,'y_max':length/2}
    assert result['native_xy_to_pitch_bounds_verified'] is True
    assert result['physical_units'] is result['attacked_end_positive_y'] is result['penalty_area_occupation'] is None
    assert result['active_participation_verified'] is False
    assert not any(k.startswith('_') for k in result)


@pytest.mark.parametrize('offset,reason',[(0xD8,'dimension'),(0xDC,'dimension'),(0x30,'corner'),(0x40,'corner'),(0x90,'corner'),(0xA0,'corner'),(0,'goal_centre'),(0x60,'goal_centre')])
def test_actual_geometry_disagreement_is_explicitly_unavailable(source,offset,reason):
    construct(source);source.values[PITCH+0x1A0+offset]^=1
    result=project(source)
    expected='unavailable_native_goal_centre_constructor_disagreement' if reason=='goal_centre' else 'unavailable_native_pitch_'+reason+'_constructor_disagreement'
    assert result['state']==expected
    assert result['native_xy_bounds'] is None and result['native_xy_to_pitch_bounds_verified'] is False


def test_changed_geometry_refuses_final_verification(source):
    construct(source);captured=bounds.capture(source.read,BASE,source.bound,fixed_tick=TICK)
    source.values[PITCH+0x1A0+0x90]^=1
    with pytest.raises(ValueError,match='geometry changed'):bounds.verify_capture(source.read,BASE,captured,source.bound)


def test_unverified_projection_and_native_drift_refuse(source):
    construct(source)
    with pytest.raises(ValueError):bounds.project(bounds.capture(source.read,BASE,source.bound,fixed_tick=TICK))
    at,_=bounds.NATIVE_SPANS[0];source.values[BASE+at]^=1
    with pytest.raises(ValueError,match='constructor changed'):bounds.capture(source.read,BASE,source.bound,fixed_tick=TICK)
