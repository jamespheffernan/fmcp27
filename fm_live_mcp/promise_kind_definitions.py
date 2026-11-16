"""Five source-proved compiled English promise-title definitions.

These are static definition templates, not the selected/localized UI title,
recipient, current target, active state or fulfilment verdict. Kind7's generic
native-title default branch remains unknown instead of receiving a guessed name.
"""
import hashlib

SOURCE = (
    (0x2441a20, 36, 'cd2941e696cb0b91e7ab88eb9f78c0dc7c096216b983315f834db79d4321805a'),
    (0x53b90a6, 496, 'bf9ec80ef36bfda978edfbe99565f7fbcd44afcbeb93fb091b116d7f9eac3a50'),
    (0x24421e0, 36, 'acf70db0c7452e7ed7b38d888f73f1c0be356237b538aa049d266bcfbae69838'),
    (0x24429ac, 36, 'ea56869a5b7639b0ac74e141284fef192ebe06df1a67e189855232d06af4bbad'),
    (0x2442edc, 36, 'e4ea3a114afa1b81c554ffaa444a1ec383b03a62d26401062f753dbafa844228'),
    (0x244274c, 36, 'b46dd4e7405730b85ca616b11f998202a44d9c431347a8434ab93ba42c12dc12'),
    (0x2442f98, 36, 'f208d836a981ac70a52f09000175680e3a54e15971e99f43073d95186c0f0adc'),
)
ENGLISH_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'
DEFINITIONS = {
    1: (491277, 'Fair increase in playing time'),
    16: (422390, 'Will send player on intensive language course'),
    25: (377014, 'Find loan move for player'),
    69: (499122, 'Will receive agreed playing time on return from injury'),
    120: (496472, 'Play loanee [%person#1] more often'),
}


def inspect(read, base, native_kind):
    if type(native_kind) is not int or not -32768 <= native_kind <= 32767:
        raise ValueError('Expected the native signed16 promise kind')
    if type(base) is not int or base < 4096 or base % 8 or base+0x53b9296 >= 1 << 64:
        raise ValueError('Invalid promise definition image base')
    for rva, size, digest in SOURCE:
        if hashlib.sha256(read(base+rva, size)).hexdigest() != digest:
            raise ValueError(f'Promise definition native binding changed at RVA {rva:#x}')
    definition = DEFINITIONS.get(native_kind)
    return {'state': 'compiled_english_definition_template' if definition else 'unmapped_native_kind',
            'native_kind': native_kind, 'translation_id': definition[0] if definition else None,
            'english_template': definition[1] if definition else None,
            'source': 'original_native_promise_title_dispatch_and_pinned_compiled_English_resource',
            'english_resource_sha256': ENGLISH_SHA256,
            'localized_UI_rendered': False, 'placeholder_people_resolved': False,
            'lifecycle_evaluated': False}
