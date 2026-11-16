"""Compare full native club/staff traversals across pagination strategies."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fm_live_mcp.bridge import Bridge


def main():
    bridge = Bridge()
    sid = bridge.attach()['session_id']
    receipt = {'observed_at': datetime.now(timezone.utc).isoformat(), 'verified': False, 'searches': []}
    try:
        for method, name, key, total_key in (
            ('find_clubs', 'United', 'clubs', 'total_club_records'),
            ('find_staff', 'Lenny Grün', 'staff', 'total_person_records'),
        ):
            runs = []
            for limit, budget in ((100, 200000), (5, 5000)):
                cursor, rows, scanned, pages, unavailable = None, [], 0, 0, 0
                while True:
                    page = getattr(bridge, method)(sid, name, max_matches=limit, record_budget=budget, cursor=cursor)
                    rows.extend({k: v for k, v in row.items() if not k.endswith('_ref')} for row in page[key])
                    scanned += page['scanned_records']
                    unavailable += page.get('unavailable_name_records', 0)
                    pages += 1
                    assert pages < 1000 and page['scanned_records'] > 0
                    cursor = page['next_cursor']
                    if cursor is None:
                        assert page['stop_reason'] == 'table_end' and scanned == page[total_key]
                        break
                runs.append({'rows': rows, 'scanned_records': scanned, 'pages': pages, 'unavailable_names': unavailable})
            assert runs[0]['rows'] == runs[1]['rows'] and runs[0]['rows']
            assert runs[0]['unavailable_names'] == runs[1]['unavailable_names']
            receipt['searches'].append({'method': method, 'name': name, 'count': len(runs[0]['rows']),
                'scanned_records': runs[0]['scanned_records'], 'pages': [run['pages'] for run in runs],
                'unavailable_names': runs[0]['unavailable_names']})
            if key == 'staff':
                assert any(row['name'] == name for row in runs[0]['rows'])
                for row in page[key]:
                    assert bridge.get_staff(sid, row['staff_ref'])['staff']['name'] == row['name']
        receipt['verified'] = True
    finally:
        bridge.detach()
        (ROOT/'evidence/live-reader-searches.json').write_text(json.dumps(receipt, indent=2)+'\n')
    print(json.dumps(receipt, indent=2))


if __name__ == '__main__':
    main()
