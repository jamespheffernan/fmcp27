from unittest.mock import patch
import pytest
from fm_live_mcp import live_match_identities as identity


def test_join_preserves_source_identity_and_missing_virtual_name():
    rows=[{'person_index_word':7,'team_index_word':5,'minutes':90}, {'person_index_word':8,'team_index_word':6,'minutes':None}]
    source={'people':{'7':{'native_id':700,'name':None,'record_kind':'virtual','identity_state':'same_snapshot_canonical_PERSON'}},'teams':{'5':{'native_id':500,'owner':{'native_id':501,'short_name':'Club'}}}}
    joined=identity.join(rows,source)
    assert joined[0]['canonical_person_id']==700 and joined[0]['person_name'] is None
    assert joined[0]['canonical_team_id']==500 and joined[0]['canonical_club_id']==501
    assert joined[1]['canonical_person_id'] is None and joined[1]['identity_state']=='unresolved_source_local_word'
    assert rows[0]=={'person_index_word':7,'team_index_word':5,'minutes':90}


def test_resolve_preserves_unsupported_person_and_team():
    with patch.object(identity.assessment_people,'verify_native'),patch.object(identity.database,'table',return_value={'identity':('people',)}),patch.object(identity.teams,'lookup',return_value={'lookup_identity':('teams',)}),patch.object(identity.live_team_sheet_source,'_person',side_effect=ValueError('unsupported')),patch.object(identity.teams,'by_index',side_effect=ValueError('missing')):
        result=identity.resolve(None,0,[7,7],[5])
    assert len(result['people'])==1 and result['people'][7]['native_id'] is None
    assert result['teams'][5]['reason']=='missing'


def test_resolve_rejects_changed_table():
    with patch.object(identity.assessment_people,'verify_native'),patch.object(identity.database,'table',side_effect=[{'identity':('before',)},{'identity':('after',)}]),patch.object(identity.teams,'lookup',return_value={'lookup_identity':('teams',)}):
        with pytest.raises(ValueError,match='table changed'):
            identity.resolve(None,0,[],[])
