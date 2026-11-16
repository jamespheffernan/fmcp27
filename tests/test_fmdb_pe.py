"""PEImage against the Python runtime DLL: from its file, and loaded in a child process."""
import subprocess
import sys
from pathlib import Path

import pytest

from fm_live_mcp.fmdb.pe import (
    DIR_EXCEPTION, MACHINE_AMD64, PEError, PEImage, compare_with_memory,
)

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="needs Windows images and a Windows process")

CHILD = "import os, sys; print(os.getpid(), flush=True); sys.stdin.read()"


def runtime_dll() -> Path:
    name = f"python{sys.version_info.major}{sys.version_info.minor}.dll"
    return Path(sys.base_prefix) / name


@pytest.fixture(scope="module")
def image():
    return PEImage.from_file(runtime_dll())


@pytest.fixture
def loaded():
    from fm_live_mcp.fmdb.memory_windows import WindowsMemory
    child = subprocess.Popen([sys.executable, "-c", CHILD], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        pid = int(child.stdout.readline())
        with WindowsMemory(pid) as memory:
            yield memory, memory.module(runtime_dll().name)
    finally:
        child.kill()
        child.wait()


def test_rejects_other_bytes(tmp_path):
    with pytest.raises(PEError, match="no MZ header"):
        PEImage(b"\x7fELF" + bytes(128))
    with pytest.raises(PEError, match="no PE signature"):
        PEImage(b"MZ" + bytes(126))


def test_headers_and_sections(image):
    assert image.machine == MACHINE_AMD64 and not image.mapped
    names = [s.name for s in image.sections]
    assert names[0] == ".text" and ".rdata" in names and ".reloc" in names
    text = image.section(".text")
    assert text.executable and not text.writable and image.section(".data").writable
    assert all(a.end <= b.rva for a, b in zip(image.sections, image.sections[1:]))
    assert image.sections[-1].end <= image.size_of_image
    assert image.section_of(image.entry_point) is text
    assert len(image.sha256) == 64


def test_exports_point_at_functions(image):
    exports = image.exports()
    assert len(exports) > 1000
    text = image.section(".text")
    for name in ("Py_Initialize", "PyLong_FromLong", "PyObject_GetAttr"):
        assert text.contains(exports[name])
    code = [rva for rva in exports.values() if text.contains(rva)]
    # A leaf function (no calls, no stack frame) has no entry in the function table, so not
    # every export is found there (1,086 of 1,495 in python312.dll 3.12.10); the ones that are
    # found start exactly at the export.
    found = [image.function_of(rva) for rva in code]
    listed = [entry for entry in found if entry is not None]
    assert len(listed) > 0.5 * len(code)
    assert sum(entry[0] == rva for entry, rva in zip(found, code) if entry is not None) > 0.95 * len(listed)


def test_function_table(image):
    functions = image.functions()
    rva, size = image.directory(DIR_EXCEPTION)
    assert len(functions) > 5000 and len(functions) <= size // 12
    assert functions == sorted(functions)
    assert all(a[1] <= b[0] for a, b in zip(functions, functions[1:]))
    text = image.section(".text")
    assert all(text.rva <= begin and end <= text.end for begin, end in functions)
    assert image.function_of(text.end + 16) is None
    begin, end = functions[100]
    assert image.function_of(end - 1) == (begin, end)


def test_imports_and_relocations(image):
    imports = image.imports()
    libraries = {entry.library.lower() for entry in imports}
    assert "kernel32.dll" in libraries
    named = {entry.name for entry in imports if entry.library.lower() == "kernel32.dll"}
    assert "GetLastError" in named or "CloseHandle" in named
    assert len({entry.slot for entry in imports}) == len(imports)
    slots = image.relocations()
    assert len(slots) > 1000 and list(slots) == sorted(slots)
    assert all(image.section_of(slot) is not None for slot in slots[:2000])
    # a relocated slot holds an address inside the image as linked
    for slot in list(slots[:200]):
        value = image.u64(slot)
        assert image.image_base <= value < image.image_base + image.size_of_image


def test_codeview_names_the_build(image):
    record = image.codeview()
    assert record is not None and len(record.guid) == 32 and record.age >= 1
    assert record.pdb.lower().endswith(".pdb") and record.key.startswith(record.guid)


def test_file_matches_the_loaded_image(image, loaded):
    memory, module = loaded
    assert module is not None and module.size == image.size_of_image
    by_name = {match.name: match for match in compare_with_memory(image, memory, module.base)}
    text = by_name[".text"]
    assert text.identical and text.size == image.section(".text").virtual_size
    assert by_name[".reloc"].identical or by_name[".reloc"].unreadable_pages   # the loader may discard it
    assert not by_name[".data"].identical              # the running interpreter has written to it
    assert all(match.same_bytes <= match.size for match in by_name.values())


def test_mapped_layout_reads_the_same_tables(image, loaded):
    memory, module = loaded
    mapped = PEImage.from_memory(memory, module.base, path=Path(module.path))
    assert mapped.mapped and mapped.loaded_at == module.base
    assert [s.name for s in mapped.sections] == [s.name for s in image.sections]
    assert mapped.timestamp == image.timestamp and mapped.size_of_image == image.size_of_image
    assert mapped.exports() == image.exports()
    assert mapped.functions() == image.functions()
    assert mapped.codeview() == image.codeview()
    assert [(e.library, e.name, e.ordinal, e.slot) for e in mapped.imports()] == \
           [(e.library, e.name, e.ordinal, e.slot) for e in image.imports()]
    text = image.section(".text")
    assert mapped.read(text.rva, 4096) == image.read(text.rva, 4096)
    # in the loaded image an import slot holds the function's address in another module
    slot = mapped.imports()[0].slot
    target = mapped.u64(slot)
    assert any(m.base <= target < m.end for m in memory.modules())
