import copy,hashlib,importlib.util,struct,unittest
from pathlib import Path

spec=importlib.util.spec_from_file_location('pass_location_evidence',Path(__file__).with_name('pass_location_evidence.py'))
q=importlib.util.module_from_spec(spec);spec.loader.exec_module(q)


class PassLocationGuards(unittest.TestCase):
    def fixture(self):
        f={'date':'2030-11-06','competition':{'native_id':9},'home_team':{'database_index':1,'native_id':10,'native_type_code':0},'away_team':{'database_index':2,'native_id':20,'native_type_code':0}}
        geometry={'half_width_native':34.,'half_length_native':52.5};rawframe=b'';roster=[];players=[]
        for side in(0,1):
            for slot in(0,1):
                word=11+side*2+slot;child=bytearray(100);child[0]=2;struct.pack_into('<I',child,1,word);child[86]=int(slot==0);child[87]=int(side==0 and slot==0)
                start=len(rawframe);rawframe+=bytes(child);digest=hashlib.sha256(child).hexdigest();identity=100+side*2+slot
                p={'fixture_key':7,'side_index':side,'stored_player_slot':slot,'canonical_person_id':identity,'person_index_word':word,'person_name':f'Player{side}-{slot}',
                   'team_index_word':side+1,'canonical_team_id':(10,20)[side],'raw_child_hex':child.hex(),'row_sha256':digest,'start':start,'end':len(rawframe),'passes_attempted':child[86],'passes_completed':child[87]}
                roster.append(p);players.append({'side':side,'slot':slot,'id':identity,'name':p['person_name'],'source_row_sha256':digest,'passes_attempted':child[86],'passes_completed':child[87]})
        events=[]
        for side in(0,1):
            e=bytearray(56);struct.pack_into('<ff',e,24,10. if side==0 else 40.,25.);e[39:43]=bytes((0,side,1 if side==0 else 255,7 if side==0 else 9));struct.pack_into('<I',e,44,side+1);struct.pack_into('<H',e,48,256);events.append(bytes(e))
        raw=b''.join(events);eventhash=hashlib.sha256(raw).hexdigest();framehash=hashlib.sha256(rawframe).hexdigest();mapping={(p['side_index'],p['stored_player_slot']):p for p in roster}
        evidence={'state':q.STATE,'native_match_key':7,'fixture':f,'raw_frame_sha256':framehash,'raw_events_sha256':eventhash,'source_events_hex':raw.hex(),'pitch_geometry':geometry,
                  'native_binding_proof':{'state':'verified_expected_installed_native_pass_map_spans'},'points':[q._point(e,i,mapping,geometry)for i,e in enumerate(events)]}
        capture={'receipt':{'same_native_epoch_verified':True,'raw_events_sha256':eventhash},'raw_frames':[{'key':7,'raw_sha256':framehash,'raw':{'_bytes_hex':rawframe.hex(),'sha256':framehash}}],'retained_players':roster}
        data={'match_key':7,'fixture':f,'geometry':geometry,'players':players,'team_totals':[{'side_index':0,'passes_attempted':1,'passes_completed':1},{'side_index':1,'passes_attempted':1,'passes_completed':0}],'provenance':[],'existing_layer':{'preserve':True}}
        return data,capture,evidence
    def add(self,d,c,e):return q.add_pass_location_evidence(d,(c,{}),(e,{}))
    def test_complete_counter_population_and_outside_point_are_preserved(self):
        d,c,e=self.fixture();result=self.add(d,c,e);r=result['pass_event_locations']
        self.assertEqual(len(r['points']),2);self.assertEqual(r['side_coverage'][1]['outside_pitch_count'],1)
        self.assertEqual(r['side_coverage'][0]['player_counter_checks'],2);self.assertEqual(result['existing_layer'],{'preserve':True})
    def test_legacy_xy_not_promoted(self):
        d,c,e=self.fixture();e['state']='legacy_raw_xy';r=self.add(d,c,e)['pass_event_locations']
        self.assertIsNone(r['points']);self.assertEqual(r['state'],'unavailable_missing_verified_pass_event_locations')
    def test_mutated_location_or_bins_fail_native_byte_join(self):
        for field,value in [('native_x',99),('analytical_pitch_third','defensive'),('inside_native_pitch_extents',False),('recipient_person_native_id',999)]:
            d,c,e=self.fixture();e['points'][0][field]=value
            with self.subTest(field=field),self.assertRaisesRegex(ValueError,'point fields'):self.add(d,c,e)
    def test_missing_or_added_events_cannot_be_counter_complete(self):
        for mutation in('missing','extra'):
            d,c,e=self.fixture()
            if mutation=='missing':e['points'].pop()
            else:e['points'].append(copy.deepcopy(e['points'][0]))
            with self.subTest(mutation=mutation),self.assertRaisesRegex(ValueError,'event membership'):self.add(d,c,e)
    def test_wrong_fixture_frame_or_event_hash_reject(self):
        for field in('native_match_key','raw_frame_sha256','raw_events_sha256'):
            d,c,e=self.fixture();e[field]=99 if field=='native_match_key'else'bad'
            with self.subTest(field=field),self.assertRaises(ValueError):self.add(d,c,e)
    def test_changed_child_counters_or_original_slots_reject(self):
        for mutation in('counter','slot','identity','child'):
            d,c,e=self.fixture();p=c['retained_players'][0]
            if mutation=='counter':p['passes_completed']=0
            elif mutation=='slot':p['stored_player_slot']=9
            elif mutation=='identity':p['canonical_person_id']=999
            else:p['raw_child_hex']=bytes(100).hex()
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.add(d,c,e)
    def test_missing_roster_row_stays_unavailable_not_false_zero(self):
        d,c,e=self.fixture();c['retained_players'].pop()
        with self.assertRaisesRegex(ValueError,'roster is incomplete'):self.add(d,c,e)
    def test_unverified_native_binding_or_epoch_reject(self):
        d,c,e=self.fixture();e.pop('native_binding_proof')
        with self.assertRaisesRegex(ValueError,'native binding'):self.add(d,c,e)
        d,c,e=self.fixture();c['receipt']['same_native_epoch_verified']=False
        with self.assertRaisesRegex(ValueError,'epoch'):self.add(d,c,e)


if __name__=='__main__':unittest.main()
