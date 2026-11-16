"""Immutable root-collected29-player training source, with strict missing bytes."""
import gzip
import hashlib
import json
from pathlib import Path
import struct


class GenuineTraining:
    def __init__(self):
        folder=Path(__file__).parent/'fixtures'
        raw=gzip.decompress((folder/'individual_training_roles_genuine.json.gz').read_bytes())
        assert hashlib.sha256(raw).hexdigest()=='2411f9a4a60a7617d1ecc8e3dfbfb07986c3c714d32456d4cb8052060ab794b1'
        self.packet=json.loads(raw);self.cells={};self.reads=[]
        for region in self.packet['journal']:
            at=region['address']
            for i,value in enumerate(bytes.fromhex(region['raw_hex'])):
                assert at+i not in self.cells or self.cells[at+i]==value
                self.cells[at+i]=value
        raw=(folder/'individual_training_roles_native29.json').read_bytes()
        assert hashlib.sha256(raw).hexdigest()=='6cb2270bc650a6cda869623c39b29a0b6c305c11bb4d31212d4dea62534877ca'
        self.native=json.loads(raw)
        assert self.native['capture_sha256']=='2411f9a4a60a7617d1ecc8e3dfbfb07986c3c714d32456d4cb8052060ab794b1'
        self.base=self.packet['base'];self.rows=self.packet['training']['rows']

    def read(self,at,n):
        self.reads.append((at,n))
        try:return bytes(self.cells[at+i]for i in range(n))
        except KeyError as error:raise ValueError(('Missing genuine training operand',hex(error.args[0])))from error

    def entries(self,row):
        child=int.from_bytes(self.read(row['primary']+0x1A0,8),'little')
        if not child:return None
        start,end,capacity=struct.unpack('<QQQ',self.read(child,24))
        assert (end-start)%24==0 and start<=end<=capacity and capacity-start<=256*24
        return tuple(self.read(at,24)for at in range(start,end,24))
