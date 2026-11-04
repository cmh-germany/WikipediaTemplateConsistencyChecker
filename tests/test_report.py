"""Tests for report.py's HTML report generation. Focused on the
per-severity finding counts shown in the filter checkboxes (e.g.
"high (12)") rather than re-testing every row/column already covered
indirectly via test_main.py's --scan tests."""

import json
import re

import suppress
from report import SuppressionView, generate_html_report
from rules import RULE_TITLES, Finding
from suppress import Suppression, SuppressionStore


def test_filter_checkboxes_show_counts_for_each_severity(tmp_path):
    results = {
        "Article A": [
            Finding("r1", "very high", "m1"),
            Finding("r2", "high", "m2"),
        ],
        "Article B": [Finding("r3", "low", "m3")],
        "Clean Article": [],
    }
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    assert "very high (1)" in html
    assert "high (1)" in html
    assert "medium (0)" in html
    assert "low (1)" in html


def test_filter_checkboxes_omit_checkbox_for_zero_findings(tmp_path):
    # medium has no findings here -- its label must still be shown
    # (issue #13: all severity labels stay visible for context), but
    # without a checkbox, since there's nothing to filter.
    results = {
        "Article A": [
            Finding("r1", "very high", "m1"),
            Finding("r2", "high", "m2"),
        ],
        "Article B": [Finding("r3", "low", "m3")],
    }
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    assert '<input type="checkbox" value="very high"' in html
    assert '<input type="checkbox" value="high"' in html
    assert '<input type="checkbox" value="low"' in html
    assert '<input type="checkbox" value="medium"' not in html
    assert "medium (0)" in html


def test_filter_checkboxes_all_zero_when_no_findings(tmp_path):
    results: dict[str, list[Finding]] = {"Clean Article": []}
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    assert "very high (0)" in html
    assert "high (0)" in html
    assert "medium (0)" in html
    assert "low (0)" in html
    assert '<input type="checkbox" value=' not in html


def test_note_column_shows_note_when_present(tmp_path):
    results = {
        "Article A": [Finding("r1", "high", "core message", note="extra context")],
    }
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    assert "<th>Note</th>" in html
    assert "extra context" in html
    # The note must not also be appended to the message cell (issue #2).
    assert "core message extra context" not in html


def test_note_column_shows_dash_when_absent(tmp_path):
    results = {"Article A": [Finding("r1", "high", "core message")]}
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    # Both the params and note cells fall back to a dash for this finding.
    assert html.count("&ndash;</td>") == 2


def test_filter_note_shown_and_escaped_when_given(tmp_path):
    output = tmp_path / "report.html"

    generate_html_report({"Article A": []}, str(output), filter_note="Filter <x>")

    html = output.read_text(encoding="utf-8")
    assert '<div class="filter-note">Filter &lt;x&gt;</div>' in html


def test_filter_note_absent_by_default(tmp_path):
    output = tmp_path / "report.html"

    generate_html_report({"Article A": []}, str(output))

    assert '<div class="filter-note">' not in output.read_text(encoding="utf-8")


def test_filter_checkboxes_count_across_all_articles_not_just_first(tmp_path):
    # Regression guard: severity_counts must be built from every
    # article's findings, not e.g. accidentally only the last one
    # processed.
    results = {
        "Article A": [Finding("r1", "medium", "m1")],
        "Article B": [Finding("r2", "medium", "m2")],
        "Article C": [Finding("r3", "medium", "m3")],
    }
    output = tmp_path / "report.html"

    generate_html_report(results, str(output))

    html = output.read_text(encoding="utf-8")
    assert "medium (3)" in html


# ---------------------------------------------------------------------
# Suppressions
# ---------------------------------------------------------------------

PARAMS = {"status": "a", "sterbedatum": "2020-01-01"}
FINDING = Finding(
    "death_date_with_non_deceased_status",
    "high",
    "sterbedatum is set, but status=a.",
    params=["sterbedatum", "status"],
)


def _report(tmp_path, results, view=None) -> str:
    output = tmp_path / "report.html"
    generate_html_report(results, str(output), suppressions=view)
    return output.read_text(encoding="utf-8")


def _suppressions_data(report_html: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="suppressions-data">(.*?)</script>',
        report_html,
        re.DOTALL,
    )
    assert match
    return json.loads(match.group(1))


def test_each_finding_row_has_suppress_checkbox_with_identifying_data(tmp_path):
    view = SuppressionView(params_by_title={"Athlete": PARAMS})
    html = _report(tmp_path, {"Athlete": [FINDING]}, view)

    assert 'data-rule="death_date_with_non_deceased_status"' in html
    assert 'data-article="Athlete"' in html
    assert f'data-fingerprint="{suppress.fingerprint(FINDING, PARAMS)}"' in html
    assert 'data-suppression=""' in html
    assert '<input type="checkbox" class="suppress-cb"' in html
    assert "<th" in html and ">Suppress</th>" in html


def test_suppressed_findings_get_their_own_collapsed_section(tmp_path):
    entry = Suppression(FINDING.rule_id, "Athlete", reason="known & fine")
    view = SuppressionView(store=SuppressionStore([entry]))
    view.add_article("Athlete", PARAMS, [], [(FINDING, entry)])

    html = _report(tmp_path, {"Athlete": []}, view)

    main_table, section = html.split('<details class="suppressed-section">')
    assert 'data-article="Athlete"' not in main_table
    assert "1 suppressed finding(s)" in section
    assert 'data-suppression="0"' in section
    assert 'value="known &amp; fine"' in section
    assert (
        'class="suppress-cb" title="Suppress this finding as a false positive" checked'
        in section
    )
    assert "(1 suppressed findings hidden)" in html


def test_no_suppressed_section_without_suppressed_findings(tmp_path):
    html = _report(tmp_path, {"Athlete": [FINDING]})
    assert 'class="suppressed-section"' not in html


def test_include_suppressed_shows_them_greyed_in_main_table(tmp_path):
    entry = Suppression(FINDING.rule_id, "Athlete")
    view = SuppressionView(store=SuppressionStore([entry]), include_suppressed=True)
    view.add_article("Athlete", PARAMS, [], [(FINDING, entry)])

    html = _report(tmp_path, {"Athlete": []}, view)

    assert 'class="suppressed-section"' not in html
    assert '<tr class="suppressed-row"' in html
    assert "(plus 1 suppressed, shown greyed out)" in html
    # Suppressed findings don't count towards the severity filter counts.
    assert "high (0)" in html


def test_rules_section_lists_every_rule_with_suppressed_ones_ticked(tmp_path):
    entry = Suppression("missing_birthplace", reason="not our concern")
    view = SuppressionView(store=SuppressionStore([entry]))

    html = _report(tmp_path, {"Athlete": []}, view)

    section = html.split('<details class="rules-section">')[1].split("</details>")[0]
    assert f"(1 of {len(RULE_TITLES)} suppressed)" in section
    for rule_id in RULE_TITLES:
        assert f'data-rule="{rule_id}"' in section
    assert (
        '<tr data-key="entry|0" data-suppression="0" data-rule="missing_birthplace">'
        in section
    )
    assert 'value="not our concern"' in section
    assert section.count(" checked>") == 1


def test_existing_suppressions_are_embedded_for_saving(tmp_path):
    store = SuppressionStore(
        [Suppression("missing_birthplace"), Suppression(FINDING.rule_id, "Athlete")]
    )
    html = _report(tmp_path, {"Athlete": []}, SuppressionView(store=store))
    assert _suppressions_data(html) == json.loads(store.to_json())


def test_embedded_suppressions_cannot_close_the_script_element(tmp_path):
    store = SuppressionStore(
        [Suppression(FINDING.rule_id, "</script><script>alert(1)</script>")]
    )
    html = _report(tmp_path, {}, SuppressionView(store=store))
    assert "</script><script>alert(1)" not in html
    assert _suppressions_data(html)["suppressions"][0]["article"] == (
        "</script><script>alert(1)</script>"
    )


def test_save_bar_shows_target_path(tmp_path):
    path = tmp_path / "suppressions.json"
    html = _report(tmp_path, {}, SuppressionView(path=path))
    assert 'id="save-button"' in html
    assert f"<code>{path}</code>" in html


def test_add_article_keeps_params_only_for_articles_with_findings():
    view = SuppressionView()
    view.add_article("Clean", PARAMS, [], [])
    view.add_article("Athlete", PARAMS, [FINDING], [])
    assert view.params_by_title == {"Athlete": PARAMS}
