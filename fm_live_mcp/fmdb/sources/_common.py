"""Shared helpers for collection sources: live tables, pointer -> idx maps, bulk reads and
propertied-getter reads through verified direct plans (the snapshot's own plan machinery).

Caches live on the engine for one build (`sources.reset_cache` clears them)."""
from __future__ import annotations

import struct
import time

from .. import bulkplans, snapshot
from ..bulkplans import Missing, Ref


def cache(engine) -> dict:
    return engine.__dict__.setdefault('_collection_cache', {})


def live(engine, kind):
    """LiveTable of a DATABASE_TABLE kind ('people', 'clubs', 'teams', 'competitions', ...), shared
    with the snapshot build when it runs inside one."""
    pre = getattr(engine, '_collection_live', None)
    if pre and kind in pre:
        return pre[kind]
    store = engine.__dict__.setdefault('_collection_live_cache', {})
    if kind not in store:
        store[kind] = snapshot.enumerate_table(engine, kind)
    return store[kind]


def index_of(engine, kind) -> dict:
    """{record pointer: idx} for a live table."""
    key = ('index', kind)
    c = cache(engine)
    if key not in c:
        c[key] = {p: i for i, p in enumerate(live(engine, kind).pointers) if p}
    return c[key]


def uid_index(engine, kind) -> dict:
    return live(engine, kind).uid_index()


def u64s(engine, addresses) -> list[int]:
    """One 8-byte little-endian value per address (0 when unreadable)."""
    return [struct.unpack('<Q', raw)[0] if raw else 0 for raw in blobs(engine, [(a, 8) for a in addresses])]


def _valid(address) -> bool:
    return 4096 <= address < (1 << 48)


def blobs(engine, requests) -> list:
    """read_many that answers None for null or out-of-range addresses instead of raising."""
    requests = list(requests)
    good = [(a, n) for a, n in requests if _valid(a) and 0 < n <= (1 << 24)]
    got = iter(engine.read_many(good) if good else [])
    return [next(got) if _valid(a) and 0 < n <= (1 << 24) else None for a, n in requests]


def team_clubs(engine) -> dict:
    """{team pointer: club idx} through team +0x30 (the club pointer `tables.managed` and the
    snapshot's team.parent_club_idx read), kept only for live CLUB table entries."""
    c = cache(engine)
    if 'team_clubs' not in c:
        teams = [p for p in live(engine, 'teams').pointers if p]
        clubs = index_of(engine, 'clubs')
        c['team_clubs'] = {t: clubs.get(p) for t, p in zip(teams, u64s(engine, [t + 0x30 for t in teams]))}
    return c['team_clubs']


def packed_date(value: int) -> str | None:
    """ISO date of a packed game date (year << 16 | day of year in the low nine bits), else None."""
    from datetime import date, timedelta
    year, day = value >> 16, value & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        return None
    d = date(year, 1, 1) + timedelta(days=day - 1)
    return d.isoformat() if d.year == year else None


def sql_value(v, resolve=None):
    """A canonical getter value as an SQL value: Missing -> None, bool -> int, Ref -> resolve(ref)."""
    if isinstance(v, Missing):
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, Ref):
        return resolve(v) if resolve else None
    return v


def ref_resolver(engine, kind):
    """Ref -> idx in the live table `kind` (by unique id; the random id must agree when present)."""
    tbl = live(engine, kind)
    index = tbl.uid_index()

    def resolve(ref):
        i = index.get(ref.unique_id)
        if i is None:
            return None
        if ref.random_id and tbl.rids[i] and tbl.rids[i] != ref.random_id:
            return None
        return i
    return resolve


# --------------------------------------------------------------------------- propertied getters
def store(engine):
    c = cache(engine)
    if 'plan_store' not in c:
        c['plan_store'] = snapshot.plan_store(engine)
    return c['plan_store']


def plans_missing(engine, cls, codes) -> list[str]:
    return store(engine).missing(cls, list(codes))


def derive_plans(engine, cls, pointers, codes, names, log=None) -> dict:
    """Trace, derive and verify direct plans for (cls, codes) on these records (cached)."""
    return snapshot.derive_class_plans(engine, store(engine), cls, list(pointers), sorted(codes), names, log)


def getter_values(engine, cls, pointers, codes, *, budget_s=None) -> tuple[dict, dict]:
    """({code: [canonical value per pointer]}, {code: route}) for one record class.

    Codes with a verified direct plan are read in bulk; the others are emulated record by record
    through the class's own property getter (vtable slot 3)."""
    pointers = list(pointers)
    out, route = {}, {}
    st = store(engine)
    direct = {}
    for code in codes:
        plan = st.get(cls, code) if len(pointers) > 0 else None
        if plan and plan.get('status') == 'direct':
            direct[code] = plan
    if direct and pointers:
        got = bulkplans.evaluate(engine.read_many, pointers, direct)
        for code in direct:
            out[code] = got[code]
            route[code] = f'direct plan verified against the {cls} getter ({direct[code].get("verified", "?")} records)'
    started = time.time()
    for code in codes:
        if code in out:
            continue
        values = []
        for start in range(0, len(pointers), 2000):
            chunk = pointers[start:start + 2000]
            engine.prefetch(chunk, before=0, after=0x200)
            values += [bulkplans.canonical(engine.get_property(p, code)) for p in chunk]
            if budget_s is not None and time.time() - started > budget_s:
                raise TimeoutError(f'emulating {code} for {len(pointers)} {cls} records exceeded {budget_s}s')
        out[code] = values
        route[code] = f'{cls} getter emulated per record'
    return out, route
