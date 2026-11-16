"""183DFF0 loan-offer leaf, excluding caller-owned common1865C8C.

Current inherited version20 only. Reference mode is an explicit conditional
source witness; runtime globals and offer activation are not asserted.
"""

from .wire import UnsupportedOffer as Unsupported
import struct

PREFIX_FIELDS = (
    (268, 4),
    (272, 4),
    (276, 4),
    (248, 8),
    (293, 1),
    (280, 4),
    (144, 8),
    (284, 4),
    (152, 8),
    (288, 2),
    (264, 4),
    (290, 2),
    (256, 4),
    (260, 4),
    (292, 1),
)


def parse(
    data,
    start,
    *,
    version=20,
    limit=None,
    comp_reference_mode=None,
    child_readers=None,
    max_items=4096,
):
    if type(version) is not int or version != 20:
        raise ValueError("Unsupported inherited LOAN_OFFER version")
    if comp_reference_mode not in ("compact16", "direct32"):
        raise ValueError("Explicit LOAN_OFFER reference witness required")
    bound = len(data) if limit is None else limit
    if (
        type(start) is not int
        or type(bound) is not int
        or (not 0 <= start <= bound <= len(data))
    ):
        raise ValueError("Invalid LOAN_OFFER extent")
    if type(max_items) is not int or not 0 <= max_items <= 65536:
        raise ValueError("Invalid LOAN_OFFER work bound")
    at = start
    fields = {}
    children = {} if child_readers is None else child_readers

    def take(n):
        nonlocal at
        if n < 0 or n > bound - at:
            raise ValueError(f"Truncated LOAN_OFFER at{at}")
        old = at
        at += n
        return bytes(data[old:at])

    def num(code):
        return struct.unpack("<" + code, take(struct.calcsize("<" + code)))[0]

    def field(offset, width):
        old = at
        raw = take(width)
        row = {"source_offset": old, "width": width, "raw_hex": raw.hex()}
        if width == 4:
            row["stored_signed32"] = int.from_bytes(raw, "little", signed=True)
        elif width in (1, 2):
            row["stored_unsigned"] = int.from_bytes(raw, "little")
        fields[hex(offset)] = row

    def child(native):
        nonlocal at
        reader = children.get(native)
        if reader is None:
            raise Unsupported(native, at, {"fields": fields})
        out = reader(data, at, limit=bound)
        end = out.get("end") if isinstance(out, dict) else None
        if (
            type(end) is not int
            or not at < end <= bound
            or out.get("complete_child_wire") is False
        ):
            raise ValueError("Invalid LOAN_OFFER child endpoint")
        at = end
        return out

    for offset, width in PREFIX_FIELDS:
        field(offset, width)
    ref_start = at
    if comp_reference_mode == "compact16":
        value = num("h")
        reference = {"stored_signed16": value}
        if value == -2:
            value = num("i")
            if value < 0:
                raise ValueError("Negative LOAN_OFFER escaped reference")
            reference["stored_escaped_index"] = value
        elif value < -1:
            raise ValueError("Negative LOAN_OFFER compact reference")
    else:
        reference = {"stored_unsigned32": num("I")}
    reference.update(
        start=ref_start,
        end=at,
        raw_hex=bytes(data[ref_start:at]).hex(),
        native_reader="0x1101bfc",
        resolved_identity=False,
    )
    marker = num("B")
    if marker != 1:
        raise ValueError(
            "LOAN_OFFER discarded marker differs from paired current writer"
        )
    for offset, width in ((164, 4), (168, 4), (172, 1), (160, 4)):
        field(offset, width)
    option_count = num("b")
    options = []
    for _ in range(max(option_count, 0)):
        options.append(child(20070192))
    count_start = at
    reference_count = num("I")
    if reference_count > max_items:
        raise ValueError("LOAN_OFFER16EF9D8 count exceeds work bound")
    reference_collection = None
    if reference_count:
        if 24050136 not in children:
            raise Unsupported(
                24050136,
                count_start,
                {
                    "fields": fields,
                    "count": reference_count,
                    "count_start": count_start,
                },
            )
        at = count_start
        reference_collection = child(24050136)
        if reference_collection.get("count") != reference_count:
            raise ValueError("LOAN_OFFER reference collection count mismatch")
    presence = num("B")
    if presence not in (0, 1):
        raise ValueError(
            "LOAN_OFFER nested contract presence differs from current writer"
        )
    contract = child(25570304) if presence else None
    field(240, 4)
    return {
        "start": start,
        "end": at,
        "complete_child_wire": True,
        "inherited_version": version,
        "fields": fields,
        "reference_e0": reference,
        "comp_reference_mode": comp_reference_mode,
        "option_count_signed8": option_count,
        "options": options,
        "reference_collection_count": reference_count,
        "reference_collection": reference_collection,
        "optional_contract_presence": presence,
        "optional_contract": contract,
        "semantic_fields": {
            "unused_monthly_fee_stored_signed": fields["0x104"]["stored_signed32"],
            "playing_wage_stored_signed": fields["0x108"]["stored_signed32"],
            "unused_wage_stored_signed": fields["0x100"]["stored_signed32"],
            "future_purchase_fee_base_stored_signed": fields["0x110"][
                "stored_signed32"
            ],
            "future_buy_back_fee_stored_signed": fields["0x114"]["stored_signed32"],
        },
        "currency": None,
        "currency_context_verified": False,
        "native_resource_limit_observed": False,
        "runtime_globals_observed": False,
        "activation_or_payment_evaluated": False,
    }
