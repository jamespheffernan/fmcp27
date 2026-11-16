"""Relation lists of the core tables exploded into one row per item (views, no data of their own).

The core snapshot stores list fields as JSON (record references as
`{"table", "unique_id", "random_id"}`), filled by the background column fill in priority
order (managed club first), so these views grow as the fill reaches more rows: a NULL list
means "not read yet", `[]` means "read, empty". References resolve through the target table's
`uid` (the record's unique id). Item keys keep the editor codes' meanings: `leve` level
(0-100), `rrea` reason code (enum not mapped), `perm` permanent, `rcdt` (rival flag, meaning
not established), `ntin` (second-nation info value, not mapped).
"""
from __future__ import annotations


def _ref_view(owner_table, owner_col_code, kind, target_table, item_key, extra=''):
    return (
        f"SELECT o.idx AS {owner_table}_idx, '{kind}' AS kind, '{target_table}' AS target_table, "
        f"tg.idx AS target_idx, CAST(json_extract(j.value, '$.{item_key}.unique_id') AS INTEGER) AS target_uid, "
        "json_extract(j.value, '$.leve') AS level, json_extract(j.value, '$.rrea') AS reason_code"
        f"{extra} FROM {owner_table} o, json_each(o.{{{owner_table}.{owner_col_code}}}) j "
        f"LEFT JOIN {target_table} tg ON tg.uid = json_extract(j.value, '$.{item_key}.unique_id') "
        f"WHERE json_valid(o.{{{owner_table}.{owner_col_code}}})")


def views(engine):
    public = {'scope': 'public', 'reason': 'rivals and affiliations are shown on club profiles'}
    person_fav = ' UNION ALL '.join([
        _ref_view('person', 'Pfvp', 'favourite', 'person', 'pers', ", json_extract(j.value, '$.perm') AS permanent"),
        _ref_view('person', 'Pdsp', 'disliked', 'person', 'pers', ", json_extract(j.value, '$.perm') AS permanent"),
        _ref_view('person', 'Pfvc', 'favourite', 'club', 'club', ', NULL AS permanent'),
        _ref_view('person', 'Pdsc', 'disliked', 'club', 'club', ', NULL AS permanent'),
    ])
    club_people = ' UNION ALL '.join([
        _ref_view('club', 'Cfvp', 'favourite', 'person', 'pers', ", json_extract(j.value, '$.perm') AS permanent"),
        _ref_view('club', 'Cdsp', 'disliked', 'person', 'pers', ", json_extract(j.value, '$.perm') AS permanent"),
    ])
    return {
        'club_rival': ('one row per rival of each club (club.rival_clubs): rival club idx, level, reason code',
                       _ref_view('club', 'Crvc', 'rival', 'club', 'club',
                                 ", json_extract(j.value, '$.rcdt') AS rcdt"), public),
        'club_affiliate': ('one row per current affiliation of each club (club.current_affiliations, raw items)',
                           "SELECT o.idx AS club_idx, j.key AS item, j.value AS item_json FROM club o, "
                           "json_each(o.{club.Cafl}) j WHERE json_valid(o.{club.Cafl})", public),
        'person_favourite': ('favourite and disliked people and clubs of every person (person.favourite_people, '
                             'disliked_people, favourite_clubs, disliked_clubs): target idx, level, reason code',
                             person_fav, {'scope': 'public', 'reason': 'favoured and disliked clubs and people are on every '
                         'profile (PERSON panel list 0x3B1B8C: CanViewFavouredClubs and CanViewFavouredPeople for '
                         'every person)'}),
        'club_favourite_person': ('favourite and disliked people of every club', club_people,
                                  {'scope': 'public', 'reason': 'favoured personnel are on every club profile (CLUB '
                                   'panel list 0xD725C: CanViewFavouredPersonnel for every club)'}),
        'player_position': ('one row per position rating of each player (player.position_ratings, 1-20); '
                            'position_index is the stored list order (labels not established here)',
                            "SELECT o.idx AS player_idx, CAST(j.key AS INTEGER) AS position_index, j.value AS rating "
                            "FROM player o, json_each(o.{player.PPra}) j WHERE json_valid(o.{player.PPra})",
                            {'scope': 'own_club', 'own_person_column': 'player_idx',
                             'reason': 'position ratings: own club exact; others through the '
                             'manager view knowledge masks'}),
        'person_nationality': ('every nationality of every person: the main nationality (person.nationality_idx) '
                               'and each second nation (person.second_nations_PNRs)',
                               "SELECT o.idx AS person_idx, 'main' AS kind, o.{person.Pnat} AS nation_idx, NULL AS "
                               "info FROM person o WHERE o.{person.Pnat} IS NOT NULL UNION ALL "
                               "SELECT o.idx, 'second', n.idx, json_extract(j.value, '$.ntin') FROM person o, "
                               "json_each(o.{person.PNRs}) j LEFT JOIN nation n ON n.uid = "
                               "json_extract(j.value, '$.nati.unique_id') WHERE json_valid(o.{person.PNRs})",
                               {'scope': 'public', 'reason': 'nationalities are on every profile'}),
    }
