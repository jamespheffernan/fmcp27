"""Check `sources/club_finance` and the routed `club` finance columns against the hand-built finance tools on N clubs (FM27 attached, read-only).

Usage: PYTHONPATH=. python scripts/fmdb_club_finance_check.py [--clubs 50] [--json out.json]

Clubs: the managed club(s), then clubs with a full CLUB_FINANCE object spread across the table, then
clubs with a base finance object. Compared per club:
  balance                    club_finance.decode balance
  wage_budget_weekly         club_finance.decode weekly_wage_budget
  transfer_budget            club_finance.decode current_transfer_budget.amount (when decoded)
  remaining_wage_budget_weekly  club_finance.decode remaining_weekly_wage_budget.amount (when decoded)
  wage_spend_weekly          club_finance.decode remaining_weekly_wage_budget.weekly_spending_used
  scouting_budget            financial_details.club_details scouting_budget.amount (native property)
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
import struct
import sys
import time

from fm_live_mcp import club_finance, financial_details, world
from fm_live_mcp.fmdb import tables
from fm_live_mcp.fmdb.sources import club_finance as source


def pairs(src: dict, hand: dict, details: dict | None):
    yield 'balance', src['balance'], hand.get('balance')
    yield 'wage_budget_weekly', src['wage_budget_weekly'], hand.get('weekly_wage_budget')
    ctb = hand.get('current_transfer_budget') or {}
    if ctb.get('amount') is not None:
        yield 'transfer_budget', src['transfer_budget'], ctb['amount']
    rem = hand.get('remaining_weekly_wage_budget') or {}
    if rem.get('amount') is not None:
        yield 'remaining_wage_budget_weekly', src['remaining_wage_budget_weekly'], rem['amount']
    if rem.get('weekly_spending_used') is not None:
        yield 'wage_spend_weekly', src['wage_spend_weekly'], rem['weekly_spending_used']
        yield 'wage_spend_annual', src['wage_spend_annual'], rem['weekly_spending_used'] * 52
    sb = (details or {}).get('scouting_budget') or {}
    if sb.get('amount') is not None:
        yield 'scouting_budget', src['scouting_budget'], sb['amount']


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('--clubs', type=int, default=50)
    ap.add_argument('--json')
    args = ap.parse_args(argv)
    from fm_live_mcp.fmdb.engine import Engine
    engine = Engine.open()
    try:
        base, read = engine.base, engine.cached_read
        managed, _ = tables.managed(read, base)
        pointers, _ = engine.table_entries('clubs')
        full_vt = base + world.TYPES['club_finance'][0]
        full, basic = [], []
        for p in pointers[::7]:
            if not p:
                continue
            fin = struct.unpack('<Q', read(p + 0x150, 8))[0]
            if fin:
                (full if struct.unpack('<Q', read(fin, 8))[0] == full_vt else basic).append(p)
        step = max(1, len(full) // args.clubs)
        chosen = list(dict.fromkeys(managed + full[::step]))[:args.clubs - 5] + basic[:5]
        index = {p: i for i, p in enumerate(pointers)}
        names = [c.name for c in source.columns()]
        stamp = engine._bridge.plugin_identity[0]
        tally, mismatches, rows = Counter(), [], []
        started = time.time()
        src_seconds = 0.0
        for club in chosen:
            t = time.time()
            src = dict(zip(names, source.row(engine, index[club], club)))
            # the club-table columns the source points to: balance (direct), transfer and scouting budget
            # (routed Ctbu -> Ctfc and CSbR, computed on demand)
            for col, key in (('balance', 'Ccba'), ('transfer_budget', 'Ctfc'), ('scouting_budget', 'CSbR'),
                             ('corporate_facilities', 'Ccfa')):
                src[col] = source._value(engine, club, key)
            src_seconds += time.time() - t
            rs = world.ReadSet(engine.read)
            hand = club_finance.decode(rs, base, club)
            details = None
            if hand.get('state') == 'stored':
                details = financial_details.club_details(rs, base, club, stamp)
            name = engine.get_property(club, 'Cnam').value
            for field, mine, theirs in pairs(src, hand, details):
                ok = mine == theirs
                tally[(field, ok)] += 1
                if not ok:
                    mismatches.append({'club': name, 'field': field, 'source': mine, 'hand_built': theirs})
            rows.append({'club': name, 'source': src})
        print(f'{len(chosen)} clubs ({len(full)} sampled with CLUB_FINANCE, {len(basic)} base); '
              f'source rows {src_seconds:.1f}s, total {time.time() - started:.1f}s')
        for field in ('balance', 'wage_budget_weekly', 'transfer_budget', 'remaining_wage_budget_weekly',
                      'wage_spend_weekly', 'wage_spend_annual', 'scouting_budget'):
            print(f'  {field:30} equal {tally[(field, True)]:3}  different {tally[(field, False)]}')
        for m in mismatches[:20]:
            print('  MISMATCH', m)
        mine = rows[0]['source'] if managed else None
        if mine:
            print('managed club:', rows[0]['club'], {k: mine[k] for k in (
                'balance', 'wage_budget_weekly', 'wage_budget_annual', 'wage_spend_annual',
                'remaining_wage_budget_weekly', 'remaining_wage_budget_annual', 'transfer_budget', 'scouting_budget',
                'corporate_facilities')})
        if args.json:
            with open(args.json, 'w') as fh:
                json.dump({'tally': {f'{k[0]}:{k[1]}': v for k, v in tally.items()}, 'mismatches': mismatches,
                           'rows': rows}, fh, default=str)
        # Ccwt is the game layer's recomputed bill; the stored spending can lag it (documented, not a failure)
        return 1 if any(m['field'] != 'wage_spend_weekly' for m in mismatches) else 0
    finally:
        engine.close()


if __name__ == '__main__':
    sys.exit(main())
