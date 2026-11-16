"""Same-read-snapshot canonical identities for retained match source-local words."""
from . import assessment_people, database, live_team_sheet_source, teams

def resolve(read, base, person_indices, team_indices):
    people_indices=sorted(set(person_indices));team_indices=sorted(set(team_indices))
    if len(people_indices)>4096 or len(team_indices)>256:
        raise ValueError('Match identity work budget exceeded')
    if any(type(x) is not int or x<0 for x in people_indices+team_indices):
        raise ValueError('Invalid match identity index')
    assessment_people.verify_native(read,base)
    people=database.table(read,base,'people');team_table=teams.lookup(read,base)
    person_rows={};team_rows={}
    for index in people_indices:
        try:
            person_rows[index]=live_team_sheet_source._person(read,base,people,index)
        except ValueError as error:
            person_rows[index]={'database_index':index,'native_id':None,'name':None,'identity_state':'unresolved_source_local_word','reason':str(error)}
    for index in team_indices:
        try:
            row,_=teams.by_index(read,base,index,info=team_table)
            row['identity_state']='same_snapshot_canonical_TEAM';team_rows[index]=row
        except ValueError as error:
            team_rows[index]={'database_index':index,'native_id':None,'owner':None,'identity_state':'unresolved_source_local_word','reason':str(error)}
    if database.table(read,base,'people')['identity']!=people['identity'] or teams.lookup(read,base)['lookup_identity']!=team_table['lookup_identity']:
        raise ValueError('Match identity table changed during read')
    return {'people':person_rows,'teams':team_rows,'identity_scope':'same_snapshot_live_database_table_membership','native_functions_executed':False}

def join(rows, identities):
    """Return rows with canonical identities; preserve unknowns and original words."""
    result=[]
    for row in rows:
        person=identities['people'].get(row['person_index_word'],identities['people'].get(str(row['person_index_word']),{}))
        team=identities['teams'].get(row['team_index_word'],identities['teams'].get(str(row['team_index_word']),{}));owner=team.get('owner') or {}
        result.append({**row,'canonical_person_id':person.get('native_id'),'person_name':person.get('display_name') or person.get('name'),'identity_state':person.get('identity_state','unresolved_source_local_word'),'person_identity':person,'canonical_team_id':team.get('native_id'),'team_name':owner.get('short_name') or owner.get('name'),'canonical_club_id':owner.get('native_id'),'team_identity':team})
    return result
