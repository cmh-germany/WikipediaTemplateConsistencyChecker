"""Tests for json_report.py: the document's layout (checked field by
field and against a snapshot) and how it's written to a file or a
stream. The --json flag itself is covered in test_main.py."""

import dataclasses
import io
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

import json_report
import rules
import suppress
from report import SuppressionView
from rules import Finding
from suppress import Suppression, SuppressionStore

SNAPSHOT = Path(__file__).parent / "fixtures" / "json_report_snapshot.json"
FIXED_TIME = datetime(2026, 11, 15, 12, 0, 0, tzinfo=UTC)

BOLT_PARAMS = {"geburtsort": "", "status": "z", "sterbedatum": ""}
OWENS_PARAMS = {
    "status": "v",
    "medaillen": "{{Medaillen Sommersport|...}}",
    "groesse": "1,78",
}


def _run(**overrides) -> json_report.RunInfo:
    run = json_report.RunInfo(
        mode="scan", tool_version="9.9", limit=50, generated_at=FIXED_TIME
    )
    return dataclasses.replace(run, **overrides)


def _sample() -> tuple[dict[str, list[Finding]], SuppressionView]:
    """A small, deterministic run: one article with findings of several
    severities, one with a suppressed finding, and one clean article."""
    bolt_findings = [
        Finding("missing_birthplace", rules.LOW, "No birthplace.", ["geburtsort"]),
    ]
    owens_findings = [
        Finding(
            "medal_count_mismatch",
            rules.HIGH,
            "Olympische Spiele: 4 medals listed, but the summary declares 3.",
            ["medaillen"],
        ),
        Finding(
            "height_comma_format",
            rules.MEDIUM,
            "Height '1,78' uses a comma.",
            ["groesse"],
            note="Renders as 1,78 m.",
        ),
    ]
    suppressed_finding = Finding(
        "update_outdated", rules.LOW, "Update is 5 years old.", ["update"]
    )
    suppression = Suppression(
        rule_id="update_outdated", article="Jesse Owens", reason="Known"
    )
    view = SuppressionView(store=SuppressionStore([suppression]))
    view.add_article("Usain Bolt", BOLT_PARAMS, bolt_findings, [])
    view.add_article(
        "Jesse Owens", OWENS_PARAMS, owens_findings, [(suppressed_finding, suppression)]
    )
    view.add_article("Clean Article", {}, [], [])
    results = {
        "Usain Bolt": bolt_findings,
        "Jesse Owens": owens_findings,
        "Clean Article": [],
    }
    return results, view


def _document(**run_overrides) -> dict:
    results, view = _sample()
    return json_report.build_document(results, view, _run(**run_overrides))


def test_document_matches_snapshot():
    # The snapshot pins the whole layout, so an accidental rename or
    # removal of a field (a breaking change for consumers, see
    # FORMAT_VERSION) shows up as a test failure. If a change is
    # intentional, update tests/fixtures/json_report_snapshot.json by
    # hand -- and bump FORMAT_VERSION unless fields were only added.
    expected = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert _document() == expected


def test_document_has_version_and_generator():
    document = _document()
    assert document["format_version"] == json_report.FORMAT_VERSION
    assert document["generator"] == {
        "name": "WikipediaInfoboxConsistencyChecker",
        "version": "9.9",
    }
    assert document["generated_at"] == "2026-11-15T12:00:00+00:00"


def test_finding_fields():
    document = _document()
    entry = next(
        f for f in document["findings"] if f["rule_id"] == "height_comma_format"
    )
    assert entry["rule_title"] == rules.RULE_TITLES["height_comma_format"]
    assert entry["severity"] == rules.MEDIUM
    assert entry["article"] == "Jesse Owens"
    assert entry["article_url"] == "https://de.wikipedia.org/wiki/Jesse_Owens"
    assert entry["params"] == ["groesse"]
    assert entry["note"] == "Renders as 1,78 m."
    assert entry["suppression"] is None
    finding = Finding("height_comma_format", rules.MEDIUM, "x", ["groesse"])
    assert entry["fingerprint"] == suppress.fingerprint(finding, OWENS_PARAMS)


def test_finding_without_note_has_null_note():
    document = _document()
    entry = next(
        f for f in document["findings"] if f["rule_id"] == "missing_birthplace"
    )
    assert entry["note"] is None


def test_findings_sorted_by_severity():
    severities = [f["severity"] for f in _document()["findings"]]
    assert severities == [rules.HIGH, rules.MEDIUM, rules.LOW]


def test_summary_counts_exclude_suppressed_findings():
    summary = _document()["summary"]
    assert summary == {
        "articles_checked": 3,
        "articles_with_findings": 2,
        "findings": 3,
        "by_severity": {"very high": 0, "high": 1, "medium": 1, "low": 1},
        "suppressed_findings": 1,
    }


def test_suppressed_findings_listed_separately_with_reason_and_scope():
    document = _document()
    assert all(f["rule_id"] != "update_outdated" for f in document["findings"])
    [entry] = document["suppressed_findings"]
    assert entry["rule_id"] == "update_outdated"
    assert entry["suppression"] == {"reason": "Known", "scope": "article"}


@pytest.mark.parametrize(
    ("suppression", "scope"),
    [
        (Suppression(rule_id="update_outdated"), "rule"),
        (Suppression(rule_id="update_outdated", article="A"), "article"),
        (
            Suppression(rule_id="update_outdated", article="A", fingerprint="abc"),
            "finding",
        ),
    ],
)
def test_suppression_scope(suppression, scope):
    finding = Finding("update_outdated", rules.LOW, "old", ["update"])
    view = SuppressionView()
    view.add_article("A", {"update": "2020"}, [], [(finding, suppression)])
    document = json_report.build_document({"A": []}, view, _run())
    assert document["suppressed_findings"][0]["suppression"]["scope"] == scope


def test_articles_list_includes_clean_articles():
    articles = _document()["articles"]
    assert [a["title"] for a in articles] == [
        "Clean Article",
        "Jesse Owens",
        "Usain Bolt",
    ]
    assert articles[0]["findings"] == 0
    assert articles[1]["findings"] == 2


def test_run_section_records_filter():
    finding_filter = rules.FindingFilter(
        disabled_rules=frozenset({"missing_birthplace"}),
        fail_on=rules.HIGH,
        include_suppressed=True,
    )
    run = _document(
        finding_filter=finding_filter,
        suppressed_rules=frozenset({"update_outdated"}),
    )["run"]
    assert run["fail_on"] == rules.HIGH
    assert run["disabled_rules"] == ["missing_birthplace"]
    assert run["suppressed_rules"] == ["update_outdated"]
    assert run["include_suppressed"] is True


def test_local_file_has_no_article_urls():
    document = _document(mode="check", source="local_file", target="draft.txt")
    assert all(f["article_url"] is None for f in document["findings"])
    assert all(a["url"] is None for a in document["articles"])


def test_ids_unique_for_findings_sharing_a_fingerprint():
    # Two competitions' mismatches are about the same field and thus
    # share a fingerprint, but must still get distinct ids.
    findings = [
        Finding("medal_count_mismatch", rules.HIGH, "Olympics: 4 vs 3", ["medaillen"]),
        Finding("medal_count_mismatch", rules.HIGH, "WM: 2 vs 1", ["medaillen"]),
    ]
    view = SuppressionView()
    view.add_article("A", OWENS_PARAMS, findings, [])
    entries = json_report.build_document({"A": findings}, view, _run())["findings"]
    assert entries[0]["fingerprint"] == entries[1]["fingerprint"]
    assert entries[0]["id"] != entries[1]["id"]


def test_ids_stable_across_runs():
    first = [f["id"] for f in _document()["findings"]]
    second = [f["id"] for f in _document(generated_at=datetime.now(UTC))["findings"]]
    assert first == second


# --- JsonOutput -------------------------------------------------------


def test_write_file_is_utf8_json(tmp_path):
    path = tmp_path / "out.json"
    document = {"article": "Žaneta Žilinská"}
    json_report.JsonOutput(path=path).write(document)
    text = path.read_text(encoding="utf-8")
    assert "Žaneta Žilinská" in text
    assert json.loads(text) == document
    assert list(tmp_path.iterdir()) == [path]  # no leftover temp file


def test_write_file_replaces_existing_file(tmp_path):
    path = tmp_path / "out.json"
    path.write_text("old", encoding="utf-8")
    json_report.JsonOutput(path=path).write({"new": True})
    assert json.loads(path.read_text(encoding="utf-8")) == {"new": True}


def test_failed_write_keeps_old_file_and_removes_temp_file(tmp_path, monkeypatch):
    path = tmp_path / "out.json"
    path.write_text("old", encoding="utf-8")

    def fail_replace(src, dst):
        raise PermissionError("locked")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(PermissionError):
        json_report.JsonOutput(path=path).write({"new": True})
    assert path.read_text(encoding="utf-8") == "old"
    assert list(tmp_path.iterdir()) == [path]


def test_write_stream_is_single_ascii_document():
    stream = io.StringIO()
    document = {"article": "Žaneta", "n": 1}
    json_report.JsonOutput(stream=stream).write(document)
    text = stream.getvalue()
    assert text.isascii()
    assert text.endswith("}\n")
    assert json.loads(text) == document


def test_write_without_destination_is_an_error():
    with pytest.raises(ValueError):
        json_report.JsonOutput().write({})


def test_description_names_file_or_stdout(tmp_path):
    path = tmp_path / "out.json"
    assert json_report.JsonOutput(path=path).description == f"'{path.resolve()}'"
    assert json_report.JsonOutput(stream=io.StringIO()).description == (
        "standard output"
    )
