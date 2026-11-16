"""What a running Windows process's images look like to the reader. Read-only.

    python scripts/windows_probe.py fm.exe            # by executable name
    python scripts/windows_probe.py 1234              # by pid
    python scripts/windows_probe.py fm.exe --all      # include Windows' own DLLs
    python scripts/windows_probe.py fm.exe --json out.json

For each image the process has loaded from outside the Windows directory it prints the build
record, the size of the function, relocation, import and export tables, the number of C++ type
names (MSVC RTTI) in the loaded image, and, section by section, how much of the file on disk
equals the loaded image once the file is relocated. A code section that does not match its file
was unpacked or decrypted at load time, which is what an anti-tamper layer does; for those
images the reader has to work from the loaded image (`PEImage.from_memory`) instead of the file.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fm_live_mcp.fmdb.memory_windows import WindowsMemory, find_processes  # noqa: E402
from fm_live_mcp.fmdb.pe import PEError, PEImage, compare_with_memory  # noqa: E402


def probe_module(memory, module) -> dict:
    row = {"name": module.name, "path": module.path, "base": module.base, "size": module.size}
    try:
        mapped = PEImage.from_memory(memory, module.base)
    except (PEError, RuntimeError) as exc:
        row["error"] = f"loaded image: {exc}"
        return row
    row["unreadable_pages"] = len(mapped.unreadable_pages)
    row["type_names_loaded"] = mapped.data.count(b".?AV") + mapped.data.count(b".?AU")
    row["functions_loaded"] = len(mapped.functions())
    try:
        image = PEImage.from_file(module.path)
    except (OSError, PEError) as exc:
        row["error"] = f"file: {exc}"
        return row
    record = image.codeview()
    row.update(
        sha256=image.sha256, timestamp=image.timestamp, file_bytes=len(image.data),
        codeview=record.key if record else None, pdb=record.pdb if record else None,
        functions_file=len(image.functions()), relocations=len(image.relocations()),
        exports=len(image.exports()), type_names_file=image.data[:].count(b".?AV") + image.data[:].count(b".?AU"),
    )
    try:
        imports = image.imports()
        row["imports"] = len(imports)
        row["import_libraries"] = sorted({entry.library.lower() for entry in imports})
    except (PEError, UnicodeError, ValueError) as exc:
        row["imports_error"] = str(exc)
    row["sections"] = [
        {"name": match.name, "size": match.size, "same_bytes": match.same_bytes, "pages": match.pages,
         "same_pages": match.same_pages, "unreadable_pages": match.unreadable_pages,
         "executable": match.executable, "writable": match.writable,
         "file_bytes": image.section(match.name).file_size if image.section(match.name) else 0}
        for match in compare_with_memory(image, memory, module.base)
    ]
    return row


def print_module(row: dict) -> None:
    print(f"\n{row['name']}  base {row['base']:#x}  {row['size'] / 1048576:.1f} MiB loaded")
    print(f"  {row['path']}")
    if "error" in row:
        print(f"  could not read: {row['error']}")
        if "sections" not in row:
            return
    if "sha256" in row:
        print(f"  build {row['codeview']}  pdb {row['pdb']}")
        print(f"  file {row['file_bytes'] / 1048576:.1f} MiB  sha256 {row['sha256'][:16]}")
        print(f"  functions {row['functions_file']:,} in the file, {row['functions_loaded']:,} loaded; "
              f"relocations {row['relocations']:,}; imports {row.get('imports', '?')}; exports {row['exports']:,}")
        print(f"  C++ type names {row['type_names_file']:,} in the file, {row['type_names_loaded']:,} loaded")
    for section in row.get("sections", ()):
        kind = ("code" if section["executable"] else "data") + (", writable" if section["writable"] else "")
        share = 100.0 * section["same_bytes"] / section["size"] if section["size"] else 100.0
        note = "" if not section["unreadable_pages"] else f", {section['unreadable_pages']} pages unreadable"
        print(f"    {section['name']:<9} {section['size'] / 1024:>10,.0f} KiB  {kind:<15} "
              f"{share:6.2f}% equals the file ({section['same_pages']}/{section['pages']} pages{note})")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("target", help="executable name (fm.exe) or pid")
    parser.add_argument("--all", action="store_true", help="include images from the Windows directory")
    parser.add_argument("--json", type=Path, help="also write the full result to this file")
    args = parser.parse_args()
    if args.target.isdigit():
        pid = int(args.target)
    else:
        found = find_processes(args.target)
        if not found:
            print(f"no running process named {args.target}", file=sys.stderr)
            return 1
        pid = found[0][0]
    windows = os.environ.get("SystemRoot", r"C:\Windows").lower()
    with WindowsMemory(pid) as memory:
        modules = memory.modules()
        chosen = [m for m in modules if args.all or not m.path.lower().startswith(windows)]
        print(f"process {pid}: {memory.executable}")
        print(f"{len(modules)} images loaded, {len(chosen)} probed; {len(memory.regions()):,} committed regions")
        rows = [probe_module(memory, module) for module in chosen]
    for row in rows:
        print_module(row)
    if args.json:
        args.json.write_text(json.dumps({"pid": pid, "modules": rows}, indent=1))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
