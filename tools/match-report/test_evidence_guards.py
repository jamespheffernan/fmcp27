import hashlib
import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('report',Path(__file__).with_name('render_match_report.py'))
report=importlib.util.module_from_spec(spec);spec.loader.exec_module(report)

class EvidenceGuards(unittest.TestCase):
    def fixture(self):
        digest=hashlib.sha256(b'child').hexdigest()
        data={'match_key':7,'players':[{'side':0,'id':42,'slot':3,'minutes':90,'source_row_sha256':digest,'pressures_completed':0}], 'provenance':[]}
        capture=({'raw_frames':[{'key':7,'raw_sha256':'frame'}]}, {})
        evidence={'state':'verified_raw_frame_boundary_and_canonical_player_pressure_fields','native_match_key':7,'raw_frame_sha256':'frame','rows':[{'side_index':0,'canonical_person_id':42,'fixture_key':7,'stored_player_slot':3,'minutes':90,'row_sha256':digest,'raw_child_hex':b'child'.hex(),'pressures_attempted':0,'pressures_completed':0,'pressure_completion_percentage_computed':None,'pressure_completion_state':'undefined_zero_pressure_attempts'}],'sides':[{'side_index':0,'pressures_attempted':0,'pressures_completed':0,'pressure_completion_percentage_computed':None}]}
        return data,capture,evidence
    def test_zero_denominator_stays_null(self):
        d,c,e=self.fixture();r=report.add_pressure_evidence(d,c,(e,{}));self.assertIsNone(r['players'][0]['pressure_completion_percentage_computed'])
    def test_other_frame_rejected(self):
        d,c,e=self.fixture();e['raw_frame_sha256']='other'
        with self.assertRaisesRegex(ValueError,'raw frame'):report.add_pressure_evidence(d,c,(e,{}))
    def test_child_bytes_mismatch_rejected(self):
        d,c,e=self.fixture();e['rows'][0]['raw_child_hex']=b'wrong'.hex()
        with self.assertRaisesRegex(ValueError,'raw child'):report.add_pressure_evidence(d,c,(e,{}))
    def test_missing_row_not_assumed_zero(self):
        d,c,e=self.fixture();e['rows']=[]
        with self.assertRaisesRegex(ValueError,'full roster'):report.add_pressure_evidence(d,c,(e,{}))
    def test_completion_above_attempts_rejected(self):
        d,c,e=self.fixture();e['rows'][0]['pressures_completed']=1
        with self.assertRaisesRegex(ValueError,'Invalid pressure'):report.add_pressure_evidence(d,c,(e,{}))
    def test_team_ratio_not_mean_of_players(self):
        d,c,e=self.fixture();e['sides'][0]['pressure_completion_percentage_computed']=0
        with self.assertRaisesRegex(ValueError,'team ratio'):report.add_pressure_evidence(d,c,(e,{}))

    def key_fixture(self):
        data={'match_key':7,'teams':[{'native_id':99}],'players':[{'side':0,'id':42,'slot':3,'key_passes':3}], 'provenance':[]}
        capture=({'raw_frames':[{'key':7,'raw_sha256':'frame'}]}, {})
        evidence={'native_match_key':7,'raw_frame_sha256':'frame','sides':[{'side_index':0,'team_native_id':99,'official_key_pass_total':3,'player_checks':[{'person_native_id':42,'stored_player_slot':3,'official_key_passes':3,'source_annotation_count':2,'counts_match':False,'state':'unavailable_key_pass_counter_mismatch'}]}],'annotations':[]}
        return data,capture,evidence
    def test_withheld_key_passes_stay_null(self):
        d,c,e=self.key_fixture();r=report.add_key_pass_evidence(d,c,(e,{}));self.assertIsNone(r['players'][0]['retained_key_pass_annotations'])
    def test_contradictory_key_pass_flag_rejected(self):
        d,c,e=self.key_fixture();e['sides'][0]['player_checks'][0]['counts_match']=True
        with self.assertRaisesRegex(ValueError,'closure flag'):report.add_key_pass_evidence(d,c,(e,{}))
    def test_missing_supported_annotations_rejected(self):
        d,c,e=self.key_fixture();check=e['sides'][0]['player_checks'][0];check['counts_match']=True;check['source_annotation_count']=3
        with self.assertRaisesRegex(ValueError,'annotations are incomplete'):report.add_key_pass_evidence(d,c,(e,{}))

if __name__=='__main__':unittest.main()
