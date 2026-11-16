"""Private current-owner stored history with compiled, unrendered English.

The outer caller must verify the installed English resource path/digest before
and after collection, bind the canonical owner/save/current context, and recheck
every consumed byte after its last lifetime/presentation callback. This decoder
performs no file I/O, profile generation, native call or game write. It does not
combine historical packets or resolve template placeholders/current UI status.
"""
import hashlib

from . import _concern_template_definitions as definitions
from . import player_concern_history_source as history

ENGLISH_RESOURCE_SHA256 = definitions.ENGLISH_RESOURCE_SHA256
SOURCE = definitions.SOURCE
DESCRIPTION_SCOPE = (
    'Compiled static English first translation templates for these stored native history records. '
    'Context-dependent keys and unsupported lookups remain unknown. Placeholders remain literal. '
    'This is not rendered UI text, a current complaint/status, satisfaction, or promise fulfilment.'
)


def _verify_templates(read, base):
    for rva, size, expected in SOURCE:
        if hashlib.sha256(read(base + rva, size)).hexdigest() != expected:
            raise ValueError(f'Native concern template source changed at {rva:#x}')


def _description(record):
    reason = record['native_reason_code']
    flags = record['native_flags1b']
    category = definitions.REASON_CATEGORY_TABLE[reason - 500] if 500 <= reason <= 1362 else 0
    if category != record['compiled_reason_category_code']:
        raise ValueError('Compiled concern category and raw history source disagree')
    if flags & 0x80 and category == 8:
        state = 'compiled_wrapper_override_template'
        key = definitions.WRAPPER_OVERRIDE_KEY
        template = definitions.WRAPPER_OVERRIDE_TEMPLATE
        selection = 'flags_bit7_and_reason_category8'
    else:
        selection = 'default_inner_formatter'
        first = definitions.FIRST_KEYS.get(reason)
        if first is None:
            state = definitions.UNKNOWN_PREFIX_STATES.get(reason, 'outside_default_reason_dispatch')
            key, template = None, None
        else:
            state = 'compiled_wrapper_default_first_template'
            key, template = first
    return dict(
        native_reason_code=reason,
        native_flags_1b=flags,
        compiled_reason_category=category,
        state=state,
        selection=selection,
        translation_id=key,
        english_template=template,
        english_resource_sha256=ENGLISH_RESOURCE_SHA256,
        native_wrapper_entry='0x15472c4',
        wrapper_first_branch_evaluated=True,
        compiled_prefix_only=True,
        complete_formatter_executed=False,
        placeholder_people_resolved=False,
        localized_UI_rendered=False,
        lifecycle_evaluated=False,
        scope=definitions.WRAPPER_SCOPE,
    )


def inspect(read, base, primary, kind, *, english_resource_sha256, include_stored_name=False):
    """Decorate one fresh raw history through the caller's shared read set.

    The digest is a private caller binding, never a user-selected declaration.
    The caller owns its actual resource-path/hash verification and final fence.
    """
    if type(english_resource_sha256) is not str or english_resource_sha256 != ENGLISH_RESOURCE_SHA256:
        raise ValueError('Verified static English resource binding required for concern templates')
    result = history.inspect(read, base, primary, kind, include_stored_name=include_stored_name)
    result['compiled_description_scope'] = DESCRIPTION_SCOPE
    result['compiled_English_resource_sha256'] = ENGLISH_RESOURCE_SHA256
    if result['records'] is None:
        result['unrendered_description_count'] = None
        result['unrendered_description_unknown_count'] = None
        return result
    _verify_templates(read, base)
    known, unknown = 0, 0
    for entry in result['records']:
        record = entry['record']
        if record is None:
            continue
        description = _description(record)
        record['compiled_unrendered_description'] = description
        if description['translation_id'] is None:
            unknown += 1
        else:
            known += 1
    result['unrendered_description_count'] = known
    result['unrendered_description_unknown_count'] = unknown
    return result
