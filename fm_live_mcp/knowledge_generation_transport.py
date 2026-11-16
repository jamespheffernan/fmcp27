"""Private kernel generation checks around unchanged lazy native read streams.

Package copy of `evidence/knowledge-complete-identity-v2-20261109/generation_transport.py` (lane codex/continuous-knowledge-20261109, commit 268c3a2, SHA256 5eddd006337cd90c74e68b09f126e6832aa1187a957531aa1c92db8ab7e292fe); the code is unchanged.


proc_pidinfo signature: local macOS SDK libproc.h. Flavor17 and56-byte ABI:
Apple XNU bsd/sys/proc_info_private.h and bsd/kern/proc_info.c (pinned sources).
No game bytes, Bridge callbacks or game functions are read by kernel_identity.
"""
from copy import deepcopy
import ctypes
import errno
import hashlib
import struct


class ProcUniqueIdentifier(ctypes.Structure):
    _fields_=[('uuid',ctypes.c_ubyte*16),('uniqueid',ctypes.c_uint64),
        ('parent_uniqueid',ctypes.c_uint64),('idversion',ctypes.c_int32),
        ('original_parent_idversion',ctypes.c_int32),('reserved2',ctypes.c_uint64),
        ('reserved3',ctypes.c_uint64)]


assert ctypes.sizeof(ProcUniqueIdentifier)==56
assert ProcUniqueIdentifier.uniqueid.offset==16 and ProcUniqueIdentifier.idversion.offset==32
PROC_PIDUNIQIDENTIFIERINFO=17


class KernelIdentity:
    def __init__(self,library=None):
        self.library=library or ctypes.CDLL('/usr/lib/libproc.dylib',use_errno=True)
        self.pidinfo=self.library.proc_pidinfo
        self.pidinfo.argtypes=[ctypes.c_int,ctypes.c_int,ctypes.c_uint64,ctypes.c_void_p,ctypes.c_int]
        self.pidinfo.restype=ctypes.c_int

    def __call__(self,pid):
        if type(pid)is not int or not 1<=pid<1<<31:
            raise ValueError('Invalid kernel generation PID')
        info=ProcUniqueIdentifier()
        ctypes.set_errno(0)
        count=self.pidinfo(pid,PROC_PIDUNIQIDENTIFIERINFO,0,ctypes.byref(info),ctypes.sizeof(info))
        if count!=ctypes.sizeof(info):
            raise OSError(ctypes.get_errno()or errno.EIO,
                'Kernel generation metadata length differs from56: '+str(count))
        raw=ctypes.string_at(ctypes.byref(info),ctypes.sizeof(info))
        result=dict(pid=pid,process_unique_id=info.uniqueid,idversion_bits=info.idversion&0xffffffff,
            executable_uuid_hex=bytes(info.uuid).hex(),kernel_token_rawhex=raw.hex(),
            api='libproc.proc_pidinfo(PROC_PIDUNIQIDENTIFIERINFO17,arg0)',returned_bytes=count)
        token(result)
        return result


def token(record):
    assert type(record)is dict
    pid,unique,version,uuid=(record[k]for k in('pid','process_unique_id','idversion_bits','executable_uuid_hex'))
    if (type(pid)is not int or not 1<=pid<1<<31 or type(unique)is not int or not 0<unique<1<<64
            or type(version)is not int or not 0<=version<1<<32 or type(uuid)is not str or len(uuid)!=32):
        raise ValueError('Invalid kernel process generation token')
    bytes.fromhex(uuid)
    return pid,unique,version,uuid


def require_generation(observed,expected):
    if token(observed)!=token(expected):
        raise ValueError('Kernel process incarnation changed')


def bound_stream_type(base_type,kernel_identity,expected):
    """Use one pre-attachment generation baseline across every native port."""
    baseline=deepcopy(expected)
    token(baseline)
    class GenerationStream(base_type):
        def __init__(self,bridge,reader_type,helper,pid):
            owner=self
            class BoundPort:
                def __init__(self,path,process_id):
                    if process_id!=baseline['pid']:
                        raise ValueError('Kernel-bound native port PID differs')
                    self.inner=reader_type(path,process_id)
                    self.first=True;self.closed=False

                def checked(self,phase):
                    try:
                        observed=kernel_identity(pid)
                        owner.segment.setdefault('kernel_generation_checks',{})[phase]=deepcopy(observed)
                        require_generation(observed,baseline)
                        return observed
                    except Exception as exc:
                        owner.segment.setdefault('kernel_generation_errors',{})[phase]=dict(type=type(exc).__name__,error=str(exc))
                        raise

                def read(self,address,length):
                    if self.first:self.checked('before_lazy_port_open')
                    raw=self.inner.read(address,length)
                    if self.first:
                        self.checked('after_first_physical_read')
                        self.first=False
                    return raw

                def close(self):
                    try:self.checked('before_port_close')
                    finally:
                        self.inner.close()
                        self.closed=True
            super().__init__(bridge,BoundPort,helper,pid)

        def _close_segment(self):
            reader,self.reader=self.reader,None
            if reader is not None:
                try:reader.close()
                finally:
                    self.segment['closed']=reader.closed
                    self.segment['requests_and_raw_sha256']=self.digest.hexdigest()
                    self.segment['kernel_generation_baseline']=deepcopy(baseline)
    return GenerationStream
