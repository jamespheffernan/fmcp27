"""Actual captured PLAYER counters and near-identical invalid-source controls."""
from historical_match_identity_fixture import historical_team_identity_contract
from copy import deepcopy
import gzip,hashlib,json,struct,unittest
from pathlib import Path
from fm_live_mcp import current_player_passing as counter,world

PACKET=Path(__file__).resolve().parent/'fixtures/current_player_passing140.json.gz'

class Original:
    historical_identity_fixture = PACKET.name
    def __init__(self):
        assert hashlib.sha256(gzip.decompress(PACKET.read_bytes())).hexdigest()=='0cdfa3197a6aaf9b1b64f180b8d58779b88b37ce6698fc83bc89e12fabeef3de'
        self.packet=json.loads(gzip.decompress(PACKET.read_bytes()));self.memory={};self.reads=[]
        for r in self.packet['raw_consumed_byte_journal']['regions']:
            at=int(r['address'],16)
            for i,b in enumerate(bytes.fromhex(r['rawhex'])):
                if at+i in self.memory:assert self.memory[at+i]==b
                self.memory[at+i]=b
        self.base=int(self.packet['plugin']['base_private'],16);self.engine=self.packet['context_before']['private']['engine'];self.uid=self.packet['context_before']['official_match_unique_id']
    def read(self,a,n):
        self.reads.append((a,n))
        try:return bytes(self.memory[a+i] for i in range(n))
        except KeyError as ex:raise ValueError('Missing original captured byte') from ex
    def write(self,a,raw):
        for i,b in enumerate(raw):self.memory[a+i]=b
    def run(self):
        r=world.ReadSet(self.read);out=counter.inspect(r,self.base,self.engine,expected_match_unique_id=self.uid);r.verify();return out
    def raw(self,state='raw_typed_engine_PLAYER_bytes'):
        return next(r for r in self.packet['rows'] if r['state']==state)

class CurrentPlayerPassingTests(unittest.TestCase):
    def setUp(self):self.f=Original()
    def test_actual40_counter_rows_and12_unknown_rows(self):
        out=self.f.run();self.assertEqual(out['state'],'available_partial');self.assertEqual(out['coverage'],dict(resident_slots=52,available_counter_rows=40,unavailable_rows=12,complete_on_pitch_population_verified=False))
        for actual,original in zip(out['rows'],self.f.packet['rows'],strict=True):
            self.assertEqual(actual['person'],original['person']);self.assertEqual(actual['identity_state'],original['identity_state'])
            self.assertEqual((actual['side_index'],actual['engine_array_index']),(original['side_index'],original['engine_array_index']))
            if original['state']=='raw_typed_engine_PLAYER_bytes':
                attempts,completed=bytes.fromhex(original['raw_BA_BB_hex']);self.assertEqual(actual['state'],'available_native_counter_observation');self.assertEqual((actual['passes_attempted'],actual['passes_completed']),(attempts,completed));self.assertEqual(actual['pass_completion_percentage_computed'],100*completed/attempts if attempts else None)
            else:
                self.assertEqual(actual['state'],original['state']);self.assertIsNone(actual['passes_attempted']);self.assertIsNone(actual['passes_completed']);self.assertIsNone(actual['pass_completion_percentage_computed'])
        for flag in ['native_timestamp_association','displayed_time_verified','counter_publication_fence_verified','atomic_snapshot_verified','participation_verified','complete_side_total_verified']:self.assertIs(out[flag],False)
        self.assertEqual(sum(r['passes_attempted']==r['passes_completed']==0 for r in out['rows']),10)
        # No native clocks or raw PLAYER window may be consumed incidentally.
        forbidden=[(self.f.engine+0x154dc,4)]
        self.assertTrue(all(a+size<=at or at+n<=a for a,size in self.f.reads for at,n in forbidden))
        self.assertTrue(all(size!=0xc0 for a,size in self.f.reads))
    def test_unsigned_extremes_and_zero_percentage(self):
        raw=self.f.raw();stats=int(raw['stats_private'],16)
        for a,b in [(0,0),(255,255),(255,0),(255,254),(128,127)]:
            with self.subTest(a=a,b=b):
                self.f.write(stats+0xba,bytes([a,b]));out=self.f.run()['rows'][raw['side_index']*26+raw['engine_array_index']];self.assertEqual((out['passes_attempted'],out['passes_completed']),(a,b));self.assertEqual(out['pass_completion_percentage_computed'],100*b/a if a else None)
    def test_completed_greater_than_attempted_refuses(self):
        self.f.write(int(self.f.raw()['stats_private'],16)+0xba,b'\x01\x02')
        with self.assertRaisesRegex(ValueError,'completed exceeds'):self.f.run()
    def test_stats_PERSON_mismatch_stays_unknown(self):
        row=self.f.raw();self.f.write(int(row['stats_private'],16)+0x18,struct.pack('<I',row['stats_person_index']+1));out=self.f.run()['rows'][row['side_index']*26+row['engine_array_index']];self.assertEqual(out['state'],'unavailable_stats_person_mismatch');self.assertIsNone(out['passes_completed'])
    def test_null_stats_stays_unknown(self):
        row=self.f.raw();self.f.write(int(row['match_player_private'],16)+0x1880,b'\0'*8);out=self.f.run()['rows'][row['side_index']*26+row['engine_array_index']];self.assertEqual(out['state'],'unavailable_stats');self.assertIsNone(out['passes_attempted'])
    def test_changed_source_guards_refuse(self):
        for at,raw in (*counter.SOURCE_SPANS,*counter.people.ACTOR_SLOT_SPANS):
            with self.subTest(rva=hex(at)):
                f=Original();f.write(f.base+at,bytes([raw[0]^1])+raw[1:])
                with self.assertRaisesRegex(ValueError,'native source changed'):f.run()
    def test_changed_stats_type_refuses(self):
        self.f.write(int(self.f.raw()['stats_private'],16),struct.pack('<Q',self.f.base+0x55fa850))
        with self.assertRaisesRegex(ValueError,'type changed'):self.f.run()
    def test_changed_owner_and_original_slot_refuse(self):
        raw=self.f.raw();mp=int(raw['match_player_private'],16)
        for at,value in [(mp+0x280,struct.pack('<Q',self.f.engine+8)),(mp+0x288,struct.pack('<Q',self.f.engine+16)),(mp+0x1e27,b'\xff')]:
            with self.subTest(at=hex(at)):
                f=Original();f.write(at,value)
                with self.assertRaises(ValueError):f.run()
    def test_bad_uid_refuses(self):
        for uid in [None,False,True,0,-1,1<<64,self.f.uid+1]:
            with self.subTest(uid=uid):
                with self.assertRaises(ValueError):counter.inspect(self.f.read,self.f.base,self.f.engine,expected_match_unique_id=uid)
    def test_missing_counter_byte_refuses_not_zero(self):
        del self.f.memory[int(self.f.raw()['stats_private'],16)+0xbb]
        with self.assertRaisesRegex(ValueError,'Missing original captured byte'):self.f.run()
    def test_late_counter_drift_refuses(self):
        read=world.ReadSet(self.f.read);counter.inspect(read,self.f.base,self.f.engine,expected_match_unique_id=self.f.uid);stats=int(self.f.raw()['stats_private'],16);self.f.write(stats+0xba,b'\xff')
        with self.assertRaisesRegex(ValueError,'Game state changed'):read.verify()
    def test_late_PERSON_drift_refuses(self):
        read=world.ReadSet(self.f.read);counter.inspect(read,self.f.base,self.f.engine,expected_match_unique_id=self.f.uid);mp=int(self.f.raw()['match_player_private'],16);self.f.write(mp+0x20,b'\0'*8)
        with self.assertRaisesRegex(ValueError,'Game state changed'):read.verify()
    def test_duplicate_PERSON_refuses(self):
        rows=[r for r in self.f.packet['rows'] if r['state']=='raw_typed_engine_PLAYER_bytes' and r['side_index']==0];p=int(rows[0]['match_player_private'],16);q=int(rows[1]['match_player_private'],16);self.f.write(q+0x20,self.f.read(p+0x20,8))
        with self.assertRaisesRegex(ValueError,'Duplicate canonical'):self.f.run()

if __name__=='__main__':unittest.main()
