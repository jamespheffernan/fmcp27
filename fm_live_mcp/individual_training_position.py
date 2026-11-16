"""Pure native IP-position operand from the selected stored training occurrence.

The named audit2CF5728 selects the same occurrence as original1579B00, then
maps its signed low6-bit code to W22. This module supplies that source mask,
without translating it into a displayed position or an effective assignment.
"""
import hashlib

from . import individual_training_ip_role as role

NATIVE_GUARDS=(
    (0x2CF5728,2140,'45681bc16d2042b3595c2df1e491db6067a6c738bc6f3404382b4f4fb79cd3b5'),
    (0x53CDFCA,30,'1212d9afe807ed5dd9b7f1214b5943ee274c68253664f6a4a38dad8b5f3c9150'),
)
# Original W22 values for signed codes-15 through11. Every other signed6-bit
# code reaches the original zero branch. These include native side flags;
# the mask is preserved as one native operand, without assigning labels.
MASKS=(0x1,0,0x4,0x200010,0x10,0x100010,0x8,0x20,0x200080,
       0x80,0x100080,0x40,0x100,0x200400,0x400,0x100400,
       0x200,0x800,0x202000,0x2000,0x102000,0x1000,0x8000,
       0x204000,0x4000,0x104000,0x10000)


def verify_native(read,base):
    if type(base)is not int or base<4096 or base%4096:
        raise ValueError('Invalid training-position native image base')
    for rva,size,digest in NATIVE_GUARDS:
        raw=read(base+rva,size)
        if type(raw)is not bytes or len(raw)!=size or hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError('Individual-training position source changed or incomplete')


def decode(entries):
    """Keep absence of a native selected occurrence distinct from mask zero."""
    selected=role.decode(entries)
    slot=selected['selected_stored_slot']
    if slot is None:
        return dict(state='no_native_selected_occurrence',native_code=None,
                    native_mask='0x00000000',selected_stored_slot=None)
    code=selected['occurrences'][slot]['native_signed_position_code']
    mask=MASKS[code+15]if -15<=code<=11 else 0
    return dict(state='checked_native_nonzero'if mask else'checked_native_zero',
                native_code=code,native_mask=f'0x{mask:08x}',selected_stored_slot=slot)
