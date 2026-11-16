"""Offline checks for fm_live_mcp.fmdb.extras (live reads are covered by scripts/fmdb_oracle.py)."""
from fm_live_mcp.fmdb import extras, tables
from fm_live_mcp.fmdb.vm import Unavailable


def test_derived_fields_are_well_formed():
    for rtype, fields in extras.DERIVED.items():
        assert rtype in tables.RECORD_TYPES, rtype
        for name, field in fields.items():
            assert name.isidentifier() and field.label and field.source and callable(field.read), name


def test_unknown_derived_field_is_unavailable():
    result = extras.read_derived(object(), 0, 'no_such_field')
    assert isinstance(result.value, Unavailable) and result.key == 'x:no_such_field'


def test_player_slots_name_both_layouts():
    assert extras.PLAYER_SLOTS[21] == (0xD09BB0, 0xD5BEA8)
    assert extras.PLAYER_SLOTS[138][0] == 0xD3012C and extras.PLAYER_SLOTS[23][0] == 0xD2CA74


def test_census_fields_are_outside_the_catalog_and_labelled():
    if not extras.EXTRA_FIELDS:
        return
    from fm_live_mcp.fmdb import catalog
    if not catalog.DEFAULT_EDITOR_FMF.exists():
        return
    codes = catalog.load_catalog().codes()
    for rtype, fields in extras.EXTRA_FIELDS.items():
        assert rtype in tables.RECORD_TYPES, rtype
        for code, info in fields.items():
            assert len(code) == 4 and code not in codes, (rtype, code)
            assert info['name'] and isinstance(info['name_inferred'], bool), (rtype, code)
            assert info['view'] in ('database', 'game'), (rtype, code)
            assert 0 < info['records_with_value'] <= info['records_sampled'], (rtype, code)
        assert extras.CENSUS['types'][rtype]['with_value'] == len(fields)
