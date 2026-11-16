"""Current native responsibility queries over the own stored CLUB population."""
import hashlib
import struct
import time

import unicorn as uc
from unicorn import arm64_const as arm
from . import assessment_people, club_staff_responsibilities as stored, database, teams,world
from . import knowledge_retained_person as retained

NATIVE_SPANS = (
    (0x17b9558, 312, '5cdd26745bcd5dd4b94a929ce5260436c6a74df245748196ada53f50752ad7c0', 'code'),
    # The resolver and the selector as (start, end): their whole functions run here, and both
    # grew on 27.0.1 (632 -> 652 and 840 -> 864 bytes), so the span follows the mapped ends.
    (0x15c18a4, 0x15c1b1c, '0a979f02b341e88c5988157dbb5df5d397d4f4557f569b59fd1fe573753de0e6', 'code'),
    (0x15b6654, 104, 'e1d4e862c689024285f94f3fc10d78a84beff8cbb1bdbfd4b0e36902460771a3', 'code'),
    (0x15b66bc, 72, '216aefcd90604544aa5275275b150814eeb4dcfb66b67de8f0a2233a80976da7', 'code'),
    (0x1084ca4, 300, 'b6823950094e48633de8533ebaf0cdd8d9d10ff0a110f74a98b9cfc41b009eac', 'code'),
    (0x15c1254, 256, '84586b709895e10c958a560e2c6524035d8c71f250a53968435daf0f484d03c5', 'code'),
    (0x17bb4c0, 2056, 'ceaf44b1f88181479f71d0241766f2bc6f1acc530a73ccce5645a08101eb7878', 'code'),
    (0x17bbfc8, 0x17bc310, '82a09dd7b6d5573ac5deb5fd0cd60fbedef6a97bbdf832bf72abc586c4103533', 'code'),
    (0x17bb120, 472, '08388c4ef58e124a618701183b33e5dc274254d636b2f35b4b8930d573362859', 'code'),
    (0x15c06cc, 72, '9b25e636d2efe7652a426b01313af2b26b4edf32e6f433f9dc156e14d49b2f3b', 'code'),
    (0x15b7480, 56, 'c1f51fd59193c7501d1600461f6e02e4c83380b62458fe18d84dfb43b49e5b5f', 'code'),
    (0x539e968, 91, '2d80edba7dba6bd048f0e2da4bebbe2ab229d307b0b2621e4723f97ba2bbe34b', 'data'),
    (0xe2767c, 216, '2cbf244ebd582d26650d8cea46ef61433ad412faec7ad7e28609be1543c7607a', 'code'),
    (0xe27754, 432, '5e114ccb87d69d25a805df2a8d38b790317181f1aa0c17196703885acaa60379', 'code'),
    (0x5389a4e, 91, '2fc726cecf7ae78c9e7b2bb62ceb656bd53b7b1a2234db63721409fc874d3ac5', 'data'),
    (0x1300058, 8, '5103ba3de080c52a046485f800433848701faa49ab8f60241a80987ca249d7ac', 'code'),
    (0x1300074, 20, '3f6f9d5a8b337d573adebd2a1339b59a12468aba23fb837448a097c1ff86c9fa', 'code'),
    (0xca4638, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a', 'code'),
    (0xcb85fc, 1644, '671f408e0f459d91457c63d89717b3937b07703b9bdeebfe868c1ad1baa62b62', 'code'),
    (0xcb8c68, 20, '25c942ded4925619f93fb980c3fde293992b8e61aa50588e1f093c2a01e5cabb', 'code'),
    (0x129fffc, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a', 'code'),
    (0x129a4b8, 8, '23ba31bca6e99eeaeca35232f284c89f546e52d3ab4cc441902fc17db7fc1dc1', 'code'),
    (0x1bdbc08, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a', 'code'),
    (0x17bbcc8, 768, '8ec24f9fabb5633ddc061f005a736f7d466fa8f1a0a7226178b7f0a6eb415796', 'code'),
    (0xd8c3d0, 8, '94152e462f3e98d8d99662739e87c91ff06eb16d5afefc0047346c214bd99ac8', 'code'),
    (0xd88c6c, 8, '2f6110664dbd16b514a0c2c7c8326932a36e85d2f15b91e57ca76efd2c7a625a', 'code'),
    (0x15bb758, 12, 'e96bd5e844a15e4aa8e302510bc3212f7b689e12506d8e2052acd6acc81ed03d', 'data'),
)

SLOT_LIMIT = 128
STACK, STOP = 0x300000000000, 0x400000000000
LIMITATIONS = ('Current native delegate queries over the selected CLUB own stored responsibility '
    'slots, using the observed responsibility-list consumer flags: default candidate generation '
    'disabled and human delegates allowed. Stored references remain separate from current delegates. '
    'Native CLUB overrides and supported eligibility/context paths execute as original ARM64 in '
    'a private emulator. Unsupported callees, writes outside its private stack or exhausted bounds '
    'remain unavailable. Missing own source is unavailable, not empty. This does not establish the '
    'complete UI population, current edit-session changes, generated default candidates, workload, '
    'coaching stars or suitability. No function is called in the game process and no game-memory '
    'write is used.')


class NativePathUnavailable(ValueError):
    """A source path needs an unproved callee or unsupported private operation."""


def _private_overlap(at,n):
    return any(at < end and start < at+n for start,end in
               ((STACK,STACK+0x10000),(STOP,STOP+4096)))


def _external_reader(read):
    def external(at,n):
        if _private_overlap(at,n):
            raise NativePathUnavailable('external_source_overlaps_private_memory')
        return read(at,n)
    return external


class NativeSource:
    def __init__(self, read, base):
        self.read, self.base, self.code = _external_reader(read), base, []
        self.executed_instructions = 0
        for rva,size,digest,kind in NATIVE_SPANS:
            size = size-rva if size > rva else size          # (start, end) or (start, length)
            raw = stored._read(self.read,base+rva,size)
            if hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('Current responsibility native source changed')
            self.code.append((base+rva,raw,kind))

    def query(self, entry, args):
        if any(_private_overlap(value,1)for value in args):
            raise NativePathUnavailable('external_argument_overlaps_private_memory')
        vm = uc.Uc(uc.UC_ARCH_ARM64,uc.UC_MODE_ARM)
        mapped,known,executable,hooks = set(),set(),[],[]
        counts = {'instructions':0,'reads':0}
        errors = []
        current_word = [None]
        current_pc = [None]
        pending_return,returned = [False],[False]
        deadline = time.monotonic()+1

        def map_pages(at,n):
            for page in range(at&-4096,(at+n+4095)&-4096,4096):
                if page not in mapped:
                    if len(mapped) >= 512:
                        raise NativePathUnavailable('native_memory_budget_exhausted')
                    vm.mem_map(page,4096)
                    mapped.add(page)

        def hook(kind, callback):
            def guarded(*arguments):
                try:return callback(*arguments)
                except Exception as error:
                    errors.append(error)
                    raise
            hooks.append(vm.hook_add(kind,guarded))

        def fetch(at,n):
            if _private_overlap(at,n):
                # Supported routines address ABI frames through SP/FP. A
                # source-derived object/vector pointer must never read a saved
                # register merely because its number aliases private storage.
                register = None if current_word[0] is None else(current_word[0]>>5)&31
                # 15C18CC passes its one-byte team selector by address to
                # 15C1254. At this callee's SP the owned byte is exactly+0x4F.
                local_byte = (current_pc[0] == self.base+0x15C128C and register == 23 and n == 1
                              and at == machine_sp()+0x4F)
                if not (STACK <= at and at+n <= STACK+0x10000 and (register in (29,31) or local_byte)):
                    raise NativePathUnavailable('external_source_overlaps_private_memory')
                if not all(at+i in known for i in range(n)):
                    raise NativePathUnavailable('native_uninitialized_stack_read')
                return
            counts['reads'] += 1
            if counts['reads'] > 4096:
                raise NativePathUnavailable('native_operand_budget_exhausted')
            if not all(at+i in known for i in range(n)):
                if not 0 < n <= 16:
                    raise NativePathUnavailable('native_operand_width_not_supported')
                raw = stored._read(self.read,at,n)
                map_pages(at,n)
                vm.mem_write(at,raw)
                known.update(range(at,at+n))
            raw = bytes(vm.mem_read(at,n))
            if any(_private_overlap(int.from_bytes(raw[i:i+8],'little'),1)
                   for i in range(max(0,len(raw)-7))):
                raise NativePathUnavailable('source_value_overlaps_private_address_domain')

        def instruction(machine,pc,n,_):
            if pc == STOP:
                if not pending_return[0] or machine_sp() != STACK+0xF000:
                    raise NativePathUnavailable('return_monitor_reached_without_native_ret')
                returned[0] = True
                machine.emu_stop()
                return
            if not any(start <= pc and pc+n <= end for start,end in executable):
                raise NativePathUnavailable('native_callee_not_supported')
            current_word[0] = int.from_bytes(machine.mem_read(pc,4),'little')
            current_pc[0] = pc
            word = current_word[0]
            opcode,register = word&0xFFFFFC1F,(word>>5)&31
            pending_return[0] = False
            if opcode in (0xD61F0000,0xD63F0000):
                target = register_value(register)
                entries = {start for start,_ in executable}
                same_body = any(start<=pc<end and start<=target<end for start,end in executable)
                if (target not in entries and not (opcode==0xD61F0000 and same_body)
                        and not constant_return(target)):
                    raise NativePathUnavailable('native_indirect_callee_not_supported')
            elif opcode == 0xD65F0000 and register_value(register) == STOP:
                if register != 30 or machine_sp() != STACK+0xF000:
                    raise NativePathUnavailable('native_return_frame_not_restored')
                pending_return[0] = True
            counts['instructions'] += 1
            self.executed_instructions += 1
            if time.monotonic() > deadline:
                raise NativePathUnavailable('native_time_budget_exhausted')

        def constant_return(target):
            # 27.0.1's resolver and selector call the PERSON's virtual +0x510 (the hidden-PERSON
            # test, knowledge_retained_person). Only a plugin method that is a constant return
            # (mov w0|x0, #0 or #1; ret) runs; its 8 bytes are then executable for this query.
            from . import address_book
            if (address_book.ACTIVE.get('sha256') not in retained.HIDDEN_PERSON_PREDICATE_BUILDS
                    or not self.base <= target < self.base+(80<<20)):
                return False
            code = stored._read(self.read,target,8)
            if code not in (*retained._RETURNS_FALSE, retained._RETURNS_TRUE):
                return False
            map_pages(target,8)
            vm.mem_write(target,code)
            known.update(range(target,target+8))
            executable.append((target,target+8))
            return True

        def load(machine,access,at,n,value,_):fetch(at,n)

        def store(machine,access,at,n,value,_):
            if not (STACK <= at and at+n <= STACK+0x10000):
                raise NativePathUnavailable('native_nonstack_write_not_supported')
            register = None if current_word[0] is None else(current_word[0]>>5)&31
            local_byte = (current_pc[0] == self.base+0x15C12A0 and register == 23 and n == 1
                          and at == machine_sp()+0x4F)
            if register not in (29,31) and not local_byte:
                raise NativePathUnavailable('private_stack_object_access_not_supported')
            known.update(range(at,at+n))

        def machine_sp():return vm.reg_read(arm.UC_ARM64_REG_SP)

        def register_value(index):
            if index == 31:return 0
            register = (arm.UC_ARM64_REG_FP if index==29 else arm.UC_ARM64_REG_LR if index==30
                        else arm.UC_ARM64_REG_X0+index)
            return vm.reg_read(register)

        def invalid(machine,access,at,n,value,_):
            if access == uc.UC_MEM_FETCH_UNMAPPED:
                raise NativePathUnavailable('native_callee_not_supported')
            if access == uc.UC_MEM_WRITE_UNMAPPED:
                raise NativePathUnavailable('native_nonstack_write_not_supported')
            if access != uc.UC_MEM_READ_UNMAPPED:
                raise NativePathUnavailable('native_memory_access_not_supported')
            fetch(at,n)
            return True

        try:
            for at,raw,kind in self.code:
                map_pages(at,len(raw))
                vm.mem_write(at,raw)
                known.update(range(at,at+len(raw)))
                if kind == 'code':executable.append((at,at+len(raw)))
            map_pages(STACK,0x10000)
            map_pages(STOP,4)
            hook(uc.UC_HOOK_CODE,instruction)
            hook(uc.UC_HOOK_MEM_READ,load)
            hook(uc.UC_HOOK_MEM_WRITE,store)
            hook(uc.UC_HOOK_MEM_INVALID,invalid)
            vm.reg_write(arm.UC_ARM64_REG_SP,STACK+0xF000)
            vm.reg_write(arm.UC_ARM64_REG_LR,STOP)
            for index,value in enumerate(args):
                vm.reg_write(arm.UC_ARM64_REG_X0+index,value&((1<<64)-1))
            try:vm.emu_start(self.base+entry,0,count=10000)
            except uc.UcError as error:
                if errors:raise errors[0] from error
                raise NativePathUnavailable('native_execution_not_supported') from error
            if not returned[0]:
                raise NativePathUnavailable('native_instruction_budget_exhausted')
            return vm.reg_read(arm.UC_ARM64_REG_X0),counts['instructions']
        finally:
            for handle in hooks:vm.hook_del(handle)


def _result(report):
    result = {'state':'unavailable','reason':report.get('reason'),'club':report['club'],
        'source_slot_count':report['source_slot_count'],'records':None,
        'complete_native_current_queries_verified':False,'complete_UI_population_verified':False,
        'consumer_flags':{'default_candidate_generation':False,'allow_human_delegates':True},
        'original_native_code_emulated':False,'native_game_calls':False,'limitations':LIMITATIONS}
    return result


def _oversized_source(read,base,club):
    """Check admission before resolving up to4096 stored PERSON profiles."""
    stored.verify_native(read,base)
    canonical,_ = world.club(read,base,club)
    clubs = database.table(read,base,'clubs')
    index = struct.unpack('<I',stored._read(read,club+8,4))[0]
    database.club_membership(read,base,clubs,index,club)
    secondary = stored._pointer(read,club+0xB0,True)
    vector = stored._pointer(read,secondary+0x48,True) if secondary else 0
    count = len(stored._slots(read,vector)) if vector else None
    if count is None or count<=SLOT_LIMIT:return None
    result = _result({'club':{**canonical,'database_index':index},'source_slot_count':count})
    result['reason'] = 'native_query_slot_budget_exceeded'
    return result


def decode(read, base, club):
    """Caller rechecks every consumed byte after its final lifetime callbacks."""
    read = _external_reader(read)
    oversized = _oversized_source(read,base,club)
    if oversized is not None:return oversized
    report = stored.decode(read,base,club)
    result = _result(report)
    if report['state'] != 'available_own_stored_records':return result
    native = NativeSource(read,base)
    people = database.table(read,base,'people')
    rows,unavailable = [],0
    for stored_row in report['records']:
        row = dict(stored_row)
        row.update(context_team=None,current_delegate=None)
        if stored_row['state'] == 'null_slot':
            row['current_delegate'] = {'state':'null_stored_slot','person':None}
            rows.append(row)
            continue
        try:
            code,team_type = stored_row['responsibility_code'],stored_row['team_type_code']
            if team_type == -1:context = 0
            else:
                context,_ = native.query(0x17BBCC8,[club,team_type])
            if context:
                index = struct.unpack('<I',stored._read(read,context+8,4))[0]
                context_row,binding = teams.by_index(read,base,index)
                if binding['address'] != context:
                    raise ValueError('Current responsibility TEAM canonical membership changed')
                row['context_team'] = context_row
            person,_ = native.query(0x17BB4C0,[club,code,context,0,1])
            row['current_delegate'] = {'state':'resolved' if person else 'native_returned_none',
                'person':assessment_people.assessor(read,base,people,person) if person else None}
        except NativePathUnavailable as error:
            unavailable += 1
            row['current_delegate'] = {'state':'unavailable','reason':str(error),'person':None}
        rows.append(row)
    result.update(state='available_current_queries',reason=None,records=rows,
        unsupported_path_count=unavailable,original_instruction_count=native.executed_instructions,
        original_native_code_emulated=native.executed_instructions>0,
        complete_native_current_queries_verified=unavailable == 0)
    return result
