"""Bounded native injury-status reconstruction, distinct from return estimates."""
import struct
from datetime import date, timedelta

from . import database, player_health, players, world

SENTINEL_DATE = 0x52EFDF0
ENGLISH_RESOURCE_SHA256 = '3ce742519bf694636f41a1dae8d45a3dab86fad7d164a58696139e4b4509dd43'


def verify_native(read, base):
    for rva, raw in NATIVE_SPANS:
        if read(base + rva, len(raw)) != raw:
            raise ValueError(f'Injury-status native source changed at RVA {rva:#x}')
    if players.u64(read(base + players.RVA[0] + 0x460, 8)) != base + 0xD1FDD4:
        raise ValueError('Actual-player injury-status getter changed')


def calendar(raw):
    low, year = struct.unpack('<HH', raw)
    day = low & 511
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError('Unsupported injury-status date')
    result = date(year, 1, 1) + timedelta(days=day - 1)
    if result.year != year:
        raise ValueError('Invalid injury-status year/day pair')
    return result, year, day


def _unsupported(reason):
    return {'state': 'unsupported', 'reason': reason, 'flagged': None,
            'native_status_code': None, 'computed_flag_bit': None, 'english_label': None}


def _checked(code, reason):
    return {
        'state': 'checked', 'reason': reason, 'flagged': code != 0,
        'native_status_code': code,
        'computed_flag_bit': None if code == 0 else {'word_index': 0, 'bit_index': 8 if code == 1 else 41},
        'english_label': None if code == 0 else {
            'short': 'Inj', 'text': 'Injured', 'short_resource_key': 661813,
            'text_resource_key': 661814,
        },
    }


def evaluate(raw, current_raw, sentinel_raw):
    """Project only the audited single, same-year injury branch; no estimates."""
    if not isinstance(raw, bytes) or len(raw) != 0x38:
        raise ValueError('Invalid injury-status instance size')
    _, year, today = calendar(current_raw)
    _, start_year, start = calendar(raw[0x20:0x24])
    duration, phase = struct.unpack_from('<hh', raw, 0x28)
    low, sentinel_year = struct.unpack('<HH', sentinel_raw)
    if (low & 511, sentinel_year) != (1, 1900):
        return _unsupported('native_duration_sentinel_changed')
    if year != start_year:
        return _unsupported('cross_year_injury_branch')
    if duration < 0:
        return _unsupported('negative_duration_branch')
    if start + duration > 365:
        return _unsupported('injury_end_crosses_audited_year_range')
    if today > start + duration:
        return _checked(0, 'expired_single_injury_source')
    if today < start:
        return _unsupported('future_start_injury_branch')
    kind, native_phase = raw[0x30], raw[0x2E]
    if kind == 4:
        return _checked(1, 'single_injury_native_branch')
    elapsed = today - start
    if kind == 0 and elapsed == 0:
        return _checked(0, 'native_zero_status_on_start_day')
    if kind & 8:
        return _checked(2, 'single_injury_native_branch')
    weeks = struct.unpack_from('<b', raw, 0x33)[0]
    end_input = weeks * 7 if weeks >= 0 else duration
    phase_input = weeks * 7 if weeks >= 0 else phase
    if native_phase == 3 and duration > phase and end_input < 6:
        code = 1
    else:
        code = 2 if elapsed < phase_input else 1
    return _checked(code, 'single_injury_native_branch')


def project(read, base, primary, record_kind, current_raw, sentinel_raw):
    """Keep declared injury records separate from the status getter's result."""
    if record_kind != 'actual':
        return {**_unsupported('unsupported_player_record_kind'),
                'stored_injury_record_count': None, 'stored_injuries': None}
    if players.u64(read(primary, 8)) != base + players.RVA[0]:
        raise ValueError('Injury-status primary player type changed')
    secondary = players.u64(read(primary + 0xF0, 8))
    if not secondary:
        return {**_checked(0, 'empty_current_injury_source'),
                'stored_injury_record_count': 0, 'stored_injuries': []}
    if secondary < 4096 or secondary % 8:
        raise ValueError('Invalid injury-status vector header')
    start, end, capacity = struct.unpack('<QQQ', read(secondary, 24))
    if (start, end, capacity) == (0, 0, 0):
        count = 0
    else:
        if start < 4096 or any(value % 8 for value in (start, end, capacity)) or not start <= end <= capacity:
            raise ValueError('Invalid injury-status vector geometry')
        count = (end - start) // 8
    if count == 0:
        return {**_checked(0, 'empty_current_injury_source'),
                'stored_injury_record_count': 0, 'stored_injuries': []}
    if count != 1:
        return {**_unsupported('multiple_injury_selection_branch'),
                'stored_injury_record_count': count, 'stored_injuries': None}
    instance = players.u64(read(start, 8))
    if instance < 4096 or instance % 8:
        raise ValueError('Invalid injury-status instance pointer')
    raw = read(instance, 0x38)
    injuries = database.table(read, base, 'injuries')
    named = player_health.injury(read, base, instance, injuries)
    return {**evaluate(raw, current_raw, sentinel_raw),
            'stored_injury_record_count': 1, 'stored_injuries': [named]}


NATIVE_SPANS = (
    (0xd1fdd4, bytes.fromhex(
        'f44fbea9fd7b01a9fd4300917ca7ff97a00600b408c040391f110071610000542000805230000014'
        '8b4c02d06be1369169014079292100120a4040794a2100126b0540790c4440796d010c6be8000054'
        '20214a7aa20000548b010b4b8c2d80126b7d0c1b03000014ab2d8052ab7d0b1b29010a4b7401090b'
        '0901142a690000350000805218000014c802183708b840391f0d0071a10100540850c0790954c079'
        '1f01096b2d010054812e029021c03791f30300aa82b62094e80300aae00313aa1f190071ebfaff54'
        '812e029021c03791f30300aa23b520949f02006baa00005440008052fd7b41a9f44fc2a8c0035fd6'
        '812e029021c03791e00313aa70b62094c8ffff17210600b4ffc301d1fc6f01a9fa6702a9f85f03a9'
        'f65704a9f44f05a9fd7b06a9fd830191f30301aaf40300aa080040f909815ef80100098b29604039'
        '09010036884d02f0006546f9080040f9086140f900013fd6c0730037880240f908015ef89602088b'
        'd53e40f9d50000b4a80240f9084940f9e00315aa00013fd680020034c80240f908815ef8c96a68f8'
        '291941f9c002088b20013fd6600000b4c83e40f9c80100b4c80240f908815ef8c96a68f829fd41f9'
        'c002088b20013fd6'
    )),
    (0xd09bd0, bytes.fromhex(
        'fc6fbaa9fa6701a9f85f02a9f65703a9f44f04a9fd7b05a9fd430191087840f9a80900b4082540a9'
        '280108eb40090054f30300aa140080d218fd439339858b527a008052fb0180525c4d0290554d0290'
        'b5e23691180700d1687a40f9e80000b4082540a9290108cb1f0f89eb62000054167978f802000014'
        '160080d2c952c0792903f837c8464079ca4240794a21001229010a0b290500510a7d191b4a3d0012'
        '5ff928716b339a1a2a3d00131f010b6aa00000545fb505712b0100546ad29f52040000145fb90571'
        'ab0000544ad29f524901090b08050011f0ffff172005001106000014e803094b013d0013c0820091'
        'cd43ce97087c105389775b793f21286b68020054e300005408200012494d029029715b7929210012'
        '1f01096b83010054540100b4e00316aae10315aae50e2194f70300aae00314aae10315aae10e2194'
        'ff02006b4d000054f40316aa58f8ffb502000014140080d2e00314aafd7b45a9f44f44a9f65743a9'
        'f85f42a9fa6741a9fc6fc6a8c0035fd600b0c479c0035fd600b4c479c0035fd600b8c479c0035fd6'
        'f44fbea9fd7b01a9fd430091f30300aa08cc437908073036689e4379699a4379292100121fb11d71'
        '2009417a41060054680240f908815ef8696a68f8299d40f9212f02d021c037916002088b20013fd6'
        'f40300aa680240f908c941f9e00313aa00013fd6e8038052290480521f380071'
    )),
    (0x154d334, bytes.fromhex(
        '08ccc039a800f83709711d532801084b003d0013c0035fd62804407929004079292100121fb11d71'
        '2009417ae0020054eb2bbc6de923016df44f02a9fd7b03a9fdc300910854c07900800091f30301aa'
        'e10308aaef71b694e80313aa0a7c1053'
    )),
    (0x154d890, bytes.fromhex(
        '08ccc039a800f83709711d532801084b003d0013c0035fd62804407929004079292100121fb11d71'
        '2009417a20020054f44fbea9fd7b01a9fd4300910850c07900800091f30301aae10308aa9a70b694'
        '0b7c10536a0640796802407908210012'
    )),
    (0x20ad544, bytes.fromhex(
        'e80240f9083142f9e00317aa00013fd61f080071810000540840c0d2e06740f909000014e06740f9'
        '080040f9083142f900013fd61f040071e06740f9a100005408208052290340f9280108aa280300f9'
    )),
    (0x154d3bc, bytes.fromhex(
        '08544079003d0013c0035fd6'
    )),
    (0x154d900, bytes.fromhex(
        '08504079003d0013c0035fd6'
    )),
)
