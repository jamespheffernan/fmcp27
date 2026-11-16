"""Compare the same live roster through one-shot and query-scoped readers."""
from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from fm_live_mcp.bridge import Bridge


def verify():
    bridge = Bridge()
    session = bridge.attach()['session_id']
    evidence = {'observed_at': datetime.now(timezone.utc).isoformat(), 'runs': {}}
    scope = bridge._read_scope
    records = {}
    try:
        for mode in ('one_shot', 'query_scoped'):
            bridge._read_scope = (lambda session: nullcontext()) if mode == 'one_shot' else scope
            started = time.monotonic()
            roster = bridge.get_managed_squad(session, include_clubs=True)
            seconds = time.monotonic() - started
            records[mode] = {'save': roster['save'], 'club': roster['club'],
                             'players': [{k: v for k, v in p.items() if k != 'player_ref'}
                                         for p in roster['players']]}
            digest = hashlib.sha256(json.dumps(records[mode], sort_keys=True).encode()).hexdigest()
            evidence['runs'][mode] = {'seconds': seconds, 'count': roster['count'], 'sha256': digest}
            print(f'{mode}: {roster["count"]} players in {seconds:.3f}s', flush=True)
        assert records['one_shot'] == records['query_scoped'], 'Live records changed between transport checks'
        assert bridge._reader is None
        evidence['verified'] = True
        evidence['speedup'] = evidence['runs']['one_shot']['seconds'] / evidence['runs']['query_scoped']['seconds']
    finally:
        bridge.detach()
        destination = Path(__file__).resolve().parents[1] / 'evidence/live-read-transport.json'
        destination.write_text(json.dumps(evidence, indent=2) + '\n')
        print(destination)


if __name__ == '__main__':
    verify()
