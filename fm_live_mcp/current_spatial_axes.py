"""Build-pinned tracking axes; no forward sign, metres or human left/right."""

def verify_native(read, base):
    for rva, expected in NATIVE_SPANS:
        if read(base+rva, len(expected)) != expected:
            raise ValueError('Current spatial width/length native source changed')


NATIVE_SPANS = (
    (0x1a75bc, bytes.fromhex('280141bd290541bd0029281e4950a8522101271e0a18211e2029291e0959a8522101271e9c0340b958008052bb9999529bb9a7720b18211e')),
    (0x1a76c4, bytes.fromhex('2003407d00a4100f00d8215e1f00007148e19a526884b7720101271e48e19a526884a7720201271e411c211e2208201e2007407d00a4100f00d8215e2308201e4003407d00a4100f00d8215e2008201e4407407d84a4100f84d8215e2108241e')),
    (0x1a77d4, bytes.fromhex('84182c1e8500021f0529251ea5182a1eab00381e7f01017188fdff548404031f2429241e84182b1e8c00381e9f8d0171c8fcff54')),
    (0x1aeafc, bytes.fromhex('21aa8e52a1a8ad72f8210995a02301d1e2a3019141488f528108a772f3210995')),
)
