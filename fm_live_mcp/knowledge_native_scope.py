"""Private collector stream; final callbacks/fences belong inside its body."""
from contextlib import contextmanager

from .reader import ReadStream


@contextmanager
def collection_stream(bridge, session):
    process=bridge._current(session)
    if bridge._reader is not None:
        raise ValueError('Nested private native stream rejected')
    reader=bridge._reader=ReadStream(bridge.helper,process.pid)
    try:
        yield
    finally:
        # Never call _current after the collector's last physical fence.
        bridge._reader=None
        reader.close()
