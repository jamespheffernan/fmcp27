"""Pure read-only retained-entry union for a bound club Player Search source.

Replays0x208C380..0x208C698 against freshly rebound base frames. Restricted
frames require the explicit checked native-admission path; only admitted
identities seed deduplication. A raw base pointer is insufficient by itself.
Only selected-club/container1 context is covered by the current base observer;
national/container2 base frames are not supplied or invented here. Retained
entry payloads, field visibility, final search filters and manager knowledge
are not evaluated. No game getter, refresh, allocation or cache write occurs.
"""
from copy import deepcopy
from dataclasses import dataclass
import struct

from . import assessment_people, database, players, virtual_identity, world
from . import knowledge_search_population_source as base_source


SKIPPED_KINDS = frozenset((2, 7, 10, 11))
ENTRY_LIMIT = 100_000  # Total physical retained slots, a reader budget.
PAGE_LIMIT = 2048


@dataclass(frozen=True)
class Continuation:
    """Internal consumed-byte checkpoint, never a public cursor or seen-ID seed."""

    next_offset: int
    lifetime: tuple
    base_frames: tuple
    observed: tuple


def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base + rva, len(expected)) != expected:
            raise ValueError(f'Retained union native source changed at {rva:#x}')


def _rebind_base(read, base, coach, supplied, check_current):
    if type(supplied) not in (tuple, list) or not supplied:
        raise ValueError('Retained union requires observer base frames, not arbitrary identity seeds')
    frames = deepcopy(tuple(supplied))
    current, seed = [], set()
    for frame in frames:
        if (type(frame) is not dict or type(frame.get('source_offset')) is not int
                or type(frame.get('scanned_count')) is not int
                or not 0 <= frame['scanned_count'] <= PAGE_LIMIT):
            raise ValueError('Invalid bounded observer base frame')
        observed = base_source.observe(read, base, coach, check_current=check_current,
            source_offset=frame['source_offset'], source_limit=max(1, frame['scanned_count']),
            apply_native_admission=frame.get('native_base_admission_evaluated',False))
        if observed != frame:
            raise ValueError('Base frame differs from the current native observation')
        if observed['admission_state'] not in ('unrestricted_show_all_bypass',
                'native_restricted_base_admission_evaluated'):
            raise base_source.SourceUnavailable('Restricted base admission is not implemented')
        current.append(observed)
        seed.update(row['native_identity']['database_index'] for row in observed['subjects']
                    if row['state'] == 'canonical_actual_subject' and row.get('native_admitted',True))
    context_keys = ('save', 'selected_team', 'list_context', 'vector', 'vector_choice',
                    'vector_mode_992', 'fow_enabled_raw', 'source_total', 'admission_state')
    if any(any(frame[key] != current[0][key] for key in context_keys) for frame in current[1:]):
        raise ValueError('Base frames refer to different native contexts')
    intervals = sorted((frame['source_offset'], frame['scanned_count']) for frame in current)
    end = 0
    complete = True
    for start, count in intervals:
        if start < end:
            raise ValueError('Overlapping observer base frames are not accepted')
        complete &= start == end
        end = start + count
    complete &= end == current[0]['source_total']
    return frames, current[0], seed, bool(complete)


def _context_team(read, base, human, coach):
    contract = world.pointer(read, human + 0x4B0)
    _, table = base_source._typed_contract(read, base, contract)
    if players.u64(read(table + 0x58, 8)) != base + 0xD8C3C8:
        raise ValueError('Retained union current-contract context getter changed')
    if read(contract + 0x26, 1)[0] < 2:
        return None  # 208B3A4 / 208C388: native union has no context TEAM.
    team = world.pointer(read, contract + 0x10)
    if team != coach['team_address']:
        raise ValueError('Retained union contract TEAM differs from the selected owner')
    marker = read(team + 0x2F, 1)[0]
    if marker != 0:
        # Native marker1 uses HUMAN260, but the frozen observer only binds
        # marker0 club frames. Substituting a personal230 list is never valid.
        raise base_source.SourceUnavailable('Retained union requires a proved club/container1 base frame')
    return team


def _entries(read, human, destination):
    start, count = base_source._bounds(read, human + 0x248, base_source.LIST_LIMIT)
    pointers = base_source._values(read, start, count)
    headers, entries = [], []
    for ordinal, listing in enumerate(pointers):
        if not listing:
            raise base_source.SourceUnavailable('Null header in native retained-list iteration')
        base_source._pointer(listing)
        if world.pointer(read, listing + 0xD0) != human:
            raise ValueError('Retained list HUMAN owner backlink differs')
        kind = read(listing + 0x4C, 1)[0]
        state = ('destination_skipped' if listing == destination else
                 'native_kind_skipped' if kind in SKIPPED_KINDS else 'retained_source')
        header = dict(native_list_ordinal=ordinal, native_kind=kind, state=state)
        if state == 'retained_source':
            begin, total = base_source._bounds(read, listing + 0x80, ENTRY_LIMIT)
            if len(entries) + total > ENTRY_LIMIT:
                raise ValueError('Retained union exceeds its total physical-slot reader budget')
            header['stored_slots'] = total
            # Read bounded pointer blocks, not payload/profile blocks. Capturing
            # the complete slot arrays also binds them across continuation pages.
            for offset in range(0, total, PAGE_LIMIT):
                values = base_source._values(read, begin + offset * 8, min(PAGE_LIMIT, total - offset))
                entries.extend((ordinal, offset + index, entry) for index, entry in enumerate(values))
        headers.append(header)
    return headers, entries


def _discarded_people(read, base, human, people):
    # The selected club marker0 branch uses personal-data+BD8, not personal230.
    data = world.pointer(read, human + 0x388)
    start, count = base_source._bounds(read, data + 0xBD8 + 0x30, ENTRY_LIMIT)
    discarded = set()
    if not count:
        return discarded
    mode = read(base + 0x56D34E0, 1)[0]
    if not mode & 1:
        # Original1693B68 loads only this pair; +78 is not an operand.
        fallback_start, fallback_end = struct.unpack('<QQ',read(people['root']+0x68,16))
        if (fallback_start,fallback_end)==(0,0):
            fallback_count=0
        else:
            base_source._pointer(fallback_start)
            if (fallback_end%8 or fallback_end<fallback_start
                    or fallback_end-fallback_start>base_source.SOURCE_LIMIT*8):
                raise ValueError('Invalid native alternate PEOPLE pair')
            fallback_count=(fallback_end-fallback_start)//8
    for offset in range(0, count, PAGE_LIMIT):
        records = base_source._values(read, start + offset * 8, min(PAGE_LIMIT, count - offset))
        for record in records:
            if not record:
                continue
            base_source._pointer(record)
            index = struct.unpack('<i', read(record, 4))[0]
            if index < 0:
                continue
            if not mode & 1 and index < fallback_count:
                # A null in-range fallback slot does NOT fall back to canonical.
                person = base_source._optional_pointer(read, fallback_start + index * 8)
            elif index < people['count']:
                person = base_source._optional_pointer(read, people['start'] + index * 8)
            else:
                person = 0
            if person:
                discarded.add(person)
    return discarded


def _identity(read, base, people, person):
    primary, _, result, _, _ = assessment_people._person(read, base, people, person)
    if result['record_kind'] == 'virtual':
        compact = virtual_identity.inspect(read, primary, tuple(base + rva for rva in players.RVA))
        if compact['native_identity'] != result['native_identity']:
            raise ValueError('Retained compact identity disagrees with its canonical PERSON')
    elif result['record_kind'] in ('actual', 'player_staff'):
        actual = base_source._base_identity(read, base, people, primary)
        if actual['person'] != person or actual['native_identity'] != result['native_identity']:
            raise ValueError('Retained actual/combined identity disagrees')
    # Other recognised canonical PERSON types can occur in a retained list.
    # Native union copies them too; later Player Search filters are not replayed.
    return dict(primary=primary, person=person, record_kind=result['record_kind'],
                native_identity=result['native_identity'])


def _base_pointer_snapshot(read, base, frame):
    """Read the selected unsorted vector; absence is not an index-bit proof."""
    header = base + base_source.BASE_VECTORS[frame['vector']]
    start, count = base_source._bounds(read, header, base_source.SOURCE_LIMIT)
    if count != frame['source_total']:
        raise ValueError('Selected base pointer-vector count changed after frame rebinding')
    # The frozen b1 observer chunks this at2048 pointers/16384 bytes per read.
    pointers = base_source._values(read, start, count)
    present = set()
    for pointer in pointers:
        if pointer:
            present.add(base_source._pointer(pointer))
    # Re-read the header through the ReadSet before using a membership result.
    base_source._bounds(read, header, base_source.SOURCE_LIMIT)
    return frozenset(present), dict(selected_vector=frame['vector'], stored_slots=count,
        null_slots=pointers.count(0), complete_pointer_scan=True,
        complete_identity_coverage=False, additional_base_matches_in_scanned_prefix=0,
        scope='positive_canonical_retained_primary_matches_only')


def _positive_base_match(read, identity, pointers):
    if identity['primary'] not in pointers:
        return False
    if identity['record_kind'] not in ('actual', 'player_staff'):
        raise base_source.SourceUnavailable('Non-actual retained primary occurs in the actual base vector')
    # 208BB94..BBA0 converts this exact primary to PERSON before appending;
    # 208C2CC..30C seeds its signed PERSON+8 index. _identity has already bound
    # that PERSON/index canonically. No other base object's profile is read.
    table = players.u64(read(identity['primary'], 8))
    displacement = struct.unpack('<q', read(table - 0x18, 8))[0]
    if identity['primary'] + displacement != identity['person']:
        raise ValueError('Native show-all primary-to-PERSON adjustment differs')
    return True


def observe(read, base, coach, base_frames, *, check_current, source_limit=128, continuation=None):
    return _observe(read,base,coach,base_frames,check_current=check_current,
        source_limit=source_limit,continuation=continuation,maximum=PAGE_LIMIT)


def observe_complete(read,base,coach,base_frames,*,check_current):
    """Join the complete bounded retained source once, with no caller seed."""
    result,next_page=_observe(read,base,coach,base_frames,check_current=check_current,
        source_limit=ENTRY_LIMIT,continuation=None,maximum=ENTRY_LIMIT)
    if next_page is not None or not result['all_union_decisions_resolved']:
        raise base_source.SourceUnavailable('Complete retained identities remain unresolved')
    return result


def _observe(read, base, coach, base_frames, *, check_current, source_limit, continuation, maximum):
    """Return (qualified physical-slot page, optional internal continuation).

    Frames must be actual outputs of the frozen base observer and are re-read
    and compared, including canonical identities. Complete contiguous base
    coverage seeds exact native dedup. With partial coverage, exact primary
    matches in the fully read/rechecked raw base vector prove additional base
    duplicates. Pointer absence still leaves canonical-index overlap unresolved.
    A later duplicate is certainly skipped even when that first encounter's
    overlap is unresolved. Compact/non-player types cannot belong to this base.

    Each continuation validates the actual lifetime, previous consumed bytes
    and the unchanged frame set, then replays the prefix to reconstruct dedup.
    all_scanned_union_decisions_resolved covers that prefix plus this page;
    all_union_decisions_resolved requires the entire source in the returned page.
    Source offset is never accepted as an unbound caller-supplied seen-ID seed.
    This remains a non-atomic read; it is not a manager-knowledge result.
    """
    if type(source_limit) is not int or not 1 <= source_limit <= maximum:
        raise ValueError('Invalid retained-union page size')
    if type(base_frames) not in (tuple, list) or not base_frames:
        raise ValueError('Retained union requires observer base frames, not arbitrary identity seeds')
    if not callable(check_current):
        raise ValueError('Retained union requires a process/save/build lifetime check')
    before = deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('Retained union requires a checked lifetime identity tuple')
    snapshot = world.ReadSet(read)
    offset = 0
    if continuation is not None:
        if not isinstance(continuation, Continuation):
            raise ValueError('Invalid retained-union continuation')
        if continuation.lifetime != before:
            raise ValueError('Retained union process/save/build lifetime changed across pages')
        if tuple(base_frames) != continuation.base_frames:
            raise ValueError('Base frame set changed across retained-union pages')
        for address, size, expected in continuation.observed:
            if snapshot(address, size) != expected:
                raise ValueError('Retained union consumed source changed across pages')
        offset = continuation.next_offset
    verify_native(snapshot, base)
    frames, base_frame, seed, base_complete = _rebind_base(snapshot, base, coach, base_frames, check_current)
    _, human = base_source.prepared_tactics_source._team_and_human(snapshot, base, coach)
    destination, _ = base_source._selected_list(snapshot, human)
    context = _context_team(snapshot, base, human, coach)
    headers, entries = _entries(snapshot, human, destination) if context else ([], [])
    pointers = frozenset()
    restricted = base_frame['admission_state']=='native_restricted_base_admission_evaluated'
    admission = None
    pointer_metadata = dict(selected_vector=base_frame['vector'], stored_slots=base_frame['source_total'],
        null_slots=None, complete_pointer_scan=False, complete_identity_coverage=False,
        additional_base_matches_in_scanned_prefix=0,
        scope='positive_canonical_retained_primary_matches_only')
    if not base_complete and entries:
        pointers, pointer_metadata = _base_pointer_snapshot(snapshot, base, base_frame)
        if restricted:
            from .knowledge_search_base_admission import Frame
            admission = Frame(snapshot, base, human, show_all=False)
    total = len(entries)
    if type(offset) is not int or not 0 <= offset <= total:
        raise ValueError('Retained-union continuation offset is outside the source')
    end = min(offset + source_limit, total)
    people = database.table(snapshot, base, 'people')
    identities, seen, discarded, rows = {}, set(seed), None, []
    pointer_matches = set()
    unresolved = 0
    for ordinal, (list_ordinal, entry_ordinal, entry) in enumerate(entries[:end]):
        row = dict(source_ordinal=ordinal, native_list_ordinal=list_ordinal,
                   native_entry_ordinal=entry_ordinal, state='null_entry', would_append=False)
        if entry:
            base_source._pointer(entry)
            person = base_source._optional_pointer(snapshot, entry)
            row['state'] = 'null_subject'
            if person:
                if person not in identities:
                    identities[person] = _identity(snapshot, base, people, person)
                identity = identities[person]
                row.update(deepcopy(identity))
                if discarded is None:
                    discarded = _discarded_people(snapshot, base, human, people)
                index = identity['native_identity']['database_index']
                if person in discarded:
                    row['state'] = 'discarded_native_person_lookup'
                elif index in seed:
                    row['state'] = 'duplicate_base_admitted'
                elif (_positive_base_match(snapshot, identity, pointers)
                        and (admission is None or admission.admitted(person))):
                    pointer_matches.add(index)
                    seen.add(index)
                    row['state'] = 'duplicate_base_admitted'
                elif index in seen:
                    row['state'] = 'duplicate_prior_retained'
                else:
                    seen.add(index)
                    unknown = not base_complete and identity['record_kind'] in ('actual', 'player_staff')
                    row.update(state='base_overlap_unresolved' if unknown else 'retained_union_addition',
                               would_append=None if unknown else True)
                    unresolved += int(unknown)
        if ordinal >= offset:
            rows.append(row)
    pointer_metadata['additional_base_matches_in_scanned_prefix'] = len(pointer_matches)
    result = dict(source_state='available' if context else 'native_union_context_absent',
        source_scope='selected_club_container1_retained_identity_union_before_final_filters',
        current_date=base_frame['save']['current_date'], selected_team=base_frame['selected_team'],
        admission_state=base_frame['admission_state'], base_coverage_complete=base_complete,
        known_base_seed_subjects=len(seed), base_pointer_metadata=pointer_metadata,
        native_union_active=context is not None,
        native_container=1 if context else None, list_headers=headers,
        source_total=total, source_offset=offset, scanned_count=end - offset,
        replayed_prefix_count=offset, complete_returned_source=offset == 0 and end == total,
        all_scanned_union_decisions_resolved=unresolved == 0,
        all_union_decisions_resolved=offset == 0 and end == total and unresolved == 0,
        unresolved_base_overlap_in_scanned_prefix=unresolved, subjects=rows,
        complete_search_population=False, manager_knowledge_verified=False, non_atomic_read=True)
    snapshot.verify()
    if check_current() != before:
        raise ValueError('Retained union process/save/build lifetime changed')
    snapshot.verify()
    next_page = None
    if end < total:
        next_page = Continuation(end, before, frames,
            tuple((address, size, raw) for (address, size), raw in snapshot.observed.items()))
    return result, next_page


# Exact static guards; no target is executed.
NATIVE_SPANS = (
    # Kind1's stored show-all bit bypass, exact primary -> PERSON append path.
    (0x208bb88, bytes.fromhex(
        '28054439c8000036190900b4280340f908815ef83503088b45000014'
    )),
    (0x208c380, bytes.fromhex(
        'f92342a9fb1f40f9280100b4683341391f250071290080522821c81a894480520801090a0499407a20030054f60000b4'
        'e81b40f9020116cbc8b00190004945f9e10316aac4268b94e12340f9e10000b4e12700f9e82b40f9020101cbc8b00190'
        '004945f9bc268b94fd7b4ca9f44f4ba9f6574aa9f85f49a9fa6748a9fc6f47a9e923466dff430391c0035fd61c0080d2'
        'e81740f908bd40391f010071e9179f1a4a0080522bb501f06b5141f9eb0f00f91f0500715801891a3500c0d2089301d0'
        '084945fdb80100341f0700718100005408498052094a805203000014084c8052094d8052296b69f8286b68f8280108cb'
        '08fd439302000014e80318aa9f0308eb62f9ff54f80100341f0b007181000054293741f9283341f903000014292b41f9'
        '282741f9290108cb9f0f89eba200005417797cf8ff021beb610000540a000014170080d2e83241391f2d007129008052'
        '2821c81a899081520801090a0499407a800000549c07009118fbff35e3ffff17e82648a93f0108eb60ffff541a0080d2'
        '130080d249ff5d93146969f8d40b00b4810240f9810b00b4e81740f908bd403929c741f91f01007108b781520a7b8152'
        '4801889a2001088b691dd897400a00b5880240f9080980b9e90f40f91f01096b0a01005429b501f0294d41f90afd43d3'
        '4ae57d9229696af82825c89ac8080037'
    )),
    (0x208c630, bytes.fromhex(
        '880240f9140980b928b501f0085141f91f0114ebc80000548106009120b501f000600a910200805228b3899728b501f0'
        '084d41f989fe43d329e57d922a0080524a21d49a0b6969f86a010aaa0a6929f8f91340f973060091e82648a9290108cb'
        '5a03158b7f0e89eb63f3ff54'
    )),
    (0x208b36c, bytes.fromhex(
        'e80240f908815ef8e802088b153d40f9550100b4a80240f9082d40f9e00315aa00013fd61f08007183000054a80a40f9'
        'e81700f902000014ff1700f9'
    )),
    (0x208c2cc, bytes.fromhex(
        '390b80b928b501f0085141f91f0119ebc80000542107009120b501f000600a910200805202b48997884f41f929ff43d3'
        '29e57d92ea22d99a0b6969f86a010aaa0a6929f8'
    )),
    (0x1693adc, bytes.fromhex(
        '082443a92a0108eba0070054e90102f029c146f94afd4393290600b40b0202906b8153395f0500f14a859f9a8b020036'
        '000140f9c00100b40b0040b92b01f8372c4540f98c3540a9ad010ceba00000547f0d8deb620000548b796bf802000014'
        '0b0080d27f0101ebc0040054082100914a0500f1e1fdff5421000014000140f9600200b40b0040b9cb01f8372cb546a9'
        'ad010ccb7f0d8debe30000542c4540f98c3540a9ad010cebc00000547f0d8deb820000548b0d0b8b6b0140f902000014'
        '0b0080d27f0101ebc0010054082100914a0500f141fdff5409000014010100b55f0500f149859f9a000140f9a00000b5'
        '08210091290500f181ffff54000080d2c0035fd6'
    )),
    (0xd8c3c8, bytes.fromhex(
        '00984039c0035fd6'
    )),
)
