"""The POSIX file calls this package uses, with Windows equivalents.

On macOS and Linux every name here is the ``os`` value or call unchanged, looked up when it is
used (so a test that replaces ``os.open`` or ``os.pread`` still sees the call). On Windows:

* ``open_fd`` always opens in binary mode. Without ``O_BINARY`` Windows opens a descriptor in
  text mode, which rewrites line endings and stops at a Ctrl-Z byte.
* ``O_NOFOLLOW`` does not exist; ``open_fd`` refuses a symbolic link or junction before opening,
  with the error POSIX gives (``ELOOP``). The check and the open are two steps, so it is weaker
  than the POSIX flag against a link swapped in between them.
* ``O_NONBLOCK`` has no meaning for a regular file and is dropped. ``O_CLOEXEC`` becomes
  ``O_NOINHERIT``.
* ``pread`` is a seek and a read under a lock, because Windows has no positional read on a
  descriptor.
* There are no numeric user ids or permission bits: ``os.stat`` reports uid 0 and synthetic mode
  bits. ``current_uid`` is 0 to match, and ``group_or_other_access`` is 0 because access is set
  by the folder's access-control list (private to the user under their profile by default), not
  by mode bits.
* A directory cannot be opened as a descriptor, so ``sync_directory`` only checks that the path
  is a real directory.
* ``st_ctime`` is the creation time when a file is examined by path and the change time when it
  is examined by descriptor. ``change_time_ns`` is the creation time on Windows, which both give.
"""

from __future__ import annotations

import errno
import os
import stat
import threading

if os.name == "nt":
    O_NOFOLLOW = 1 << 28           # not a Windows flag: handled and removed by open_fd
    O_DIRECTORY = 1 << 29          # likewise; a directory cannot be opened here
    O_NONBLOCK = 0
    O_CLOEXEC = os.O_NOINHERIT
    _PREAD_LOCK = threading.Lock()

    def _is_link(path) -> bool:
        return os.path.islink(path) or os.path.isjunction(path)

    def open_fd(path, flags, mode=0o777):
        """``os.open`` for a file, in binary mode, honouring ``O_NOFOLLOW``."""
        if flags & O_DIRECTORY:
            raise PermissionError(errno.EACCES, "a directory cannot be opened as a descriptor on Windows", str(path))
        if flags & O_NOFOLLOW and _is_link(path):
            raise OSError(errno.ELOOP, "refusing to follow a link", str(path))
        return os.open(path, (flags & ~O_NOFOLLOW) | os.O_BINARY, mode)

    def pread(descriptor, length, offset):
        """``length`` bytes at ``offset`` (fewer at end of file)."""
        with _PREAD_LOCK:
            os.lseek(descriptor, offset, os.SEEK_SET)
            return os.read(descriptor, length)

    def current_uid() -> int:
        return 0

    def group_or_other_access(info) -> int:
        return 0

    def change_time_ns(info) -> int:
        # Python on Windows fills st_ctime with the creation time for a path and with the change
        # time for a descriptor, so the two never compare. The creation time is the same from
        # both, and a replaced file has a new one; an edit in place shows in size and mtime.
        return info.st_birthtime_ns

    def sync_directory(path) -> None:
        info = os.lstat(path)
        if not stat.S_ISDIR(info.st_mode) or _is_link(path):
            raise NotADirectoryError(errno.ENOTDIR, "not a real directory", str(path))

    def unlinked_spool(directory, prefix):
        """A new nameless file in ``directory``: ``(writer descriptor, read-only descriptor)``.

        Windows refuses to delete a file that is open unless every handle allowed it when it was
        opened, which ``os.open`` never does. So both handles come from ``CreateFileW`` with
        delete sharing, and a third handle removes the name with a POSIX-semantics delete (NTFS,
        Windows 10 1607 and later): the name goes when that handle closes, here, and the data
        lives until the last other handle or mapping closes.
        """
        import ctypes
        import msvcrt
        import secrets
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateFileW.restype = wintypes.HANDLE
        kernel32.CreateFileW.argtypes = (wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                         wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE)
        kernel32.SetFileInformationByHandle.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                        wintypes.DWORD)
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        invalid = wintypes.HANDLE(-1).value
        read, write, delete = 1 << 31, 1 << 30, 1 << 16          # GENERIC_READ, GENERIC_WRITE, DELETE
        share_all = 1 | 2 | 4                                    # read, write, delete
        create_new, open_existing, temporary = 1, 3, 1 << 8      # FILE_ATTRIBUTE_TEMPORARY
        disposition_ex = 21                                      # FileDispositionInfoEx
        posix_delete = ctypes.c_ulong(1 | 2)                     # DELETE | POSIX_SEMANTICS

        def fail(what):
            code = ctypes.get_last_error()
            return OSError(errno.EIO, f"{what}: {ctypes.FormatError(code).strip()}", str(directory))

        for _ in range(100):
            name = os.path.join(os.fspath(directory), prefix + secrets.token_hex(8))
            writer = kernel32.CreateFileW(name, read | write, share_all, None, create_new, temporary, None)
            if writer != invalid:
                break
            if ctypes.get_last_error() != 80:                    # ERROR_FILE_EXISTS: try another name
                raise fail("cannot create the spool file")
        else:
            raise FileExistsError(errno.EEXIST, "no free spool file name", str(directory))
        reader = remover = invalid
        named = True
        try:
            reader = kernel32.CreateFileW(name, read, share_all, None, open_existing, 0, None)
            if reader == invalid:
                raise fail("cannot reopen the spool file")
            remover = kernel32.CreateFileW(name, delete, share_all, None, open_existing, 0, None)
            if remover == invalid or not kernel32.SetFileInformationByHandle(
                    remover, disposition_ex, ctypes.byref(posix_delete), ctypes.sizeof(posix_delete)):
                raise fail("cannot remove the spool file's name")
            kernel32.CloseHandle(remover)                    # the name is gone from here on
            remover = invalid
            named = False
            writer_fd = msvcrt.open_osfhandle(writer, os.O_BINARY | os.O_NOINHERIT)
            writer = invalid
            try:
                reader_fd = msvcrt.open_osfhandle(reader, os.O_RDONLY | os.O_BINARY | os.O_NOINHERIT)
            except BaseException:
                os.close(writer_fd)
                raise
            reader = invalid
            return writer_fd, reader_fd
        finally:
            for handle in (writer, reader, remover):
                if handle != invalid:
                    kernel32.CloseHandle(handle)
            if named:                                        # failed before the name was removed
                try:
                    os.unlink(name)
                except OSError:
                    pass

else:
    O_NOFOLLOW = os.O_NOFOLLOW
    O_DIRECTORY = os.O_DIRECTORY
    O_NONBLOCK = os.O_NONBLOCK
    O_CLOEXEC = os.O_CLOEXEC

    def open_fd(*args, **kwargs):
        return os.open(*args, **kwargs)

    def pread(*args, **kwargs):
        return os.pread(*args, **kwargs)

    def current_uid() -> int:
        return os.getuid()

    def group_or_other_access(info) -> int:
        """The permission bits that let anyone but the owner in (0 when the entry is private)."""
        return info.st_mode & 0o077

    def change_time_ns(info) -> int:
        """The time a file's contents or metadata last changed, for comparing two stat results."""
        return info.st_ctime_ns

    def sync_directory(path) -> None:
        """Flush a directory's entries to disk; refuses a link."""
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    def unlinked_spool(directory, prefix):
        """A new nameless file in ``directory``: ``(writer descriptor, read-only descriptor)``.

        The file is unlinked before anything is written, so an interrupted writer cannot leave
        an orphan. The read-only descriptor stays valid after the writer is closed.
        """
        import tempfile

        writer, name = tempfile.mkstemp(prefix=prefix, dir=directory)
        try:
            reader = os.open(name, os.O_RDONLY | os.O_NOFOLLOW)
        except BaseException:
            os.close(writer)
            os.unlink(name)
            raise
        try:
            os.unlink(name)
        except BaseException:
            os.close(writer)
            os.close(reader)
            raise
        return writer, reader
