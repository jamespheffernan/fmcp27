"""What happened to every pass of a retained full-detail match, read from the CBE event records
with the game's CBE builder (0x488A5A4) and category function (0x48930AC) as the map.

CBE record (56 bytes) as the builder writes it from an engine event E:
  +0x00 vector<(f32 x, f32 y)> path samples      +0x18 f32 x, +0x1C f32 y  E location
  +0x22 u16 E time (E+0x44)                      +0x24 u8  linked event time - E time
  +0x25 u8  E+0x6C, +0x26 u8 E+0x6D              +0x27 u8  actor slot (E+0x6B)
  +0x28 u8  side (E+0x6A)                        +0x29 u8  linked event actor slot, else 0xFF
  +0x2A u8  category 0x48930AC(E kind, E outcome) +0x2C u32 event id   +0x30 u16 flags

Proven from the builder code:
* +0x29 is written 0xFF at 0x488A67C and replaced by the linked event's actor (0x488AD08) only
  on the branch at 0x488AB54..0x488AB68: category 7 (completed pass) or 12, or predicate
  0x495AAEC true. A pass that is not completed therefore keeps 0xFF: the record stores no
  intended recipient (every one of the failed passes in the retained matches holds 0xFF).
* +0x24 is the time from E to the event E links to (E+0x30); 0 when E has no link or the
  linked event falls in the same time unit.
* Pass categories (0x488A688..0x488A748): the builder walks the pass's linked engine events
  (+0x30) and takes the first with kind <= 0x1D. Kind 9 or 14 (possession won) gives outcome 8,
  kinds 1/2 (block, clearance) outcome 6, kinds 18-20 (goalkeeper saves) outcome 5, any other
  kind outcome 0; with no link it uses the pass's own outcome (+0x69). 0x48930AC maps the outcome
  through [7,10,10,11,6,10,9,10,8] (other values give 10).
* The engine pass event holds the intended target point at +0x10/+0x14 from the moment it is
  created (sampled live in West Ham v Newcastle, 13 Dec 2030: set at creation and unchanged on all
  270 pass events; within 2 units of the reception point on 186 of 233 completed passes).
  The builder copies it into the path only for category 10 (0x488AF2C); every other category's
  path ends at the linked event, and the target point is discarded. The engine pass event holds
  no target-player field: no byte of the first 0x100 bytes, nor of the objects it points to,
  equals the receiver slot on the completed passes captured live.

Read from the stored records with the game's own counters as the check (docs/fmdb/MATCH.md):
* the path starts at the pass event's own location (every one of 23,881 passes in 23 matches)
  and, when the linked event was converted, ends exactly at that event's location (1,142 of 1,188
  intercepted, 91 of 96 blocked, 4,105 completed passes): origin and destination of the ball.
* the linked event of category 8 is always an opposing possession-won event (category 52, the
  events that make up each player's stored possession_won counter on 652 of 652 players);
  category 9 links to an opposing category 25 + 54 pair (25 sits beside the blocked-shot
  category 5 in the same way), and category 11 ends outside the pitch on every pass.
* +0x25 is the elapsed whole minute: +1 equals the stored goal minute (minute + added) on 60 of
  62 goals in the 23 matches, the other two differ by one; +0x26 is the second.

Flags (+0x30), from the builder and the event post-processor 0x48D8F48..0x48D9494, checked on the
captured matches (Lille v Newcastle 6 Nov 2030, Newcastle v Southampton 2 Nov 2030, Manchester
City v Newcastle 23 Nov 2030 and 16 fragments of a 13 Dec 2030 memory capture):
* 0x008 throw-in. The builder copies engine flag bit 5 (0x488ABD4 -> 0x488AF34) and the statistics
  writer skips the event, so a throw-in is not a counted pass attempt. All 143 flagged events
  start on the touchline (|x| 34.11..35.50, the half width); of 5,571 unflagged passes 5 start
  beyond |x| 33.9.
* 0x040 corner. Engine flag bit 3 on any kind but 21 (0x488ABB4 -> 0x488B0E4). 71 of 72 flagged
  events start at a corner flag; the other is a completed pass elsewhere.
* 0x010 / 0x020 free kick. Engine flag bit 4, without / with bit 6 (0x488ABC0 -> 0x488B054). In
  Lille v Newcastle each side's flagged events equal the fouls stored against the other side
  (10 and 8). What bit 6 separates is not named (0x020 is on short completed passes only).
* 0x002 key pass, 0x400 chance created, 0x004 assist: set afterwards on the record of the pass
  (lookup 0x4894F0C) when an engine event of kind 24, 27 or 0 arrives (0x48D91B8, 0x48D9310,
  0x48D948C); the same kinds increment the player counters +0xBC key passes, +0xA0 chances
  created and +0x9F. A marker is missing when the lookup finds no record: in Lille v Newcastle
  25 key-pass markers against 28 stored, 8 chance markers against 10 stored, and no 0x004 marker
  at all in a 2-3 match. A set marker is the game's own; an absent one proves nothing.
* 0x100 engine flag bit 7 (the attack-direction bit the pass-map readers use); 0x001 engine kind
  in the set 0x3F739E.
"""
from __future__ import annotations

import struct
from collections import Counter, defaultdict

PASS_CATEGORIES = (6, 7, 8, 9, 10, 11)
FAILURE = {
    8: ('intercepted', 'builder 0x488A6E4..0x488A728: the first linked engine event is kind 9 or 14 '
                       '(possession won, CBE 31/52) -> engine outcome 8 -> category 8'),
    9: ('blocked', 'builder 0x488A708 -> 0x488B074: the linked engine event is kind 1 (block, CBE 25) or '
                   '2 (clearance, CBE 24) -> outcome 6 -> category 9'),
    11: ('out_of_play', 'no linked event; the engine outcome 3 (table 0x48930AC) -> category 11; the path '
                        'ends outside the pitch'),
    10: ('not_completed_other', 'a goalkeeper save or claim (linked kinds 18-20 -> outcome 5, builder '
                                '0x488AF44) or, with no linked event, engine outcomes 1, 2, 5, 7 or above 8; '
                                'the path end is the engine target point (0x488AF2C reads event +0x10)'),
    6: ('not_completed_outcome_4', 'no linked event, engine outcome 4; not seen in the retained matches'),
}
WON_BY_CATEGORY = {8: 52, 9: 25}
NO_SLOT = 0xFF
MASK_EXCLUDED = 8   # flags bit the statistics writer skips (not a counted attempt): a throw-in
FLAG_KEY_PASS, FLAG_ASSIST, FLAG_THROW_IN = 0x002, 0x004, 0x008
FLAG_FREE_KICK, FLAG_FREE_KICK_BIT6, FLAG_CORNER, FLAG_CHANCE_CREATED = 0x010, 0x020, 0x040, 0x400


def pass_type(flags):
    """What the flags word says about a pass record (module docstring, Flags)."""
    restart = ('throw_in' if flags & FLAG_THROW_IN else 'corner' if flags & FLAG_CORNER
               else 'free_kick' if flags & (FLAG_FREE_KICK | FLAG_FREE_KICK_BIT6) else None)
    return {'flags': flags, 'restart': restart,
            'key_pass': bool(flags & FLAG_KEY_PASS), 'chance_created': bool(flags & FLAG_CHANCE_CREATED),
            'assist_marked': bool(flags & FLAG_ASSIST)}


def records(event_bytes):
    return [event_bytes[i:i + 56] for i in range(0, len(event_bytes), 56)]


def clock(e):
    return struct.unpack_from('<H', e, 0x22)[0]


def decode(event_bytes, paths=None, roster=None, *, include_uncounted=False):
    """[pass row] for every counted pass attempt (flags mask 8 excluded, as the counters do).

    paths: {record index: [(x, y), ...]} from the +0x00 vectors (optional).
    roster: {(side, slot): person index} for both sides (optional).
    include_uncounted: also return the throw-ins (flags mask 8) the game's pass counters leave
    out, with counted False; every other row has counted True."""
    roster = roster or {}
    paths = paths or {}
    recs = records(event_bytes)
    by_clock = defaultdict(list)
    for n, e in enumerate(recs):
        by_clock[clock(e)].append(n)
    out = []
    for n, e in enumerate(recs):
        cat = e[0x2A]
        flags = struct.unpack_from('<H', e, 0x30)[0]
        if cat not in PASS_CATEGORIES or (flags & MASK_EXCLUDED and not include_uncounted):
            continue
        side, slot = e[0x28], e[0x27]
        # +0x24 is 0 both without a link and for a link in the same time unit, so the linked
        # event is looked up at E time + offset in every case.
        linked_time = clock(e) + e[0x24]
        linked = [m for m in by_clock.get(linked_time, ()) if m != n]
        won = None
        if cat in WON_BY_CATEGORY:
            hits = [recs[m] for m in linked if recs[m][0x28] != side and recs[m][0x2A] == WON_BY_CATEGORY[cat]]
            if len(hits) == 1:
                won = hits[0]
        pts = paths.get(n) or []
        x, y = struct.unpack_from('<ff', e, 0x18)
        end = pts[-1] if pts else None
        end_linked = bool(end) and any(struct.unpack_from('<ff', recs[m], 0x18) == end for m in linked)
        completed = cat == 7
        recipient_slot = e[0x29] if e[0x29] != NO_SLOT else None
        out.append({
            'record_index': n, 'event_id': struct.unpack_from('<I', e, 0x2C)[0],
            'side': side, 'slot': slot, 'person_idx': roster.get((side, slot)),
            'category': cat, 'completed': completed,
            'outcome': 'completed' if completed else FAILURE.get(cat, ('unknown', ''))[0],
            'outcome_evidence': None if completed else FAILURE.get(cat, (None, None))[1],
            'recipient_slot': recipient_slot,
            'recipient_person_idx': roster.get((side, recipient_slot)) if recipient_slot is not None else None,
            'recipient_state': ('stored_linked_event_actor' if recipient_slot is not None else
                                'not_stored_by_game' if not completed else 'missing'),
            'won_by_side': won[0x28] if won else None, 'won_by_slot': won[0x27] if won else None,
            'won_by_person_idx': roster.get((won[0x28], won[0x27])) if won else None,
            'won_by_category': won[0x2A] if won else None,
            'linked_offset': e[0x24], 'clock_raw': clock(e),
            'displayed_minute': e[0x25] + 1, 'second': e[0x26],
            'x': x, 'y': y,
            'origin_x': pts[0][0] if pts else None, 'origin_y': pts[0][1] if pts else None,
            'end_x': end[0] if end else None, 'end_y': end[1] if end else None,
            'end_state': ('linked_event_location' if end_linked else
                          'engine_target_point' if cat == 10 and end else
                          'outside_pitch_sample' if cat == 11 else
                          'unlinked_end_sample' if end else None),
            'target_x': end[0] if cat == 10 and end else None,
            'target_y': end[1] if cat == 10 and end else None,
            'counted': not flags & MASK_EXCLUDED, **pass_type(flags),
        })
    return out


def reconcile(rows, players):
    """Per player: attempts, completions and failures by type against the stored counters."""
    by = defaultdict(Counter)
    for r in rows:
        if r.get('counted', True):          # throw-ins are not in the game's pass counters
            by[(r['side'], r['slot'])][r['outcome']] += 1
    checks = []
    for p in players:
        key = (p['side_index'], p['stored_player_slot'])
        c = by.get(key, Counter())
        attempts, completed = sum(c.values()), c['completed']
        checks.append({'side': key[0], 'slot': key[1], 'person_idx': p.get('person_index_word'),
                       'attempts': attempts, 'completed': completed, 'failed_by_type': {k: v for k, v in c.items() if k != 'completed'},
                       'stored_attempts': p.get('passes_attempted'), 'stored_completed': p.get('passes_completed'),
                       'ok': attempts == p.get('passes_attempted') and completed == p.get('passes_completed')})
    return checks


def read_paths(engine, event_bytes):
    """{record index: [(x, y)]} for every pass record, reading the +0x00 sample vectors."""
    recs = records(event_bytes)
    want = []
    for n, e in enumerate(recs):
        if e[0x2A] in PASS_CATEGORIES:
            start, end, _cap = struct.unpack_from('<QQQ', e, 0)
            if 4096 <= start < end and (end - start) % 8 == 0 and end - start <= 8 * 4096:
                want.append((n, start, end - start))
    out = {}
    for (n, _, _), raw in zip(want, engine.read_many([(s, k) for _, s, k in want])):
        if raw:
            out[n] = list(struct.iter_unpack('<ff', raw))
    return out
