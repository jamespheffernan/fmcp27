"""Match data for the snapshot: every stored result, its events, the archived statistics frames,
the retained full-detail event streams and the per-competition season statistics.

Tables (lazy; see docs/fmdb/MATCH.md for each table's invalidation rule):

* `match`                one row per FIXTURE_RESULT the fixture manager holds (save-wide)
* `match_event`          result goal/penalty vectors, plus appearances, substitutions and
                         dismissals from the statistics frames
* `match_team_stats`     per side, from the archived MATCH_STATS frames
* `match_player_stats`   per player, from the archived frames (every stored per-match counter)
* `match_shot`           retained full-detail matches: every attempt with location and xG
* `match_pass`           retained full-detail matches: every pass attempt with location
* `match_event_stream`   retained full-detail matches: every raw 56-byte engine event
* `player_season_stats`  per player, competition and season: the game's competition statistic
                         getter (labels from the game), counters by verified direct plans
* `player_season_rates`  the same getter's derived values (per 90, percentages), emulated for
                         the rows a statement reads (`season_rates.py`)
* view `team_season_stats`  per team, competition and season, aggregated from `match`

Incremental refresh. `match.idx` is a function of the match (date and home team:
`YYYYMMDD * 100000 + home team idx`; a team plays at most once a day, checked on 134,105
results), so every table computes the idx of a new result without the stored rows and a full
rebuild numbers the matches as the incremental path does. Every table is `append`: a played
result is final once stored, so a refresh after a match day decodes only the results, frames and
retained records that are new, and nothing at all while the fixture fingerprint is unchanged.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
import hashlib
import struct

from . import Column, SourceTable
from ._common import cache
from .. import match_archive as ma
from .. import match_compstats as mc

SIDE = {0: 'home', 1: 'away'}
# Event categories whose per-player counts equal a stored per-match counter on every one of 652
# players in 23 retained matches (docs/fmdb/MATCH.md); 26+27 = tackles attempted, 28+29 aerials.
CATEGORY_NAMES = {1: 'goal', 12: 'cross completed', 20: 'yellow card', 26: 'tackle won', 27: 'tackle lost',
                  28: 'aerial duel won', 29: 'aerial duel lost', 34: 'dribble', 37: 'save held',
                  38: 'save parried', 39: 'save tipped', 49: 'own goal marker', 52: 'possession won',
                  53: 'possession lost'}
MATCH_NOTE = ('FIXTURE_RESULT records (vtable 0x5672E00) in the fixture manager year buckets, decoded '
              'by the hand-built fixtures.record and the result getters; frames from MATCH_STATS_MANAGER '
              'banks decoded by the hand-built MATCH_STATS60/FIXTURE31 wire readers')
TEAM_SPAN = 100_000             # match.idx = YYYYMMDD * TEAM_SPAN + home team idx (66,021 teams)
TAIL_DAYS = 7                   # results this recent are decoded again on a refresh (late frames)
DETAIL_RANK = {'result': 0, 'result_and_goals': 1, 'statistics': 2, 'full_events': 3}
LAYOUT = 'match-idx-v2'         # match.idx from date and home team (earlier: row number of one pass)


def match_idx(date_iso: str, home_team_idx) -> int:
    """The stable match identity: the date and the home team (TEAM_SPAN - 1 when unresolved)."""
    team = home_team_idx if home_team_idx is not None and 0 <= home_team_idx < TEAM_SPAN - 1 else TEAM_SPAN - 1
    return int(date_iso.replace('-', '')) * TEAM_SPAN + team


def idx_date(idx: int) -> str:
    d = idx // TEAM_SPAN
    return f'{d // 10000:04d}-{d // 100 % 100:02d}-{d % 100:02d}'


def idx_floor(date_iso: str) -> int:
    return match_idx(date_iso, 0)


def days_before(date_iso: str, days: int) -> str:
    return (date.fromisoformat(date_iso) - timedelta(days=days)).isoformat()


class _Collector:
    """The match data of one refresh pass, read lazily per match and shared by every table of
    this module (cached on the engine for one `refresh_tables` call)."""

    def __init__(self, engine):
        self.engine = engine
        self._addresses = None
        self._index = None
        self._by_key = None
        self.duplicates = 0
        self._rows = {}             # idx -> decoded result row
        self._events = {}           # idx -> (state, events)
        self._banks = None
        self._frames = {}           # entry (bank, key, offset, length) -> (rank, header, totals, players) | error
        self._bound = {}            # idx -> entry
        self._scanned = set()       # idx whose frame was looked for
        self._retained = None
        self.unbound_frames = 0

    # ------------------------------------------------------------------ results
    def addresses(self):
        """(year, day, group, slot, record pointer) of every resident result (about 1.2 s)."""
        if self._addresses is None:
            self._addresses = ma.result_addresses(self.engine)[0]
        return self._addresses

    def result_fingerprint(self) -> str:
        """Hash of the resident results' record pointers and buckets: it changes when a result
        is added (a match played) or a year is paged in or out, and not when an unplayed
        fixture record is replaced or moved (which changes the fixture fingerprint)."""
        from . import digest
        return digest(*(f'{y}/{d}/{g}/{s}/{a}' for y, d, g, s, a in self.addresses()))

    def index(self) -> dict:
        """{idx: light index entry} of every resident result (`match_archive.result_index`),
        kept on the engine while the result fingerprint is unchanged (the refresh of each table
        referenced later in this process then costs the fingerprint, 0.6 s, not 2.5 s)."""
        if self._index is None:
            try:
                rfp = self.result_fingerprint()
            except Exception:  # noqa: BLE001
                rfp = None
            memo = self.engine.__dict__.get('_fmdb_match_index')
            if rfp is not None and memo is not None and memo[0] == rfp:
                self._index, self.duplicates = memo[1], memo[2]
                return self._index
            out = {}
            for e in ma.result_index(self.engine, self.addresses()):
                i = match_idx(e['date'], e['home_team_idx'])
                if i in out:
                    self.duplicates += 1
                    continue
                e['idx'] = i
                out[i] = e
            self._index = out
            if rfp is not None:
                self.engine.__dict__['_fmdb_match_index'] = (rfp, out, self.duplicates)
        return self._index

    def by_key(self):
        if self._by_key is None:
            by = defaultdict(list)
            for i, e in self.index().items():
                by[e['native_match_key']].append(i)
            self._by_key = by
        return self._by_key

    def results(self, idxs) -> dict:
        """{idx: decoded row} (`match_archive.results`: the hand-built record decoder)."""
        index = self.index()
        want = [i for i in dict.fromkeys(idxs) if i not in self._rows and i in index]
        if want:
            entries = [index[i] for i in want]
            rows, _ = ma.results(self.engine, addresses=[(e['year_bucket'], e['day'], e['group'], e['slot'],
                                                         e['address']) for e in entries])
            for i, r in zip(want, rows):
                if match_idx(r['date'], r['home_team_idx']) != i:
                    raise ValueError('Result identity changed during read')
                r['idx'] = i
                self._rows[i] = r
        return {i: self._rows[i] for i in idxs if i in self._rows}

    def events(self, idxs) -> dict:
        index = self.index()
        want = [i for i in dict.fromkeys(idxs) if i not in self._events and i in index]
        if want:
            got = ma.goal_events(self.engine, [index[i] for i in want])
            for pos, i in enumerate(want):
                self._events[i] = got[pos]
        return {i: self._events[i] for i in idxs if i in self._events}

    # ------------------------------------------------------------------ frames
    def banks(self):
        if self._banks is None:
            self._banks = ma.banks(self.engine)
        return self._banks

    def _decode(self, entries, level):
        rank = ma.LEVELS.index(level)
        for entry, header, totals, players, error in ma.decode_entries(self.banks(), entries, level):
            if error:
                self._frames[entry] = error
                continue
            for p in players or ():
                for k in ('raw_child_hex', 'raw_segments', 'raw_variable_suffix_hex', 'unknown_semantics'):
                    p.pop(k, None)
            self._frames[entry] = (rank, header, totals, players)

    def frames(self, idxs, level) -> dict:
        """{idx: (key, bank ordinal, header, totals, players)} for the idxs whose archived frame
        binds to them (same key and the same home and away team, unique among the results),
        decoded to `level` (`match_archive.LEVELS`)."""
        index = self.index()
        idxs = [i for i in dict.fromkeys(idxs) if i in index]
        todo = [i for i in idxs if i not in self._scanned]
        if todo:
            keys = {index[i]['native_match_key'] for i in todo}
            entries = [(b['ordinal'], k, o, n) for b in self.banks() for k, o, n in b['entries'] if k in keys]
            whole = len(todo) * 2 > len(index)          # a full build: decode once at the level wanted
            fresh = [e for e in entries if e not in self._frames]
            if fresh:
                self._decode(fresh, level if whole else 'header')
            by_key = self.by_key()
            wanted = set(todo)
            for entry in entries:                        # bank order: a later frame of a match wins
                got = self._frames.get(entry)
                if not isinstance(got, tuple):
                    continue
                teams = got[1]['teams']
                cands = [i for i in by_key.get(entry[1], ())
                         if [index[i]['home_team_idx'], index[i]['away_team_idx']] == teams]
                if len(cands) == 1 and cands[0] in wanted:
                    self._bound[cands[0]] = entry
                elif len(cands) != 1:
                    self.unbound_frames += 1
            self._scanned.update(todo)
        rank = ma.LEVELS.index(level)
        deeper = [self._bound[i] for i in idxs if i in self._bound and self._frames[self._bound[i]][0] < rank]
        if deeper:
            self._decode(deeper, level)
        out = {}
        for i in idxs:
            entry = self._bound.get(i)
            got = self._frames.get(entry) if entry else None
            if isinstance(got, tuple):
                out[i] = (entry[1], entry[0], got[1], got[2], got[3])
        return out

    # ------------------------------------------------------------------ retained
    def retained(self):
        """[(idx | None, item)] for every retained full-detail source (same date, owner team on
        either side, unique)."""
        if self._retained is None:
            index = self.index()
            by_date = defaultdict(list)
            for i, e in index.items():
                by_date[e['date']].append(i)
            out = []
            for item in ma.retained_sources(self.engine):
                cands = [i for i in by_date.get(item['date'], ())
                         if item['owner_team_id'] in (index[i]['home_team_id'], index[i]['away_team_id'])]
                out.append((cands[0] if len(cands) == 1 else None, item))
            self._retained = out
        return self._retained


def collector(engine) -> _Collector:
    c = cache(engine)
    if 'matches' not in c:
        c['matches'] = _Collector(engine)
    return c['matches']


# --------------------------------------------------------------------------- column lists
MATCH_COLUMNS = [
    Column('idx', 'INTEGER', 'match identity: YYYYMMDD * 100000 + home team idx (a team plays at most once a '
           'day); stable across refreshes and snapshots'),
    Column('date', 'TEXT', 'match date (fixture day bucket), ISO'),
    Column('kickoff_time', 'TEXT', 'stored kick-off time HH:MM'),
    Column('competition_idx', 'INTEGER', 'competition of the fixture', references='competition'),
    Column('season_code', 'INTEGER', 'stored season code of the fixture'),
    Column('stage_index', 'INTEGER', 'stored stage index of the fixture within its competition'),
    Column('home_team_idx', 'INTEGER', 'home team', references='team'),
    Column('away_team_idx', 'INTEGER', 'away team', references='team'),
    Column('stadium_idx', 'INTEGER', 'stadium', references='stadium'),
    Column('home_goals', 'INTEGER', 'home goals at the end of play (after extra time, before penalties)'),
    Column('away_goals', 'INTEGER', 'away goals at the end of play (after extra time, before penalties)'),
    Column('home_goals_normal', 'INTEGER', 'home goals in normal time (score block +0x64)'),
    Column('away_goals_normal', 'INTEGER', 'away goals in normal time'),
    Column('home_goals_extra', 'INTEGER', 'home goals after extra time; null when no extra time'),
    Column('away_goals_extra', 'INTEGER', 'away goals after extra time; null when no extra time'),
    Column('home_penalties', 'INTEGER', 'home penalty shoot-out score; null when none'),
    Column('away_penalties', 'INTEGER', 'away penalty shoot-out score; null when none'),
    Column('home_aggregate', 'INTEGER', 'home aggregate score of a two-legged tie; null when none'),
    Column('away_aggregate', 'INTEGER', 'away aggregate score of a two-legged tie; null when none'),
    Column('home_goals_half_time', 'INTEGER', 'home goals at half time, counted from the stored goal events '
           '(minute <= 45); null when the result stores no goal events and the score is not 0-0'),
    Column('away_goals_half_time', 'INTEGER', 'away goals at half time (as home_goals_half_time)'),
    Column('attendance', 'INTEGER', 'announced attendance (result +0x5c; MATCH_STATS AnnouncedAttendance)'),
    Column('away_attendance', 'INTEGER', 'away supporters (result +0x60; MATCH_STATS AwayAttendance)'),
    Column('referee_person_idx', 'INTEGER', 'referee, from the statistics frame (null without a frame)',
           references='person'),
    Column('native_match_key', 'INTEGER', 'match key (result +0x58) shared with the statistics archive; -1 none'),
    Column('goal_events_state', 'TEXT', 'present | absent (no event vector) | empty'),
    Column('detail_level', 'TEXT', 'result | result_and_goals | statistics | full_events: the deepest '
           'data stored for this match (the game later discards frames and full detail of older matches; '
           'the rows stored here stay)'),
]

PLAYER_FIELDS = [
    ('minutes', 'INTEGER', 'minutes played (stored duration, reconciled with on/off minutes)'),
    ('entry_minute', 'INTEGER', 'minute the player came on (0 for starters)'),
    ('exit_minute', 'INTEGER', 'minute the player went off or the end clock'),
    ('exit_reason', 'TEXT', 'end_clock | substituted | injury | sent_off'),
    ('started', 'INTEGER', '1 starter, 0 substitute (stored substitute-duration branch)'),
    ('rating', 'REAL', 'match rating, stored hundredths / 100 (the rating the match screens show)'),
    ('form_rating', 'REAL', 'stored form rating tenths / 10 (what the form/last-5 averages use)'),
    ('rating_gate', 'TEXT', 'qualified, or why the game withholds a rating (too few minutes)'),
    ('position', 'TEXT', 'stored match position'),
    ('goals', 'INTEGER', 'goals'), ('assists', 'INTEGER', 'assists'),
    ('yellow_cards_received', 'INTEGER', 'yellow cards'), ('red_cards_received', 'INTEGER', 'red cards'),
    ('sent_off_minute', 'INTEGER', 'stored sent-off minute (0 none)'),
    ('injury_minute', 'INTEGER', 'stored injury minute (0 none)'),
]


def registry_fields():
    reg = ma.stat_registry()
    skip = {'yellow_cards_received', 'red_cards_received', 'pressure_completion_state'}
    out = []
    for name in sorted(reg):
        if name in skip:
            continue
        unit = reg[name].get('unit') or reg[name].get('encoding') or ''
        sql = 'REAL' if ('float' in str(unit) or name in ('distance_metres', 'expected_goals', 'expected_assists')
                         or name.endswith('_percentage_computed')) else 'INTEGER'
        out.append((name, sql, f'{name.replace("_", " ")} ({unit})' if unit else name.replace('_', ' ')))
    return out


_registry_fields = registry_fields          # earlier name


# --------------------------------------------------------------------------- row builders
# Each takes the collector and the match idxs to produce (None: every resident match).
def _all(col, idxs):
    return sorted(col.index()) if idxs is None else sorted(set(idxs))


def match_rows(col, idxs=None):
    idxs = _all(col, idxs)
    rows = col.results(idxs)
    events = col.events(idxs)
    frames = col.frames(idxs, 'header')
    retained = {i for i, _ in col.retained() if i is not None}
    for i in idxs:
        r = rows.get(i)
        if r is None:
            continue
        state, evs = events.get(i, ('absent', []))
        ht = [0, 0]
        for e in evs:
            if e['kind'] in (0, 1, 2) and e['minute'] <= 45 and e['side'] in (0, 1):
                ht[e['side']] += 1
        if state != 'present' and (r['home_goals'] or r['away_goals']):
            ht = [None, None]
        frame = frames.get(i)
        detail = ('full_events' if i in retained else 'statistics' if frame else
                  'result_and_goals' if state == 'present' else 'result')
        yield (i, r['date'], r['kickoff_time'], r['competition_idx'], r['season_code'], r['stage_index'],
               r['home_team_idx'], r['away_team_idx'], r['stadium_idx'], r['home_goals'], r['away_goals'],
               r['home_goals_normal'], r['away_goals_normal'], r['home_goals_extra'], r['away_goals_extra'],
               r['home_penalties'], r['away_penalties'], r['home_aggregate'], r['away_aggregate'],
               ht[0], ht[1], r['attendance'], r['away_attendance'],
               frame[2]['official_person_idx'] if frame else None, r['native_match_key'], state, detail)


def event_rows(col, idxs=None, sources=('result_vector', 'statistics_frame')):
    idxs = _all(col, idxs)
    events = col.events(idxs) if 'result_vector' in sources else {}
    frames = col.frames(idxs, 'players') if 'statistics_frame' in sources else {}
    for i in idxs:
        for e in events.get(i, ('absent', []))[1]:
            yield (i, 'result_vector', e['seq'], e['kind'], ma.EVENT_KINDS.get(e['kind']), e['side'],
                   e['person_idx'], e['second_person_idx'] if e['second_person_idx'] >= 0 else None,
                   e['minute'], e['added_minute'])
        frame = frames.get(i)
        if not frame:
            continue
        for p in frame[4]:
            side, person = p['side_index'], p['person_index_word']
            if p.get('native_substitute_duration_flag') and p.get('native_on_minute'):
                yield (i, 'statistics_frame', None, 100, 'substitution on', side, person, None,
                       p['native_on_minute'], None)
            if p.get('native_off_minute'):
                yield (i, 'statistics_frame', None, 101, 'substitution off', side, person, None,
                       p['native_off_minute'], None)
            if p.get('native_sent_off_minute'):
                yield (i, 'statistics_frame', None, 102, 'sent off', side, person, None,
                       p['native_sent_off_minute'], None)
            if p.get('native_injury_minute'):
                yield (i, 'statistics_frame', None, 103, 'injured', side, person, None,
                       p['native_injury_minute'], None)


def team_rows(col, idxs=None):
    frames = col.frames(_all(col, idxs), 'totals')
    for i in sorted(frames):
        for t in frames[i][3]['teams']:
            yield (i, t['side_index'], t['team_index'], t['shots'], t['shots_on_target'], t['expected_goals'],
                   t['passes_attempted'], t['passes_completed'], t['corners'], t['crosses_attempted'],
                   t['crosses_completed'], t['possession_time_raw'], t['possession_share_percentage_computed'])


def player_rows(col, idxs=None, fields=None):
    fields = fields if fields is not None else registry_fields()
    frames = col.frames(_all(col, idxs), 'full')
    for i in sorted(frames):
        for p in frames[i][4]:
            src = p.get('source') or {}
            hundredths = src.get('native_rating_hundredths')
            tenths = p.get('form_rating_tenths')
            base = (i, p['side_index'], p['team_index_word'], p['person_index_word'], p['stored_player_slot'],
                    p.get('minutes'), p.get('entry_minute'), p.get('exit_minute'), p.get('exit_reason'),
                    0 if p.get('native_substitute_duration_flag') else 1,
                    hundredths / 100 if hundredths is not None and p.get('rating_gate') == 'qualified' else None,
                    tenths / 10 if tenths else None, p.get('rating_gate') or p.get('form_statistics_state'),
                    p.get('stored_match_position'), p.get('goals'), p.get('assists'),
                    p.get('yellow_cards_received'), p.get('red_cards_received'),
                    p.get('native_sent_off_minute'), p.get('native_injury_minute'))
            yield base + tuple(p.get(name) for name, _, _ in fields)


def _retained_bound(col, idxs, level):
    """[(idx, item, frame)] for retained items bound to a result with a frame (idxs: None every)."""
    pairs = [(i, item) for i, item in col.retained()
             if i is not None and 'events' in item and (idxs is None or i in idxs)]
    frames = col.frames([i for i, _ in pairs], level)
    return [(i, item, frames[i]) for i, item in pairs if i in frames]


def shot_rows(col, idxs=None):
    from ...live_retained_shots import decode_attempts
    for i, item, frame in _retained_bound(col, idxs, 'totals'):
        got = decode_attempts(item['shot_vectors'], item['events'], frame[3]['teams'],
                              pitch_geometry=item['geometry'])
        slots = {(p['side_index'], p['stored_player_slot']): p['person_index_word'] for p in frame[4]}
        for s in got['shots'] + got['own_goal_markers']:
            side = s.get('beneficiary_side_index', s.get('side_index'))
            yield (i, s['event_id'], s.get('event_side_index'), slots.get((s.get('event_side_index'), s['stored_player_slot'])),
                   s['native_category_code'], s.get('outcome') or s.get('kind'), s.get('expected_goals', s.get('native_expected_goals')),
                   s.get('body_part'), 1 if s.get('is_penalty') else 0, s['native_x'], s['native_y'],
                   s.get('distance_to_goal'), s.get('location_group'), s['native_clock_start_raw'], side)


def pass_rows(col, idxs=None):
    from .. import match_pass_decode as mpd
    for i, item, frame in _retained_bound(col, idxs, 'full'):
        players = frame[4]
        roster = {(p['side_index'], p['stored_player_slot']): p['person_index_word'] for p in players}
        rows = mpd.decode(item['events'], item.get('paths'), roster)
        # Publish a match only when every player's attempts and completions close against
        # the stored counters (as the hand-built pass readers require).
        if not all(c['ok'] for c in mpd.reconcile(rows, players)):
            continue
        for r in rows:
            yield (i, r['event_id'], r['side'], r['person_idx'], r['recipient_person_idx'], r['recipient_state'],
                   1 if r['completed'] else 0, r['outcome'], r['category'], r['won_by_person_idx'],
                   r['won_by_category'], r['displayed_minute'], r['second'], r['clock_raw'], r['linked_offset'],
                   r['x'], r['y'], r['origin_x'], r['origin_y'], r['end_x'], r['end_y'], r['end_state'],
                   r['target_x'], r['target_y'])


def stream_rows(col, skip=frozenset()):
    from ...retained_shot_outcomes import OUTCOMES
    from ..match_pass_decode import FAILURE
    for i, item in col.retained():
        if 'events' not in item or (item['list'], item['date'], item['owner_team_id']) in skip:
            continue
        ev = item['events']
        for n in range(len(ev) // 56):
            e = ev[n * 56:(n + 1) * 56]
            cat = e[42]
            label = ('pass completed' if cat == 7 else f'pass {FAILURE[cat][0]}' if cat in FAILURE
                     else OUTCOMES[cat][1] if cat in OUTCOMES else CATEGORY_NAMES.get(cat))
            x, y = struct.unpack_from('<ff', e, 24)
            yield (i, item['list'], item['date'], item['owner_team_id'], n, struct.unpack_from('<I', e, 44)[0],
                   e[40], e[39], e[41] if e[41] != 0xFF else None, cat, label, x, y,
                   struct.unpack_from('<H', e, 34)[0], e[37] + 1, e[38], e[36],
                   struct.unpack_from('<H', e, 50)[0], struct.unpack_from('<H', e, 48)[0], e.hex())


# --------------------------------------------------------------------------- incremental selection
def since_watermark(index_idxs, have, tail_days=TAIL_DAYS):
    """Matches a frame-derived table may still be missing: not in `have` (match idxs the table
    holds) and dated at most `tail_days` before the newest match it holds (every match when it
    holds none). A frame is archived when its match is played, so older matches never gain one."""
    if not have:
        return sorted(index_idxs)
    floor = idx_floor(days_before(idx_date(max(have)), tail_days))
    return sorted(i for i in index_idxs if i >= floor and i not in have)


def new_match_rows(col, stored: dict, game_date: str, tail_days=TAIL_DAYS):
    """`match` rows to add: results not stored, and results of the last `tail_days` whose detail
    level rose (a statistics frame or a retained record bound after the result was stored). A
    stored row never loses detail: the game discarding a frame later leaves it as it is."""
    floor = idx_floor(days_before(game_date, tail_days)) if game_date else None
    cands = [i for i in col.index() if i not in stored or (floor is not None and i >= floor)]
    out = []
    for row in match_rows(col, cands):
        old = stored.get(row[0])
        if old is None or DETAIL_RANK[row[-1]] > DETAIL_RANK.get(old, -1):
            out.append(row)
    return out


def new_event_rows(col, existing):
    have_rv = {m for m, s in existing if s == 'result_vector'}
    have_sf = {m for m, s in existing if s == 'statistics_frame'}
    index = col.index()
    vector = [i for i, e in index.items() if e['events_pointer'] and i not in have_rv]
    frame = since_watermark(index, have_sf)
    return (list(event_rows(col, vector, ('result_vector',)))
            + list(event_rows(col, frame, ('statistics_frame',))))


def _fingerprint_gate(engine, table, fingerprint):
    """(proceed, record). Two stages, cheapest first: the fixture fingerprint (bucket vectors of
    the main and linked years; it also moves when an unplayed fixture record is replaced or the
    calendar is touched), then the result fingerprint (the pointers of the resident results
    only). proceed is False when `table` was brought up to date in this process at either value:
    no result was added since, so nothing can be new."""
    seen = engine.__dict__.setdefault('_fmdb_match_seen', {})
    mine = seen.get(table) or {}
    try:
        fp = fingerprint()
    except Exception:  # noqa: BLE001 - no fixture fingerprint: go to the result fingerprint
        fp = None
    if fp is not None and mine.get('fixture') == fp:
        return False, lambda: None
    try:
        rfp = collector(engine).result_fingerprint()
    except Exception:  # noqa: BLE001
        rfp = None
    if rfp is not None and mine.get('result') == rfp:
        seen[table] = {'fixture': fp, 'result': rfp}          # the fixture moved, the results did not
        return False, lambda: None
    return True, lambda: seen.__setitem__(table, {'fixture': fp, 'result': rfp})


def gated(engine, table, fingerprint, fn):
    """new_rows(existing) that does nothing while no result was added (`_fingerprint_gate`)."""
    def run(existing):
        proceed, record = _fingerprint_gate(engine, table, fingerprint)
        if not proceed:
            return []
        rows = list(fn(existing))
        record()
        return rows
    return run


# --------------------------------------------------------------------------- tables
def views(engine):
    """team_season_stats: aggregated from `match` on every read (no rows of its own, so it is as
    current as `match`, which is incremental)."""
    return {'team_season_stats': (
        'Per team, competition and season: played, won, drawn, lost, goals and three-points-for-a-win '
        'points, aggregated from match (results with a score; shoot-outs not counted)', TEAM_SEASON_SQL,
        {'scope': 'public'})}


TEAM_SEASON_SQL = """SELECT team_idx, competition_idx, season_code, COUNT(*) AS played, SUM(gf > ga) AS won,
 SUM(gf = ga) AS drawn, SUM(gf < ga) AS lost, SUM(gf) AS goals_for, SUM(ga) AS goals_against,
 SUM(gf) - SUM(ga) AS goal_difference, 3 * SUM(gf > ga) + SUM(gf = ga) AS points_3_1,
 SUM(home) AS home_played, SUM(1 - home) AS away_played
FROM (SELECT home_team_idx AS team_idx, competition_idx, season_code, home_goals AS gf, away_goals AS ga, 1 AS home
      FROM match WHERE home_goals IS NOT NULL
      UNION ALL
      SELECT away_team_idx, competition_idx, season_code, away_goals, home_goals, 0
      FROM match WHERE home_goals IS NOT NULL)
GROUP BY team_idx, competition_idx, season_code
ORDER BY coalesce(competition_idx, -1), coalesce(season_code, 0), coalesce(team_idx, 0)"""


def tables(engine) -> list[SourceTable]:
    """The match tables, each `append` with an identity, a `replace_key` where a stored row may
    be superseded, and `new_rows` that reads only what is new (module docstring; MATCH.md)."""
    from . import fixture_tables

    def fingerprint():
        return fixture_tables.fingerprint(engine)

    out = _tables(engine)
    by = {t.name: t for t in out}
    col = lambda: collector(engine)  # noqa: E731 - the collector of the current refresh pass

    def game_date():
        try:
            return engine.game_date()
        except Exception:  # noqa: BLE001
            return None

    rules = {
        'match': (('idx', 'detail_level'), ('idx',),
                  lambda ex: new_match_rows(col(), dict(ex), game_date())),
        'match_event': (('match_idx', 'source'), ('match_idx', 'source'), lambda ex: new_event_rows(col(), ex)),
        'match_team_stats': (('match_idx',), (),
                             lambda ex: team_rows(col(), since_watermark(col().index(), {m for (m,) in ex}))),
        'match_player_stats': (('match_idx',), (),
                               lambda ex: player_rows(col(), since_watermark(col().index(), {m for (m,) in ex}))),
        'match_shot': (('match_idx',), (),
                       lambda ex: shot_rows(col(), {i for i, _ in col().retained() if i is not None}
                                            - {m for (m,) in ex})),
        'match_pass': (('match_idx',), (),
                       lambda ex: pass_rows(col(), {i for i, _ in col().retained() if i is not None}
                                            - {m for (m,) in ex})),
        'match_event_stream': (('retained_list', 'date', 'owner_team_native_id'), (),
                               lambda ex: stream_rows(col(), skip=frozenset(ex))),
    }
    for name, (identity, replace_key, fn) in rules.items():
        t = by[name]
        t.invalidation, t.identity, t.replace_key, t.layout = 'append', identity, replace_key, LAYOUT
        t.new_rows = gated(engine, name, fingerprint, fn)
    from .. import match_season
    return out + match_season.tables(engine, fingerprint)


def _tables(engine) -> list[SourceTable]:
    col = lambda: collector(engine)  # noqa: E731
    reg = registry_fields()
    public = {'scope': 'public'}
    return [
        SourceTable('match', 'Every played fixture the game holds a result for, save-wide, with its '
                    'deepest available detail level', MATCH_COLUMNS, lambda: match_rows(col()),
                    cost_note='first build about 15 s (134,105 results, 4,771 frame headers); a match day '
                              'adds its results in about 3 s', source_note=MATCH_NOTE,
                    indexes=('date', 'competition_idx', 'home_team_idx', 'away_team_idx', 'native_match_key'),
                    manager=public),
        SourceTable('match_event', 'Goals, penalties and shoot-out kicks stored on each result (kind codes '
                    '0..5), and appearances changes from the statistics frames (codes 100..103)',
                    [Column('match_idx', 'INTEGER', 'match.idx'),
                     Column('source', 'TEXT', 'result_vector (result +0x78) | statistics_frame'),
                     Column('seq', 'INTEGER', 'order within the result vector'),
                     Column('kind', 'INTEGER', 'event kind', enum={**ma.EVENT_KINDS, 100: 'substitution on',
                            101: 'substitution off', 102: 'sent off', 103: 'injured'}),
                     Column('kind_label', 'TEXT', 'label of kind (inferred labels say so)'),
                     Column('side', 'INTEGER', '0 home, 1 away', enum=SIDE),
                     Column('person_idx', 'INTEGER', 'player', references='person'),
                     Column('second_person_idx', 'INTEGER', 'second player (assist on goals, inferred)',
                            references='person'),
                     Column('minute', 'INTEGER', 'stored minute'),
                     Column('added_minute', 'INTEGER', 'stored added-time minute')],
                    lambda: event_rows(col()), source_note=MATCH_NOTE, indexes=('match_idx', 'person_idx'),
                    manager=public),
        SourceTable('match_team_stats', 'Per-side team statistics of every match with an archived statistics frame',
                    [Column('match_idx', 'INTEGER', 'match.idx'), Column('side', 'INTEGER', 'side', enum=SIDE),
                     Column('team_idx', 'INTEGER', 'team', references='team'),
                     Column('shots', 'INTEGER', 'shots'), Column('shots_on_target', 'INTEGER', 'shots on target'),
                     Column('expected_goals', 'REAL', 'expected goals (float32)'),
                     Column('passes_attempted', 'INTEGER', 'passes attempted'),
                     Column('passes_completed', 'INTEGER', 'passes completed'), Column('corners', 'INTEGER', 'corners'),
                     Column('crosses_attempted', 'INTEGER', 'crosses attempted (sum of stored player counters)'),
                     Column('crosses_completed', 'INTEGER', 'crosses completed'),
                     Column('possession_time_raw', 'INTEGER', 'stored possession time counter (units unknown)'),
                     Column('possession_pct', 'INTEGER', 'possession share computed by the native ratio')],
                    lambda: team_rows(col()), source_note=MATCH_NOTE, indexes=('match_idx', 'team_idx'),
                    manager=public),
        SourceTable('match_player_stats', 'Every statistic the archived frames store per player per match',
                    [Column('match_idx', 'INTEGER', 'match.idx'), Column('side', 'INTEGER', 'side', enum=SIDE),
                     Column('team_idx', 'INTEGER', 'team', references='team'),
                     Column('person_idx', 'INTEGER', 'player', references='person'),
                     Column('slot', 'INTEGER', 'stored player slot (links match_shot / match_pass)')]
                    + [Column(n, t, m) for n, t, m in PLAYER_FIELDS] + [Column(n, t, m) for n, t, m in reg],
                    lambda: player_rows(col(), fields=reg),
                    cost_note='first build decodes every archived frame in full (about 18 ms a frame)',
                    source_note=MATCH_NOTE + '; per-field decoders saved_match_player_*',
                    indexes=('match_idx', 'person_idx', 'team_idx'), manager=public),
        SourceTable('match_shot', 'Every attempt of the retained full-detail matches, reconciled with the frame '
                    'team totals (shots, on target, xG)',
                    [Column('match_idx', 'INTEGER', 'match.idx'), Column('event_id', 'INTEGER', 'engine event id'),
                     Column('side', 'INTEGER', 'side of the shooter', enum=SIDE),
                     Column('person_idx', 'INTEGER', 'shooter', references='person'),
                     Column('category', 'INTEGER', 'engine end-shot category'),
                     Column('outcome', 'TEXT', 'goal | missed_target | hit_woodwork | saved | blocked | own_goal_marker'),
                     Column('expected_goals', 'REAL', 'xG of the attempt (float32)'),
                     Column('body_part', 'TEXT', 'head | feet | null (unclassified)'),
                     Column('is_penalty', 'INTEGER', '1 penalty'),
                     Column('x', 'REAL', 'native x'), Column('y', 'REAL', 'native y'),
                     Column('distance_to_goal', 'REAL', 'distance to goal from the pitch geometry'),
                     Column('location_group', 'TEXT', 'location group from the pitch geometry'),
                     Column('clock_raw', 'INTEGER', 'engine clock at the event (raw)'),
                     Column('beneficiary_side', 'INTEGER', 'side credited', enum=SIDE)],
                    lambda: shot_rows(col()), source_note='human manager retained CBE records (live_retained_shots)',
                    indexes=('match_idx',), manager=public),
        SourceTable('match_pass', 'Every pass attempt of the retained full-detail matches with what happened to '
                    'it (completed, intercepted, blocked, out of play, other), who won the ball, the displayed '
                    "minute and the ball's origin and end point; published per match only when every player's "
                    'attempts and completions close against the stored counters',
                    [Column('match_idx', 'INTEGER', 'match.idx'), Column('event_id', 'INTEGER', 'engine event id'),
                     Column('side', 'INTEGER', 'side', enum=SIDE),
                     Column('person_idx', 'INTEGER', 'passer', references='person'),
                     Column('recipient_person_idx', 'INTEGER', 'receiver of a completed pass', references='person'),
                     Column('recipient_state', 'TEXT', 'stored_linked_event_actor | not_stored_by_game (the CBE builder '
                            '0x488A5A4 writes the receiver only for completed passes; failed passes hold 0xFF)'),
                     Column('completed', 'INTEGER', '1 completed (CBE_END_PASS_COMPLETED)'),
                     Column('outcome', 'TEXT', 'completed | intercepted | blocked | out_of_play | not_completed_other '
                            '(names from the linked event and the path; see match_pass_decode)'),
                     Column('category', 'INTEGER', 'engine category 6..11 (0x48930AC of the engine outcome)'),
                     Column('won_by_person_idx', 'INTEGER', 'opponent who won the ball: actor of the linked '
                            'possession-won (intercepted) or block (blocked) event', references='person'),
                     Column('won_by_category', 'INTEGER', 'category of that event (52 possession won, 25 block)'),
                     Column('displayed_minute', 'INTEGER', 'match minute as displayed (elapsed whole minute + 1)'),
                     Column('second', 'INTEGER', 'second within the elapsed minute'),
                     Column('clock_raw', 'INTEGER', 'engine time of the pass (+0x22)'),
                     Column('linked_offset', 'INTEGER', 'engine time to the linked event (+0x24)'),
                     Column('x', 'REAL', 'native x of the pass event'), Column('y', 'REAL', 'native y of the pass event'),
                     Column('origin_x', 'REAL', 'first path sample (equals the pass location)'),
                     Column('origin_y', 'REAL', 'first path sample'),
                     Column('end_x', 'REAL', 'last path sample'), Column('end_y', 'REAL', 'last path sample'),
                     Column('end_state', 'TEXT', 'linked_event_location (where the ball was received, won or '
                            'blocked) | engine_target_point | outside_pitch_sample | unlinked_end_sample'),
                     Column('target_x', 'REAL', 'intended target point x (engine pass event +0x10); stored only for '
                            'not_completed_other passes, discarded by the game for the others'),
                     Column('target_y', 'REAL', 'intended target point y (engine pass event +0x14)')],
                    lambda: pass_rows(col()), source_note='human manager retained CBE records (match_pass_decode)',
                    indexes=('match_idx', 'person_idx', 'won_by_person_idx'), manager=public),
        SourceTable('match_event_stream', 'Raw engine event stream (56-byte records) of every retained full-detail match',
                    [Column('match_idx', 'INTEGER', 'match.idx (null when no result matches the date/owner)'),
                     Column('retained_list', 'TEXT', 'own_team | opponent | other (human +0x188/+0x170/+0x1A0)'),
                     Column('date', 'TEXT', 'date of the retained record'),
                     Column('owner_team_native_id', 'INTEGER', 'team native id the record is filed under'),
                     Column('seq', 'INTEGER', 'record order'), Column('event_id', 'INTEGER', 'engine event id (+44)'),
                     Column('side', 'INTEGER', 'actor side (+40)'), Column('slot', 'INTEGER', 'actor player slot (+39)'),
                     Column('second_slot', 'INTEGER', 'linked event actor slot (+41; receiver of completed passes; null 0xFF)'),
                     Column('category', 'INTEGER', 'engine category (+42)'),
                     Column('category_label', 'TEXT', 'label: CBE_* names, pass outcomes, and categories '
                            'identified by the stored player counters (CATEGORY_NAMES), else null'),
                     Column('x', 'REAL', 'native x (+24)'), Column('y', 'REAL', 'native y (+28)'),
                     Column('clock_start_raw', 'INTEGER', 'engine time (+34)'),
                     Column('displayed_minute', 'INTEGER', 'match minute as displayed (+37 elapsed minute + 1)'),
                     Column('second', 'INTEGER', 'second within the elapsed minute (+38)'),
                     Column('linked_offset', 'INTEGER', 'engine time to the linked event (+36)'),
                     Column('clock_end_raw', 'INTEGER', '+50'),
                     Column('flags', 'INTEGER', '+48'), Column('raw_hex', 'TEXT', 'the 56 bytes')],
                    lambda: stream_rows(col()), source_note='human manager retained CBE records',
                    indexes=('match_idx',), manager={'scope': 'never'}),
    ]
