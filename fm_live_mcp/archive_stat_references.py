"""Build-pinned archive reference transport and checked table identities.

The source adapter must select flags2/reference-mode0/switches0000 before
using decode_prefix. Prefix parsing does not establish the physical record width.
Call verify_native once per query and use the caller's rechecked ReadSet to resolve.
"""
import struct

from . import competitions, database, teams, world

REFERENCE_MODE = 0x56D2C98
REFERENCE_SWITCHES = 0x56D3522
SUPPORTED_ENCODING = {'stream_flags': 2, 'global_reference_mode': '00',
                      'global_reference_switches': '0000', 'version': 7}
NATIVE_SPANS = {
    0x11019C0: 'a8324039c8010837',
    0x11019FC: '882e02d00889149109014039080540393f05007161000054a8000037070000145f0c0071c1010054a8010036882e02b008617239c8020036ff0b00b9a80240f9081940f9e1230091e00315aa8200805200013fd6e80b40b9150000147f0200f9',
    0x1101AB4: 'e81b40391f09007141010054e21f4039e00313aae10314aa37160094',
    0x1101AE4: '950240f9a80240f9081940f9e1230091e00315aa8200805200013fd6a81240b9e8fbff35e80b40b91f05003180030054e91b40393f05007161030054940240f9',
    0x1101B14: 'e91b40393f05007161030054',
    0x1101B88: '8802f837892e02b020d946f909a846a94a0109cb1f0d8aeb82000054297968f8690200f902000014690240f9c9f7ffb5094440f9292940a94a0109cb1f0d8aeb82000054287968f8680200f9c8f6ffb5',
    0x1101C1C: '8832403948020837',
    0x1101C68: '882e02d00889149109014039080540393f05007161000054a8000037070000145f040071e1010054c8010036',
    0x1101CC8: '7f0200f9ff3f0039802e02b000603491030c40f9e10313aae20315aa0400805236050094',
    0x11031E8: '3f0000f964070034',
    0x11032D8: 'd70240f9e80240f9081940f9e1630091e00317aa4200805200013fd6e81240b968000034000080521f000014e833c0791f05003160030054e80b00b91f09003161010054d60240f9c80240f9081940f9e1230091e00316aa8200805200013fd6c81240b908feff35e80b40b9c8fdff37a9225f3929010037e903082a8aae46a96b010acb3f0d8beb82000054497969f8690200f902000014690240f9090100b4',
    0x1103394: 'e803082a894640f9292940a94a0109cb1f0d8aeba2faff54287968f8680200f928feffb5',
}


def verify_native(read, base):
    for rva, hex_bytes in NATIVE_SPANS.items():
        expected = bytes.fromhex(hex_bytes)
        if read(base + rva, len(expected)) != expected:
            raise ValueError('Archive statistics reference transport changed')
    if read(base + REFERENCE_MODE, 1) != b'\0' or read(base + REFERENCE_SWITCHES, 2) != b'\0\0':
        raise ValueError('Unsupported archive statistics reference encoding')


def decode_prefix(raw: bytes) -> dict:
    if not isinstance(raw, bytes) or len(raw) < 7:
        raise ValueError('Truncated archive statistics reference prefix')
    tag = raw[0]
    if tag != 0:
        raise ValueError(f'Unsupported archive statistics team reference tag: {tag}')
    team_index, marker = struct.unpack_from('<ih', raw, 1)
    if team_index < -1:
        raise ValueError('Invalid archive statistics team table index')
    extended = marker == -2
    consumed = 11 if extended else 7
    if len(raw) < consumed:
        raise ValueError('Truncated extended archive statistics competition reference')
    competition_index = struct.unpack_from('<i', raw, 7)[0] if extended else marker
    if competition_index < 0 and (extended or competition_index != -1):
        raise ValueError('Invalid archive statistics competition table index')
    return {'consumed_bytes': consumed,
            'team_reference': {'tag': tag, 'index': None if team_index == -1 else team_index,
                               'state': 'null' if team_index == -1 else 'table_index'},
            'competition_reference': {'marker': marker, 'extended': extended,
                                      'index': None if competition_index == -1 else competition_index,
                                      'state': 'null' if competition_index == -1 else 'table_index'}}


def _validated_indices(prefix):
    if not isinstance(prefix, dict):
        raise ValueError('Invalid archive statistics reference prefix')
    consumed = prefix.get('consumed_bytes')
    if type(consumed) is not int or consumed not in (7, 11):
        raise ValueError('Invalid archive statistics reference prefix length')
    team = prefix.get('team_reference')
    competition = prefix.get('competition_reference')
    if not isinstance(team, dict) or not isinstance(competition, dict):
        raise ValueError('Invalid archive statistics references')
    if type(team.get('tag')) is not int or team['tag'] != 0:
        raise ValueError('Unsupported archive statistics team reference tag')
    for name, reference in (('team', team), ('competition', competition)):
        if 'index' not in reference:
            raise ValueError(f'Missing archive statistics {name} index')
        index = reference['index']
        if index is None:
            if reference.get('state') != 'null':
                raise ValueError(f'Invalid null archive statistics {name} reference')
        elif (type(index) is not int or not 0 <= index <= 0x7fffffff
              or reference.get('state') != 'table_index'):
            raise ValueError(f'Invalid archive statistics {name} table index')
    marker, extended = competition.get('marker'), competition.get('extended')
    if (type(marker) is not int or not -32768 <= marker <= 32767 or type(extended) is not bool
            or extended != (marker == -2) or consumed != (11 if extended else 7)):
        raise ValueError('Invalid archive statistics competition marker')
    index = competition['index']
    if (extended and index is None) or (not extended and index != (None if marker == -1 else marker)):
        raise ValueError('Archive statistics competition marker disagrees with index')
    return team['index'], competition['index']


def _checked_identity(read, address, row, index):
    identity = read(address + 8, 12)
    native_index, primary, secondary = struct.unpack('<III', identity)
    random_id = None if primary == secondary else secondary
    if (native_index != index or not primary or row['database_index'] != index
            or (row['native_id'], row['random_id']) != (primary, random_id)):
        raise ValueError('Archive statistics linked identity changed')
    return identity


def resolve(read, base: int, prefix: dict) -> dict:
    team_index, competition_index = _validated_indices(prefix)
    team_row = competition_row = team_binding = competition_binding = None
    if team_index is not None:
        team_row, team_binding = teams.by_index(read, base, team_index)
        identity = _checked_identity(read, team_binding['address'], team_row, team_index)
        if identity != team_binding['identity']:
            raise ValueError('Archive statistics team binding changed')
    if competition_index is not None:
        competition_row = competitions.by_index(read, base, competition_index)
        info = database.table(read, base, 'competitions')
        if competition_index >= info['count']:
            raise ValueError('Archive statistics competition membership changed')
        address = world.pointer(read, info['start'] + competition_index*8)
        identity = _checked_identity(read, address, competition_row, competition_index)
        competition_binding = {'address': address, 'identity': identity, 'database_index': competition_index,
                               'native_id': competition_row['native_id'], 'random_id': competition_row['random_id'],
                               'kind': 'competition'}
    return {'team': team_row, 'competition': competition_row,
            '_bindings': {'team': team_binding, 'competition': competition_binding}}
