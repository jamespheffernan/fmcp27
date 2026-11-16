"""Private complete ordinary CLUB kind1 identities before final filters.

Every base ordinal and retained slot is joined from current checked bytes.
No partial source is promoted to complete. Names, attributes, final filters,
Manager mode and field permissions are outside this internal source boundary.
"""
from copy import deepcopy

from . import bridge as bridge_module, players, world
from .knowledge_native_scope import collection_stream
from . import knowledge_search_population_source as population
from . import knowledge_search_retained_union as retained


def observe_complete(read,base,coach,*,check_current,page_size=2048):
    if type(page_size) is not int or not 1<=page_size<=retained.PAGE_LIMIT:
        raise ValueError('Invalid complete identity source page size')
    if not callable(check_current):
        raise ValueError('A checked identity source lifetime is required')
    before=deepcopy(check_current())
    if type(before) is not tuple or not before:
        raise ValueError('A checked nonempty identity source lifetime is required')
    snapshot=world.ReadSet(read)
    frames=[]
    offset=0
    while True:
        frame=population.observe(snapshot,base,coach,check_current=check_current,
            source_offset=offset,source_limit=page_size,apply_native_admission=True)
        frames.append(frame)
        offset=frame['next_source_offset']
        if offset is None:
            break
    union=retained.observe_complete(snapshot,base,coach,frames,check_current=check_current)
    subjects=[]
    for frame in frames:
        for row in frame['subjects']:
            if row['state']=='canonical_actual_subject' and row['native_admitted']:
                subjects.append(dict(primary=row['primary'],person=row['person'],
                    native_identity=deepcopy(row['native_identity']),record_kind=row['record_kind'],
                    native_origin='base'))
    for row in union['subjects']:
        if row['would_append'] is True:
            subjects.append(dict(primary=row['primary'],person=row['person'],
                native_identity=deepcopy(row['native_identity']),record_kind=row['record_kind'],
                native_origin='retained'))
    snapshot.verify()
    if check_current()!=before:
        raise ValueError('Complete identity source lifetime changed')
    snapshot.verify()
    return dict(scope='private_complete_native_club_kind1_identity_source_before_final_filters',
        native_admission_state=frames[0]['admission_state'],
        native_show_all_raw=frames[0]['list_context']['show_all_raw'],
        base_source_slots=frames[0]['source_total'],retained_source_slots=union['source_total'],
        base_pages=len(frames),complete_native_identity_source=True,
        complete_search_population=False,field_visibility_evaluated=False,
        manager_knowledge_verified=False,subjects=subjects,non_atomic=True)


def collect(bridge,session_id,*,coach_name=None,page_size=2048):
    """Bridge-owned current context and a final physical fence, private only."""
    if not isinstance(bridge,bridge_module.Bridge):
        raise ValueError('A genuine reader Bridge instance is required')
    with bridge.lock,collection_stream(bridge,session_id):
        process=deepcopy(bridge._current(session_id))
        tables=bridge._player_layout(process)
        base=tables[0]-players.RVA[0]
        plugin=deepcopy(bridge.plugin_identity)
        snapshot,save,identity=bridge._world_state(process,tables)
        coach=deepcopy(bridge._select_coach(save,coach_name))
        checks=[]
        lifetime=(process.pid,repr(process),repr(plugin),repr(identity),repr(coach))
        def current():
            now=bridge._current(session_id)
            layout=bridge._player_layout(now)
            fresh,current_save,current_identity=bridge._world_state(now,layout)
            selected=bridge._select_coach(current_save,coach_name)
            if (now!=process or layout!=tables or bridge.plugin_identity!=plugin
                    or current_save!=save or current_identity!=identity or selected!=coach):
                raise ValueError('Complete identity source process/save/coach changed')
            checks.append(fresh)
            fresh.verify()
            return lifetime
        result=observe_complete(snapshot,base,coach,check_current=current,page_size=page_size)
        current()  # No lifetime/public callback may follow these physical fences.
        for fresh in checks:
            fresh.verify()
        snapshot.verify()
        return result
