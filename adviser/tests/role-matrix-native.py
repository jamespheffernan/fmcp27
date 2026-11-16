"""Finite actual donor-pair experiment using original code in offline Unicorn."""
from pathlib import Path
import hashlib,importlib.util,itertools,json,struct,sys
from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_WRITE,UC_HOOK_MEM_READ_UNMAPPED,UC_HOOK_MEM_FETCH_UNMAPPED
from unicorn.arm64_const import UC_ARM64_REG_PC,UC_ARM64_REG_SP,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21
sys.path.append('/Users/jamesheffernan/GitHub/FM26 Deepener/.venv/lib/python3.14/site-packages')
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('writer',ROOT/'pi/fm-tactic-files.py');w=importlib.util.module_from_spec(spec);spec.loader.exec_module(w)
PLUGIN=w.ROLE_NATIVE_PLUGIN
HERE=Path(__file__).resolve().parent
with PLUGIN.open('rb') as stream:
    assert hashlib.file_digest(stream,'sha256').hexdigest()=='774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
    stream.seek(0x5ED4000);header=struct.unpack('<IIIIIIII',stream.read(32));assert header[0]==0xFEEDFACF
    at=0x5ED4000+32;segments=[]
    for _ in range(header[4]):
        stream.seek(at);command,size=struct.unpack('<II',stream.read(8))
        if command==0x19:
            name=stream.read(16).rstrip(b'\0').decode();vmaddr,vmsize,fileoff,filesize=struct.unpack('<QQQQ',stream.read(32));segments.append((name,vmaddr,vmsize,fileoff,filesize))
        at+=size
    groups={}
    for path in sorted(w.TEMPLATES.glob('*.fmf')):
        _,blob,members=w.read_template(str(path));tac=members['.tac']
        for phase,records in w.phase_records(tac).items():
            for r in records:
                prefix=tac[r['record_offset']:r['role_word_offset']]
                key=(tac[11],phase,r['position_index'],w.sha(prefix))
                groups.setdefault(key,{})[r['native_role_word']]={'path':str(path),'sha256':w.sha(blob),'record':r,'tac':tac}
    results=[]
    for (major,phase,slot,prefix_sha),variants in groups.items():
        for source,donor in itertools.permutations(variants.values(),2):
            a,b=source['record'],donor['record'];raw=source['tac'];entries=[]
            assert a['position_mask']==b['position_mask']
            for i in range(a['instruction_entry_count']):
                off=a['instruction_vector_offset']+i*24
                assert raw[off+8:off+11]==b'\2\2\2'
                entries.append((struct.unpack_from('<Q',raw,off)[0],struct.unpack_from('<Q',raw,off+11)[0]))
            record,vector,stack=0x10000000,0x10010000,0x20000000
            uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM);uc.mem_map(record,4096);uc.mem_map(vector,4096);uc.mem_map(stack,0x10000)
            uc.mem_write(record,struct.pack('<I',a['position_mask']));uc.mem_write(record+8,struct.pack('<QQQ',vector,vector+len(entries)*24,vector+len(entries)*24));uc.mem_write(record+0x40,bytes.fromhex(a['native_role_word'])[::-1])
            vec=b''.join(struct.pack('<QQQ',key,bits,0) for key,bits in entries);uc.mem_write(vector,vec)
            mapped={record,vector};pages={};pcs=[];writes=[]
            def fault(machine,kind,address,size,value,data):
                page=address&~4095
                if page in mapped:return False
                if page<4096:raise AssertionError('Unproved zero/null native context read')
                seg=next((s for s in segments if s[1]<=page and page+4096<=s[1]+s[4]),None)
                if seg is None:raise AssertionError(f'Uncaptured native context {address:x}')
                stream.seek(0x5ED4000+seg[3]+page-seg[1]);chunk=stream.read(4096);assert len(chunk)==4096
                machine.mem_map(page,4096);machine.mem_write(page,chunk);mapped.add(page);pages[page]=w.sha(chunk);return True
            def code(machine,address,size,data):
                pcs.append(address)
                if len(pcs)>=10000:raise AssertionError('Instruction bound reached')
            def write(machine,kind,address,size,value,data):
                assert stack<=address and address+size<=stack+0x10000 or address==record+0x40 and size==8 or vector<=address and address+size<=vector+len(vec),f'Unproved native write {address:x}'
                writes.append((address,size,value))
            uc.hook_add(UC_HOOK_MEM_READ_UNMAPPED|UC_HOOK_MEM_FETCH_UNMAPPED,fault);uc.hook_add(UC_HOOK_CODE,code);uc.hook_add(UC_HOOK_MEM_WRITE,write)
            uc.reg_write(UC_ARM64_REG_SP,stack+0xF000);uc.reg_write(UC_ARM64_REG_X19,0);uc.reg_write(UC_ARM64_REG_X20,record);uc.reg_write(UC_ARM64_REG_X21,int(b['native_role_word'],16))
            start,stop=(0x539184,0x5391CC) if phase=='in_possession' else (0x539508,0x53954C)
            error=None
            try:
                uc.emu_start(start,stop,count=10000);assert uc.reg_read(UC_ARM64_REG_PC)==stop
            except Exception as exc:error=str(exc)
            word=int.from_bytes(uc.mem_read(record+0x40,8),'little');preserved=uc.mem_read(vector,len(vec))==vec
            row={'major':major,'phase':phase,'slot':slot,'position':a['position_name'],'prefix_sha256':prefix_sha,'source':source['path'],'source_sha256':source['sha256'],'donor':donor['path'],'donor_sha256':donor['sha256'],'source_word':a['native_role_word'],'requested_donor_word':b['native_role_word'],'native_result_word':f'{word:016x}','source_role':a['role'],'donor_role':b['role'],'instructions':len(pcs),'IP_validator_calls':pcs.count(0x4973360),'OOP_validator_calls':pcs.count(0x4975150),'PI_preserved':preserved,'matches_donor':not error and word==int(b['native_role_word'],16) and preserved,'error':error,'native_pages':pages,'native_live_calls':False,'game_import_verified':False}
            results.append(row)
            print(major,phase,slot,a['role']['compiled_english_name'],'->',b['role']['compiled_english_name'],row['matches_donor'],row['native_result_word'],row['instructions'],flush=True)
    assert len(results) == 26 and all(r['matches_donor'] for r in results)
    for r in results:
        mask,prefix,words,bits=w.MATRIX_ROLE_CASES[(r['major'],r['phase'],r['slot'])]
        assert prefix==r['prefix_sha256'] and int(r['source_word'],16) in words and int(r['requested_donor_word'],16) in words
    expected={offset:digest for offset,size,digest in w.MATRIX_ROLE_NATIVE_SPANS if size==4096}
    assert {int(address):digest for r in results for address,digest in r['native_pages'].items()}==expected
    output=Path(sys.argv[1]) if len(sys.argv)>1 else ROOT/'tmp/role-matrix-native.json'
    output.parent.mkdir(exist_ok=True,parents=True)
    output.write_text(json.dumps(results,indent=2)+'\n')
    print('exact donor matches',sum(r['matches_donor'] for r in results),'of',len(results))
