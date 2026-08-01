"""Tests for main.py's command-line interface: argument parsing/
dispatch (--scan vs. --check, --limit, --output, --no-cache, --open)
and the --check target-resolution logic (article title, article URL,
local wikitext file). run_scan's internals (the actual scan loop) are
out of scope here -- these tests are about the CLI surface, not the
scan business logic.

run_check/run_scan themselves make real network calls via fetch.py, so
every test here either fully mocks fetch/report, or (for --scan)
replaces run_scan itself, to keep the suite network-free."""

import os
import sys

import pytest

import main

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


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
    assert main._extract_title_from_input(url) == "Leichtathletik-Weltmeisterschaften 2019"


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
    calls = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls["limit"] == 10


def test_check_rejects_empty_target(monkeypatch):
    # args.check == "" is falsy but not None -- without an explicit
    # check, `if args.check:` in main() would misread this as "--scan
    # was chosen" and silently run a full scan instead of erroring.
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", ""])
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.append(kw) or 0)
    with pytest.raises(SystemExit):
        main.main()
    assert calls == []


def test_check_rejects_whitespace_only_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "   "])
    with pytest.raises(SystemExit):
        main.main()


def test_scan_invokes_run_scan_with_defaults(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan"])
    calls = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls == {
        "limit": None, "output": "report.html",
        "use_cache": True, "open_output": False,
    }


def test_scan_passes_through_limit_output_no_cache_and_open(monkeypatch):
    monkeypatch.setattr(sys, "argv", [
        "main.py", "--scan", "--limit", "50", "--output", "athletes.html",
        "--no-cache", "--open",
    ])
    calls = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)
    main.main()
    assert calls == {
        "limit": 50, "output": "athletes.html",
        "use_cache": False, "open_output": True,
    }


def test_check_invokes_run_check_with_target(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", "Usain Bolt"])
    calls = {}
    monkeypatch.setattr(main, "run_check", lambda target: calls.update(target=target) or 0)
    main.main()
    assert calls["target"] == "Usain Bolt"


def test_check_passes_target_through_unmodified_url(monkeypatch):
    # main() itself doesn't resolve titles/URLs -- that happens inside
    # run_check -- so the raw --check value must reach run_check as-is.
    url = "https://de.wikipedia.org/wiki/Usain_Bolt"
    monkeypatch.setattr(sys, "argv", ["main.py", "--check", url])
    calls = {}
    monkeypatch.setattr(main, "run_check", lambda target: calls.update(target=target) or 0)
    main.main()
    assert calls["target"] == url


# ---------------------------------------------------------------------
# run_check: local file / article title / URL / not-found / no-infobox
# ---------------------------------------------------------------------

def test_run_check_local_wikitext_file(monkeypatch, capsys):
    # Real fixture, but nation='{{JAM}}' would otherwise trigger a real
    # network call to check "Vorlage:JAM" -- mock it out.
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {t: True for t in titles})
    path = os.path.join(FIXTURES_DIR, "usain_bolt.wikitext")

    result = main.run_check(path)

    assert result == 0
    out = capsys.readouterr().out
    assert "usain_bolt.wikitext" in out
    assert "No findings." in out


def test_run_check_resolves_article_url_to_title_before_fetching(monkeypatch):
    seen = {}

    def fake_fetch(session, titles):
        seen["titles"] = titles
        return {}

    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(main.fetch, "fetch_pages_content_and_categories", fake_fetch)

    main.run_check("https://de.wikipedia.org/wiki/Usain_Bolt")

    assert seen["titles"] == ["Usain Bolt"]


def test_run_check_article_not_found_returns_1_and_prints_message(monkeypatch, capsys):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch, "fetch_pages_content_and_categories", lambda session, titles: {},
    )

    result = main.run_check("Nonexistent Article XYZ")

    assert result == 1
    assert "not found" in capsys.readouterr().out


def test_run_check_no_infobox_found_returns_1_and_prints_message(monkeypatch, capsys):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(
        main.fetch, "fetch_pages_content_and_categories",
        lambda session, titles: {titles[0]: {"wikitext": "no infobox here", "categories": []}},
    )

    result = main.run_check("Some Random Article")

    assert result == 1
    assert "No Infobox Leichtathlet embedding found" in capsys.readouterr().out


def test_run_check_local_file_invalid_encoding_returns_1(tmp_path, capsys):
    # A draft accidentally saved as UTF-16 (e.g. from a word processor
    # default) instead of plain UTF-8 -- realistic given the README
    # explicitly warns against saving as .docx/rich text.
    path = tmp_path / "draft.wikitext"
    path.write_bytes("{{Infobox Leichtathlet|status=a}}".encode("utf-16"))

    result = main.run_check(str(path))

    assert result == 1
    assert "not valid UTF-8" in capsys.readouterr().out


def test_run_check_local_file_unreadable_returns_1(monkeypatch, capsys, tmp_path):
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

    assert result == 1
    assert "Could not read" in capsys.readouterr().out


# ---------------------------------------------------------------------
# --output validation and report-write failure handling
# ---------------------------------------------------------------------

def test_scan_rejects_output_path_in_nonexistent_directory(monkeypatch, tmp_path):
    bad_output = tmp_path / "no_such_subdir" / "report.html"
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(bad_output)])
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.append(kw) or 0)

    with pytest.raises(SystemExit):
        main.main()
    # Must fail before doing any (slow, network-bound) scan work.
    assert calls == []


def test_scan_rejects_output_path_that_is_a_directory(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(tmp_path)])
    calls = []
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.append(kw) or 0)

    with pytest.raises(SystemExit):
        main.main()
    assert calls == []


def test_scan_accepts_output_path_in_existing_writable_directory(monkeypatch, tmp_path):
    output = tmp_path / "report.html"
    monkeypatch.setattr(sys, "argv", ["main.py", "--scan", "--output", str(output)])
    calls = {}
    monkeypatch.setattr(main, "run_scan", lambda **kw: calls.update(kw) or 0)

    main.main()

    assert calls["output"] == str(output)


def test_run_scan_report_write_failure_returns_1_instead_of_crashing(monkeypatch, capsys):
    monkeypatch.setattr(main.fetch, "get_session", lambda: object())
    monkeypatch.setattr(main.fetch, "list_pages_using_template", lambda session, limit=None: [])
    monkeypatch.setattr(
        main.fetch, "fetch_all_with_cache",
        lambda session, titles, use_cache=True: {},
    )
    monkeypatch.setattr(main.fetch, "templates_exist", lambda session, titles: {})

    def raise_permission_error(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(main.report, "generate_html_report", raise_permission_error)

    result = main.run_scan(output="Z:/no_access/report.html")

    assert result == 1
    assert "Could not write report" in capsys.readouterr().out
