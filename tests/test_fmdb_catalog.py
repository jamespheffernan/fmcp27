"""Offline tests for the editor.fmf schema catalog (synthetic frames plus the installed file)."""
from __future__ import annotations

import json
import os
import struct
from compression import zstd
from pathlib import Path

import pytest
from fm_live_mcp.fmdb import catalog as cat_mod
from fm_live_mcp.fmdb.catalog import (
    DEFAULT_EDITOR_FMF,
    build_catalog,
    editor_fmf_for_plugin,
    load_catalog,
    load_catalog_for_plugin,
    parse_container,
    split_comment,
)

PREAMBLE = b"\x02\x01fmf.\x08\x00\x00"


def _str(s: str) -> bytes:
    raw = s.encode()
    return struct.pack("<I", len(raw)) + raw


def make_fmf(files: dict[str, str]) -> bytes:
    """Build an fmf archive: header, back-to-back zstd frames, directory chunk."""
    frames, entries, offset = [], [], 0
    for name, xml in files.items():
        raw = ("﻿" + xml).encode() if name.endswith("0.xml") else xml.encode()
        z = zstd.compress(raw)
        frames.append(z)
        entries.append((name, offset, len(z), len(raw)))
        offset += len(z)
    tree: dict = {}
    for name, off, cs, us in entries:
        *dirs, leaf = name.split("/")
        node = tree
        for d in dirs:
            node = node.setdefault(d, {})
        node.setdefault("", []).append((leaf, off, cs, us))

    def dir_bytes(name: str, node: dict) -> bytes:
        files_ = node.get("", [])
        out = _str(name) + struct.pack("<I", len(files_))
        for leaf, off, cs, us in files_:
            stem, dot, ext = leaf.rpartition(".")
            out += _str(stem) + _str("." + ext) + struct.pack("<QQQQQ", off, cs, us, 1793419156, 1793419156)
        subs = [(k, v) for k, v in node.items() if k]
        out += struct.pack("<I", len(subs))
        for k, v in subs:
            out += dir_bytes(k, v)
        return out

    (root_name, root_node), = tree.items()
    directory = zstd.compress(dir_bytes(root_name, root_node))
    data_rel = 17
    dir_rel = data_rel + sum(len(f) for f in frames)
    return (PREAMBLE + struct.pack("<QQ", dir_rel, data_rel) + b"\x03" + b"".join(frames)
            + PREAMBLE + directory)


def wrap(*records: str, comment: str = "fields for the whole thing") -> str:
    return f"<record>\n<!-- {comment} -->\n" + "\n".join(records) + "\n</record>"


def rtype(code: str, *fields: str) -> str:
    return f'<record id="{code}"><list id="fields">{"".join(fields)}</list></record>'


def fdef(code: str, ftype: str, *body: str, name: str | None = None) -> str:
    label = f'<translation id="name" translation_id="1" type="use" value="{name or code}" />'
    return (f'<record><flags id="field" value="{code}" />{label}'
            f'<flags id="type" value="{ftype}" />{"".join(body)}</record>')


# ---------------------------------------------------------------- container


def test_container_directory_roundtrip():
    data = make_fmf({"editor/a/one.xml": "<record/>", "editor/a/two.xml": "<record><x/></record>",
                     "editor/b/three.xml": "<record/>"})
    frames, meta = parse_container(data)
    assert meta["mode"] == "directory" and meta["files"] == 3
    assert [f.name for f, _ in frames] == [
        "editor/a/one.xml", "editor/a/two.xml", "editor/b/three.xml", "<directory>"]
    assert frames[1][1] == b"<record><x/></record>"
    assert frames[0][0].offset == 26 and frames[0][0].size == len(b"<record/>")


def test_container_falls_back_to_magic_scan_when_directory_is_damaged():
    data = bytearray(make_fmf({"editor/a/one.xml": "<record/>", "editor/a/two.xml": "<record><x/></record>"}))
    data[9] ^= 0xFF  # directory pointer no longer valid
    frames, meta = parse_container(bytes(data))
    assert meta["mode"] == "magic-scan" and "directory_error" in meta
    assert [x for _, x in frames][:2] == [b"<record/>", b"<record><x/></record>"]


def test_container_rejects_garbage():
    with pytest.raises(cat_mod.CatalogError):
        parse_container(b"not an archive")


# ---------------------------------------------------------------- comments


@pytest.mark.parametrize("raw,clean,comment", [
    ("Name[COMMENT: a note]", "Name", "a note"),
    ("Name[COMMENT; editor; a note]", "Name", "editor; a note"),
    ("Name[COMMENT - comp editor; x]", "Name", "comp editor; x"),
    ("Name", "Name", None),
    ("[%string#file] ([%string#description])", "[%string#file] ([%string#description])", None),
    ("Two[COMMENT: has [brackets] inside]", "Two", "has [brackets] inside"),
])
def test_split_comment(raw, clean, comment):
    assert split_comment(raw) == (clean, comment)


# ---------------------------------------------------------------- definitions


def build(*frames: str):
    return build_catalog(make_fmf({f"editor/db/f{i}.xml": x for i, x in enumerate(frames)}))


def test_definition_range_name_comment_category():
    xml = wrap(rtype("play", (
        '<record><flags id="field" value="PCAB" />'
        '<translation id="name" translation_id="293291" type="use" value="Current Ability[COMMENT: editor; ca]" />'
        '<translation id="category" translation_id="293611" type="use" value="Player Attributes" />'
        '<translation id="hint" translation_id="5" type="use" value="Hint text[COMMENT: h]" />'
        '<flags id="type" value="integer" />'
        '<integer id="min_value" value="0" /><integer id="max_value" value="200" />'
        '<boolean id="is_optional" value="true" /><boolean id="is_weekly_wage" value="false" />'
        '<integer id="default_value" value="7" />'
        '<list id="dependencies"><record field="Ptyp" equals="2" /></list>'
        '</record>')))
    c = build(xml)
    f = c.field("play", "PCAB")
    assert (f.type, f.min_value, f.max_value) == ("integer", 0, 200)
    assert (f.name, f.comment) == ("Current Ability", "editor; ca")
    assert f.category == "Player Attributes" and f.hint == "Hint text" and f.translation_id == 293291
    assert f.flags == {"is_optional": True, "is_weekly_wage": False}
    assert f.extra["default_value"] == 7 and f.extra["hint_comment"] == "h"
    assert f.dependencies == ({"field": "Ptyp", "equals": "2"},)
    assert c.record_types["play"].comment == "fields for the whole thing"
    assert c.report["fields_without_type"] == 0 and c.report["unparsed_elements_by_tag"] == {}


def test_real_and_float_ranges_and_unknown_children_are_kept():
    xml = wrap(rtype("inju", fdef(
        "Iocr", "real", '<integer id="min_value" value="0" /><float id="max_value" value="5.0" />',
        '<string id="format" value="%1.6f" />', '<weird id="w" value="1"><kid/></weird>')))
    f = build(xml).field("inju", "Iocr")
    assert (f.min_value, f.max_value) == (0, 5.0)
    assert f.extra["format"] == "%1.6f"
    assert f.extra["unhandled"][0]["tag"] == "weird"


def test_byte_order_mark_is_ignored():
    xml = "\ufeff" + wrap(rtype("play", fdef("a", "string")))
    assert "a" in build(xml).record_types["play"].fields


def test_code_spelled_as_integer_element():
    xml = wrap(rtype("nnpl", (
        '<record><integer id="field" value="Natt" /><flags id="type" value="attribute" />'
        '<integer id="min_value" value="1" /><integer id="max_value" value="20" /></record>')))
    assert build(xml).field("nnpl", "Natt").type == "attribute"


# ---------------------------------------------------------------- enums


def test_inline_enum_labels_and_symbolic_keys():
    xml = wrap(rtype("pers", fdef("Pcst", "enum", (
        '<list id="enum_values">'
        '<record enum="1"><translation id="name" translation_id="2" type="use" value="Full Time[COMMENT: contract type]" /></record>'
        '<record enum="0"><translation id="name" translation_id="3" type="use" value="Part Time" /></record>'
        '</list>')), fdef("Pgen", "enum", (
        '<list id="enum_values"><record enum="male" enum_id="0"><string id="name" value="Male" /></record>'
        '<record enum="female" enum_id="1"><string id="name" value="Female" /></record></list>'))))
    c = build(xml)
    assert c.field("pers", "Pcst").enum == {1: "Full Time", 0: "Part Time"}
    assert c.field("pers", "Pcst").extra["enum_comments"] == {"1": "contract type"}
    assert c.field("pers", "Pgen").enum == {0: "Male", 1: "Female"}
    assert c.field("pers", "Pgen").extra["enum_extra"]["0"]["key"] == "male"
    assert c.report["enum_fields_with_inline_labels"] == 2


def test_named_enum_registry_resolves_even_when_defined_in_a_later_frame():
    fields = wrap(rtype("comp", fdef("dbty", "enum", '<flags id="enum_values" value="cdbt" />'),
                        fdef("xxxx", "enum", '<flags id="enum_values" value="gone" />'),
                        fdef("yyyy", "enum", '<string id="enum_values" value="stub" />'),
                        fdef("zzzz", "multiple_enum")))
    enums = wrap('<record id="cdbt"><list id="enum_values">'
                 '<record enum="0"><translation id="name" translation_id="1" type="use" value="League" /></record>'
                 '<record enum="1"><translation id="name" translation_id="2" type="use" value="Cup" /></record>'
                 '</list></record>', '<record id="stub" />')
    c = build(fields, enums)
    assert c.enums["cdbt"] == {0: "League", 1: "Cup"}
    f = c.field("comp", "dbty")
    assert f.enum == {0: "League", 1: "Cup"} and f.enum_ref == "cdbt"
    assert c.field("comp", "xxxx").enum is None and c.field("comp", "xxxx").enum_ref == "gone"
    assert c.stub_enums == ("stub",)
    r = c.report
    assert r["enum_fields_resolved_via_named_enum"] == 1
    assert r["enum_fields_referencing_undeclared_enum"] == 1
    assert r["enum_fields_referencing_enum_declared_without_labels"] == 1
    assert r["enum_fields_without_labels_or_reference"] == 1  # zzzz has neither


# ---------------------------------------------------------------- references and lists


def test_reference_fields_and_table_types():
    club = wrap(rtype("club",
                      fdef("dbnm", "string", '<flags id="database_table_type" value="club" />'),
                      fdef("Cnti", "database_record_unique_id", '<flags id="database_table_type" value="nation" />'),
                      fdef("Cbad", "database_record_list", '<flags id="database_table_type" value="mystery" />'),
                      fdef("Cnot", "database_record_unique_id")))
    nation = wrap(rtype("natc", fdef("dbnm", "string", '<flags id="database_table_type" value="nation" />')))
    c = build(club, nation)
    assert c.field("club", "Cnti").references == "nation"
    assert c.field("club", "dbnm").references is None  # a name field, not a reference
    assert c.resolve_table("nation") == ("natc",) and c.resolve_table("club") == ("club",)
    assert c.report["reference_fields_without_target"] == 1
    assert c.report["reference_fields_with_unresolvable_target"] == 1
    assert c.report["unresolvable_targets"] == ["mystery"]


def test_list_items_are_scoped_and_found():
    xml = wrap(
        rtype("nnpl",
              '<record><flags id="field" value="EDpr" /><flags id="type" value="list" />'
              '<translation id="name" translation_id="9" type="use" value="Roles" />'
              '<record id="list_item"><list id="fields">'
              + fdef("Cipp", "integer", '<integer id="min_value" value="1" />')
              + fdef("Cipp", "integer", '<integer id="min_value" value="2" />')
              + '</list></record></record>',
              fdef("Cipp", "string")),
        rtype("play", fdef("Cipp", "boolean")))
    c = build(xml)
    roles = c.field("nnpl", "EDpr")
    assert set(roles.item_fields) == {"Cipp"} and roles.item_fields["Cipp"].min_value == 1
    assert len(roles.item_field_list) == 2 and c.report["duplicate_item_field_codes"] == 1
    scopes = sorted(s.scope for s in c.find("Cipp"))
    assert scopes == ["nnpl/Cipp", "nnpl/EDpr/Cipp", "nnpl/EDpr/Cipp", "play/Cipp"]
    # scoped, not flattened: the top-level definitions keep their own types
    assert c.field("nnpl", "Cipp").type == "string" and c.field("play", "Cipp").type == "boolean"
    assert c.report["nested_field_definitions"] == 2


def test_database_table_item_view_and_unresolved_view():
    c = build(wrap(rtype("lsts", (
        '<record><flags id="field" value="clls" /><flags id="type" value="database_table" />'
        '<flags id="database_table_type" value="club" />'
        '<record id="list_item"><flags id="fields" value="clcl" /></record></record>'),
        '<record><flags id="field" value="zzls" /><flags id="type" value="database_table" />'
        '<flags id="database_table_type" value="club" />'
        '<record id="list_item"><flags id="fields" value="nope" /></record></record>')),
        wrap(rtype("clcl", '<record db_field="club,Cnam" />')))
    assert c.field("lsts", "clls").item_view == "clcl"
    assert c.report["item_view_references_not_defined_in_archive"] == 1
    assert c.report["item_views_not_in_archive"] == ["nope"]


# ---------------------------------------------------------------- scoping, search, views


def test_scoped_duplicates_across_record_types_and_search():
    c = build(wrap(rtype("curr", fdef("Cnam", "string", name="Name[COMMENT: currency name]")),
                   rtype("club", fdef("Cnam", "string", name="Club Name"))))
    assert sorted(s.scope for s in c.find("Cnam")) == ["club/Cnam", "curr/Cnam"]
    assert [s.scope for s in c.search("currency")] == ["curr/Cnam"]  # matches the comment only
    assert {s.scope for s in c.search("NAME")} == {"club/Cnam", "curr/Cnam"}
    assert c.find("none") == []


def test_duplicates_in_one_record_type_keep_every_definition():
    c = build(wrap(rtype("comp", fdef("duni", "integer"), fdef("duni", "string"))))
    rt = c.record_types["comp"]
    assert rt.fields["duni"].type == "integer" and len(rt.field_list) == 2
    assert rt.duplicates["duni"][1].type == "string"
    assert c.report["duplicate_definitions_in_scope"] == {"comp": 1}


def test_views_filters_columns_and_layouts():
    filt = wrap('<record id="prfl"><list id="fields">'
                '<record db_field="pers,duni"/>  <!-- unique id -->'
                '<record db_field="pers,Page" filter_min_value="20" filter_max_value="30" />'
                '<record db_field=" club,Cnam" hidden="true"/>'
                '<record db_field="pers,Pnai"><translation id="name" translation_id="4" type="use" '
                'value="Nation Contracted[COMMENT: n]" /></record>'
                '</list></record>', comment="fields to show for person filters")
    layout = wrap('<record id="agrc"><list id="fields">'
                  '<record><translation id="name" translation_id="1" type="use" value="Details" />'
                  '<flags id="type" value="record" /><boolean id="is_section" value="true" />'
                  '<list id="or_dependencies"><record field="Ptyp" equals="2" /></list>'
                  '<list id="fields"><record db_field="agrm,AGna" /></list></record>'
                  '<record insert_fields="dbch" /></list></record>')
    c = build(filt, layout)
    assert c.views["prfl"] == [("pers", "duni"), ("pers", "Page"), ("club", "Cnam"), ("pers", "Pnai")]
    entries = c.view_entries["prfl"]
    assert entries[1].attrs == {"filter_min_value": "20", "filter_max_value": "30"}
    assert entries[2].attrs["hidden"] == "true" and entries[2].attrs["db_field_raw"] == " club,Cnam"
    assert entries[3].attrs["name"] == "Nation Contracted" and entries[3].attrs["name_comment"] == "n"
    assert c.view_comments["prfl"] == "fields to show for person filters"
    assert "prfl" not in c.record_types
    assert c.views["agrc"] == [("agrm", "AGna")]
    assert c.view_entries["agrc"][0].section == ("Details",)
    assert c.view_includes["agrc"] == ("dbch",)
    assert c.sections["agrc"][0]["props"]["or_dependencies"] == [{"field": "Ptyp", "equals": "2"}]
    assert c.report["unparsed_elements_by_tag"] == {}


def test_section_wrapped_definitions_keep_section_title():
    xml = wrap('<record id="pers"><list id="fields"><record>'
               '<translation id="name" translation_id="1" type="use" value="Contract" />'
               '<flags id="type" value="record" /><boolean id="is_section" value="true" />'
               '<list id="fields">' + fdef("Pcsd", "date") + '</list></record></list></record>')
    f = build(xml).field("pers", "Pcsd")
    assert f.extra["section"] == ["Contract"]


# ---------------------------------------------------------------- export and cache


def test_to_json_is_stable_sorted_and_serialisable():
    xml = wrap(rtype("play", fdef("b", "integer", '<integer id="max_value" value="9" />'), fdef("a", "string")))
    data = make_fmf({"editor/db/x.xml": xml})
    one, two = build_catalog(data).to_json(), build_catalog(data).to_json()
    assert json.dumps(one, sort_keys=False) == json.dumps(two, sort_keys=False)
    assert list(one["record_types"]["play"]["fields"]) == ["a", "b"]  # sorted by code
    assert one["record_types"]["play"]["order"] == ["b", "a"]  # definition order preserved
    json.dumps(one)


def test_load_catalog_caches_by_path_size_mtime_and_hash(tmp_path):
    p = tmp_path / "editor.fmf"
    p.write_bytes(make_fmf({"editor/db/x.xml": wrap(rtype("play", fdef("a", "string")))}))
    first = load_catalog(p)
    assert load_catalog(p) is first and first.source_path == str(p)
    p.write_bytes(make_fmf({"editor/db/x.xml": wrap(rtype("play", fdef("a", "string"), fdef("b", "string")))}))
    second = load_catalog(p)
    assert second is not first and set(second.record_types["play"].fields) == {"a", "b"}


def test_plugin_path_resolution(tmp_path):
    bundle = tmp_path / "fm.app/Contents/PlugIns/game_plugin.bundle"
    target = bundle / "Contents/Resources/shared/data/editor.fmf"
    target.parent.mkdir(parents=True)
    target.write_bytes(make_fmf({"editor/db/x.xml": wrap(rtype("play", fdef("a", "string")))}))
    binary = bundle / "Contents/MacOS/game_plugin"
    assert editor_fmf_for_plugin(binary) == target
    assert editor_fmf_for_plugin(bundle) == target
    assert "a" in load_catalog_for_plugin(binary).record_types["play"].fields


def test_cli_find_search_and_dump(tmp_path, capsys):
    p = tmp_path / "editor.fmf"
    p.write_bytes(make_fmf({"editor/db/x.xml": wrap(rtype("curr", fdef("Cexr", "real", name="Exchange Rate")))}))
    assert cat_mod.main(["--path", str(p), "--find", "Cexr"]) == 0
    assert "curr/Cexr" in capsys.readouterr().out
    assert cat_mod.main(["--path", str(p), "--search", "exchange"]) == 0
    assert "1 match" in capsys.readouterr().out
    out = tmp_path / "o.json"
    assert cat_mod.main(["--path", str(p), "--dump", str(out), "--summary"]) == 0
    assert json.loads(out.read_text())["record_types"]["curr"]["fields"]["Cexr"]["type"] == "real"
    assert "type histogram" in capsys.readouterr().out
    assert cat_mod.main(["--path", str(p), "--find", "nope"]) == 1


# ---------------------------------------------------------------- installed file

installed = pytest.mark.skipif(not DEFAULT_EDITOR_FMF.exists(), reason="Football Manager 27 is not installed")


@pytest.fixture(scope="module")
def real():
    return load_catalog()


@installed
def test_installed_container_is_decoded_from_its_directory(real):
    assert len(real.frames) == 107
    assert real.container["mode"] == "directory" and real.container["files"] == 106
    assert real.frames[-1].name == "<directory>"
    assert real.frames[1].name == "editor/format/filters/comp filter.xml"
    assert sum(f.size for f in real.frames) > 2_000_000
    assert len(real.sha256) == 64


@installed
def test_installed_record_types_and_definitions(real):
    for code in ("pers", "play", "club", "comp", "natc", "nati", "stad", "team", "city", "curr", "inju"):
        assert code in real.record_types, code
    ca = real.field("play", "PCAB")
    assert (ca.type, ca.min_value, ca.max_value, ca.name) == ("integer", 0, 200, "Current Ability")
    assert {"Cnam", "Cexr"} <= set(real.record_types["curr"].fields)
    assert "crep" in real.record_types["comp"].fields
    assert len(real.codes()) >= 2000


@installed
def test_installed_enum_labels(real):
    contract = {0: "Part Time", 1: "Full Time", 2: "Amateur", 3: "Youth", 4: "Non-Contract"}
    assert real.field("pers", "Pcst").enum == contract
    assert {k: real.enums["cnst"][k] for k in contract} == contract
    assert len(real.enums["cdbt"]) == 39
    assert real.field("comp", "dbty").enum == real.enums["cdbt"]


@installed
def test_installed_views_and_references(real):
    assert ("pers", "duni") in real.views["prfl"] and ("comp", "crep") in real.views["cmfl"]
    assert len(real.views["prfl"]) > 100 and "clcl" in real.views
    assert "regi" not in real.views and "alnm" in real.view_includes["regi"]
    assert real.field("pers", "Pcti").references == "team"
    assert real.resolve_table("club") == ("club",)
    assert real.table_type_ids["club"] == 3
    assert real.field("lsts", "clls").item_view == "clcl"
    scopes = real.find("tbcl")
    assert {s.record_type for s in scopes} == {"club", "natc"}


@installed
def test_installed_report_is_clean_where_it_claims_to_be(real):
    r = real.report
    assert r["fields_without_type"] == 0 and r["field_records_without_code"] == 0
    assert r["unparsed_elements_by_tag"] == {}
    assert r["reference_fields_without_target"] == 0
    assert r["enum_fields_without_labels_or_reference"] == 0
    assert r["field_definitions"] == sum(1 for _ in real.iter_fields())


@installed
def test_installed_load_is_cached_and_json_is_serialisable(real):
    assert load_catalog() is real
    assert len(json.dumps(real.to_json())) > 1_000_000
