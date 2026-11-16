"""Pinned current Premier League age requirement, evaluated without native calls.

Roster membership and the PERSON current-team context are separate. This is
neither a submitted squad list nor a complete registration/fixture decision.
"""
from datetime import date, timedelta
import struct

from . import assessment_people, competition_stages, competitions, database, players, teams, world

SQUAD_TYPES = {0: 'Senior', 266: 'U21', 268: 'U18'}


def _date(value):
    if type(value) is not str:
        raise ValueError('Expected exact ISO date')
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value or not 1850 <= parsed.year <= 2200:
        raise ValueError('Date outside supported native range')
    return parsed


def native_age(birth_date, at_date):
    born, at = _date(birth_date), _date(at_date)
    if born == date(1900, 1, 1) or at.year == 1900 or born > at:
        return None
    bd, ad = born.timetuple().tm_yday, at.timetuple().tm_yday
    def native_leap(year):
        return (year & (15 if ((year*0x5C29) & 65535) < 0xA3E else 3)) == 0
    if abs(bd-ad) <= 1 and native_leap(born.year) != native_leap(at.year):
        return None  # Mixed-leap anniversary branch deliberately unsupported.
    return max(14, min(100, at.year-born.year-int(bd > ad)))


def classify(birth_date, current_date, cutoff_date):
    """Mirror requirement3's strict age thresholds; preserve unavailable inputs."""
    if birth_date is None:
        return dict(state='unavailable', reason='birth_date_unavailable', age_exempt=None,
                    current_age=None, age_at_cutoff=None)
    age = native_age(birth_date, current_date)
    if age is None:
        return dict(state='unavailable', reason='native_age_unavailable', age_exempt=None,
                    current_age=None, age_at_cutoff=None)
    cutoff_age = native_age(birth_date, cutoff_date) if 20 <= age <= 23 else None
    if 20 <= age <= 23 and cutoff_age is None:
        return dict(state='unavailable', reason='native_cutoff_age_unavailable', age_exempt=None,
                    current_age=age, age_at_cutoff=None)
    exempt = age < 20 or (age <= 23 and cutoff_age < 21)
    return dict(state='age_exempt' if exempt else 'not_exempt', reason='native_age_requirement3',
                age_exempt=exempt, current_age=age, age_at_cutoff=cutoff_age)


def verify_native(read, base):
    for rva, raw in NATIVE_SPANS:
        if read(base+rva, len(raw)) != raw:
            raise ValueError(f'League age native layout changed at {rva:#x}')


def _pointer_or_null(read, address):
    pointer = players.u64(read(address, 8))
    if pointer and (pointer < 4096 or pointer % 8):
        raise ValueError('Invalid league age source pointer')
    return pointer


def context(read, base, managed_team, current_date):
    """Accept the proved own-runtime, empty-override, default rule3 branch only."""
    _date(current_date)
    team_index = int.from_bytes(read(managed_team+8, 4), 'little')
    team, binding = teams.by_index(read, base, team_index)
    if binding['address'] != managed_team or not binding['owner_address']:
        raise ValueError('Managed TEAM canonical membership changed')
    public = dict(source_state='unavailable', reason=None, team=team, competition=None,
                  native_season_code=None, cutoff_date=None, requirement_code=None)
    club_teams = world.vector(read, binding['owner_address']+0x18, 64)
    if (not club_teams or club_teams[0] != managed_team
            or read(managed_team+0x28, 2) != b'\0\0'):
        public['reason'] = 'managed_team_not_supported_first_team'
        return public, binding['owner_address']
    comp = _pointer_or_null(read, managed_team+0x50)
    if not comp:
        public['reason'] = 'current_competition_absent'
        return public, binding['owner_address']
    index = int.from_bytes(read(comp+8, 4), 'little')
    record = competitions.by_index(read, base, index)
    saved = dict(address=comp, database_index=index, native_id=record['native_id'], random_id=record['random_id'])
    runtime_context, runtime, identity = competition_stages.runtime_context(read, base, saved)
    public.update(competition=record, native_season_code=runtime_context['native_season_code'])
    if record['native_id'] != 11 or runtime is None or runtime_context['shared_runtime']:
        public['reason'] = 'unsupported_current_competition'
        return public, binding['owner_address']
    if identity[1] != 0x566C2B8 or not _pointer_or_null(read, comp+0x60):
        public['reason'] = 'unsupported_runtime_profile'
        return public, binding['owner_address']
    if (read(runtime+0x3BE, 1) != b'\0' or read(runtime+0x4C, 1)[0] & 8):
        public['reason'] = 'unsupported_rule_selection_branch'
        return public, binding['owner_address']
    owner = _pointer_or_null(read, runtime+0x388)
    bank = _pointer_or_null(read, owner+0x1F0) if owner else 0
    if not bank:
        public['reason'] = 'rule_bank_absent'
        return public, binding['owner_address']
    rules, _ = competition_stages.vector(read, bank+0x60, 256)
    rule_index = read(runtime+0x49, 1)[0]
    if rule_index >= 128 or rule_index >= len(rules) or not rules[rule_index]:
        public['reason'] = 'default_rule_absent'
        return public, binding['owner_address']
    rule = rules[rule_index]
    requirement = _pointer_or_null(read, rule+0x70)
    if (int.from_bytes(read(rule+0x108,4),'little',signed=True) != 11
            or read(rule+0x125, 1) != b'\x08' or read(rule+0xF1,1) != b'\x08'
            or int.from_bytes(read(rule+0xE8, 4),'little') != 0x402
            or read(rule+0xF2, 1) != b'\0' or not requirement
            or read(requirement+0x18, 2) != b'\x01\x03'):
        public['reason'] = 'unsupported_age_requirement'
        return public, binding['owner_address']
    overrides, _ = competition_stages.vector(read, runtime+0x2B0, 256)
    if players.u64(read(base+identity[1]+0xE8, 8)) != base+0x3AD4D70:
        raise ValueError('Runtime age cutoff dispatch changed')
    if overrides:
        public['reason'] = 'unsupported_cutoff_override'
        return public, binding['owner_address']
    day, year = struct.unpack('<HH', read(runtime+0xD0, 4)); day &= 511
    if year == 1900 and day == 1:
        public['reason'] = 'cutoff_date_unset'
        return public, binding['owner_address']
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Invalid native cutoff date')
    start = date(year,1,1)+timedelta(days=day-1)
    if start.year != year:
        raise ValueError('Invalid native cutoff day')
    public.update(source_state='available', reason='native_current_competition_rule3',
                  cutoff_date=(start-timedelta(days=1)).isoformat(), requirement_code=3)
    return public, binding['owner_address']


def collect(read, base, tables, managed_team, current_date):
    """Return public rows and private bindings; caller verifies before publishing."""
    verify_native(read, base)
    source, club = context(read, base, managed_team, current_date)
    people = database.table(read, base, 'people')
    rows, pending, squads, excluded = [], [], [], []
    for team_slot, address in enumerate(world.vector(read, club+0x18, 64)):
        team, binding = teams.by_index(read, base, int.from_bytes(read(address+8,4),'little'))
        if binding['address'] != address or binding['owner_address'] != club:
            raise ValueError('Club squad canonical relationship changed')
        kind = int.from_bytes(read(address+0x28,2),'little')
        if kind not in SQUAD_TYPES:
            excluded.append(dict(club_team_slot=team_slot, native_type=kind, team=team))
            continue
        roster = world.vector(read, address+0x38, 256)
        squads.append(dict(club_team_slot=team_slot, native_type=kind, label=SQUAD_TYPES[kind],
                           team=team, native_slot_count=len(roster)))
        for slot, primary in enumerate(roster):
            if len(rows) >= 768:
                raise ValueError('League age roster response exceeds supported limit')
            offset = players.person_offset(read, primary, tables) if players.u64(read(primary,8)) in (base+players.RVA[0],base+players.STAFF_RVA[0]) else None
            if offset is None:
                if players.u64(read(primary,8)) != base+world.TYPES['virtual_player'][0]:
                    raise ValueError('Unsupported roster player type')
                offset = 0x20
            person = primary+offset
            checked, checked_offset, identity, native_id, secondary = assessment_people._person(read,base,people,person)
            if checked != primary or checked_offset != offset:
                raise ValueError('Roster PERSON relation changed')
            row = dict(club_team_slot=team_slot, squad=SQUAD_TYPES[kind], roster_slot=slot,
                       native_identity=identity['native_identity'], record_kind=identity['record_kind'],
                       name=None, display_name=None, birth_date=None, current_team=None,
                       current_team_state='unavailable', player_ref=None,
                       state='unavailable', reason='unsupported_virtual_age_source', age_exempt=None,
                       current_age=None, age_at_cutoff=None)
            private = None
            if identity['record_kind'] in ('actual','player_staff'):
                database.player_membership(read,base,people,identity['native_identity']['database_index'],primary)
                decoded, token = players.decode(read,primary,tables)
                if (token[1] if identity['record_kind']=='player_staff' else token[0]) != native_id or token[-1] != secondary:
                    raise ValueError('Roster decoded identity changed')
                row.update(name=decoded['name'],display_name=decoded['display_name'],birth_date=decoded['birth_date'])
                private = dict(address=primary,identity=token,tables=tables,world_bound=True,
                               database_index=identity['native_identity']['database_index'],record_kind=identity['record_kind'])
                vt = players.u64(read(person,8))
                if any(players.u64(read(vt+slot,8)) != base+fn for slot,fn in ((0x138,0x148F4C0),(0x1B8,0xCA4640),(0x230,0xD5C578))):
                    raise ValueError('Player age/current-team dispatch changed')
                adjustment = struct.unpack('<q',read(vt-0x1C8,8))[0]
                if person+adjustment+0x58 != primary+0x2D0+(0xF8 if identity['record_kind']=='player_staff' else 0):
                    raise ValueError('Player birth-date virtual base changed')
                team_adjustment = struct.unpack('<q',read(vt-0x240,8))[0]
                if person+team_adjustment != primary:
                    raise ValueError('Player current-team virtual base changed')
                current = _pointer_or_null(read,person+team_adjustment+0x128)
                current_binding = None
                if current:
                    current_team,current_binding = teams.by_index(read,base,int.from_bytes(read(current+8,4),'little'))
                    if current_binding['address'] != current:
                        raise ValueError('Player current TEAM canonical membership changed')
                    row.update(current_team=current_team,current_team_state='canonical_current_team')
                if not current:
                    row.update(reason='current_team_absent')
                elif current_binding['owner_address'] != club:
                    row.update(state='outside_club_context',reason='current_team_outside_managed_club')
                elif source['source_state'] != 'available':
                    row.update(reason=source['reason'])
                elif int.from_bytes(read(person+0x18,8),'little') & (1<<12):
                    row.update(reason='unsupported_player_age_calendar')
                else:
                    row.update(classify(row['birth_date'],current_date,source['cutoff_date']))
            rows.append(row); pending.append(private)
    counts = {state:sum(r['state']==state for r in rows) for state in ('age_exempt','not_exempt','outside_club_context','unavailable')}
    return dict(source=source,squads=squads,excluded_squads=excluded,players=rows,count=len(rows),
                counts=counts,complete_selected_roster_scan=True,
                all_selected_players_classified=not counts['unavailable'] and not counts['outside_club_context'],
                missing_squad_types=[label for code,label in SQUAD_TYPES.items() if not any(s['native_type']==code for s in squads)],
                scope='Current Premier League age exemption only. Current PERSON team/club context is checked separately from roster inclusion. '
                      'Outside-club players are not classified; this is not a loan determination. Other squad types are excluded. '
                      'No submitted-list status, complete registration decision or fixture clearance is evaluated. '
                      'Reads are non-atomic with consumed-byte and identity rechecks; no game functions are executed.'), pending


NATIVE_SPANS = (
    (0x148F4C0, bytes.fromhex('f44fbea9fd7b01a9fd430091f30301aa080040f908dd40f900013fd60804407909004079292100121fb11d712009417aa0000054e10313aafd7b41a9f44fc2a8ec1fa31400008052fd7b41a9f44fc2a8c0035fd6')),
    (0xCA4640, bytes.fromhex('080040f9082107d1080140f90800088b00610191c0035fd6')),
    (0xD5C578, bytes.fromhex('080040f9080109d1080140f90800088b009540f9c0035fd6')),
    (0x3D5756C, bytes.fromhex('29004079292100120a0040794b2100126c01094b9f090071ab00005409044079e903292a0801090b250000140a0440799f0900312d0400546c0500512e858b524d7d0e1bad3d00126f008052f0018052bff928710d328f1aad010a0a0e7d0e1bce3d0012dff928710e328f1ace01080adf010071a019407ae0000054bf0100718d07805260114d7ac089407a6b018c1a040000146d0900517fed0071ab818c1a6b0500116b2100123f010b6b62000054e9032a2adcffff1708010a4b083d0013c90180521f39007108c1891a890c80521f91017100b1891a001c0013c0035fd6')),
    (0x14FB04C, bytes.fromhex('140080d2c80240b9a90d02d029e13691290140b90a6110122b0080528beda0725f010b6b2801881aa8831cb8a80240f9089d40f9a1e300d1e00315aa00013fd61f5c0071cc0e00541f500071ab0f0054a4835cb8a80e40f900314cd3e10314aae20313aa030080d2050080526571a194a0c31cb8a80240f908dd40f9e00315aa00013fd6a1d300d1f770a1941f5400717e000014')),
    (0x14FB2D0, bytes.fromhex('1f480071e0a79f1ae5ffff17')),
    (0x3AA5A40, bytes.fromhex('17c441f9970e00b4682641391ffd0371e0120054df0600316100005476264139f6df003978fa4e3908a701511f490071042b577a041b487a2101005421de00f021002b91a2de009042c03c91e00313aa030080d256234194203000b56832413928021836689e40f9480100b4083140f91f0100f1021b4e7a280080520821d81a690088520801090a0499407ac1000054b50000b4e00315aa46840a94f50300aa002e00b5150080d2d62d3837c81e4093e9fa40f9292946a94a0109cb4afd43935f0108ebe92c0054357968f8552800b5')),
    (0x3AD4D9C, bytes.fromhex('175841f9185c41f9ff0218eb80010054e00240f9080040f9080d40f9e10314aae20313aae30316aae40315aa00013fd680380037f7220091f4ffff1788a6417989a24179292100121fb11d712009417a4003005488d240b9680200b935370034')),
    (0x3D57708, bytes.fromhex('e05a40f9600600b4747e50d32800805288eda072e80f00b9080040f9087540f9e1330091e20316aae30315aa00013fd6682200129fb21d71610000541f050071a0030054c9ca00d029755b793f41536bc1000054c9ca00d029715b79292100121f01096b80020054f91f007928858b52')),
    (0x3D577BC, bytes.fromhex('ea1f4079e81b40790921001229090071020e00544a05005162000014')),
    (0x3D5795C, bytes.fromhex('2b858b524b7d0b1b6b3d00126c008052ed0180527ff92871ab318c1a4a3d00127f010a6aab2d80526b158b1a6901090b081917122801080b00050011403d1033')),
    (0x3D57684, bytes.fromhex('620000b4e83240f9e80000b440eb43f9e20318aad7351394f40300aaf70200b4d40200b5e92e40f9c90200b448eb43f9293140f9690100b41f0300710a0780520b0880526a118a9a29696af8a90000b429f940f9690000b4343d40f9540100b51f030071092e80520a2f80524911899a146969f804000014770000b536000014140080d2')),
    (0x14F9A8C, bytes.fromhex('56634039fc2b40f9b60400b453670091fb0100347a024039a77301d1e00317aae1031aaae20315aae30314aae50318aae60319aa38010094c014003573060091d60600f181feff5415000014')),
)
