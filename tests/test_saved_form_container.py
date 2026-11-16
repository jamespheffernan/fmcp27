"""Native F0 geometry controls; fixtures are inputs, never discovery offsets."""
import struct

import pytest

from fm_live_mcp.saved_form_container import locate_form_groups, WIRE_PROFILE
from fm_live_mcp.saved_form_children import BoundedReader

# B44 complete source-profile records, main spoolSHA4d563471...c2d58e0.
# Values end immediately after actual+58presence; noformgroupdata appended.
SOURCE_PREFIXES = [(13009, True, '0000000000000001'), (13248, True, '0000000000000001'), (41999, True, '0000000000000001'), (14805, True, '01032400002343ee072c004000030200ffffffff002102000001ffffffff000700ff00000000000001'), (33495, True, '0000000000000001'), (35795, True, '0000000000000101f49be502240200009e010000a81aea0701'), (37706, True, '0000000000000101a6f02c06090200009e010000b838eb0701'), (47009, True, '0000000000000001'), (11178, True, '0000000000000001'), (40862, True, '0000000000000001'), (55949, True, '000001048e020000fb4cbd01000000000800000023020000a71d00000b000000f10100000000000801006c07000001045a6b0000c578000000000000323800009e01000089010000b590ee07f336ed07000000000000000000400000060100000000000003034700000000000000000000400000000001'), (53192, True, '000000000104b80b0000b80b0000ec100000ec1000009e010000ac010000b590eb07f43aea07000000000000000080000000060000000000000003033a00000000000000000000000000000001'), (55948, True, '0103610001011e73ee071b0100000200c302000000cf0200000100760e02001e81ee0706000b00010100ffffffff00c302000001ffffffff000000ff000104670300005ca88000000000000a000000a7020000691600000a0000000dfe0020eb19000001006c0700000104ac170000ac17000000000000000000009e01000074010000b690ed07e936ec07000000000000000004000000060100000000000003033900000000000000000004000000000001'), (8209, True, '0000000000000101b218f501270200009e010000b41eed0701'), (37623, True, '00000000000001018698fd03b70100009e010000c180ed0701'), (15163, True, '0000010466020000c19301000000000003000000c80000005b1d000007000000520400000000000801006c07000000000001'), (53560, True, '00000000000001011e837303b20100009e010000d934ed0701'), (49717, True, '0000000000000101240de902480200009e010000e92aed0701'), (36634, True, '0000000000000001'), (36819, True, '00000104b00200006b905b003000000023000000df090000601900002600000092fe00f65f9a000801006c0700010576020000e5a9bc01c0e3a803e077af0748e801003c75e202070668060000aa0019001501cb2dd840001e000100000000000093c202000000000000000001'), (38945, True, '00000104b00200006b905b000d0000000b00000008030000981e00000d0000007c0000b8bd1b0a0801006c070001058202000099363677a041b00430482805cc76020080a812010a0a15090000ef00060026035ce2dc4000148000002002000000b8a302000000000000000001'), (56412, True, '00000104b00200006b905b000d000000090000006c020000681900000a00000073fe00997aa1050001006c0700010502010000c2673b7716dccf0194562303e6750000ffffffff0a0a950a0000f2003600280ed7a3e040150f000000200200000068c400000000000000000001'), (39235, True, '00000104b0020000a04d55770d0000000400000019010000f81a00000d0000007cfb006956460a0001006c07000105c1030000f73900007bd89201c4263a01eb030100f7ca05010a0ac10200003e0000001a0048e1e24000001000000004000000833e01000000000000000101c4263a01490200009e010000aa1aee0701'), (20265, True, '00000104b0020000a04d55770d00000005000000510100007f1500000d0000006cfa00a74a1b0a009742ee0700010557040000790400000cd1c900fd827b00df620100ffffffff0906c8090000e6003a002200c3f5d04001000000000000000000737401000000000000000001'), (38560, True, '00000104b00200006b905b000d000000080000002d0200006f1b00000d000000160000aa9efe0608722aee07000105c60500000f600b00001bb70000a51d016e0c00001ecdc5000a0a0a070000c6000f0023008fc2ed40000000000000000000004d6c01000000000000000001'), (52310, True, '00000104b0020000a04d55770d0000000600000098010000f81a00000b00000029fc006903ff080001006c07000105df020000bc2b4e0078a30e034455ef02edbe0100c0ea21010a0a13070000a00000002200c3f5d8400000800000000400000085f901000000000000000001'), (13250, True, '00000104b0020000a04d55770d0000000a000000b0020000722000000d00000014000050ee8e070801006c0700010576020000e5a9bc0140d2df03a0a37c031fa00300ffffffff0909b1190000ed00070030000ad7db4000000000000004000000044904000000000000000101eeb28003650100009e010000bb5aee0701'), (42203, True, '00000104b0020000a04d55770d000000010000004a000000be1400000b000000ebf800b6f90e050001006c070001053e070000c655570001f25e009b706800a7120000ffffffff0a0a170a00008200000001009a99e94000140000000002000000a46b0000000000000000010176087100bb0400009e010000cb1aee0701'), (1512, False, '000000010538060000ffffffff4601000046010000ae020000000000000907c4020000470003002303da05e44000000000000000000000ffffffff0000000000000000'), (1513, False, '0000000105ca020000ffffffff360100003601000021040000000000000501c40200002d0001000a00d7a3d04000000000000000000000ffffffff0000000000000000')]


@pytest.mark.parametrize('ordinal,present,hex_value', SOURCE_PREFIXES)
def test_thirty_checked_source_prefixes(ordinal, present, hex_value):
    raw = bytes.fromhex(hex_value)
    out = locate_form_groups(raw, 0, len(raw))
    assert out['state'] == ('present' if present else 'absent')
    assert out['end'] == len(raw)
    assert out['form_start'] == (len(raw) if present else None)
    assert out['complete_person'] is False
    assert out['wire_profile_is_conditional'] is True
    for limit in range(len(raw)):
        with pytest.raises(ValueError):
            locate_form_groups(raw, 0, limit)


def test_absolute_coordinate_and_exclusive_bound():
    raw = bytes.fromhex(SOURCE_PREFIXES[0][2])
    data = b'leading' + raw + b'forbidden'
    out = locate_form_groups(data, 7, 7 + len(raw))
    assert out['form_start'] == out['end'] == 7 + len(raw)


def test_presence_absence_and_present_empty_are_separate():
    assert locate_form_groups(bytes(8), 0, 8)['state'] == 'absent'
    data = bytes(7) + b'\1'
    out = locate_form_groups(data, 0, 8)
    assert out['state'] == 'present' and out['form_start'] == 8
    #No group count is required to locate; downstream row reader validates it.


def test_vector18_is_a_stop_not_absence():
    out = locate_form_groups(b'\0\1', 0, 2)
    assert out['state'] == 'stopped' and out['form_present'] is None
    assert out['next_native_reader'] == '0x405D598' and out['end'] == 2


def test_tagged_reference_escape_is_an_explicit_stop():
    #One version3 vector row,root40 index36,nooptionalchild,11rawfields,
    #PERSON raw32,then unclosed group reference tag2.
    raw = b'\1\3' + struct.pack('<h',36) + b'\0' + bytes(15) + b'\2'
    out = locate_form_groups(raw, 0, len(raw))
    assert out['state'] == 'stopped' and out['end'] == len(raw)-1
    assert out['next_native_reader'] == '0x11073A8'


def test_group_reference_tag1_null_omits_secondary():
    row = b'\3' + struct.pack('<h',36) + b'\0' + bytes(15) + b'\1' + bytes.fromhex('ffffffff') + bytes(9)
    raw = b'\1' + row + bytes(7)
    assert locate_form_groups(raw,0,len(raw))['state'] == 'absent'


def test_root40_extended_index_and_group_secondary():
    row = b'\3' + struct.pack('<hI',-2,123456) + b'\0' + bytes(15) + b'\1' + struct.pack('<II',545,688) + bytes(9)
    raw = b'\1' + row + bytes(7)
    assert locate_form_groups(raw,0,len(raw))['end'] == len(raw)


def test_every_fixed_child_and_unobserved48_geometry():
    sizes = [42,59,69,13,17]
    versions = [4,5,4,1,1]
    raw = bytearray(bytes(2))
    for version,size in zip(versions,sizes,strict=True):
        raw += b'\1' + bytes([version]) + bytes(size-1)
    raw += b'\1'
    out = locate_form_groups(raw,0,len(raw))
    assert out['form_start'] == len(raw)
    assert [v['end']-v['start'] for v in out['validated_children']] == sizes
    for child in out['validated_children']:
        changed = bytearray(raw);changed[child['start']] ^= 0x80
        with pytest.raises(ValueError,match='version'):
            locate_form_groups(changed,0,len(changed))


@pytest.mark.parametrize('marker', [2,3,128,255])
def test_non_boolean_current_writer_presence_rejects(marker):
    for at in range(2,8):
        raw = bytearray(bytes(8));raw[at] = marker
        with pytest.raises(ValueError,match='presence'):
            locate_form_groups(raw,0,len(raw))


def test_opaque_bytes_are_not_plausibility_checks():
    raw = bytes(2) + b'\0\1\5' + b'\xff'*58 + bytes(4)
    assert locate_form_groups(raw,0,len(raw))['state'] == 'absent'


def test_work_budget_stop():
    out = locate_form_groups(b'\1',0,1,max_vector_rows=0)
    assert out['state'] == 'stopped' and out['stop_reason'] == 'offline_vector_row_budget'


@pytest.mark.parametrize('start,limit', [(-1,8),(True,8),(0,True),(0,9),(2,1)])
def test_invalid_bounds(start,limit):
    with pytest.raises(ValueError):
        locate_form_groups(bytes(8),start,limit)


@pytest.mark.parametrize('kwargs',[{'source_major':3753},{'source_major':True},{'source_minor':8},
                                   {'source_minor':True},{'reference_profile':'raw64'},
                                   {'max_vector_rows':True},{'max_vector_rows':513}])
def test_invalid_profiles_and_budgets(kwargs):
    with pytest.raises(ValueError):
        locate_form_groups(bytes(8),0,8,**kwargs)


def test_bounded_reader_adapter_for_rows():
    reader = BoundedReader(b'xx'+struct.pack('<BhI',3,-2,123)+b'outside',2,9)
    assert reader.offset == 2 and reader.size == 9
    assert reader.u8() == 3 and reader.i16() == -2 and reader.u32() == 123
    with pytest.raises(ValueError):reader.take(1)


@pytest.mark.parametrize('data',['notbytes',[0]*8,None])
def test_non_buffer_input_rejects(data):
    with pytest.raises(ValueError,match='byte buffer'):
        locate_form_groups(data,0,8)


def test_non_byte_memoryview_rejects():
    import array
    with pytest.raises(ValueError,match='byte offsets'):
        locate_form_groups(memoryview(array.array('I',[0]*8)),0,8)
