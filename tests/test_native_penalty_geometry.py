"""Complete original native predicate controls over owned synthetic geometry."""
import hashlib
import struct

import pytest
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_MEM_READ,UC_HOOK_MEM_WRITE
from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_LR,UC_ARM64_REG_PC
from fm_live_mcp import native_penalty_geometry as geometry
from test_frame_attack_direction import PLUGIN

BASE,SHAPE,POINT,STOP=0x100000000,0x30000000,0x31000000,0x32000000


def neighbors(v):
    bits=struct.unpack('<I',struct.pack('<f',v))[0]
    if not v:return [-struct.unpack('<f',struct.pack('<I',1))[0],0.0,struct.unpack('<f',struct.pack('<I',1))[0]]
    return [struct.unpack('<f',struct.pack('<I',bits+i))[0] for i in (-1,0,1)]


def test_complete_original_predicate_at_all_edges_and_both_ends():
    with PLUGIN.open('rb') as f:
        assert hashlib.file_digest(f,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
        at,expected=geometry.NATIVE_PREDICATE
        f.seek(0x5ED4000+at);raw=f.read(len(expected));assert raw==expected
    uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    for page in (BASE+(at&~4095),SHAPE,POINT,STOP):uc.mem_map(page,4096)
    uc.mem_write(BASE+at,raw)
    def read(machine,kind,address,size,value,extra):
        assert (address,size) in {(SHAPE+0xDC,4),(POINT,4),(POINT+4,4)}
    def write(*args):raise AssertionError('Native selected-area predicate unexpectedly writes')
    uc.hook_add(UC_HOOK_MEM_READ,read);uc.hook_add(UC_HOOK_MEM_WRITE,write)
    checks=0
    for half_length in (52.5,55.0,8.0):
        threshold=geometry._f32(half_length+geometry._f32(-16.459))
        ys=neighbors(threshold)+neighbors(-threshold)+neighbors(0.0)+neighbors(half_length)+neighbors(-half_length)
        xs=neighbors(geometry._f32(20.13))+neighbors(geometry._f32(-20.13))+[0.0,20.12,-20.12,34.0,-34.0]
        uc.mem_write(SHAPE+0xDC,struct.pack('<f',half_length))
        for selected in (False,True):
            for x in xs:
                for y in ys:
                    uc.mem_write(POINT,struct.pack('<ff',x,y))
                    for reg,val in [(UC_ARM64_REG_X0,SHAPE),(UC_ARM64_REG_X1,POINT),(UC_ARM64_REG_X2,int(selected)),(UC_ARM64_REG_LR,STOP)]:uc.reg_write(reg,val)
                    uc.emu_start(BASE+at,STOP,count=100)
                    assert uc.reg_read(UC_ARM64_REG_PC)==STOP
                    projected=geometry.classify(x,y,selected_goal_positive_y=selected,half_width=34,half_length=half_length)
                    assert projected['native_selected_goal_end_strip'] is bool(uc.reg_read(UC_ARM64_REG_X0)),(x,y,selected,half_length)
                    checks+=1
    assert checks==990


def test_native_strip_has_no_goal_line_cap_but_composite_does():
    result=geometry.classify(0,60,selected_goal_positive_y=True,half_width=34,half_length=52.5)
    assert result['native_selected_goal_end_strip'] is True
    assert result['inside_native_pitch_bounds'] is result['inside_native_pitch_and_selected_goal_end_area'] is False
    assert result['actor_on_pitch'] is result['physical_units'] is None


def test_native_selected_area_does_not_use_retained_renderer_width():
    result=geometry.classify(20.12,45,selected_goal_positive_y=True,half_width=34,half_length=52.5)
    assert result['inside_native_pitch_and_selected_goal_end_area'] is True
    assert 20.12>geometry._f32(20.1168)


@pytest.mark.parametrize('bad',[True,None,float('nan'),float('inf'),1e100])
def test_invalid_float_inputs_refuse(bad):
    with pytest.raises(ValueError):geometry.classify(bad,40,selected_goal_positive_y=True,half_width=34,half_length=52.5)


def test_unknown_direction_or_nonpositive_dimensions_refuse():
    for direction in (None,1,'positive'):
        with pytest.raises(ValueError):geometry.classify(0,40,selected_goal_positive_y=direction,half_width=34,half_length=52.5)
    for width,length in [(0,52.5),(34,-1)]:
        with pytest.raises(ValueError):geometry.classify(0,40,selected_goal_positive_y=True,half_width=width,half_length=length)


def test_guard_matches_exact_original_bytes_and_refuses_drift():
    at,expected=geometry.NATIVE_PREDICATE
    geometry.verify_native(lambda a,n:expected if (a,n)==(BASE+at,len(expected)) else b'',BASE)
    with pytest.raises(ValueError):geometry.verify_native(lambda a,n:bytes(n),BASE)
