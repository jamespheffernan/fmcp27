"""Contracts: every main, loan and trial contract in the save, with every stored clause and bonus.

Containers (hand-proven, docs/research.md and the hand-built decoders):
* main contract: pointer at PERSON - 0x98 (`world.player_clubs`, `wages`, `contract_terms`);
  a `FULL_CONTRACT` or `BASIC_CONTRACT` whose +8 is the PERSON (owner check). The slot is used
  only for PERSON classes whose contract-pointer getter (PERSON vtable slot 121 = 0xCB3724, base
  displacement -0x110) is the one the hand-built decoders verify.
* auxiliary contract: holder at PERSON - 0x90, holder +0 the current `LOAN_CONTRACT` or
  `TRIAL_CONTRACT` (`loan_contracts`, `world.player_clubs`), owner-checked the same way.

Fields come from each contract's own property getter (vtable slot 3: FULL 0x128670C, BASIC
0xD8BAB4, LOAN 0x1374874, TRIAL 0xFF5678), read through direct plans that the snapshot's plan
machinery verified against that getter on separate records, else emulated per record. Teams
are +0x10/+0x18 (research: both contract kinds), the team's club is team +0x30. Clauses and
bonuses are the FULL_CONTRACT entry vector at +0x68 (`contract_bonuses.read_entries`: int32
amount, int16 parameter, u8 kind, u8 flags), labelled by `contract_terms.KINDS` / `FIELDS`;
loan clause flags and loan fees use the `loan_contracts` layout. Amounts are in the game's base
currency (GBP; `wages.base_currency`).
"""
from __future__ import annotations

from datetime import date, timedelta
import struct

from ... import contract_bonuses, contract_terms, loan_contracts, playing_time, world
from . import Column, SourceTable
from . import _common as C

PERSON_CONTRACT_GETTER = 0xCB3724        # PERSON vtable slot 121 (contract pointer), contract_bonuses
CLASSES = {'full_contract': 'FULL_CONTRACT', 'basic_contract': 'BASIC_CONTRACT',
           'loan_contract': 'LOAN_CONTRACT', 'trial_contract': 'TRIAL_CONTRACT'}
ROLES = {'main': 'main contract (PERSON - 0x98)', 'loan': 'current loan (PERSON - 0x90 holder)',
         'trial': 'current trial (PERSON - 0x90 holder)'}
# getter keys per contract class: (code, column)
CODES = {
    'FULL_CONTRACT': ('Csda', 'Ceda', 'Cwwa', 'Csqn', 'Ctyp', 'Cjob'),
    'BASIC_CONTRACT': ('Ceda', 'Cwwa', 'Ctyp', 'Cjob'),
    'LOAN_CONTRACT': ('Csda', 'Ceda', 'Cwwa', 'Csqn', 'Ctyp', 'Cjob'),
    'TRIAL_CONTRACT': ('Csda', 'Ceda', 'Cwwa', 'Csqn', 'Ctyp', 'Cjob'),
}
CODE_NAMES = {'Csda': 'Date Last Contract Signed', 'Ceda': 'Contract Expires', 'Cwwa': 'Wage',
              'Csqn': 'Squad Number', 'Ctyp': 'Contract Type', 'Cjob': 'Job'}
LOAN_CASH = {'loan_unused_weekly_wage': 0xD4, 'loan_playing_monthly_fee': 0xCC, 'loan_unused_monthly_fee': 0xD0,
             'loan_buy_back_fee': 0xC8, 'loan_future_fee': 0xC0}
LOAN_CLAUSE_BASE = 1000                  # contract_clause.kind_code for loan clause flags: 1000 + bit
KIND_LABELS = {**{k: v for k, v in contract_terms.KINDS.items()},
               **{LOAN_CLAUSE_BASE + bit: f'loan: {name}' for name, bit in loan_contracts.CLAUSE_BITS.items()}}
VALUE_MEANING, PARAMETER_MEANING, HAS_EXPIRY = {}, {}, set()
for _kind, _name, _slot, _prop, _editor, _label in contract_terms.FIELDS:
    if _slot == 52:
        VALUE_MEANING[_kind] = f'{_name} ({_label})'
    elif _slot == 54:
        PARAMETER_MEANING[_kind] = f'{_name} ({_label})'
    elif _slot == 56:
        HAS_EXPIRY.add(_kind)
    elif _slot == 46:
        VALUE_MEANING.setdefault(_kind, f'present ({_label})')


def _verify_dispatch(engine):
    """The getter slots the hand-built decoders verify, checked once per build."""
    base = engine.base
    full = base + world.TYPES['full_contract'][0]
    loan = base + world.TYPES['loan_contract'][0]
    checks = [(full, contract_bonuses.GETTERS), (full, contract_terms.GETTERS), (loan, loan_contracts.GETTERS)]
    for vtable, getters in checks:
        for slot, getter in getters.items():
            got = C.u64s(engine, [vtable + slot * 8])[0]
            if got != base + getter:
                raise ValueError(f'contract getter slot {slot} changed ({got - base:#x} != {getter:#x})')


def _collect(engine, getters=True):
    """Contracts with getter values (`getters=False`: walk, loan fields and clause entries only,
    for contract_clause, which needs no emulation)."""
    c = C.cache(engine)
    key = 'contracts' if getters else 'contracts_raw'
    if key in c:
        return c[key]
    contracts, skipped, rejected = _walk(engine)
    contracts = [dict(k) for k in contracts]
    out = _fields(engine, c, engine.base, contracts, skipped, rejected, getters)
    c[key] = out
    return out


def _walk(engine):
    """Owner-checked contract containers of every PERSON (no getter values; cached)."""
    c = C.cache(engine)
    if 'contract_walk' in c:
        return c['contract_walk']
    _verify_dispatch(engine)
    base = engine.base
    vt_kind = {base + world.TYPES[k][0]: k for k in CLASSES}
    people = C.live(engine, 'people')
    teams = C.index_of(engine, 'teams')
    team_club = C.team_clubs(engine)
    # PERSON classes whose -0x98 / -0x90 slots are the verified contract pointers
    by_class = {}
    for i, (p, cls) in enumerate(zip(people.pointers, people.classes)):
        if p and cls and cls != 'unreadable':
            by_class.setdefault(cls, []).append(i)
    ok_classes, skipped = [], {}
    for cls, idxs in by_class.items():
        p = people.pointers[idxs[0]]
        vtable = C.u64s(engine, [p])[0]
        slot, disp = C.blobs(engine, [(vtable + 121 * 8, 8), (vtable - 0x3D8, 8)])
        if slot and disp and struct.unpack('<Q', slot)[0] == base + PERSON_CONTRACT_GETTER \
                and struct.unpack('<q', disp)[0] == -0x110:
            ok_classes.append(cls)
        else:
            skipped[cls] = len(idxs)
    rows = [i for cls in ok_classes for i in by_class[cls]]
    ptrs = [people.pointers[i] for i in rows]
    mains = C.u64s(engine, [p - 0x98 for p in ptrs])
    holders = C.u64s(engine, [p - 0x90 for p in ptrs])
    aux = C.u64s(engine, [h if h and not h % 8 else 0 for h in holders])
    candidates = []                     # (person idx, person ptr, role, contract ptr)
    for i, p, m, a in zip(rows, ptrs, mains, aux):
        if m:
            candidates.append((i, p, 'main', m))
        if a:
            candidates.append((i, p, 'aux', a))
    heads = C.blobs(engine, [(x[3], 0x30) for x in candidates])
    contracts = []                      # dicts
    rejected = 0
    for (i, p, role, ptr), head in zip(candidates, heads):
        if not head:
            rejected += 1
            continue
        vtable, owner, t1, t2 = struct.unpack_from('<QQQQ', head, 0)
        kind = vt_kind.get(vtable)
        if owner != p or kind is None or (role == 'main') != (kind in ('full_contract', 'basic_contract')):
            rejected += 1
            continue
        contracts.append({'person_idx': i, 'person': p, 'ptr': ptr, 'class': CLASSES[kind],
                          'role': 'main' if role == 'main' else kind.split('_')[0],
                          'team_idx': teams.get(t1), 'second_team_idx': teams.get(t2),
                          'club_idx': team_club.get(t1), 'flags2b': head[0x2B]})
    c['contract_walk'] = (contracts, skipped, rejected)
    return c['contract_walk']


def _fields(engine, c, base, contracts, skipped, rejected, getters=True):
    # getter fields per class
    routes = {}
    for cls, codes in (CODES.items() if getters else ()):
        members = [k for k in contracts if k['class'] == cls]
        if not members:
            continue
        values, route = C.getter_values(engine, cls, [k['ptr'] for k in members], codes)
        routes[cls] = route
        for code in codes:
            for k, v in zip(members, values[code]):
                k[code] = C.sql_value(v)
    # rolling expiry: FULL_CONTRACT +0x2b bit 3 makes slot 30 compute the date (research), so a
    # direct plan for Ceda cannot be trusted there: emulate those rows
    rolling = [k for k in contracts if getters and k['class'] == 'FULL_CONTRACT' and k['flags2b'] & 8]
    for k in rolling:
        from .. import bulkplans
        k['Ceda'] = C.sql_value(bulkplans.canonical(engine.get_property(k['ptr'], 'Ceda')))
    # loan cash fields and clause flags (loan_contracts layout)
    loans = [k for k in contracts if k['class'] == 'LOAN_CONTRACT']
    blobs = C.blobs(engine, [(k['ptr'], 0x100) for k in loans])
    for k, raw in zip(loans, blobs):
        if not raw:
            continue
        for name, off in LOAN_CASH.items():
            v = struct.unpack_from('<i', raw, off)[0]
            k[name] = None if v == -1 else v
        flags = struct.unpack_from('<Q', raw, 0xB8)[0]
        k['loan_flag_source'] = 'override' if flags else 'base'
        k['loan_flags'] = flags or struct.unpack_from('<Q', raw, 0xB0)[0]
    # clause entry vectors of FULL contracts (+0x68)
    fulls = [k for k in contracts if k['class'] == 'FULL_CONTRACT']
    vecs = C.blobs(engine, [(k['ptr'] + 0x68, 24) for k in fulls])
    reqs, owners = [], []
    for k, raw in zip(fulls, vecs):
        if not raw:
            continue
        start, end, cap = struct.unpack('<QQQ', raw)
        if start == end:
            continue
        if start < 4096 or any(x % 8 for x in (start, end, cap)) or not start <= end <= cap \
                or cap - start > contract_bonuses.MAX_ENTRIES * 8:
            k['entries_error'] = 'invalid entry vector'
            continue
        reqs.append((start, end - start))
        owners.append(k)
    # agreed playing time (squad status) of FULL contracts: the byte slot 32 returns (+0x54; the
    # hand-built playing_time.decode, which the player-status screen shows)
    if _squad_status_getter_ok(engine, base):
        for k, raw in zip(fulls, C.blobs(engine, [(k['ptr'] + SQUAD_STATUS_AT, 1) for k in fulls])):
            k['squad_status_code'] = raw[0] if raw else None
    signed_raw = C.blobs(engine, [(k['ptr'] + 0x44, 4) for k in owners])
    mode = C.blobs(engine, [(base + 0x56D4950, 1)])[0]
    mode = mode[0] if mode else None
    for k, raw, sraw in zip(owners, C.blobs(engine, reqs), signed_raw):
        k['entries'] = list(struct.iter_unpack('<ihBB', raw)) if raw else None
        k['signed_packed'] = struct.unpack('<I', sraw)[0] if sraw else None
    return {'contracts': contracts, 'routes': routes, 'skipped_classes': skipped, 'rejected': rejected,
            'rolling': len(rolling), 'expiry_mode': mode}


SQUAD_STATUS_AT = 0x54                   # FULL_CONTRACT agreed playing time (playing_time.decode)
SQUAD_STATUS_SLOT, SQUAD_STATUS_GETTER = 32, 0x1005C78
SQUAD_STATUS_GETTER_BYTES = bytes.fromhex('00504139c0035fd6')     # ldrb w0, [x0, #0x54]; ret


def _squad_status_getter_ok(engine, base) -> bool:
    """The FULL_CONTRACT vtable slot 32 is still the one-byte accessor of +0x54."""
    vt = base + world.TYPES['full_contract'][0]
    raw = C.blobs(engine, [(vt + SQUAD_STATUS_SLOT * 8, 8), (base + SQUAD_STATUS_GETTER, 8)])
    return bool(raw[0]) and struct.unpack('<Q', raw[0])[0] == base + SQUAD_STATUS_GETTER \
        and raw[1] == SQUAD_STATUS_GETTER_BYTES


def _expiry(signed_packed, parameter, mode):
    """contract_terms.expiry: signed date + parameter days (native int16 day arithmetic)."""
    if parameter < 0 or mode in (1, 2, 3) or signed_packed is None:
        return None
    iso = C.packed_date(signed_packed)
    if iso is None:
        return None
    signed = date.fromisoformat(iso)
    if signed.timetuple().tm_yday - 1 + parameter > 32767:
        return None
    value = signed + timedelta(days=parameter)
    return value.isoformat() if value.year <= 2200 else None


def _contract_rows(engine):
    data = _collect(engine)
    for n, k in enumerate(data['contracts']):
        k['idx'] = n
        yield (n, k['person_idx'], k['role'], k['class'], k['team_idx'], k['second_team_idx'], k['club_idx'],
               k.get('Cwwa'), k.get('Csda'), k.get('Ceda'), int(bool(k['flags2b'] & 8)) if k['class'] == 'FULL_CONTRACT'
               else None, k.get('Csqn'), k.get('Ctyp'), k.get('Cjob'),
               *(k.get(name) for name in LOAN_CASH),
               len(k['entries']) if k.get('entries') is not None else (0 if k['class'] == 'FULL_CONTRACT' else None),
               k.get('squad_status_code'))


def _clause_rows(engine):
    data = _collect(engine, getters=False)
    mode = data['expiry_mode']
    n = 0
    for ci, k in enumerate(data['contracts']):
        entries = k.get('entries')
        if entries:
            selected = {}
            for index, (_, parameter, kind, _) in enumerate(entries):
                prev = selected.get(kind)
                if prev is None or (kind <= 41 and contract_terms.PARAMETER_MASK & (1 << kind)
                                    and parameter < entries[prev][1]):
                    selected[kind] = index
            for index, (amount, parameter, kind, flags) in enumerate(entries):
                expiry = _expiry(k.get('signed_packed'), parameter, mode) if kind in HAS_EXPIRY else None
                yield (n, ci, k['person_idx'], 'contract_entry', index, kind, amount, VALUE_MEANING.get(kind),
                       parameter, PARAMETER_MEANING.get(kind), expiry, flags, int(selected[kind] == index), None)
                n += 1
        if k['class'] == 'LOAN_CONTRACT' and k.get('loan_flags') is not None:
            for name, bit in loan_contracts.CLAUSE_BITS.items():
                yield (n, ci, k['person_idx'], f'loan_flags_{k["loan_flag_source"]}', bit, LOAN_CLAUSE_BASE + bit,
                       None, None, None, None, None, None, None, int(bool(k['loan_flags'] & (1 << bit))))
                n += 1


CONTRACT_COLUMNS = [
    Column('idx', 'INTEGER', 'contract row number (contract_clause.contract_idx)'),
    Column('person_idx', 'INTEGER', 'the contracted person', references='person'),
    Column('role', 'TEXT', "'main' (PERSON - 0x98), 'loan' or 'trial' (current auxiliary contract, PERSON - 0x90)"),
    Column('class', 'TEXT', 'contract record class: FULL_CONTRACT, BASIC_CONTRACT, LOAN_CONTRACT, TRIAL_CONTRACT'),
    Column('team_idx', 'INTEGER', 'team the contract is with (contract +0x10); for a loan, the loan team',
           references='team'),
    Column('second_team_idx', 'INTEGER', 'second team pointer (contract +0x18): same club, may be another of its '
           'teams (basic contracts derive it from the first)', references='team'),
    Column('club_idx', 'INTEGER', "club of team_idx (team +0x30); for a loan, the loan club", references='club'),
    Column('weekly_wage', 'INTEGER', 'weekly wage in the base currency (GBP), getter key Cwwa (the key Pcwg forwards '
           'to; slot 9 int32 +0x20); for a loan, the wage while playing'),
    Column('signed_date', 'TEXT', 'date last contract signed (getter key Csda, the key Pcsd forwards to); NULL for '
           'basic contracts (their getter has no Csda)'),
    Column('expires_date', 'TEXT', 'contract expiry date (getter key Ceda, the key Pcex forwards to)'),
    Column('rolling_expiry', 'INTEGER', 'FULL_CONTRACT +0x2b bit 3: the expiry is computed from the current date '
           '(rolling); those rows are emulated through the getter'),
    Column('squad_number', 'INTEGER', 'squad number on this contract (getter key Csqn; label inferred: agrees with '
           'person.squad_number for the managed squad)'),
    Column('contract_type_code', 'INTEGER', 'getter key Ctyp, raw (0 on main full contracts and 1 on loans in this '
           'save; labels not proven)'),
    Column('job_code', 'INTEGER', 'getter key Cjob, raw job code (1 for players in this save; research: the live '
           'job byte +0x26 through slot 11, mapped to a title per team type)'),
    Column('loan_unused_weekly_wage', 'INTEGER', 'loans: weekly wage when not playing (+0xD4; NULL when not '
           'specified)'),
    Column('loan_playing_monthly_fee', 'INTEGER', 'loans: monthly fee when playing (+0xCC)'),
    Column('loan_unused_monthly_fee', 'INTEGER', 'loans: monthly fee when not playing (+0xD0)'),
    Column('loan_buy_back_fee', 'INTEGER', 'loans: future buy-back fee (+0xC8)'),
    Column('loan_future_fee', 'INTEGER', 'loans: initial future (purchase) fee (+0xC0; additional fee components '
           'are in fm_get_loan_contract)'),
    Column('clause_count', 'INTEGER', 'number of stored clause/bonus entries (FULL_CONTRACT entry vector +0x68); '
           'rows in contract_clause'),
    Column('squad_status_code', 'INTEGER', 'agreed playing time (squad status) on a FULL contract: FULL_CONTRACT '
           '+0x54, the byte its slot 32 accessor 0x1005C78 returns (hand-built playing_time.decode; the squad and '
           'contract screens show it); labels are the compiled English fallback names; NULL for other classes',
           enum={code: label[2] for code, label in playing_time.LABELS.items()}),
]
CLAUSE_COLUMNS = [
    Column('idx', 'INTEGER', 'clause row number'),
    Column('contract_idx', 'INTEGER', 'the contract (contract.idx)', references='contract'),
    Column('person_idx', 'INTEGER', 'the contracted person', references='person'),
    Column('source', 'TEXT', "'contract_entry' (FULL_CONTRACT entry vector) or 'loan_flags_base' / "
           "'loan_flags_override' (loan clause word +0xB0, replaced by +0xB8 when that is nonzero)"),
    Column('entry_index', 'INTEGER', 'position in the entry vector (loan flags: the bit number)'),
    Column('kind_code', 'INTEGER', 'native entry kind (loan flags: 1000 + bit)', enum=KIND_LABELS),
    Column('amount', 'INTEGER', 'int32 amount: cash in GBP for fees, bonuses and wages, else the kind\'s value '
           '(see amount_meaning)'),
    Column('amount_meaning', 'TEXT', 'what amount holds for this kind (contract_terms.FIELDS)'),
    Column('parameter', 'INTEGER', 'int16 parameter: percentage, games, goals, years or days to expiry by kind'),
    Column('parameter_meaning', 'TEXT', 'what parameter holds for this kind (contract_terms.FIELDS)'),
    Column('expiry_date', 'TEXT', 'release clauses: signed date + parameter days (native slot 56 rule); NULL when '
           'the clause has no expiry'),
    Column('native_flags', 'INTEGER', 'entry flag byte, uninterpreted'),
    Column('selected', 'INTEGER', '1 when the native property getter for this kind returns this entry (duplicates: '
           'first, or lowest parameter for masked kinds)'),
    Column('flag', 'INTEGER', 'loan clause flags: 1 when the clause is set'),
]


def _ensure_plans(engine):
    """Derive and verify direct plans for every contract class's getter keys (well under a second
    each; cached in the plan store). Keys with no verifiable plan are emulated per record."""
    contracts = _walk(engine)[0]
    for cls, codes in CODES.items():
        ptrs = [k['ptr'] for k in contracts if k['class'] == cls]
        if ptrs and C.plans_missing(engine, cls, codes):
            C.derive_plans(engine, cls, ptrs, codes, CODE_NAMES)


def _coverage(engine):
    d = _collect(engine)
    skipped = ', '.join(f'{k} {v}' for k, v in sorted(d['skipped_classes'].items()))
    return (f'person classes without the verified contract slot (not read): {skipped}' if skipped else '') + (
        f'; {d["rejected"]} containers failed the owner/class check' if d['rejected'] else '')


def fingerprint(engine):
    """Hash of every verified person's contract pointers (-0x98, -0x90 holder) and the first 0x70
    bytes of each contract object (owner, teams, wage +0x20, dates, clause vector +0x68): a
    signing, loan, renewal or wage change alters it. Bulk reads only, no emulation."""
    from . import digest
    contracts, _, _ = _walk(engine)
    heads = C.blobs(engine, [(k['ptr'], 0x70) for k in contracts])
    return digest(len(contracts), *(k['ptr'] for k in contracts), *heads)


def tables(engine):
    note = ('contract getter keys read through direct plans verified against each class\'s getter, the others '
            'emulated per record through that getter')

    def contract_rows():
        _ensure_plans(engine)
        return _contract_rows(engine)
    own = {'scope': 'own_club', 'own_club_column': 'club_idx',
           'public_columns': ['idx', 'person_idx', 'role', 'class', 'team_idx', 'second_team_idx', 'club_idx',
                              'squad_number', 'expires_date', 'weekly_wage', 'signed_date'],
           'reason': 'the current contract (club, wage, start and expiry, squad number) is on every profile: the '
                     'PERSON panel list 0x3B1B8C gives CanViewCurrentContract for every person and the PERSON key '
                     'ContextContractWeeklyWage formats the exact wage of another club\'s player; loan fees, '
                     'clauses and squad status stay with the manager\'s club (CLUB list 0xD725C: CanViewContracts '
                     'and CanViewTransferClauses for his own club only); see docs/fmdb/MANAGER_VIEW.md'}
    contract_view = (
        "SELECT k.idx, k.person_idx, "
        "COALESCE(NULLIF(pe.{person.Pcna}, ''), TRIM(COALESCE(pe.{person.Pfna}, '') || ' ' || "
        "COALESCE(pe.{person.Psna}, ''))) AS person_name, pe.class AS person_class, k.role, k.class, "
        "k.club_idx, cl.{club.Cnam|dbnm} AS club_name, k.team_idx, t.{team.Tlna|dbnm} AS team_name, "
        "k.weekly_wage, k.signed_date, k.expires_date, k.rolling_expiry, k.squad_number, "
        "(SELECT label FROM _enum_labels WHERE table_name = 'contract' AND column_name = 'squad_status_code' "
        "AND value = k.squad_status_code) AS squad_status, k.contract_type_code, k.job_code, "
        "k.loan_unused_weekly_wage, k.loan_playing_monthly_fee, k.loan_unused_monthly_fee, k.loan_buy_back_fee, "
        "k.loan_future_fee, k.clause_count, "
        "CASE WHEN k.role = 'loan' THEN (SELECT m.club_idx FROM contract m WHERE m.person_idx = k.person_idx "
        "AND m.role = 'main') END AS parent_club_idx "
        "FROM contract k LEFT JOIN person pe ON pe.idx = k.person_idx LEFT JOIN club cl ON cl.idx = k.club_idx "
        "LEFT JOIN team t ON t.idx = k.team_idx")
    clause_view = (
        "SELECT q.idx, q.contract_idx, q.person_idx, k.role, k.club_idx, "
        "COALESCE(NULLIF(pe.{person.Pcna}, ''), TRIM(COALESCE(pe.{person.Pfna}, '') || ' ' || "
        "COALESCE(pe.{person.Psna}, ''))) AS person_name, q.source, q.kind_code, "
        "(SELECT label FROM _enum_labels WHERE table_name='contract_clause' AND column_name='kind_code' "
        "AND value=q.kind_code) AS kind, q.amount, q.amount_meaning, q.parameter, q.parameter_meaning, "
        "q.expiry_date, q.selected, q.flag "
        "FROM contract_clause q JOIN contract k ON k.idx = q.contract_idx LEFT JOIN person pe ON pe.idx = q.person_idx")
    return [
        SourceTable('contract', 'every main, loan and trial contract in the save: person, club/team, role, wage, '
                    'signed and expiry dates, squad number, loan fees (clauses in contract_clause)',
                    CONTRACT_COLUMNS, contract_rows, mode='lazy', invalidation='content',
                    fingerprint=lambda: fingerprint(engine),
                    cost_note='about 77,800 contracts; about 20 s',
                    source_note=('contract containers PERSON-0x98 / PERSON-0x90 (owner-checked); ' + note),
                    indexes=('person_idx', 'club_idx', 'team_idx'), manager=own,
                    coverage=lambda: _coverage(engine),
                    views={'contract_view': contract_view}),
        SourceTable('contract_clause', 'every stored clause and bonus of every full contract (release fees, wage '
                    'rises, sell-on, appearance/goal/clean-sheet bonuses, extension options, ...) and the 13 '
                    'loan clause flags of every loan',
                    CLAUSE_COLUMNS, lambda: _clause_rows(engine), mode='lazy', invalidation='content',
                    fingerprint=lambda: fingerprint(engine),
                    cost_note='one entry-vector read per full contract',
                    source_note='FULL_CONTRACT entry vector +0x68 (contract_bonuses.read_entries layout, kinds from '
                                'contract_terms); loan clause words +0xB0/+0xB8 (loan_contracts)',
                    indexes=('contract_idx', 'person_idx', 'kind_code'),
                    manager={'scope': 'own_club', 'own_club_via': 'contract.club_idx',
                             'reason': 'contract clauses are shown for the manager\'s own players only'},
                    views={'contract_clause_view': clause_view}),
    ]
