"""Census stored COMP identities and names in bounded, rechecked batches."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp import competitions, database, players
from fm_live_mcp.bridge import Bridge


def survey():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    rows, errors = [], []
    start, identity = 0, None
    try:
        while True:
            with bridge.lock, bridge._read_scope(sid):
                process = bridge._current(sid)
                tables = bridge._player_layout(process)
                base = tables[0] - players.RVA[0]
                snapshot, save, _ = bridge._world_state(process, tables)
                info = database.table(snapshot, base, 'competitions')
                if identity is not None:
                    assert info['identity'] == identity, 'Competition table changed between batches'
                identity = info['identity']
                end = min(start + 250, info['count'])
                batch, rejected, context_cache = [], [], {}
                for index in range(start, end):
                    try:
                        batch.append(competitions.by_index(snapshot, base, index, include_context=True, context_cache=context_cache))
                    except ValueError as exc:
                        rejected.append({'database_index': index, 'error': str(exc)})
                snapshot.verify()
            rows.extend(batch)
            errors.extend(rejected)
            start = end
            print(f'Checked {start}/{info["count"]}: {len(errors)} rejected', flush=True)
            if end == info['count']:
                break
        assert len(rows) + len(errors) == info['count']
        result = {
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'complete_native_table_scan': True,
            'save': bridge._public_save(save),
            'total_competition_records': info['count'],
            'decoded': len(rows), 'errors': errors, 'competitions': rows,
            'missing_names': {field: sum(row[field] is None for row in rows)
                              for field in ('name', 'short_name', 'abbreviation')},
            'empty_names': {field: sum(row[field] == '' for row in rows)
                            for field in ('name', 'short_name', 'abbreviation')},
            'foreground_ui_used': False,
        }
        (ROOT / 'evidence/competition-survey.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps({key: value for key, value in result.items() if key not in ('competitions', 'save')}))
    finally:
        bridge.detach()


if __name__ == '__main__':
    survey()
