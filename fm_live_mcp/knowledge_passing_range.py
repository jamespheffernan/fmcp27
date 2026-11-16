"""Private Passing math for FM27 build 27.0.0.2493426; no memory or game calls.

Source: evidence/knowledge-field-visibility-20261108/{native-source.asm,
context/context-source.asm} in the canonical reader. Passing is native field18;
0xD19EB0/0x4ACF834 bind its stored byte, 0x14E98E4 binds thresholds, and
0x2386EAC..0x23871EC binds the three-byte projection.

These inputs belong to a future checked, private source producer. This module
does not establish a native state/score, observer permission, assessment/date
freshness, or a Manager knowledge mode. Threshold comparison is only one state
branch; owner/context/bypass branches remain outside this component. Never
expose its private projection through an MCP tool. Construct the permitted
value explicitly after the caller has established those missing prerequisites.
"""
from dataclasses import dataclass


BINARY_SHA256 = '774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1'
PASSING_FIELD = 18
# Small source anchors for an independent offline binary check, not live proof.
NATIVE_MATH_SPANS = (
    (0xD19ECC, bytes.fromhex('e000005469c2c93968c2208b0821c539')),
    (0xD19EF0, bytes.fromhex('e9cc8c52ca9999520829091b097d1113287d480b')),
    (0x4ACF834, bytes.fromhex('1fb80071a8000054a84900b00839089108c96038')),
    (0x2386F20, bytes.fromhex('b7020034ea1e0012e80300aae90300aa5f050071')),
    (0x2386F74, bytes.fromhex('e81f8052e91f805293000014')),
    (0x2387098, bytes.fromhex('a90240f929815ef8a902098b290940b9')),
    (0x23871AC, bytes.fromhex('281d00131f05007108c59f1a491d0013')),
    (0x23871C8, bytes.fromhex('6802003969060039600a0039')),
    (0x238795C, bytes.fromhex('281d00131f01166be9b79f1a4a0080521f01186b28b18a1a')),
    (0x540420E + PASSING_FIELD, b'\x16'),
)


def _integer(value: int, lower: int, upper: int, label: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise ValueError(f'{label} must be an integer in {lower}..{upper}')
    return value


def _signed8(value: int) -> int:
    return ((value + 128) & 255) - 128


def _signed32(value: int) -> int:
    return ((value + (1 << 31)) & 0xFFFFFFFF) - (1 << 31)


def _scaled_rating(stored_byte: int) -> int:
    # 0xD19EF0 and 0x2386FE4: signed byte, madd, asr17 + logical sign bit.
    value = _signed32(_signed8(stored_byte) * 0x6667 + 0xCCCE)
    scaled = (value >> 17) + ((value & 0xFFFFFFFF) >> 31)
    return min(20, max(1, scaled))


def passing_getter(stored_byte: int, scale_mode_byte: int) -> int:
    """Replay primary+0xF0(18), including signed primary+0x270 scale mode.

    Both arguments are stored u8 bytes. The unscaled getter returns signed8,
    including0/-1 or other synthetic values; it does not validate their UI
    meaning. The negative mode converts the signed attribute byte to1..20.
    """
    _integer(stored_byte, 0, 255, 'Stored Passing byte')
    _integer(scale_mode_byte, 0, 255, 'Native scale-mode byte')
    return _scaled_rating(stored_byte) if scale_mode_byte & 128 else _signed8(stored_byte)


def passing_thresholds(category_byte: int) -> tuple[int, int]:
    """Return (range lower, exact upper) for the stored primary+0x268 byte.

    Raw categories retain native numeric meaning. This does not implement the
    context score or any own-club/exemption branch of the state producer.
    """
    _integer(category_byte, 0, 255, 'Native category byte')
    category = _signed8(category_byte)
    if category == 0:
        return 39, 77
    if category in (2, 3, 4, 13, 14):
        return 11, 49
    if category in (5, 7):
        return 6, 44
    if category in (6, 8, 9, 11, 12):
        return 9, 47
    if category == 10:
        return 4, 42
    return 0, 0


def passing_threshold_state(category_byte: int, private_knowledge_score: int) -> int:
    """Replay only 0x238795C's comparison, given an established private score."""
    _integer(private_knowledge_score, -128, 127, 'Private native knowledge score')
    lower, upper = passing_thresholds(category_byte)
    if not lower or not upper:
        return 0
    if private_knowledge_score >= upper:
        return 2
    return int(private_knowledge_score >= lower)


@dataclass(frozen=True)
class NativePassingProjection:
    """Private native state and (lower, upper, exact getter) transport bytes.

    The getter remains private for state0/1. Do not serialize this dataclass or
    its repr into model context; use permitted_passing_value explicitly.
    """

    state: int
    lower: int
    upper: int
    getter: int

    def __post_init__(self):
        _integer(self.state, 0, 2, 'Proved native Passing state')
        for value in (self.lower, self.upper, self.getter):
            _integer(value, -128, 127, 'Private native projection byte')

    @property
    def native_values(self) -> tuple[int, int, int]:
        return self.lower, self.upper, self.getter


def native_attribute_projection(getter: int, state: int, *, native_field_id: int,
                              age: int | None = None,
                              person_index: int | None = None,
                              private_knowledge_score: int | None = None,
                              assessor_bytes: tuple[int, int] | None = None
                              ) -> NativePassingProjection:
    """Replay the private three-byte range math for an established native state.

    The signed32 offset seed is PERSON index plus the explicit native field.
    State1 consumes age (ordinary native age 0 or 14..100), canonical signed32
    nonnegative PERSON table index, signed8 knowledge score, and optional stored
    NON_PLAYER+0x2C/+0x2D bytes. A missing assessor projection natively sums to0.
    State0/2 do not consume those range inputs. This function cannot establish
    the supplied state's authority or replace the missing typed source reader.
    """
    _integer(native_field_id, 0, 46, 'Native ordinary attribute field')
    _integer(getter, -128, 127, 'Native attribute getter result')
    _integer(state, 0, 2, 'Proved native Passing state')
    if state == 0:
        return NativePassingProjection(state, -1, -1, getter)
    if state == 2:
        return NativePassingProjection(state, getter, getter, getter)

    if type(age) is not int or age != 0 and not 14 <= age <= 100:
        raise ValueError('Native ordinary age must be 0 or 14..100')
    _integer(person_index, 0, 0x7FFFFFFF, 'Canonical PERSON table index')
    _integer(private_knowledge_score, -128, 127, 'Private native knowledge score')
    if assessor_bytes is None:
        judging_sum = 0
    else:
        if type(assessor_bytes) is not tuple or len(assessor_bytes) != 2:
            raise ValueError('Assessor requires two stored rating bytes or None')
        for value in assessor_bytes:
            _integer(value, 0, 255, 'Assessor stored rating byte')
        judging_sum = sum(_scaled_rating(value) for value in assessor_bytes)

    a, b = (4, 2) if age < 18 else (3, 2) if age < 21 else (2, 1)
    score = private_knowledge_score
    scalar = 2
    if judging_sum <= 11 and score <= 20:
        extra_a, extra_b = 4, 2
    elif judging_sum <= 19 and score <= 30:
        extra_a, extra_b = 3, 2
    elif judging_sum <= 24 and score <= 40:
        extra_a, extra_b = 2, 1
    else:
        extra_a = extra_b = int(score < 51 and judging_sum < 30)
        scalar = 1
    a += extra_a
    b += extra_b

    key = _signed32(person_index + native_field_id)
    quotient = abs(key) // 7 * (-1 if key < 0 else 1)
    remainder = key - quotient * 7
    offsets = {0: (-a, scalar), 1: (-scalar, a), 2: (-a, 0),
               3: (0, a), 4: (-b, b), 5: (-b, scalar), 6: (-scalar, b)}
    # Negative signed remainders take the native default raw/raw branch.
    low_offset, high_offset = offsets.get(remainder, (0, 0))
    lower = max(1, _signed8(getter + low_offset))
    upper = min(20, _signed8(getter + high_offset))
    return NativePassingProjection(state, lower, upper, getter)


def native_passing_projection(getter: int, state: int, *, age: int | None = None,
                              person_index: int | None = None,
                              private_knowledge_score: int | None = None,
                              assessor_bytes: tuple[int, int] | None = None
                              ) -> NativePassingProjection:
    """Preserve the established Passing18 projection and private result type."""
    return native_attribute_projection(getter,state,native_field_id=PASSING_FIELD,
        age=age,person_index=person_index,private_knowledge_score=private_knowledge_score,
        assessor_bytes=assessor_bytes)


def permitted_passing_value(projection: NativePassingProjection) -> dict:
    """Construct an endpoint-only value; this is not an observer permission gate.

    A caller must first establish its observer/club/date/assessment/state source.
    Only1..20 exact values or ordered endpoints within1..20 are supported here;
    zero/invalid native domain and invalid intervals are withheld, not repaired.
    State1 retains range authority even when its endpoints happen to be equal.
    No getter, score, private debug object or invalid endpoints leave this API.
    """
    if not isinstance(projection, NativePassingProjection):
        raise ValueError('Expected a private native Passing projection')
    if projection.state == 0:
        return {'state': 'unknown'}
    if projection.state == 1:
        if not 1 <= projection.lower <= projection.upper <= 20:
            return {'state': 'unavailable', 'reason': 'invalid_native_interval'}
        if not 1 <= projection.getter <= 20:
            return {'state': 'unavailable', 'reason': 'unproved_native_getter_domain'}
        return {'state': 'range', 'minimum': projection.lower, 'maximum': projection.upper}
    if (projection.lower, projection.upper) != (projection.getter, projection.getter):
        return {'state': 'unavailable', 'reason': 'inconsistent_native_exact_projection'}
    if not 1 <= projection.getter <= 20:
        return {'state': 'unavailable', 'reason': 'unproved_native_getter_domain'}
    return {'state': 'exact', 'value': projection.getter}
