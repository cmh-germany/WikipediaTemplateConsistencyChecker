"""Tests for parse.py.

Real fixtures (tests/fixtures/*.wikitext, see conftest.py) exercise the
parser against actual messy real-world formatting: a template name
followed by an HTML comment before the first "|", trailing
{{Alter|...}} annotations after a date, a bare ISO-3166 nation code
next to templated ones, multiple nation flag templates for an athlete
who changed national teams, and year-only dates. Synthetic values are
used where real articles are (correctly) too well-formed to exercise
an edge case, or where deliberately wrong data is needed."""

from datetime import date

import pytest

import parse
from parse import DateParts

# ---------------------------------------------------------------------
# find_infobox / extract_params / parse_infobox_params
# ---------------------------------------------------------------------


def test_find_infobox_amid_surrounding_article_text(bolt_wikitext):
    wikitext = (
        "'''Usain Bolt''' (* 21. August 1986) ist ein ehemaliger "
        "jamaikanischer Sprinter.\n\n== Karriere ==\n"
        + bolt_wikitext
        + "\n\n== Weblinks ==\n* [https://iaaf.org Profil]\n"
        "[[Kategorie:Leichtathlet (Jamaika)]]\n"
    )
    template = parse.find_infobox(wikitext)
    assert template is not None
    assert "kurzname" in str(template)


def test_find_infobox_strips_comment_right_after_template_name(bolt_wikitext):
    # bolt_wikitext itself has "{{Infobox Leichtathlet\n<!-- ... -->\n| ..."
    # -- the comment is part of the raw template name until the first
    # "|", so this is a real-world regression test for comment
    # stripping in _normalize_template_name.
    assert "<!--" in bolt_wikitext.split("|", 1)[0]
    assert parse.find_infobox(bolt_wikitext) is not None


def test_find_infobox_returns_none_when_absent():
    wikitext = "'''Foo Bar''' war ein Politiker.\n{{Infobox Politiker|name=Foo}}"
    assert parse.find_infobox(wikitext) is None


def test_find_infobox_case_and_underscore_insensitive():
    wikitext = "{{infobox_leichtathlet|kurzname=Foo}}"
    assert parse.find_infobox(wikitext) is not None


def test_extract_params_real_bolt_values(bolt_params):
    assert bolt_params["kurzname"] == "Usain Bolt"
    assert bolt_params["nation"] == "{{JAM}}"
    assert bolt_params["status"] == "z"
    assert bolt_params["groesse"] == "195"
    assert bolt_params["gewicht"] == "94"
    assert bolt_params["karriereende"] == "12. August 2017"


def test_extract_params_drops_empty_fields(bolt_params):
    # sterbedatum/sterbeort/sterbeland are present but empty in the raw
    # wikitext (Bolt is alive) -- must not show up as empty strings.
    assert "sterbedatum" not in bolt_params
    assert "sterbeort" not in bolt_params
    assert "sterbeland" not in bolt_params


def test_extract_params_comment_only_value_is_not_a_real_value():
    wikitext = "{{Infobox Leichtathlet|karriereende = <!-- Medaillen -->|status=a}}"
    params = parse.parse_infobox_params(wikitext)
    assert "karriereende" not in params
    assert params["status"] == "a"


def test_extract_params_bare_nation_code_real_mihambo(mihambo_params):
    assert mihambo_params["nation"] == "DEU"


def test_extract_params_multi_template_nation_real_drechsler(drechsler_params):
    assert drechsler_params["nation"] == "{{GDR|2=DDR}}, {{DEU}}"


def test_parse_infobox_params_returns_none_without_template():
    assert parse.parse_infobox_params("Just some article text.") is None


# ---------------------------------------------------------------------
# extract_template_names / nation field shape
# ---------------------------------------------------------------------


def test_extract_template_names_single_real_bolt(bolt_params):
    assert parse.extract_template_names(bolt_params["nation"]) == ["JAM"]


def test_extract_template_names_multiple_real_drechsler(drechsler_params):
    assert parse.extract_template_names(drechsler_params["nation"]) == ["GDR", "DEU"]


def test_extract_template_names_bare_code_returns_empty_real_mihambo(mihambo_params):
    assert parse.extract_template_names(mihambo_params["nation"]) == []


def test_extract_template_names_empty_value():
    assert parse.extract_template_names("") == []


# ---------------------------------------------------------------------
# medal parsing: extract_medal_years, medal_counts/totals_by_category,
# normalize_competition_name
# ---------------------------------------------------------------------


def test_extract_medal_years_real_bolt(bolt_params):
    years = parse.extract_medal_years(bolt_params["medaillen"])
    assert years == [
        2008,
        2008,
        2012,
        2012,
        2012,
        2016,
        2016,
        2016,
        2007,
        2007,
        2009,
        2009,
        2009,
        2011,
        2011,
        2013,
        2013,
        2013,
        2015,
        2015,
        2015,
        2017,
        2002,
        2002,
        2002,
        2003,
        2014,
        2015,
        2005,
    ]


def test_extract_medal_years_ignores_year_like_number_in_discipline_text():
    # Deliberately mimics the documented edge case (parse.py docstring):
    # a typo in the discipline text ("1950 m" instead of "4x100 m")
    # must NOT be picked up as a medal year -- only the "Jahr Ort"
    # argument (here "2019 Doha") is a legitimate source of years.
    value = "{{Medaillen Sommersport|Gold|2019 Doha|1950 m Staffel}}"
    assert parse.extract_medal_years(value) == [2019]


def test_extract_medal_years_ignores_number_in_link_target():
    # Deliberately mimics the documented edge case: a section-link
    # target containing unrelated years ("...von 1951 bis 1990...")
    # must be ignored in favor of the visible display text ("1986").
    value = (
        "{{Medaillen Sommersport|Gold|"
        "[[Sportlerkarriere#Laufbahn von 1951 bis 1990|Leipzig 1986]]|"
        "Weitsprung}}"
    )
    assert parse.extract_medal_years(value) == [1986]


def test_extract_medal_years_empty_value():
    assert parse.extract_medal_years("") == []


@pytest.mark.parametrize(
    "label_a,label_b,expected_key",
    [
        ("Leichtathletik-EM", "Europameisterschaften", "europameisterschaften"),
        (
            "Leichtathletik-Hallen-WM",
            "Hallenweltmeisterschaften",
            "hallenweltmeisterschaften",
        ),
        ("Olympia", "Olympische Spiele", "olympischespiele"),
        (
            "Leichtathletik-Junioren-WM",
            "Juniorenweltmeisterschaften",
            "u20weltmeisterschaften",
        ),
    ],
)
def test_normalize_competition_name_matches_across_naming_conventions(
    label_a, label_b, expected_key
):
    assert parse.normalize_competition_name(label_a) == expected_key
    assert parse.normalize_competition_name(label_b) == expected_key


def test_normalize_competition_name_empty():
    assert parse.normalize_competition_name("") == ""


def test_medal_counts_by_category_real_bolt(bolt_params):
    counts = parse.medal_counts_by_category(bolt_params["medaillen"])
    assert counts["olympischespiele"] == {
        "label": "Olympia",
        "gold": 8,
        "silber": 0,
        "bronze": 0,
    }
    assert counts["weltmeisterschaften"] == {
        "label": "Leichtathletik-WM",
        "gold": 11,
        "silber": 2,
        "bronze": 1,
    }


def test_medal_totals_by_category_real_bolt(bolt_params):
    totals = parse.medal_totals_by_category(bolt_params["Medaillenspiegel"])
    assert totals["olympischespiele"] == {
        "label": "Olympische Spiele",
        "gold": 8,
        "silber": 0,
        "bronze": 0,
    }
    assert totals["u20weltmeisterschaften"] == {
        "label": "Juniorenweltmeisterschaften",
        "gold": 1,
        "silber": 2,
        "bronze": 0,
    }


def test_medal_totals_by_category_skips_incomplete_call():
    # Deliberately incorrect/incomplete data: a Medaillenspiegel call
    # missing the bronze count (only 3 positional args instead of 4).
    value = "{{Medaillenspiegel|Olympische Spiele|8|0}}"
    assert parse.medal_totals_by_category(value) == {}


def test_medal_totals_by_category_huge_digit_run_does_not_crash():
    # Python 3.11+'s int() refuses digit runs beyond a fixed length
    # (sys.get_int_max_str_digits(), 4300 by default) and raises
    # ValueError instead of converting. Medaillenspiegel counts are
    # regular wikitext, so a hostile or corrupted value like this must
    # be treated as unparseable (count left at 0), not crash.
    value = "{{Medaillenspiegel|Olympische Spiele|" + "9" * 5000 + "|0|0}}"
    totals = parse.medal_totals_by_category(value)
    assert totals["olympischespiele"] == {
        "label": "Olympische Spiele",
        "gold": 0,
        "silber": 0,
        "bronze": 0,
    }


def test_medal_counts_by_category_strips_icon_link_and_medaillenland_call():
    # Real-world 'Wo' values can carry a decorative rings icon and a
    # trailing {{MedaillenLand|...}} note (per parse.py docstring) --
    # both must be stripped so the label is just the competition name.
    value = (
        "{{Medaillen Sommersport|Wo=[[Datei:Olympic rings.svg|30px]] "
        "[[Olympische Sommerspiele|Olympische Spiele]] "
        "{{MedaillenLand|{{DDR}}}}|Gold|2000 Sydney|Weitsprung}}"
    )
    counts = parse.medal_counts_by_category(value)
    assert counts["olympischespiele"] == {
        "label": "Olympische Spiele",
        "gold": 1,
        "silber": 0,
        "bronze": 0,
    }


# ---------------------------------------------------------------------
# visible_text
# ---------------------------------------------------------------------


def test_visible_text_resolves_piped_wikilink():
    text = parse.visible_text(
        "[[Olympische Sommerspiele 2008/Leichtathletik|2008 Peking]]"
    )
    assert text == "2008 Peking"


def test_visible_text_bare_wikilink_uses_title():
    assert parse.visible_text("[[Sherwood Content]]") == "Sherwood Content"


def test_visible_text_empty():
    assert parse.visible_text("") == ""


# ---------------------------------------------------------------------
# parse_date
# ---------------------------------------------------------------------


def test_parse_date_real_bolt_geburtstag_with_trailing_alter_template(bolt_params):
    # Real value: "21. August 1986 ({{Alter|1986|08|21}} Jahre)" -- the
    # trailing age-computation template must not confuse the parser.
    assert parse.parse_date(bolt_params["geburtstag"]) == DateParts(1986, 8, 21)


def test_parse_date_real_drechsler_karriereende_year_only(drechsler_params):
    assert parse.parse_date(drechsler_params["karriereende"]) == DateParts(
        2004, None, None
    )


def test_parse_date_iso():
    assert parse.parse_date("1986-08-21") == DateParts(1986, 8, 21)


def test_parse_date_datum_template():
    assert parse.parse_date("{{DATUM|21|8|1986}}") == DateParts(1986, 8, 21)


def test_parse_date_resolves_wikilinked_date():
    assert parse.parse_date("[[12. März|12. März]] [[1995]]") == DateParts(1995, 3, 12)


def test_parse_date_maerz_ascii_spelling_variant():
    assert parse.parse_date("16. Maerz 1995") == DateParts(1995, 3, 16)


def test_parse_date_unrecognized_free_text_returns_none():
    # Deliberately not a supported format (decade text, not a year).
    assert parse.parse_date("etwa in den 1990er Jahren") is None


def test_parse_date_empty_returns_none():
    assert parse.parse_date("") is None


# ---------------------------------------------------------------------
# date_range
# ---------------------------------------------------------------------


def test_date_range_full_precision_date():
    assert parse.date_range(DateParts(1986, 8, 21)) == (
        date(1986, 8, 21),
        date(1986, 8, 21),
    )


def test_date_range_year_only_spans_whole_year():
    assert parse.date_range(DateParts(2004, None, None)) == (
        date(2004, 1, 1),
        date(2004, 12, 31),
    )


def test_date_range_year_month_spans_whole_month():
    assert parse.date_range(DateParts(1986, 2, None)) == (
        date(1986, 2, 1),
        date(1986, 2, 28),
    )


def test_date_range_year_month_leap_year_february():
    assert parse.date_range(DateParts(1988, 2, None)) == (
        date(1988, 2, 1),
        date(1988, 2, 29),
    )


def test_date_range_none_input():
    assert parse.date_range(None) is None


def test_date_range_implausible_year_returns_none():
    # Deliberately implausible (a typo like "1500" instead of "1950").
    assert parse.date_range(DateParts(1500, None, None)) is None
