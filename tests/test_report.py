"""Tests for report.py's HTML report generation. Focused on the
per-severity finding counts shown in the filter checkboxes (e.g.
"high (12)") rather than re-testing every row/column already covered
indirectly via test_main.py's --scan tests."""

from report import generate_html_report
from rules import Finding


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
    assert '<input type="checkbox"' not in html


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
