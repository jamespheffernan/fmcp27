"""Offline pointer validation; never attaches or supplies live promise evidence."""
import importlib.util
from pathlib import Path
import pytest

@pytest.fixture(params=['collect_player_promises.py','collect_promise_definitions.py','collect_promise_status.py','collect_promise_events.py','collect_promise_selector.py'])
def source(request):
    path=Path(__file__).resolve().parents[1]/'evidence/social-promises-20261109'/request.param
    spec=importlib.util.spec_from_file_location('social_capture_'+path.stem,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

@pytest.mark.parametrize('rva',[0xd5c5fc,0xd5c600,0,0x4aef7fc])
def test_exact_arm64_code_address_accepts_four_byte_alignment(source,rva):
    base=0x100000000
    read=lambda at,size:(base+rva).to_bytes(size,'little')
    assert source.native_code_pointer(read,0x2000,base)==base+rva

@pytest.mark.parametrize('rva',[0xd5c5fe,-4,0x4aef800,0x4aef804])
def test_noninstruction_or_outside_pinned_text_is_refused(source,rva):
    base=0x100000000
    read=lambda at,size:(base+rva).to_bytes(size,'little')
    with pytest.raises(ValueError,match='Invalid original ARM64'):
        source.native_code_pointer(read,0x2000,base)


def test_old_object_pointer_alignment_rejects_the_actual_valid_getter():
    # Cause control: this is why the old shared object-pointer validator would
    # always reject the real +668 getter, before any genuine source observation.
    assert 0xd5c5fc%4==0 and 0xd5c5fc%8==4


def test_pinned_bridge_runtime_uuid_header_fits_the_read_budget(source):
    # Bridge._player_layout calls players.verify_runtime, whose original
    # Mach-O UUID preflight requests exactly16KiB before reading any PLAYER.
    assert source.MAX_READ==16384
    bridge=source.JournalBridge.__new__(source.JournalBridge)
    bridge.journal=None
    bridge.journal_process=None
    bridge.consumed_bytes=0
    observed=[]
    bridge.physical=lambda address,size:observed.append((address,size))or b'\0'*size
    assert bridge._read_memory('synthetic-process',0x100000000,16384)==b'\0'*16384
    assert observed==[(0x100000000,16384)]
    with pytest.raises(ValueError,match='Invalid bounded promise read'):
        bridge._read_memory('synthetic-process',0x100000000,16385)
    assert observed==[(0x100000000,16384)]
