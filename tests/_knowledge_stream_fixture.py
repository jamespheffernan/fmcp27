"""Owned-memory transport for private collector scope tests, never game I/O."""
import pytest

from fm_live_mcp import knowledge_native_scope


@pytest.fixture(autouse=True)
def native_stream_transport(monkeypatch):
    class OwnedStream:
        def __init__(self,helper,pid):
            assert helper=='synthetic' and pid==12345
            self.pid=pid
            self.closed=False

        def close(self):
            self.closed=True

    monkeypatch.setattr(knowledge_native_scope,'ReadStream',OwnedStream)
