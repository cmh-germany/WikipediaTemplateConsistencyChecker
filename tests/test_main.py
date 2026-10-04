"""Tests for main.py's command-line interface: argument parsing/
dispatch (--scan vs. --check, --limit, --output, --no-cache, --open,
--fail-on), the --check target-resolution logic (article title, article
URL, local wikitext file), and the exit codes --fail-on produces
(including via a real subprocess). run_scan's internals (the actual scan loop) are
out of scope here -- these tests are about the CLI surface, not the
scan business logic.

run_check/run_scan themselves make real network calls via fetch.py, so
every test here either fully mocks fetch/report, or (for --scan)
replaces run_scan itself, to keep the suite network-free."""

import os
import subprocess
import sys
from typing import Any

import pytest

import main

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")
MAIN_PY = os.path.abspath(main.__file__)


def _recording_stub(calls: list[dict]):
    """Stub for run_scan: records its kwargs into `calls` and returns 0
    (a successful exit code), for tests that assert run_scan was never
    (or was) invoked with particular arguments."""

    def _stub(**kw):
        calls.append(kw)
        return 0

    return _stub


# ---------------------------------------------------------------------
# _extract_title_from_input
# ---------------------------------------------------------------------


def test_extract_title_from_https_url():
    url = "https://de.wikipedia.org/wiki/Usain_Bolt"
    assert main._extract_title_from_input(url) == "Usain Bolt"


def test_extract_title_from_http_url():
    url = "http://de.wikipedia.org/wiki/Heike_Drechsler"
    assert main._extract_title_from_input(url) == "Heike Drechsler"


def test_extract_title_from_url_with_multiple_underscores():
    url = "https://de.wikipedia.org/wiki/Leichtathletik-Weltmeisterschaften_2019"
    assert (
        main._extract_title_from_input(url) == "Leichtathletik-Weltmeisterschaften 2019"
    )


def test_extract_title_from_plain_title_is_passthrough():
    assert main._extract_title_from_input("Usain Bolt") == "Usain Bolt"


# ---------------------------------------------------------------------
# _print_findings
# ---------------------------------------------------------------------


def test_print_findings_empty(capsys):
    main._print_findings("Test Article", [])
    out = capsys.readouterr().out
    assert "=== Test Article ===" in out
    assert "No findings." in out


def test_print_findings_lists_severity_rule_and_message(capsys):
    from rules import Finding

    finding = Finding("some_rule", "high", "Something is wrong", params=["x"])
    main._print_findings("Test Article", [finding])
    out = capsys.readouterr().out
    assert "HIGH" in out
    assert "some_rule" in out
    assert "Something is wrong" in out


def test_print_findings_prints_severity_summary(capsys):
    from rules import Finding

    findings = [
        Finding("r1", "very high", "m1"),
        Finding("r2", "high", "m2"),
        Finding("r3", "low", "m3"),
    ]
    main._print_findings("Test Article", findings)
    out = capsys.readouterr().out
    assert "Total findings: 3 (Very high: 1, High: 1, Medium: 0, Low: 1)" in out


def test_print_findings_no_summary_line_when_empty(capsys):
    main._print_findings("Test Article", [])
    out = capsys.readouterr().out
    assert "Total findings" not in out


def test_print_findings_shows_note_when_present(capsys):
    from rules import Finding

    finding = Finding("some_rule", "high", "Something is wrong", note="Extra context")
    main._print_findings("Test Article", [finding])
    out = capsys.readouterr().out
    assert "(Note: Extra context)" in out


def test_print_findings_no_note_suffix_when_absent(capsys):
    from rules import Finding

    finding = Finding("some_rule", "high", "Something is wrong")
    main._print_findings("Test Article", [finding])
    out = capsys.readouterr().out
    assert "Note:" not in out


def test_print_findings_escapes_control_chars_in_note(capsys):
    from rules import Finding

    finding = Finding("some_rule", "high", "Something is wrong", note="Bad\x1b[31m")
    main._print_findings("Test Article", [finding])
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\\x1b[31m" in out


def test_print_findings_escapes_control_chars_in_message(capsys):
    from rules import Finding

    # e.g. a crafted "sterbedatum" value smuggling an ANSI escape sequence
    finding = Finding("some_rule", "high", "Some\x1b[31mvalue\x1b[0m")
    main._print_findings("Test Article", [finding])
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\\x1b[31mvalue\\x1b[0m" in out


def test_print_findings_escapes_control_chars_in_title(capsys):
    main._print_findings("Evil\x1b]0;pwned\x07Title", [])
    out = capsys.readouterr().out
    assert "\x1b" not in out
    assert "\x07" not in out
    assert "\\x1b]0;pwned\\x07Title" in out


def test_sanitize_console_text_escapes_newlines_and_carriage_returns():
    assert main._sanitize_console_text("a\nb\rc") == "a\\x0ab\\x0dc"


def test_sanitize_console_text_leaves_plain_text_unchanged():
    text = "Something is wrong with birth year 1990 (ä, ö, ü included)"
    assert main._sanitize_console_text(text) == text


# ---------------------------------------------------------------------
# _cache_status_note
# ---------------------------------------------------------------------


def test_cache_status_note_when_cache_enabled():
    assert main._cache_status_note(True) == " (from cache where possible)"


def test_cache_status_note_when_cache_disabled():
    assert main._cache_status_note(False) == ""


# ---------------------------------------------------------------------
# _warn_if_cache_stale (issue #20)
# ---------------------------------------------------------------------


def _mock_no_untracked_entries(monkeypatch):
    """Most of these tests are only exercising the days-based branch of
    _warn_if_cache_stale, so the untracked-entries check (see
    test_warn_if_cache_stale_warns_about_untracked_entries below) is
    mocked out of the way -- otherwise it would fall through to the
    real fetch.cache_has_untracked_entries(), reading whatever
    cache.json happens to exist on this machine."""
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: False)


def test_warn_if_cache_stale_warns_when_cache_old(monkeypatch, capsys):
    _mock_no_untracked_entries(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: 45)
    main._warn_if_cache_stale(use_cache=True, overwrite_cache=False)
    err = capsys.readouterr().err
    assert "45 days old" in err
    assert "oldest" in err.lower()
    assert "--overwrite-cache" in err


def test_warn_if_cache_stale_silent_when_cache_fresh(monkeypatch, capsys):
    _mock_no_untracked_entries(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: 5)
    main._warn_if_cache_stale(use_cache=True, overwrite_cache=False)
    assert capsys.readouterr().err == ""


def test_warn_if_cache_stale_silent_when_no_cache_file_yet(monkeypatch, capsys):
    _mock_no_untracked_entries(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: None)
    main._warn_if_cache_stale(use_cache=True, overwrite_cache=False)
    assert capsys.readouterr().err == ""


def test_warn_if_cache_stale_silent_when_cache_disabled(monkeypatch, capsys):
    # use_cache=False must short-circuit before either fetch.py call --
    # cache_age_days/cache_has_untracked_entries are deliberately left
    # unmocked so a real (accidental) call would fail loudly.
    main._warn_if_cache_stale(use_cache=False, overwrite_cache=False)
    assert capsys.readouterr().err == ""


def test_warn_if_cache_stale_silent_when_overwriting_cache(monkeypatch, capsys):
    # overwrite_cache=True must short-circuit before either fetch.py
    # call, for the same reason as above.
    main._warn_if_cache_stale(use_cache=True, overwrite_cache=True)
    assert capsys.readouterr().err == ""


def test_warn_if_cache_stale_warns_about_untracked_entries(monkeypatch, capsys):
    # A cache.json from before per-entry fetch timestamps existed: its
    # age is unknown, not "fresh" -- must warn regardless of what
    # cache_age_days() would report, and must not even call it (an
    # untracked cache has no reliable "oldest timestamp" to report).
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: True)
    monkeypatch.setattr(
        main.fetch,
        "cache_age_days",
        lambda: (_ for _ in ()).throw(AssertionError("should not be called")),
    )

    main._warn_if_cache_stale(use_cache=True, overwrite_cache=False)

    err = capsys.readouterr().err
    assert "older version" in err
    assert "--overwrite-cache" in err


def test_run_scan_prints_stale_cache_warning(monkeypatch, capsys, tmp_path):
    _stub_empty_scan(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: 31)

    result = main.run_scan(output=str(tmp_path / "report.html"))

    assert result == 0
    assert "31 days old" in capsys.readouterr().err


def test_run_scan_overwrite_cache_skips_stale_warning(monkeypatch, capsys, tmp_path):
    _stub_empty_scan(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: 90)

    result = main.run_scan(output=str(tmp_path / "report.html"), overwrite_cache=True)

    assert result == 0
    assert capsys.readouterr().err == ""


def test_run_scan_prints_untracked_cache_entries_warning(monkeypatch, capsys, tmp_path):
    # e.g. a cache.json left over from before per-entry fetch timestamps
    # existed (see issue #20 discussion) -- must warn even though
    # cache_age_days() alone would find nothing to report.
    _stub_empty_scan(monkeypatch)
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: True)

    result = main.run_scan(output=str(tmp_path / "report.html"))

    assert result == 0
    assert "older version" in capsys.readouterr().err


def test_run_scan_passes_overwrite_cache_to_fetch(monkeypatch, tmp_path):
    _stub_empty_scan(monkeypatch)
    seen: dict[str, bool] = {}
    monkeypatch.setattr(
        main.fetch,
        "fetch_all_with_cache",
        lambda session, titles, use_cache=True, overwrite_cache=False: (
            seen.update(overwrite_cache=overwrite_cache) or {}
        ),
    )

    main.run_scan(output=str(tmp_path / "report.html"), overwrite_cache=True)

    assert seen["overwrite_cache"] is True


# ---------------------------------------------------------------------
# _format_severity_summary
# ---------------------------------------------------------------------


def test_format_severity_summary_matches_issue_example():
    counts = {"very high": 2, "high": 3, "medium": 5, "low": 2}
    assert main._format_severity_summary(counts) == (
        "Total findings: 12 (Very high: 2, High: 3, Medium: 5, Low: 2)"
    )


def test_format_severity_summary_all_zero():
    counts = {"very high": 0, "high": 0, "medium": 0, "low": 0}
    assert main._format_severity_summary(counts) == (
        "Total findings: 0 (Very high: 0, High: 0, Medium: 0, Low: 0)"
    )


# ---------------------------------------------------------------------
# --version
# ---------------------------------------------------------------------


def test_version_flag_prints_version_and_exits_0(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["main.py", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 0
    assert main.__version__ in capsys.readouterr().out


def test_version_flag_does_not_require_scan_or_check(monkeypatch):
    # --version must work standalone, without tripping the otherwise
    # required --scan/--check mutually exclusive group.
    monkeypatch.setattr(sys, "argv", ["main.py", "--version"])
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 0


# ---------------------------------------------------------------------
# Argument parsing / dispatch (main())
# ---------------------------------------------------------------------


def test_scan_and_check_both_missing_is_an_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py"])
    with pytest.raises(SystemExit):
        main.main()


def test_scan_and_check_both_given_is_an_error(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--check", "Usain Bolt"])
    with pytest.raises(SystemExit):
        main.main()


def test_limit_must_be_an_integer(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--limit", "not-a-number"])
    with pytest.raises(SystemExit):
        main.main()


def test_limit_rejects_negative_value(monkeypatch):
    # argparse parses "-5" as a value fine (no option string looks
    # like a negative number) -- this must still be rejected, since a
    # negative eilimit would otherwise reach the MediaWiki API.
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--limit", "-5"])
    with pytest.raises(SystemExit):
        main.main()


def test_limit_rejects_zero(monkeypatch):
    # 0 is falsy in Python -- fetch.list_pages_using_template treats a
    # falsy limit as "unlimited", so silently accepting 0 here would
    # mean "--limit 0" scans everything instead of nothing.
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--limit", "0"])
    with pytest.raises(SystemExit):
        main.main()


def test_limit_accepts_positive_value(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--limit", "10"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls["limit"] == 10


def test_check_rejects_empty_target(monkeypatch):
    # args.check == "" is falsy but not None -- without an explicit
    # check, `if args.check:` in main() would misread this as "--scan
    # was chosen" and silently run a full scan instead of erroring.
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", ""])
    calls: list[dict] = []
    monkeypatch.setattr(main, "run_scan", _recording_stub(calls))
    with pytest.raises(SystemExit):
        main.main()
    assert calls == []


def test_check_rejects_whitespace_only_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "   "])
    with pytest.raises(SystemExit):
        main.main()


def test_scan_invokes_run_scan_with_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls == {
        "limit": None,
        "output": "report.html",
        "use_cache": True,
        "open_output": False,
        "overwrite_cache": False,
        "fail_on": "low",
    }


def test_scan_passes_through_limit_output_no_cache_and_open(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "main.py",
            "--scan",
            "--limit",
            "50",
            "--output",
            "athletes.html",
            "--no-cache",
            "--open",
        ],
    )
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls == {
        "limit": 50,
        "output": "athletes.html",
        "use_cache": False,
        "open_output": True,
        "overwrite_cache": False,
        "fail_on": "low",
    }


def test_scan_passes_through_overwrite_cache(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--overwrite-cache"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls["overwrite_cache"] is True


def test_check_invokes_run_check_with_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "Usain Bolt"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        main, "run_check", lambda target, **kw: calls.update(target=target, **kw) or 0
    )
    main.main()
    assert calls["target"] == "Usain Bolt"


def test_check_passes_target_through_unmodified_url(monkeypatch):
    # main() itself doesn't resolve titles/URLs -- that happens inside
    # run_check -- so the raw --check value must reach run_check as-is.
    url = "https://de.wikipedia.org/wiki/Usain_Bolt"
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", url])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        main, "run_check", lambda target, **kw: calls.update(target=target, **kw) or 0
    )
    main.main()
    assert calls["target"] == url


# ---------------------------------------------------------------------
# run_check: local file / article title / URL / not-found / no-infobox
# ---------------------------------------------------------------------


def test_run_check_local_wikitext_file(monkeypatch, capsys):
    # Real fixture, but nation='{{JAM}}' would otherwise trigger a real
    # network call to check "Vorlage:JAM" -- mock it out.
    monkeypatch.setattr(
        main.fetch, "templates_exist", lambda session, titles: {t: True for t in titles}
    )
    path = os.path.join(FIXTURES_DIR, "usain_bolt.wikitext")

    result = main.run_check(path)

    assert result == 0
    out = capsys.readouterr().out
    assert "usain_bolt.wikitext" in out
    assert "No findings." in out


def test_run_check_prints_current_action_message(monkeypatch, capsys):
    monkeypatch.setattr(
        main.fetch, "templates_exist", lambda session, titles: {t: True for t in titles}
    )
    path = os.path.join(FIXTURES_DIR, "usain_bolt.wikitext")

    main.run_check(path)

    out = capsys.readouterr().out
    assert f"Checking '{path}' ..." in out


def test_run_check_resolves_article_url_to_title_before_fetching(monkeypatch):
    seen = {}

    def fake_fetch(session, titles):
        seen["titles"] = titles
        return {}

    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(main.fetch, "fetch_pages_content_and_categories", fake_fetch)

    main.run_check("https://de.wikipedia.org/wiki/Usain_Bolt")

    assert seen["titles"] == ["Usain Bolt"]


def test_run_check_article_not_found_returns_2_and_prints_message(monkeypatch, capsys):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch,
        "fetch_pages_content_and_categories",
        lambda session, titles: {},
    )

    result = main.run_check("Nonexistent Article XYZ")

    assert result == main.EXIT_ERROR
    assert "not found" in capsys.readouterr().out


def test_run_check_no_infobox_found_returns_2_and_prints_message(monkeypatch, capsys):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch,
        "fetch_pages_content_and_categories",
        lambda session, titles: {
            titles[0]: {"wikitext": "no infobox here", "categories": []}
        },
    )

    result = main.run_check("Some Random Article")

    assert result == main.EXIT_ERROR
    assert "No Infobox Leichtathlet embedding found" in capsys.readouterr().out


def test_run_check_local_file_invalid_encoding_returns_2(tmp_path, capsys):
    # A draft accidentally saved as UTF-16 (e.g. from a word processor
    # default) instead of plain UTF-8 -- realistic given the README
    # explicitly warns against saving as .docx/rich text.
    path = tmp_path / "draft.wikitext"
    path.write_bytes("{{Infobox Leichtathlet|status=a}}".encode("utf-16"))

    result = main.run_check(str(path))

    assert result == main.EXIT_ERROR
    assert "not valid UTF-8" in capsys.readouterr().out


def test_run_check_local_file_unreadable_returns_2(monkeypatch, capsys, tmp_path):
    import builtins

    path = tmp_path / "draft.wikitext"
    path.write_text("{{Infobox Leichtathlet|status=a}}", encoding="utf-8")

    real_open = builtins.open

    def fake_open(file, *args, **kwargs):
        if os.fspath(file) == str(path):
            raise PermissionError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)

    result = main.run_check(str(path))

    assert result == main.EXIT_ERROR
    assert "Could not read" in capsys.readouterr().out


# ---------------------------------------------------------------------
# --output validation and report-write failure handling
# ---------------------------------------------------------------------


def test_scan_rejects_output_path_in_nonexistent_directory(monkeypatch, tmp_path):
    bad_output = tmp_path / "no_such_subdir" / "report.html"
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(bad_output)])
    calls: list[dict] = []
    monkeypatch.setattr(main, "run_scan", _recording_stub(calls))

    with pytest.raises(SystemExit):
        main.main()
    # Must fail before doing any (slow, network-bound) scan work.
    assert calls == []


def test_scan_rejects_output_path_that_is_a_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(tmp_path)])
    calls: list[dict] = []
    monkeypatch.setattr(main, "run_scan", _recording_stub(calls))

    with pytest.raises(SystemExit):
        main.main()
    assert calls == []


def test_scan_accepts_output_path_in_existing_writable_directory(monkeypatch, tmp_path):
    output = tmp_path / "report.html"
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(output)])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)

    main.main()

    assert calls["output"] == str(output)


def test_run_scan_report_write_failure_returns_2_instead_of_crashing(
    monkeypatch, capsys
):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch, "list_pages_using_template", lambda session, limit=None: []
    )
    monkeypatch.setattr(
        main.fetch,
        "fetch_all_with_cache",
        lambda session, titles, use_cache=True, overwrite_cache=False: {},
    )
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {})
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: None)
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: False)

    def raise_permission_error(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(main.report, "generate_html_report", raise_permission_error)

    result = main.run_scan(output="Z:/no_access/report.html")

    assert result == main.EXIT_ERROR
    assert "Could not write report" in capsys.readouterr().out


def test_run_scan_prints_severity_summary(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch,
        "list_pages_using_template",
        lambda session, limit=None: ["Dead Athlete"],
    )
    monkeypatch.setattr(
        main.fetch,
        "fetch_all_with_cache",
        lambda session, titles, use_cache=True, overwrite_cache=False: {
            "Dead Athlete": {
                # status='a' (active) with a death date given -- a
                # "high" severity contradiction
                # (death_date_with_non_deceased_status). No birthplace
                # given either, which also triggers a "low" severity
                # missing_birthplace finding.
                "wikitext": (
                    "{{Infobox Leichtathlet|status=a|sterbedatum=2020-01-01}}"
                ),
                "categories": [],
            }
        },
    )
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {})
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: None)
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: False)

    result = main.run_scan(output=str(tmp_path / "report.html"))

    assert result == main.EXIT_FINDINGS
    out = capsys.readouterr().out
    assert "Total findings: 2 (Very high: 0, High: 1, Medium: 0, Low: 1)" in out


# ---------------------------------------------------------------------
# run_scan: console-output consistency (issue #15)
# ---------------------------------------------------------------------


def _stub_empty_scan(monkeypatch):
    """Mocks fetch.py so run_scan completes instantly against an empty
    article list, for tests that only care about console output.
    Includes cache_age_days/cache_has_untracked_entries so tests don't
    fall through to the real implementations -- which would read this
    machine's actual cache.json (if any) instead of being isolated."""
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch, "list_pages_using_template", lambda session, limit=None: []
    )
    monkeypatch.setattr(
        main.fetch,
        "fetch_all_with_cache",
        lambda session, titles, use_cache=True, overwrite_cache=False: {},
    )
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {})
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: None)
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: False)


def test_run_scan_no_cache_hint_when_cache_disabled(monkeypatch, capsys, tmp_path):
    _stub_empty_scan(monkeypatch)

    result = main.run_scan(output=str(tmp_path / "report.html"), use_cache=False)

    assert result == 0
    assert "from cache where possible" not in capsys.readouterr().out


def test_run_scan_shows_cache_hint_when_cache_enabled(monkeypatch, capsys, tmp_path):
    _stub_empty_scan(monkeypatch)

    result = main.run_scan(output=str(tmp_path / "report.html"), use_cache=True)

    assert result == 0
    assert "from cache where possible" in capsys.readouterr().out


def test_run_scan_prints_writing_report_message(monkeypatch, capsys, tmp_path):
    _stub_empty_scan(monkeypatch)
    output = tmp_path / "report.html"

    result = main.run_scan(output=str(output))

    assert result == 0
    assert (
        f"Writing report to '{os.path.abspath(str(output))}'" in capsys.readouterr().out
    )


def test_run_scan_open_prints_opening_and_opened_messages(
    monkeypatch, capsys, tmp_path
):
    _stub_empty_scan(monkeypatch)
    opened_urls: list[str] = []
    monkeypatch.setattr(main.webbrowser, "open", opened_urls.append)
    output = tmp_path / "report.html"

    result = main.run_scan(output=str(output), open_output=True)

    assert result == 0
    out = capsys.readouterr().out
    assert "Opening report in your default browser" in out
    assert "Opened report." in out
    assert opened_urls == [f"file://{os.path.abspath(str(output))}"]


def test_run_scan_no_open_messages_or_browser_call_when_open_output_false(
    monkeypatch, capsys, tmp_path
):
    _stub_empty_scan(monkeypatch)
    opened_urls: list[str] = []
    monkeypatch.setattr(main.webbrowser, "open", opened_urls.append)

    result = main.run_scan(output=str(tmp_path / "report.html"), open_output=False)

    assert result == 0
    out = capsys.readouterr().out
    assert "Opening report" not in out
    assert "Opened report." not in out
    assert opened_urls == []


def test_run_scan_done_line_ends_with_newline_before_next_output(
    monkeypatch, capsys, tmp_path
):
    # The "Done." line must be its own line, cleanly separated from
    # whatever prints next (here: the --open messages) rather than
    # running together on one line.
    _stub_empty_scan(monkeypatch)
    monkeypatch.setattr(main.webbrowser, "open", lambda url: True)

    result = main.run_scan(output=str(tmp_path / "report.html"), open_output=True)

    assert result == 0
    lines = capsys.readouterr().out.splitlines()
    done_index = next(i for i, line in enumerate(lines) if line.startswith("Done."))
    opening_index = next(
        i for i, line in enumerate(lines) if line.startswith("Opening report")
    )
    # "Done." must be a self-contained line, with a blank line before
    # the next message rather than the two running together.
    assert lines[done_index + 1] == ""
    assert opening_index > done_index + 1


# ---------------------------------------------------------------------
# --fail-on: CI-friendly exit codes (issue #12)
# ---------------------------------------------------------------------

# status='a' (active) with a death date -> one "high" finding
# (death_date_with_non_deceased_status); no birthplace -> one "low"
# finding (missing_birthplace). No nation/disziplin, so run_check needs
# no template-existence lookups (and so no network) for it.
_HIGH_AND_LOW_WIKITEXT = "{{Infobox Leichtathlet|status=a|sterbedatum=2020-01-01}}"


def _stub_scan_with_high_and_low_findings(monkeypatch):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch,
        "list_pages_using_template",
        lambda session, limit=None: ["Dead Athlete"],
    )
    monkeypatch.setattr(
        main.fetch,
        "fetch_all_with_cache",
        lambda session, titles, use_cache=True, overwrite_cache=False: {
            "Dead Athlete": {"wikitext": _HIGH_AND_LOW_WIKITEXT, "categories": []}
        },
    )
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {})
    monkeypatch.setattr(main.fetch, "cache_age_days", lambda: None)
    monkeypatch.setattr(main.fetch, "cache_has_untracked_entries", lambda: False)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("low", "low"),
        ("HIGH", "high"),
        ("very-high", "very high"),
        ("very_high", "very high"),
        ("very high", "very high"),
    ],
)
def test_severity_type_normalizes_spelling(value, expected):
    assert main._severity(value) == expected


@pytest.mark.parametrize("value", ["none", "None", " NONE "])
def test_severity_type_none_disables_failing(value):
    assert main._severity(value) is None


def test_severity_type_rejects_unknown_value_and_lists_choices():
    with pytest.raises(main.argparse.ArgumentTypeError) as exc_info:
        main._severity("critical")
    message = str(exc_info.value)
    assert "critical" in message
    assert "very-high, high, medium, low, none" in message


@pytest.mark.parametrize(
    ("fail_on", "expected"),
    [
        (None, 0),
        ("low", 1),
        ("medium", 1),
        ("high", 1),
        ("very high", 0),
    ],
)
def test_findings_exit_code_thresholds(fail_on, expected):
    counts = {"very high": 0, "high": 1, "medium": 0, "low": 2}
    assert main._findings_exit_code(counts, fail_on) == expected


def test_findings_exit_code_zero_when_no_findings():
    counts = dict.fromkeys(main.rules.SEVERITY_ORDER, 0)
    assert main._findings_exit_code(counts, "low") == 0


def test_findings_exit_code_explains_failure_on_stderr(capsys):
    counts = {"very high": 1, "high": 2, "medium": 0, "low": 5}
    main._findings_exit_code(counts, "high")
    err = capsys.readouterr().err
    assert "3 finding(s) at or above 'high' severity" in err


def test_fail_on_rejects_unknown_severity(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--fail-on", "critical"])
    calls: list[dict] = []
    monkeypatch.setattr(main, "run_scan", _recording_stub(calls))
    with pytest.raises(SystemExit) as exc_info:
        main.main()
    assert exc_info.value.code == 2
    assert calls == []


def test_scan_passes_through_fail_on(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--fail-on", "very-high"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls["fail_on"] == "very high"


def test_scan_fail_on_none_passes_none(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--fail-on", "none"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls["fail_on"] is None


def test_check_defaults_to_fail_on_low(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "X"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        main, "run_check", lambda target, **kw: calls.update(target=target, **kw) or 0
    )
    main.main()
    assert calls["fail_on"] == "low"


def test_check_passes_through_fail_on(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "X", "--fail-on", "low"])
    calls: dict[str, Any] = {}
    monkeypatch.setattr(
        main, "run_check", lambda target, **kw: calls.update(target=target, **kw) or 0
    )
    main.main()
    assert calls["fail_on"] == "low"


@pytest.mark.parametrize(
    ("fail_on", "expected"),
    [(None, 0), ("high", 1), ("low", 1), ("very high", 0)],
)
def test_run_check_exit_code_respects_fail_on(tmp_path, fail_on, expected):
    path = tmp_path / "draft.wikitext"
    path.write_text(_HIGH_AND_LOW_WIKITEXT, encoding="utf-8")
    assert main.run_check(str(path), fail_on=fail_on) == expected


def test_run_check_fails_on_any_finding_by_default(tmp_path):
    path = tmp_path / "draft.wikitext"
    path.write_text(_HIGH_AND_LOW_WIKITEXT, encoding="utf-8")
    assert main.run_check(str(path)) == main.EXIT_FINDINGS


def test_run_scan_fails_on_any_finding_by_default(monkeypatch, tmp_path):
    _stub_scan_with_high_and_low_findings(monkeypatch)
    result = main.run_scan(output=str(tmp_path / "report.html"))
    assert result == main.EXIT_FINDINGS


def test_run_scan_without_findings_exits_0_by_default(monkeypatch, tmp_path):
    _stub_empty_scan(monkeypatch)
    result = main.run_scan(output=str(tmp_path / "report.html"))
    assert result == main.EXIT_OK


def test_run_check_fail_on_still_prints_findings(tmp_path, capsys):
    path = tmp_path / "draft.wikitext"
    path.write_text(_HIGH_AND_LOW_WIKITEXT, encoding="utf-8")
    main.run_check(str(path), fail_on="low")
    assert "death_date_with_non_deceased_status" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("fail_on", "expected"),
    [(None, 0), ("medium", 1), ("very high", 0)],
)
def test_run_scan_exit_code_respects_fail_on(monkeypatch, tmp_path, fail_on, expected):
    _stub_scan_with_high_and_low_findings(monkeypatch)
    result = main.run_scan(output=str(tmp_path / "report.html"), fail_on=fail_on)
    assert result == expected


def test_run_scan_fail_on_still_writes_and_opens_report(monkeypatch, tmp_path):
    # The non-zero exit must not cost CI users the report itself.
    _stub_scan_with_high_and_low_findings(monkeypatch)
    opened_urls: list[str] = []
    monkeypatch.setattr(main.webbrowser, "open", opened_urls.append)
    output = tmp_path / "report.html"

    result = main.run_scan(output=str(output), open_output=True, fail_on="low")

    assert result == 1
    assert output.is_file()
    assert len(opened_urls) == 1


def test_run_scan_report_write_failure_still_returns_2_with_fail_on(
    monkeypatch, capsys
):
    _stub_scan_with_high_and_low_findings(monkeypatch)

    def raise_permission_error(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(main.report, "generate_html_report", raise_permission_error)

    assert (
        main.run_scan(output="Z:/no_access/report.html", fail_on="low")
        == main.EXIT_ERROR
    )
    assert "Could not write report" in capsys.readouterr().out


# Integration: the real CLI in a subprocess, so the exit code that
# actually reaches the shell (via sys.exit(main())) is what's asserted.
# --check on a local file with no nation/disziplin makes no network calls.


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, MAIN_PY, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=os.path.dirname(MAIN_PY),
        timeout=60,
    )


@pytest.mark.parametrize(
    ("extra_args", "expected"),
    [
        ([], 1),
        (["--fail-on", "none"], 0),
        (["--fail-on", "low"], 1),
        (["--fail-on", "high"], 1),
        (["--fail-on", "very-high"], 0),
    ],
)
def test_cli_check_exit_code_with_fail_on(tmp_path, extra_args, expected):
    path = tmp_path / "draft.wikitext"
    path.write_text(_HIGH_AND_LOW_WIKITEXT, encoding="utf-8")
    result = _run_cli("--check", str(path), *extra_args)
    assert result.returncode == expected, result.stderr


def test_cli_check_clean_draft_exits_0_with_fail_on_low(tmp_path):
    path = tmp_path / "draft.wikitext"
    path.write_text(
        "{{Infobox Leichtathlet|status=a|geburtsort=Berlin}}", encoding="utf-8"
    )
    result = _run_cli("--check", str(path), "--fail-on", "low")
    assert result.returncode == 0, result.stdout + result.stderr


def test_cli_check_error_exits_2_not_1(tmp_path):
    # A run that fails (here: no infobox in the draft) must be
    # distinguishable from one that merely found problems.
    path = tmp_path / "draft.wikitext"
    path.write_text("no infobox here", encoding="utf-8")
    result = _run_cli("--check", str(path), "--fail-on", "low")
    assert result.returncode == 2


def test_cli_rejects_unknown_fail_on_severity_with_exit_2(tmp_path):
    result = _run_cli("--check", "whatever", "--fail-on", "critical")
    assert result.returncode == 2
    assert "unknown severity 'critical'" in result.stderr
