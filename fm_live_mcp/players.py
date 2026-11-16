"""Build-pinned FM27 ARM64 layout with explicit native/UI verification scopes."""
from datetime import date, timedelta
import hashlib
from pathlib import Path
import struct

from . import player_profile

VERSION = "27.0.0.2493426"
SHA256 = "774cacde63567fd3901c47719e7a6ed94cc3a0a62e9b94989dcac6b4890ec0e1"
RVA = (0x5588EE8, 0x54E0BB8, 0x558A780)
STAFF_RVA = (0x558EF38, 0x54E0BB8, 0x55908E0)
SIZE = 0x3A8
ATTRIBUTES = {
    "crossing": 0x0F, "dribbling": 0x10, "finishing": 0x11,
    "heading": 0x12, "long_shots": 0x13, "marking": 0x14,
    "off_the_ball": 0x15, "passing": 0x16, "penalty_taking": 0x17,
    "tackling": 0x18, "vision": 0x19, "anticipation": 0x20,
    "decisions": 0x21, "positioning": 0x23, "first_touch": 0x25,
    "technique": 0x26, "flair": 0x29, "corners": 0x2A,
    "teamwork": 0x2B, "work_rate": 0x2C, "long_throws": 0x2D,
    "acceleration": 0x31, "free_kick_taking": 0x32, "strength": 0x33,
    "stamina": 0x34, "pace": 0x35, "jumping_reach": 0x36,
    "leadership": 0x37, "balance": 0x39, "bravery": 0x3A,
    "aggression": 0x3C, "agility": 0x3D, "natural_fitness": 0x41,
    "determination": 0x42, "composure": 0x43, "concentration": 0x44,
}


class VirtualCacheIdentityMismatchError(ValueError):
    """Typed generated cache belongs to a different nonzero virtual PERSON."""


def u64(data, offset=0):
    return struct.unpack_from("<Q", data, offset)[0]


def macho_uuid(data: bytes) -> bytes:
    if len(data) < 32 or struct.unpack_from("<II", data) != (0xFEEDFACF, 0x100000C):
        raise ValueError("Expected ARM64 Mach-O image")
    count, size = struct.unpack_from("<II", data, 16)
    if size > len(data) - 32 or count > 4096:
        raise ValueError("Invalid Mach-O commands")
    offset = 32
    for _ in range(count):
        if offset + 8 > size + 32:
            raise ValueError("Truncated Mach-O command")
        command, length = struct.unpack_from("<II", data, offset)
        if length < 8 or offset + length > size + 32:
            raise ValueError("Invalid Mach-O command length")
        if command == 0x1B and length == 24:
            return data[offset + 8:offset + 24]
        offset += length
    raise ValueError("Missing Mach-O UUID")


def disk_uuid(path: Path) -> bytes:
    # Hash in chunks; the game plugin is large.
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != SHA256:
            raise ValueError("Unsupported game plugin fingerprint")
        stream.seek(0)
        header = stream.read(4096)
        offset = 0
        if header[:4] == b"\xca\xfe\xba\xbe":
            count = struct.unpack_from(">I", header, 4)[0]
            if count > 32:
                raise ValueError("Invalid universal binary")
            for i in range(count):
                cpu, _, candidate, _, _ = struct.unpack_from(">IIIII", header, 8 + i * 20)
                if cpu == 0x100000C:
                    offset = candidate
                    break
            else:
                raise ValueError("Missing ARM64 slice")
        stream.seek(offset)
        return macho_uuid(stream.read(16384))


def verify_runtime(read, base: int, expected_uuid: bytes) -> tuple[int, int, int]:
    if macho_uuid(read(base, 16384)) != expected_uuid:
        raise ValueError("Loaded plugin UUID differs from verified binary")
    tables = tuple(base + rva for rva in RVA)
    for table, displacement, name in zip(tables, (0, 0, -0x388),
                                         (b"N2db13ACTUAL_PLAYERE", b"N2db12PLAYING_DATAE", b"N2db13ACTUAL_PLAYERE")):
        metadata = read(table - 16, 16)
        if struct.unpack_from("<q", metadata)[0] != displacement:
            raise ValueError("Native player vtable displacement changed")
        typeinfo = u64(metadata, 8)
        name_pointer = u64(read(typeinfo + 8, 8))
        if read(name_pointer, len(name) + 1) != name + b"\0":
            raise ValueError("Native player runtime type changed")
    return tables


def read_name(read, handle: int) -> str:
    pointer = u64(read(handle, 8))
    length = int.from_bytes(read(pointer, 4), "little")
    if not 1 <= length <= 128:
        raise ValueError("Invalid native name length")
    data = read(pointer + 4, length + 1)
    name = data[:-1].decode("utf-8", errors="strict")
    if data[-1] or not name or any(ord(c) < 32 or ord(c) == 127 for c in name):
        raise ValueError("Invalid native name")
    return name


def common_name(read, handle: int) -> str | None:
    if not handle:
        return None
    pointer = u64(read(handle, 8))
    if not pointer:
        return None
    if int.from_bytes(read(pointer, 4), "little") == 0:
        if read(pointer + 4, 1) != b"\0":
            raise ValueError("Invalid empty common name")
        return None
    return read_name(read, handle)


def name_part(read, handle: int) -> str:
    return common_name(read, handle) or ""


def decode(read, address: int, tables: tuple[int, int, int], include_profile=False) -> tuple[dict, tuple]:
    staff = person_offset(read, address, tables) == 0x480
    if staff:
        base = tables[0] - RVA[0]
        for rva, displacement in ((STAFF_RVA[0], 0), (STAFF_RVA[2], -0x480)):
            metadata = read(base + rva - 16, 16)
            if struct.unpack_from('<q', metadata)[0] != displacement:
                raise ValueError('Player/staff vtable displacement changed')
            info = u64(metadata, 8)
            name = u64(read(info + 8, 8))
            expected = b'N2db28ACTUAL_PLAYER_AND_NON_PLAYERE\0'
            if read(name, len(expected)) != expected:
                raise ValueError('Player/staff runtime type changed')
        # Shared PERSON_DATA getters and virtual-base adjustment prove field reuse.
        for slot, adjustment in ((40, 0x150), (41, 0x158), (42, 0x160), (55, 0x1C8)):
            a, h = base + RVA[2], base + STAFF_RVA[2]
            if (read(a + slot * 8, 8) != read(h + slot * 8, 8)
                    or struct.unpack('<q', read(h - adjustment, 8))[0] != -0x110):
                raise ValueError('Player/staff shared person getter changed')
    return _decode_record(read, address, tables, player_staff=staff, include_profile=include_profile)


def person_offset(read, address, tables):
    table = u64(read(address, 8))
    if table == tables[0]:
        return 0x388
    if table == tables[0] - RVA[0] + STAFF_RVA[0]:
        return 0x480
    raise ValueError('Unsupported player primary type')


def _decode_record(read, address: int, tables: tuple[int, int, int],
                   virtual_identity: int | None = None, player_staff=False, include_profile=False) -> tuple[dict, tuple]:
    if address <= 0 or address % 8:
        raise ValueError("Invalid player address")
    delta = 0xF8 if player_staff else 0
    size = 0x4A0 if player_staff else SIZE
    expected_tables = tuple(tables[0] - RVA[0] + rva for rva in STAFF_RVA) if player_staff else tables
    data = read(address, size)
    if tuple(u64(data, off) for off in (0, 0x140, 0x388 + delta)) != expected_tables:
        raise ValueError("Player runtime types changed")
    identity, secondary = struct.unpack_from("<II", data, 0x394 + delta)
    if virtual_identity is None:
        # Native duni/rdui are independent. Generated database players may have
        # rdui=0; cached virtual profiles instead have the non-table index -1.
        if not identity or int.from_bytes(data[0x390+delta:0x394+delta], 'little') == 0xFFFFFFFF:
            raise ValueError("Invalid player identity or non-table cache record")
    elif (identity != virtual_identity or secondary != 0
          or int.from_bytes(data[0x390:0x394], "little") != 0xFFFFFFFF):
        if (identity and identity != virtual_identity and secondary == 0
                and int.from_bytes(data[0x390:0x394], "little") == 0xFFFFFFFF):
            raise VirtualCacheIdentityMismatchError("Virtual profile cache identity disagrees")
        raise ValueError("Virtual profile cache identity disagrees")
    first = name_part(read, u64(data, 0x298 + delta))
    last = name_part(read, u64(data, 0x2A0 + delta))
    common = common_name(read, u64(data, 0x2A8 + delta))
    full_name = " ".join(part for part in (first, last) if part) or common
    if not full_name:
        raise ValueError("Player has no readable name")
    day, year = struct.unpack_from("<HH", data, 0x2D0 + delta)
    if not 1850 <= year <= 2200 or not 1 <= day <= 366:
        raise ValueError("Invalid player birth date")
    birthday = date(year, 1, 1) + timedelta(days=day - 1)
    if birthday.year != year:
        raise ValueError("Invalid player birth day")
    values = {name: data[0x148 + offset] for name, offset in ATTRIBUTES.items()}
    fifths = bool(data[0x270] & 0x80)
    attributes = {name: player_profile.rating(raw, fifths) for name, raw in values.items()}
    profile = player_profile.decode(read, tables[0] - RVA[0], data, 0x388 + delta,
                                    virtual=virtual_identity is not None) if include_profile else None
    # Recheck bytes and strings: reject detected changes, without claiming atomicity.
    if read(address, size) != data or first != name_part(read, u64(data, 0x298 + delta)) or last != name_part(read, u64(data, 0x2A0 + delta)):
        raise ValueError("Player changed during read; retry")
    if common != common_name(read, u64(data, 0x2A8 + delta)):
        raise ValueError("Player common name changed during read; retry")
    result = {"name": full_name, "display_name": common or full_name, "birth_date": birthday.isoformat(),
              "attributes": attributes,
              "evidence": "native_player_record", "attribute_scale": "1–20" if fifths else "0–20"}
    if include_profile:
        result['profile'] = profile
    identity_tuple = (identity, first, last, birthday.isoformat())
    if virtual_identity is None:
        identity_tuple = (*identity_tuple, secondary)
    if player_staff:
        result.update(record_kind='player_staff', evidence='native_player_staff_shared_playing_and_person_data')
        identity_tuple = ('player_staff', *identity_tuple)
    return result, identity_tuple
