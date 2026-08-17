"""Tests for rules.py.

Organized by infobox *argument* (status, geburtstag, nation, ...)
rather than by individual rule function: every argument that feeds
into a rule gets at least one realistic-data test (using the real
fixtures from tests/fixtures/, via conftest.py) and, where the
argument can be wrong, at least one deliberately-incorrect-data test
that should trigger a finding. Not every one of the ~20 rule
functions gets its own dedicated test -- several are covered
incidentally because they share an argument with another test.

A fixed `today` is passed to run_all_checks throughout so date-based
findings (birth/death/update in the future, outdated update, ...)
don't depend on the wall-clock date the tests happen to run on."""

from datetime import date

import pytest

from rules import Finding, count_by_severity, run_all_checks

TODAY = date(2026, 8, 1)


def finding_ids(findings):
    return {f.rule_id for f in findings}


def finding_by_id(findings, rule_id):
    return next(f for f in findings if f.rule_id == rule_id)


def check(params, **kwargs):
    kwargs.setdefault("today", TODAY)
    return run_all_checks(params, **kwargs)


# ---------------------------------------------------------------------
# Integration sanity check: real, clean articles produce no findings
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bolt_params",
        "owens_params",
        "mihambo_params",
        "drechsler_params",
    ],
)
def test_real_clean_articles_produce_no_findings(fixture_name, request):
    params = request.getfixturevalue(fixture_name)
    findings = check(params)
    assert findings == []


# ---------------------------------------------------------------------
# status / sterbedatum
# ---------------------------------------------------------------------


def test_death_date_with_non_deceased_status_is_flagged():
    params = {"status": "a", "sterbedatum": "2020-01-01"}
    findings = check(params)
    assert "death_date_with_non_deceased_status" in finding_ids(findings)
    finding = finding_by_id(findings, "death_date_with_non_deceased_status")
    # The rendering-consequence aside lives in `note`, not appended to
    # `message` (issue #2), so message stays the short core fact.
    assert "Vorlage:Status Sportler" not in finding.message
    assert "Vorlage:Status Sportler" in finding.note


def test_status_deceased_without_death_date_is_flagged():
    params = {"status": "v"}
    findings = check(params)
    assert "status_deceased_without_death_date" in finding_ids(findings)
    assert findings[0].severity == "very high"
    assert findings[0].note is None


def test_status_deceased_with_death_date_real_owens_no_finding(owens_params):
    findings = check(owens_params)
    assert "status_deceased_without_death_date" not in finding_ids(findings)
    assert "death_date_with_non_deceased_status" not in finding_ids(findings)


def test_status_spelled_out_word_is_flagged():
    params = {"status": "aktiv"}
    findings = check(params)
    assert "status_code_spelled_out" in finding_ids(findings)
    assert findings[0].severity == "low"
    assert "coincidence" not in findings[0].message
    assert "coincidence" in findings[0].note


def test_invalid_status_code_is_flagged():
    params = {"status": "X"}
    findings = check(params)
    assert "invalid_status_code" in finding_ids(findings)
    assert findings[0].severity == "very high"
    assert "as-is" not in findings[0].message
    assert findings[0].note == "The infobox will likely display this raw text as-is."


def test_valid_single_letter_status_real_bolt_no_finding(bolt_params):
    findings = check(bolt_params)
    assert "invalid_status_code" not in finding_ids(findings)
    assert "status_code_spelled_out" not in finding_ids(findings)


def test_deceased_but_living_person_category_is_flagged():
    params = {"status": "v", "sterbedatum": "2020-01-01"}
    findings = check(params, categories=["Kategorie:Lebende Personen"])
    assert "deceased_but_living_person_category" in finding_ids(findings)


# ---------------------------------------------------------------------
# geburtstag / sterbedatum date comparisons
# ---------------------------------------------------------------------


def test_death_date_before_birth_date_is_flagged():
    params = {"geburtstag": "2000-01-01", "sterbedatum": "1990-01-01"}
    assert "death_date_before_birth_date" in finding_ids(check(params))


def test_birth_date_in_future_is_flagged():
    params = {"geburtstag": "2099-01-01"}
    assert "birth_date_in_future" in finding_ids(check(params))


def test_death_date_in_future_is_flagged():
    params = {"sterbedatum": "2099-01-01"}
    assert "death_date_in_future" in finding_ids(check(params))


def test_death_date_in_future_far_typo_year_is_flagged():
    # Regression test for issue #23: a transposed-digit typo like
    # "2233" (meant as "2023") used to be silently dropped by
    # date_range's old [1850, 2100] plausibility window, so this
    # obviously-future date produced no finding at all.
    params = {"sterbedatum": "2233-01-01"}
    assert "death_date_in_future" in finding_ids(check(params))


def test_birth_date_in_future_far_typo_year_is_flagged():
    params = {"geburtstag": "2233-01-01"}
    assert "birth_date_in_future" in finding_ids(check(params))


def test_implausible_age_at_death_far_typo_year_is_flagged():
    # Same root cause as the future-date case above, but on the "too
    # old" side: a typo'd birth year outside the old plausibility
    # window used to be excluded from every comparison, not just
    # future-date checks, silently hiding this mismatch too.
    params = {"geburtstag": "1500-01-01", "sterbedatum": "2020-01-01"}
    assert "implausible_age_at_death" in finding_ids(check(params))


def test_implausible_age_at_death_too_old_is_flagged():
    params = {"geburtstag": "1850-01-01", "sterbedatum": "2020-01-01"}
    assert "implausible_age_at_death" in finding_ids(check(params))


def test_implausible_age_at_death_too_young_is_flagged():
    params = {"geburtstag": "2020-01-01", "sterbedatum": "2020-01-05"}
    assert "implausible_age_at_death" in finding_ids(check(params))


def test_plausible_age_at_death_real_owens_no_finding(owens_params):
    findings = check(owens_params)
    assert "implausible_age_at_death" not in finding_ids(findings)


def test_career_end_before_birth_date_is_flagged():
    params = {"geburtstag": "2000-01-01", "karriereende": "1990-01-01"}
    assert "career_end_before_birth_date" in finding_ids(check(params))


def test_career_end_despite_active_status_is_flagged():
    params = {"status": "a", "karriereende": "2020-01-01"}
    assert "career_end_despite_active" in finding_ids(check(params))


def test_career_end_with_non_active_status_real_bolt_no_finding(bolt_params):
    # Bolt has both status='z' and karriereende set -- fine, since 'z'
    # (zurückgetreten/retired) isn't 'a' (active).
    findings = check(bolt_params)
    assert "career_end_despite_active" not in finding_ids(findings)


# ---------------------------------------------------------------------
# nationalkader
# ---------------------------------------------------------------------


def test_national_squad_before_birth_is_flagged():
    params = {"geburtstag": "2000-01-01", "nationalkader": "1990"}
    assert "national_squad_before_birth" in finding_ids(check(params))


def test_national_squad_implausibly_young_is_flagged():
    params = {"geburtstag": "2000-01-01", "nationalkader": "2005"}
    assert "national_squad_implausibly_young" in finding_ids(check(params))


def test_national_squad_plausible_real_mihambo_no_finding(mihambo_params):
    # geburtstag 1994, nationalkader 2013 -> ~age 19, plausible.
    findings = check(mihambo_params)
    assert "national_squad_before_birth" not in finding_ids(findings)
    assert "national_squad_implausibly_young" not in finding_ids(findings)


# ---------------------------------------------------------------------
# groesse / gewicht
# ---------------------------------------------------------------------


def test_height_comma_format_is_flagged():
    params = {"groesse": "1,95"}
    assert "height_comma_format" in finding_ids(check(params))


def test_weight_not_numeric_is_flagged():
    params = {"gewicht": "schwer"}
    assert "weight_not_numeric" in finding_ids(check(params))


def test_height_implausible_too_short_is_flagged():
    params = {"groesse": "50"}
    assert "height_implausible" in finding_ids(check(params))


def test_weight_implausible_too_heavy_is_flagged():
    params = {"gewicht": "400"}
    assert "weight_implausible" in finding_ids(check(params))


def test_height_huge_digit_run_does_not_crash():
    # Python 3.11+'s int() refuses digit runs beyond a fixed length
    # (sys.get_int_max_str_digits(), 4300 by default) and raises
    # ValueError instead of converting. groesse/gewicht is regular
    # wikitext, so a hostile or corrupted value like this must be
    # reported as a finding, not crash the checker.
    params = {"groesse": "9" * 5000}
    assert "height_not_numeric" in finding_ids(check(params))


def test_height_weight_real_bolt_plausible_no_finding(bolt_params):
    findings = check(bolt_params)
    ids = finding_ids(findings)
    assert (
        not {
            "height_comma_format",
            "height_not_numeric",
            "height_implausible",
            "weight_comma_format",
            "weight_not_numeric",
            "weight_implausible",
        }
        & ids
    )


# ---------------------------------------------------------------------
# nation
# ---------------------------------------------------------------------


def test_nation_nonstandard_format_is_flagged():
    params = {"nation": "Philippinen"}
    findings = check(params)
    assert "nation_nonstandard_format" in finding_ids(findings)
    assert finding_by_id(findings, "nation_nonstandard_format").note is None


def test_nation_unknown_code_is_flagged():
    params = {"nation": "{{ZZZ}}"}
    findings = check(params, nation_exists={"Vorlage:ZZZ": False})
    assert "nation_code_unknown" in finding_ids(findings)
    finding = finding_by_id(findings, "nation_code_unknown")
    assert "flag/country name" not in finding.message
    assert "flag/country name" in finding.note


def test_nation_known_templated_code_real_bolt_no_finding(bolt_params):
    findings = check(bolt_params, nation_exists={"Vorlage:JAM": True})
    ids = finding_ids(findings)
    assert "nation_nonstandard_format" not in ids
    assert "nation_code_unknown" not in ids


def test_nation_bare_iso_code_real_mihambo_no_finding(mihambo_params):
    # 'DEU' is a bare ISO-3166-1 code -- the documented form, even
    # though real articles more commonly use a {{XXX}} flag template.
    findings = check(mihambo_params, nation_exists={"Vorlage:DEU": True})
    ids = finding_ids(findings)
    assert "nation_nonstandard_format" not in ids
    assert "nation_code_unknown" not in ids


def test_nation_multiple_templates_real_drechsler_no_finding(drechsler_params):
    # Athlete who changed national teams (GDR -> DEU) -- both codes
    # must be recognized without flagging the field as nonstandard.
    findings = check(
        drechsler_params,
        nation_exists={"Vorlage:GDR": True, "Vorlage:DEU": True},
    )
    ids = finding_ids(findings)
    assert "nation_nonstandard_format" not in ids
    assert "nation_code_unknown" not in ids


# ---------------------------------------------------------------------
# disziplin
# ---------------------------------------------------------------------


def test_discipline_link_unknown_is_flagged():
    params = {"disziplin": "Bogenschiessen"}
    findings = check(params, discipline_exists={"Bogenschiessen": False})
    assert "discipline_link_unknown" in finding_ids(findings)
    finding = finding_by_id(findings, "discipline_link_unknown")
    assert "typo" not in finding.message
    assert finding.note == "Possibly a typo."


def test_discipline_known_bare_value_no_finding():
    params = {"disziplin": "Weitsprung"}
    findings = check(params, discipline_exists={"Weitsprung": True})
    assert "discipline_link_unknown" not in finding_ids(findings)


def test_discipline_already_wikilinked_real_bolt_skips_check(bolt_params):
    # Bolt's disziplin already contains hand-written [[...]] links, so
    # the auto-link existence check doesn't apply at all -- even with
    # an existence map that would otherwise flag it.
    findings = check(bolt_params, discipline_exists={})
    assert "discipline_link_unknown" not in finding_ids(findings)


# ---------------------------------------------------------------------
# medaillen / Medaillenspiegel
# ---------------------------------------------------------------------


def test_medal_count_mismatch_is_flagged():
    params = {
        "medaillen": (
            "{{Medaillen Sommersport|Wo=Weltmeisterschaften"
            "|Gold|2019 Doha|100 m|Gold|2021 Berlin|100 m}}"
        ),
        "Medaillenspiegel": "{{Medaillenspiegel|Weltmeisterschaften|3|0|0}}",
    }
    findings = check(params)
    assert "medal_count_mismatch" in finding_ids(findings)


def test_medal_count_mismatch_huge_digit_run_does_not_crash():
    # Python 3.11+'s int() refuses digit runs beyond a fixed length
    # (sys.get_int_max_str_digits(), 4300 by default) and raises
    # ValueError instead of converting. A hostile or corrupted
    # Medaillenspiegel gold count like this must be treated as
    # unparseable (0), not crash run_all_checks -- and since it no
    # longer matches the single medal actually listed, it's flagged.
    params = {
        "medaillen": (
            "{{Medaillen Sommersport|Wo=Weltmeisterschaften|Gold|2019 Doha|100 m}}"
        ),
        "Medaillenspiegel": (
            "{{Medaillenspiegel|Weltmeisterschaften|" + "9" * 5000 + "|0|0}}"
        ),
    }
    findings = check(params)
    assert "medal_count_mismatch" in finding_ids(findings)


def test_medal_counts_real_bolt_consistent_no_mismatch(bolt_params):
    findings = check(bolt_params)
    assert "medal_count_mismatch" not in finding_ids(findings)


def test_medal_counts_real_drechsler_consistent_no_mismatch(drechsler_params):
    findings = check(drechsler_params)
    assert "medal_count_mismatch" not in finding_ids(findings)


def test_medal_year_before_birth_is_flagged():
    params = {
        "geburtstag": "2000-01-01",
        "medaillen": "{{Medaillen Sommersport|Gold|1995 Testort|100 m}}",
    }
    assert "medal_before_birth" in finding_ids(check(params))


def test_medal_implausibly_young_is_flagged():
    params = {
        "geburtstag": "2000-01-01",
        "medaillen": "{{Medaillen Sommersport|Gold|2008 Testort|100 m}}",
    }
    assert "medal_implausibly_young" in finding_ids(check(params))


def test_medal_year_before_birth_typo_outside_old_extraction_window_is_flagged():
    # Regression test, same root cause as issue #23: a typo like "1023"
    # (meant "2023") falls outside the 18xx/19xx/20xx range
    # extract_medal_years used to restrict itself to, so it was
    # silently never extracted and this rule never fired.
    params = {
        "geburtstag": "2000-01-01",
        "medaillen": "{{Medaillen Sommersport|Gold|1023 Testort|100 m}}",
    }
    assert "medal_before_birth" in finding_ids(check(params))


def test_medal_years_real_bolt_plausible_no_finding(bolt_params):
    findings = check(bolt_params)
    ids = finding_ids(findings)
    assert "medal_before_birth" not in ids
    assert "medal_implausibly_young" not in ids


# ---------------------------------------------------------------------
# geburtsort / geburtsland
# ---------------------------------------------------------------------


def test_missing_birthplace_is_flagged_when_both_absent():
    params = {"status": "a"}
    assert "missing_birthplace" in finding_ids(check(params))


def test_missing_birthplace_not_flagged_when_only_country_given():
    params = {"geburtsland": "[[Deutschland]]"}
    assert "missing_birthplace" not in finding_ids(check(params))


def test_birthplace_real_bolt_present_no_finding(bolt_params):
    findings = check(bolt_params)
    assert "missing_birthplace" not in finding_ids(findings)


# ---------------------------------------------------------------------
# update
# ---------------------------------------------------------------------


def test_outdated_update_while_active_is_flagged():
    params = {"status": "a", "update": "2015-01-01"}
    assert "update_outdated" in finding_ids(check(params))


def test_recent_update_real_mihambo_active_no_finding(mihambo_params):
    # status='a', update = 1. März 2026, evaluated as of TODAY
    # (2026-08-01) -- recent, should not be flagged as outdated.
    findings = check(mihambo_params)
    assert "update_outdated" not in finding_ids(findings)


# ---------------------------------------------------------------------
# count_by_severity
# ---------------------------------------------------------------------


def test_count_by_severity_counts_each_severity():
    findings = [
        Finding("r1", "very high", "m1"),
        Finding("r2", "high", "m2"),
        Finding("r3", "high", "m3"),
        Finding("r4", "low", "m4"),
    ]
    assert count_by_severity(findings) == {
        "very high": 1,
        "high": 2,
        "medium": 0,
        "low": 1,
    }


def test_count_by_severity_empty_list_returns_all_zero():
    assert count_by_severity([]) == {
        "very high": 0,
        "high": 0,
        "medium": 0,
        "low": 0,
    }


def test_count_by_severity_result_is_in_severity_order():
    # dict.fromkeys(SEVERITY_ORDER, ...) preserves SEVERITY_ORDER's
    # insertion order -- callers (CLI/report summaries) rely on this
    # to print severities from most to least severe without re-sorting.
    counts = count_by_severity([Finding("r1", "low", "m1")])
    assert list(counts) == ["very high", "high", "medium", "low"]
