"""Check the bounded native identity/serializer routes without executing game code."""
from pathlib import Path
import hashlib,json,sys
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from fm_live_mcp import virtual_identity
HERE=ROOT/"evidence"
from fm_live_mcp import build_paths
P=build_paths.pinned_path(build_paths.PLUGIN_IN_APP)  # the pinned build (EXPECTED)
EXPECTED='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
CHECKS={
0x18a0f0c:'ldrsh x8, [x1, #0x14]',0x18a0f10:'tbnz x8, #0x3f, #0x18a0f44',0x18a0f44:'cbz w2, #0x18a1330',
0x18a47b8:'add x0, x19, #0x20',0x18a47d8:'bl #0x1474f98',
0x1475024:'add x24, x20, #8',0x1475038:'mov w2, #0xc',0x147503c:'blr x8',
0x1475090:'str w21, [x20, #8]',0x14750c8:'ldr x22, [x9, x8, lsl #3]',
0x1475108:'mov x1, x20',0x147510c:'mov x2, x21',0x1475110:'mov w3, #1',
0x147666c:'mov x0, x19',0x1476670:'mov x1, x21',0x1476694:'b #0x11b09a0',
0x11b0d4c:'str w0, [x19, #0xc]',0x11b0d68:'str w0, [x19, #0x10]',
0x11b28c4:'ldr w20, [x20, #0xc]',0x11b2aec:'ldp w8, w20, [x20, #0xc]',
0x11b2af0:'cmp w8, w20',0x11b2b00:'str w20, [sp, #0x20]',
0x18a4a9c:'ldr w8, [x0, #8]',0x18a4aa0:'tbnz w8, #0x1f, #0x18a4af0',
0x18a4aa4:'adrp x9, #0x56d2000',0x18a4aa8:'add x9, x9, #0xdb0',
0x18a4abc:'ldr x9, [x9, #0x88]',0x18a4ac8:'ldp x9, x10, [x9, #0x68]',
0x18a4adc:'ldr x8, [x8]',0x18a4ae4:'ldr x9, [x8, #0x30]',
0x18a60a0:'mov w2, #1',0x18a60a4:'bl #0x18a0ed0',
0x18a6130:'mov w2, #1',0x18a6134:'bl #0x18a0ed0',
0x18a61c0:'mov w2, #1',0x18a61c4:'bl #0x18a0ed0',
0x18a6244:'mov w2, #1',0x18a6248:'bl #0x18a0ed0',
}
SPANS=[(0x18a0f0c,0x3c),(0x18a4644,0x208),(0x1474f98,0x254),(0x14757bc,0x10a0),(0x11b0a04,0x370),
       (0x11b2404,0x770),(0x18a4a9c,0x68),(0x18a6074,0x50),(0x18a6104,0x50),(0x18a6194,0x50),(0x18a6220,0x48)]
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);spans=[]
with P.open('rb') as f:
 digest=hashlib.file_digest(f,'sha256').hexdigest();assert digest==EXPECTED
 for address,want in CHECKS.items():
  f.seek(0x5ed4000+address);i=next(cs.disasm(f.read(4),address));got=i.mnemonic+' '+i.op_str
  assert got==want,(hex(address),got,want)
 for address,size in SPANS:
  f.seek(0x5ed4000+address);spans.append({'rva':hex(address),'length':size,'hex':f.read(size).hex()})
with P.open('rb') as source:
 for address,expected in virtual_identity.NATIVE_SPANS:
  source.seek(0x5ed4000+address)
  assert source.read(len(expected))==expected,hex(address)
receipt={'verified':True,'plugin_sha256':digest,'instruction_checks':len(CHECKS),'bounded_spans':len(SPANS),
 'checked_claims':['Virtual serializer embeds PERSON at+0x20.','PERSON serialization stores three32-bit identity words from+8 and binds index+8 to canonical table entry.',
 'Virtual PERSON setter delegates duni/rdui through the shared setter, writing+C/+10 independently; base getter reads the same offsets.',
 'Compact+8 indexes native team tables and validates owner+0x30; it is not a permanent team ID.',
 'Name and date getter paths invoke manager lookup with flag1; no direct cold field returned by these checked paths.'],
 'native_calls':False,'game_writes':False}
(HERE/'virtual-identity-layout-verification.json').write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt,indent=2))
