"""Exclusive file locks that block until granted, on macOS, Linux and Windows.

POSIX uses ``flock``. Windows has no ``fcntl``; there the first byte of the file is locked with
``msvcrt.locking``, which gives the same mutual exclusion between processes for a file that is
used only as a lock. Closing the descriptor releases the lock on every system.
"""

from __future__ import annotations

import os
import sys
import time

if sys.platform == "win32":
    import msvcrt

    def lock_exclusive(file) -> None:
        """Block until this process holds the lock on `file` (a descriptor or a file object)."""
        descriptor = file if isinstance(file, int) else file.fileno()
        while True:
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                time.sleep(0.05)

    def unlock(file) -> None:
        descriptor = file if isinstance(file, int) else file.fileno()
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def lock_exclusive(file) -> None:
        """Block until this process holds the lock on `file` (a descriptor or a file object)."""
        fcntl.flock(file, fcntl.LOCK_EX)

    def unlock(file) -> None:
        fcntl.flock(file, fcntl.LOCK_UN)
