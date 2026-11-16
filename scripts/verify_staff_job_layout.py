"""Verify native job conversion against installed code and labels.

Run: uv run --with capstone python scripts/verify_staff_job_layout.py
Evaluates only a bounded integer comparison/table function locally; no game calls.
"""
from pathlib import Path
import json,struct,re
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fm_live_mcp import players, staff_jobs
from fm_live_mcp.bridge import Bridge

bridge = Bridge()
bridge.attach()
try:
    bridge._player_layout(bridge.process)
    plugin = Path(bridge.plugin_identity[0][0])
finally:
    bridge.detach()
ROOT = plugin.parent.parent
with (ROOT/'MacOS/game_plugin').open('rb') as f:
 f.seek(0x5ed4000+0x13604d4);raw=f.read(0x708)
 f.seek(0x5ed4000+0x5395000);tables=f.read(0x1000)
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);code={i.address:(i.mnemonic,i.op_str) for i in cs.disasm(raw,0x13604d4)}
def convert(job,team):
 regs={0:job,1:0x100000000};left=right=0;pc=0x13604d4
 def val(x):
  if x.startswith('#'):return int(x[1:],0)
  if x in ('wzr','xzr'):return 0
  return regs[int(x[1:])] & (0xffffffff if x[0]=='w' else 0xffffffffffffffff)
 def put(x,v):regs[int(x[1:])]=v& (0xffffffff if x[0]=='w' else 0xffffffffffffffff)
 def condition(c):
  a,b=left,right
  signed=lambda x:x-(1<<32) if x&(1<<31) else x
  return {'eq':a==b,'ne':a!=b,'le':signed(a)<=signed(b),'gt':signed(a)>signed(b),'hi':a>b,'hs':a>=b}[c]
 for _ in range(100):
  op,tail=code[pc];args=tail.split(', ');nxt=pc+4
  if op in ('mov','adrp','adr'):put(args[0],val(args[1]))
  elif op=='movk':
   shift=int(args[2].split('#')[1]);put(args[0],(val(args[0])&~(65535<<shift))|(val(args[1])<<shift))
  elif op in ('add','sub','and','lsl'):
   a,b=val(args[1]),val(args[2]);b=b<<int(args[3].split('#')[1]) if len(args)>3 else b
   put(args[0],{'add':lambda:a+b,'sub':lambda:a-b,'and':lambda:a&b,'lsl':lambda:a<<(b&63)}[op]())
  elif op=='cmp':left,right=val(args[0]),val(args[1])
  elif op=='tst':left,right=val(args[0])&val(args[1]),0
  elif op=='csel':put(args[0],val(args[1]) if condition(args[3]) else val(args[2]))
  elif op=='cbz':
   if val(args[0])==0:nxt=val(args[1])
  elif op.startswith('b.'):
   if condition(op[2:]):nxt=val(args[0])
  elif op in ('b','br'):nxt=val(args[0])
  elif op in ('ldrb','ldrh'):
   dest,mem=tail.split(', [');parts=mem.rstrip(']').split(', ');addr=val(parts[0]);offset=val(parts[1]) if len(parts)>1 else 0
   if len(parts)>2:offset<<=int(parts[2].split('#')[1])
   addr+=offset
   if addr==0x100000028:value=team
   else:
    assert 0x5395000<=addr<0x5396000
    size=1 if op=='ldrb' else 2;value=int.from_bytes(tables[addr-0x5395000:addr-0x5395000+size],'little')
   put(dest,value)
  elif op=='ret':return val('w0')
  else:raise ValueError((hex(pc),op,tail))
  pc=nxt
 raise ValueError('Bound exceeded')

# Derive role names from the installed native label switch and English resource.
labels = {}
for line in (ROOT/'Resources/data/game_simulation/templates/user_folder/languages/example.ltf').read_text().splitlines():
    match = re.match(r'KEY-(\d+): (.*)', line)
    if match:
        labels[int(match[1])] = match[2].split('[COMMENT')[0].strip()
used = set()
for team in range(256):
    group = staff_jobs.TEAM_GROUP[team] if team < len(staff_jobs.TEAM_GROUP) else 2
    for job in range(256):
        actual = convert(job, team)
        expected = staff_jobs.JOB_GROUPS[group][job] if job < 90 else 0
        assert actual == expected, (team, job, actual, expected)
        used.add(actual)
label_evidence = []
with plugin.open('rb') as stream:
    stream.seek(0x5ed4000 + 0x539559c)
    jumps = struct.unpack('<502H', stream.read(1004))
    for code_value in sorted(used):
        rva = 0x1358b14 + jumps[code_value]*4
        stream.seek(0x5ed4000 + rva)
        instructions = list(cs.disasm(stream.read(20), rva))
        assert instructions[0].mnemonic == 'add' and instructions[0].op_str == 'x8, sp, #8'
        assert instructions[1].mnemonic == 'mov' and instructions[1].op_str.startswith('w1, #')
        assert instructions[2].mnemonic == 'movk' and instructions[2].op_str.endswith('lsl #16')
        assert instructions[3].mnemonic == 'bl' and instructions[3].op_str == '#0x43db8b8'
        translation = int(instructions[1].op_str.split('#')[1], 0)
        translation |= int(instructions[2].op_str.split('#')[1].split(',')[0], 0) << 16
        assert labels[translation] == staff_jobs.JOB_LABELS[code_value]
        label_evidence.append({'job_code': code_value, 'rva': hex(rva), 'translation_id': translation,
                               'title': labels[translation]})
    # The native caller passes contract getter slot 11 and the contract's first team.
    stream.seek(0x5ed4000 + 0xE0B19C)
    caller = [f'{i.mnemonic} {i.op_str}' for i in cs.disasm(stream.read(24), 0xE0B19C)]
    assert caller == ['ldr x8, [x20]', 'ldr x8, [x8, #0x58]', 'mov x0, x20',
                      'blr x8', 'ldr x1, [x20, #0x10]', 'bl #0x13604d4']
    stream.seek(0x5ed4000 + 0xD8C3C8)
    assert [f'{i.mnemonic} {i.op_str}'.strip() for i in cs.disasm(stream.read(8), 0xD8C3C8)] == [
        'ldrb w0, [x0, #0x26]', 'ret']
output = Path(__file__).resolve().parents[1]/'evidence/staff-job-layout-verification.json'
output.write_text(json.dumps({'verified': True, 'plugin_sha256': players.SHA256,
    'native_converter_rva': '0x13604d4', 'tested_combinations': 65536,
    'labels': label_evidence, 'scope': 'Static native conversion and installed labels; no game function execution or foreground UI comparison.'}, indent=2)+'\n')
print(f'Verified 65,536 job/team combinations, {len(used)} titles and the native contract caller. {output}')
