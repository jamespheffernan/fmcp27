"""MSVC run-time type information read from the C++ runtime DLL that ships with Python on Windows."""
import subprocess
import sys
from pathlib import Path

import pytest

from fm_live_mcp.fmdb.msvc_rtti import plain_name, read_classes

windows = pytest.mark.skipif(sys.platform != "win32", reason="needs a Windows image built with MSVC")

CHILD = "import os, sys; print(os.getpid(), flush=True); sys.stdin.read()"
NODE = ".?AVDNameNode@@"                    # the undecorator's node class in vcruntime140.dll, with five subclasses


def runtime() -> Path:
    return Path(sys.base_prefix) / "vcruntime140.dll"


@pytest.fixture(scope="module")
def image():
    from fm_live_mcp.fmdb.pe import PEImage
    return PEImage.from_file(runtime())


@pytest.fixture(scope="module")
def classes(image):
    return read_classes(image)


def test_plain_names():
    assert plain_name(".?AVPERSON@@") == "PERSON"
    assert plain_name(".?AVexception@std@@") == "std::exception"
    assert plain_name(".?AUEVENT@match@sim@@") == "sim::match::EVENT"
    template = ".?AV?$MANUAL_SINGLETON@VGAME@@@sicore@@"
    assert plain_name(template) == template


@windows
def test_classes_and_their_bases(classes):
    assert ".?AVtype_info@@" in classes and NODE in classes
    node = classes[NODE]
    assert node.name == "DNameNode" and node.bases == ()
    derived = [c for c in classes.values() if NODE in c.bases]
    assert len(derived) >= 4 and all(c.bases[0] == NODE for c in derived)
    # The base list hangs off a virtual table's locator. This image has no table for bad_alloc
    # (the class is only thrown here), so it is listed with no bases and no tables.
    assert classes[".?AVbad_alloc@std@@"].bases == ()


@windows
def test_virtual_tables_hold_relocated_pointers_into_code(image, classes):
    relocated = set(image.relocations())
    tables = [table for c in classes.values() for table in c.vtables]
    assert tables
    for table in tables:
        assert table.rva - 8 in relocated                       # the pointer to the locator
        assert len(table) >= 1
        for index, method in enumerate(table.methods):
            assert table.rva + 8 * index in relocated
            assert image.section_of(method).executable
    node = classes[NODE]
    assert node.primary is node.vtables[0] and node.primary.offset == 0
    # Subclasses override methods of the same table, so every table has the base's length.
    assert {len(c.primary) for c in classes.values() if NODE in c.bases} == {len(node.primary)}
    assert classes[".?AVbad_alloc@std@@"].primary is None


@windows
def test_loaded_image_gives_the_same_classes(classes):
    from fm_live_mcp.fmdb.memory_windows import WindowsMemory
    from fm_live_mcp.fmdb.pe import PEImage
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        pid = int(child.stdout.readline())
        with WindowsMemory(pid) as memory:
            module = memory.module(runtime().name)
            loaded = read_classes(PEImage.from_memory(memory, module.base))
    finally:
        child.kill()
        child.wait()
    assert loaded == classes
