from . import _nonplayer70, _nonplayer70_reference, _player_1347364, _player_13486e4, _player_15739b8
parent = _player_1347364
row = _player_15739b8
embedded = _player_13486e4
base = _nonplayer70
ref = _nonplayer70_reference

def current_base(d, s):
    r = base.parse(d, s, reference_reader=ref.make_current_writer_reader('raw64'))
    base.validate_current_writer(r)
    return r

def parse(d, s):
    return parent.parse(d, s, direct_references=True, row38_reader=row.parse, embedded_reader=embedded.parse, base_reader=current_base)
