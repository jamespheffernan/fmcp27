import struct,unittest
from fm_live_mcp.active_match_playback import capture,NATIVE_SPANS

class CaptureTests(unittest.TestCase):
 def setUp(self):
  self.base=0x100000000;self.mem={};self.interface=0x300000000;self.playback=0x300010000;self.provider=0x300020000;self.source=0x300030000;self.client=0x300040000;self.wrapper=0x300050000;self.engine=0x300060000
  for at, expected in NATIVE_SPANS:self.put(self.base+at,expected)
  self.q(self.base+0x5721eb0,self.interface);self.q(self.interface,self.base+0x54ec0c8);self.q(self.interface+0x58,self.playback);self.q(self.interface+0x60,0)
  self.q(self.playback,self.base+0x54ec490);self.q(self.playback+0x10,self.playback);self.q(self.playback+0x18,1);self.q(self.playback+0x1408,self.provider)
  self.q(self.provider+0x28,self.source);self.q(self.source,self.base+0x55fa258);self.q(self.source+0x20,12345)
  self.put(self.playback+0x1dc0,struct.pack('<II',800,900));self.put(self.playback+0x1ddc,struct.pack('<f',200));self.put(self.playback+0x1e4c,b'\x00')
  for off,n in [(0x5cc,688),(0x1378,11),(0x137c,11),(0x1380,765)]:self.put(self.playback+off,struct.pack('<I',n))
  self.q(self.client,self.base+0x55fac38);self.q(self.client+0xf8,self.wrapper);self.q(self.wrapper+0x18,self.engine);self.q(self.engine,self.base+0x55fa258);self.q(self.client+0x138,12345);self.q(self.engine+0x20,12345)
 def put(self,a,d):self.mem.update({a+i:b for i,b in enumerate(d)})
 def q(self,a,v):self.put(a,struct.pack('<Q',v))
 def read(self,a,n):return bytes(self.mem[a+i] for i in range(n))
 def run_capture(self):return capture(self.read,self.base,client=self.client)
 def test_exact_identity_and_raw_clock_preserve_buffer_ahead(self):
  r=self.run_capture();self.assertEqual(r['state'],'bound_playback_cursor');self.assertEqual(r['bound_playback']['current_time_slice'],800);self.assertEqual(r['bound_playback']['buffered_max_time_slice'],900);self.assertIsNone(r['no_hindsight_event_cutoff']);self.assertFalse(r['replay_exclusion_verified'])
 def test_catching_up_target_is_conditional_not_every_buffer_ahead(self):
  self.put(self.playback+0x1e4c,b'\x01');self.assertEqual(self.run_capture()['bound_playback']['official_catching_up_to_time_slice'],900)
 def test_other_match_not_silently_bound(self):
  self.q(self.source+0x20,54321);self.assertEqual(self.run_capture()['state'],'client_identity_not_retained')
 def test_no_client_has_no_identity_claim(self):self.assertEqual(capture(self.read,self.base)['state'],'present_client_unbound')
 def test_absent_interface_is_explicit(self):
  self.q(self.base+0x5721eb0,0);self.assertEqual(self.run_capture()['state'],'absent')
 def test_wrong_primary_and_playback_and_source_types_rejected(self):
  for address in [self.interface,self.playback,self.source]:
   old=self.read(address,8);self.q(address,0)
   with self.assertRaises(ValueError):self.run_capture()
   self.put(address,old)
 def test_client_engine_identity_mismatch_rejected(self):
  self.q(self.engine+0x20,999)
  with self.assertRaisesRegex(ValueError,'identities disagree'):self.run_capture()
 def test_duplicate_owner_is_ambiguous(self):
  self.q(self.interface+0x60,self.playback)
  with self.assertRaisesRegex(ValueError,'Duplicate'):self.run_capture()
 def test_cursor_beyond_buffer_rejected(self):
  self.put(self.playback+0x1dc0,struct.pack('<II',901,900))
  with self.assertRaisesRegex(ValueError,'exceeds'):self.run_capture()
 def test_source_guard_fails_closed(self):
  at,_=NATIVE_SPANS[0];self.put(self.base+at,b'\0')
  with self.assertRaisesRegex(ValueError,'guard mismatch'):self.run_capture()

if __name__=='__main__':unittest.main()
