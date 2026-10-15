"""CLI for the Infobox template consistency checker.

Two modes:
  python main.py --scan [--limit N] [--output report.html] [--no-cache]
                  [--overwrite-cache]
      Scans all Wikipedia articles that embed the template and
      generates an HTML report.

  python main.py --check <article_title|URL|local_file>
      Checks a single article or a local wikitext file (e.g. a draft)
      and prints the findings directly to the console.

Both modes accept --fail-on SEVERITY and --disable-rule RULE_ID[,...].

--fail-on SEVERITY (default: low, i.e. everything) hides findings
below SEVERITY from the console and the report ("none" hides nothing
and never fails). Exit codes: 0 = no finding at or above --fail-on
SEVERITY, 1 = such findings present, 2 = the run failed or the
arguments were invalid.
"""

import argparse
import difflib
import os
import re
import sys
import webbrowser

import fetch
import parse
import report
import rules

__version__ = "0.3"

# Process exit codes. EXIT_ERROR deliberately matches argparse's own
# exit code for invalid arguments, so CI can treat "the tool couldn't do
# its job" (2) differently from "the tool found problems" (1).
EXIT_OK = 0
EXIT_FINDINGS = 1
EXIT_ERROR = 2

# Fail on any finding unless told otherwise (--fail-on none).
DEFAULT_FAIL_ON: str | None = rules.LOW


def _extract_title_from_input(user_input):
    if user_input.startswith(("http://", "https://")):
        # .../wiki/Article_Name -> Article Name
        title = user_input.rsplit("/wiki/", 1)[-1]
        return title.replace("_", " ")
    return user_input


def _positive_int(value):
    """argparse type for --limit. Plain int() would silently accept a
    negative value (none of this parser's option strings look like a
    negative number, so argparse doesn't reject e.g. "-5" as an
    unrecognized flag) -- the MediaWiki API would only reject it much
    later, as an invalid 'eilimit'. Zero is rejected too:
    fetch.list_pages_using_template treats a falsy limit as
    "unlimited", so --limit 0 would silently scan everything instead
    of nothing."""
    try:
        n = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid int value: '{value}'") from exc
    if n < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer, got {n}")
    return n


def _severity(value: str) -> str | None:
    """argparse type for --fail-on. The canonical severity names (see
    rules.SEVERITY_ORDER) include "very high" with a space, which is
    awkward to type unquoted in a shell -- so "very-high" (and any
    capitalization) is accepted too and normalized to the canonical
    name. "none" maps to None, the only way to switch off failing on
    findings now that --fail-on defaults to "low"."""
    severity = value.strip().lower().replace("-", " ").replace("_", " ")
    if severity == "none":
        return None
    if severity not in rules.SEVERITY_ORDER:
        valid = ", ".join(s.replace(" ", "-") for s in rules.SEVERITY_ORDER)
        raise argparse.ArgumentTypeError(
            f"unknown severity '{value}' -- choose one of: {valid}, none"
        )
    return severity


def _rule_ids(value: str) -> list[str]:
    """argparse type for --disable-rule. Accepts a comma-separated list
    so several rules fit in one flag, and -- like _severity -- accepts
    "-" in place of "_" so ids can be typed either way. Unknown ids are
    rejected up front (with a "did you mean" hint for typos) rather
    than silently ignored: a mistyped id would otherwise leave the rule
    running, which looks exactly like the flag being broken."""
    ids = [item.strip().lower().replace("-", "_") for item in value.split(",")]
    if not all(ids):
        raise argparse.ArgumentTypeError(
            f"empty rule ID in '{value}' -- separate rule IDs with single "
            "commas, e.g. missing_birthplace,update_outdated"
        )
    for rule_id in ids:
        if rule_id in rules.RULE_TITLES:
            continue
        message = f"unknown rule ID '{rule_id}'"
        if close := difflib.get_close_matches(rule_id, rules.RULE_TITLES, n=1):
            message += f" -- did you mean '{close[0]}'?"
        raise argparse.ArgumentTypeError(
            f"{message} (see the list of rule IDs in the README, or the "
            "rule ID shown next to each finding in --check output)"
        )
    return ids


def _check_output_path(path):
    """Best-effort pre-flight check for --output, so an obviously bad
    path fails immediately instead of after a multi-minute scan.
    Returns an error string, or None if the path looks writable. Not
    authoritative -- os.access doesn't reflect real ACL-based write
    permission on Windows, and the target could still change between
    this check and the actual write -- so the write itself (in
    run_scan) is still wrapped in a try/except as the final guard."""
    if os.path.isdir(path):
        return f"'{path}' is a directory, not a file path"
    directory = os.path.dirname(os.path.abspath(path)) or "."
    if not os.path.isdir(directory):
        return f"directory '{directory}' does not exist"
    if not os.access(directory, os.W_OK):
        return f"no write permission for directory '{directory}'"
    return None


def _cache_status_note(use_cache: bool) -> str:
    """Composes the "(from cache where possible)" hint shown while
    loading article content, centralized here so every caller
    advertises the cache status consistently -- in particular, so the
    hint never appears when --no-cache (use_cache=False) disabled the
    cache."""
    return " (from cache where possible)" if use_cache else ""


def _format_severity_summary(counts: dict[str, int]) -> str:
    """Formats a counts-by-severity dict (see rules.count_by_severity)
    as e.g. "Total findings: 12 (Very high: 2, High: 3, Medium: 5,
    Low: 2)", for both --check and --scan console output."""
    total = sum(counts.values())
    breakdown = ", ".join(
        f"{severity.capitalize()}: {count}" for severity, count in counts.items()
    )
    return f"Total findings: {total} ({breakdown})"


def _findings_exit_code(counts: dict[str, int], fail_on: str | None) -> int:
    """Returns EXIT_FINDINGS if --fail-on is set and at least one
    finding is at or above that severity, else EXIT_OK -- so CI jobs
    can gate on findings without parsing console output or the report.
    Prints the reason to stderr, since a non-zero exit would otherwise
    look like a crash to whoever reads the CI log."""
    if fail_on is None:
        return EXIT_OK
    threshold = rules.SEVERITY_ORDER[fail_on]
    n_failing = sum(
        count
        for severity, count in counts.items()
        if rules.SEVERITY_ORDER[severity] <= threshold
    )
    if n_failing == 0:
        return EXIT_OK
    print(
        f"Exiting with code {EXIT_FINDINGS}: {n_failing} finding(s) at or "
        f"above '{fail_on}' severity (--fail-on).",
        file=sys.stderr,
    )
    return EXIT_FINDINGS


_CONTROL_CHAR_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_console_text(text: str) -> str:
    """Escapes ASCII control characters -- including ANSI/terminal
    escape sequences (\\x1b), newlines, and carriage returns -- in text
    that ultimately originates from a Wikipedia article's wikitext
    (a finding's message) or from a user-supplied URL (the article
    title). Left unescaped, a crafted field value could move the
    cursor, hide/rewrite prior output, or change the terminal's title
    bar when printed verbatim; every finding is expected to render as
    a single plain-text console line anyway."""
    return _CONTROL_CHAR_RE.sub(lambda m: f"\\x{ord(m.group()):02x}", text)


def _print_findings(title, findings):
    print(f"\n=== {_sanitize_console_text(title)} ===")
    if not findings:
        print("  No findings.")
        return
    for f in findings:
        message = _sanitize_console_text(f.message)
        line = f"  [{f.severity.upper():9s}] {f.rule_id}: {message}"
        if f.note:
            line += f" (Note: {_sanitize_console_text(f.note)})"
        print(line)
    print(f"  {_format_severity_summary(rules.count_by_severity(findings))}")


def run_check(
    target, session=None, finding_filter: rules.FindingFilter | None = None
) -> int:
    """Checks a single article (title/URL) or local wikitext file and
    prints the findings `finding_filter` keeps (default: all) to the
    console. Returns a process exit code: EXIT_ERROR if the
    target/template couldn't be resolved, else EXIT_FINDINGS if the
    filter's `fail_on` is set and a kept finding reaches that severity,
    else EXIT_OK."""
    session = session or fetch.get_session()
    finding_filter = finding_filter or rules.FindingFilter()

    print(f"Checking '{_sanitize_console_text(target)}' ...")

    if os.path.isfile(target):
        try:
            with open(target, encoding="utf-8") as fh:
                wikitext = fh.read()
        except UnicodeDecodeError:
            print(
                f"Could not read '{target}': not valid UTF-8 text -- "
                "save the draft as plain UTF-8 text, not .docx or "
                "another encoding (see README)."
            )
            return EXIT_ERROR
        except OSError as e:
            print(f"Could not read '{target}': {e.strerror or e}.")
            return EXIT_ERROR
        title = os.path.basename(target)
        categories = []
    else:
        title = _extract_title_from_input(target)
        data = fetch.fetch_pages_content_and_categories(session, [title])
        if title not in data:
            print(
                f"Article '{title}' not found or has no retrievable wikitext revision."
            )
            return EXIT_ERROR
        wikitext = data[title]["wikitext"]
        categories = data[title]["categories"]

    params = parse.parse_infobox_params(wikitext)
    if params is None:
        print(f"No Infobox Leichtathlet embedding found in '{target}'.")
        return EXIT_ERROR

    # The existence lookups are the only costly part of a rule, so skip
    # them when the only rule needing them is disabled anyway.
    nation_codes = []
    if not finding_filter.is_disabled("nation_code_unknown"):
        nation_codes = rules.nation_codes_to_check(params.get("nation", ""))
    nation_exists = None
    if nation_codes:
        nation_exists = fetch.templates_exist(
            session, [f"Vorlage:{code}" for code in nation_codes]
        )

    discipline = None
    if not finding_filter.is_disabled("discipline_link_unknown"):
        discipline = rules.discipline_candidate(params.get("disziplin", ""))
    discipline_exists = None
    if discipline:
        discipline_exists = fetch.templates_exist(session, [discipline])

    findings = finding_filter.apply(
        rules.run_all_checks(
            params,
            categories=categories,
            nation_exists=nation_exists,
            discipline_exists=discipline_exists,
        )
    )
    _print_findings(title, findings)
    return _findings_exit_code(
        rules.count_by_severity(findings), finding_filter.fail_on
    )


def _warn_if_cache_stale(use_cache: bool, overwrite_cache: bool) -> None:
    """Prints a stderr warning suggesting --overwrite-cache once the
    oldest entry still in the cache is fetch.CACHE_STALE_AGE_DAYS or
    more days old (see fetch.cache_age_days() for why this is based on
    per-entry fetch timestamps rather than cache.json's own file age).
    A cache.json left over from a version of this tool older than that
    per-entry tracking has entries with no timestamp at all -- their age
    is unknown rather than 0, so that's flagged with its own message
    instead of being silently treated as fresh forever (see
    fetch.cache_has_untracked_entries()). Skipped entirely when the
    cache isn't actually being read (--no-cache) or is about to be
    refreshed anyway (--overwrite-cache), since neither case leaves
    stale data in play."""
    if not use_cache or overwrite_cache:
        return
    if fetch.cache_has_untracked_entries():
        print(
            "Warning: cache.json has entries from an older version of "
            "this tool that don't record when they were fetched, so "
            "their age can't be checked and they may be outdated. "
            "Re-run with --overwrite-cache to refresh them.",
            file=sys.stderr,
        )
        return
    age_days = fetch.cache_age_days()
    if age_days is None or age_days < fetch.CACHE_STALE_AGE_DAYS:
        return
    print(
        f"Warning: cache.json's oldest cached article data is "
        f"{age_days:.0f} days old (>= {fetch.CACHE_STALE_AGE_DAYS} days) "
        "and may be outdated. Re-run with --overwrite-cache to force a "
        "fresh fetch from Wikipedia.",
        file=sys.stderr,
    )


def run_scan(
    limit=None,
    output="report.html",
    use_cache=True,
    open_output=False,
    overwrite_cache=False,
    finding_filter: rules.FindingFilter | None = None,
) -> int:
    """Fetches all articles embedding the template, runs the rule checks
    across the whole corpus, and writes the HTML report with the
    findings `finding_filter` keeps (default: all). Returns a process
    exit code: EXIT_ERROR if the report couldn't be written, else
    EXIT_FINDINGS if the filter's `fail_on` is set and a kept finding
    reaches that severity, else EXIT_OK. Findings are checked only
    after the report is written and opened, so a failing CI run still
    leaves the report behind."""
    session = fetch.get_session()
    finding_filter = finding_filter or rules.FindingFilter()

    _warn_if_cache_stale(use_cache, overwrite_cache)

    print("Fetching articles that embed the template ...")
    titles = fetch.list_pages_using_template(session, limit=limit)
    print(f"{len(titles)} articles found.")

    print(f"Loading wikitext and categories{_cache_status_note(use_cache)} ...")
    pages = fetch.fetch_all_with_cache(
        session, titles, use_cache=use_cache, overwrite_cache=overwrite_cache
    )

    print("Extracting infobox parameters ...")
    parsed = {}
    all_nation_codes = set()
    all_disciplines = set()
    for title, data in pages.items():
        params = parse.parse_infobox_params(data["wikitext"])
        if params is None:
            continue
        parsed[title] = (params, data["categories"])
        all_nation_codes.update(rules.nation_codes_to_check(params.get("nation", "")))
        discipline = rules.discipline_candidate(params.get("disziplin", ""))
        if discipline:
            all_disciplines.add(discipline)

    # Skip the existence lookups (the only costly part of a rule) when
    # the only rule needing them is disabled anyway.
    nation_exists = None
    if not finding_filter.is_disabled("nation_code_unknown"):
        print(f"Checking {len(all_nation_codes)} distinct nation codes ...")
        nation_exists = fetch.templates_exist(
            session, [f"Vorlage:{code}" for code in all_nation_codes]
        )

    discipline_exists = None
    if not finding_filter.is_disabled("discipline_link_unknown"):
        print(f"Checking {len(all_disciplines)} distinct bare discipline links ...")
        discipline_exists = fetch.templates_exist(session, list(all_disciplines))

    print("Running rule checks ...")
    results = {}
    for title, (params, categories) in parsed.items():
        results[title] = finding_filter.apply(
            rules.run_all_checks(
                params,
                categories=categories,
                nation_exists=nation_exists,
                discipline_exists=discipline_exists,
            )
        )

    output_path = os.path.abspath(output)
    print(f"Writing report to '{output_path}' ...")
    try:
        report.generate_html_report(results, output, n_scanned=len(parsed))
    except OSError as e:
        print(f"\nCould not write report to '{output}': {e.strerror or e}.")
        return EXIT_ERROR

    n_with_findings = sum(1 for f in results.values() if f)
    all_findings = [finding for findings in results.values() for finding in findings]
    counts = rules.count_by_severity(all_findings)
    severity_summary = _format_severity_summary(counts)
    print(
        f"\nDone. {n_with_findings} of {len(parsed)} articles have "
        f"findings. {severity_summary} Report: {output_path}\n"
    )

    if open_output:
        print(f"Opening report in your default browser: {output_path} ...")
        webbrowser.open(f"file://{output_path}")
        print("Opened report.")

    return _findings_exit_code(counts, finding_filter.fail_on)


def main():
    """Parses CLI arguments and dispatches to run_check or run_scan.
    Returns a process exit code."""
    parser = argparse.ArgumentParser(
        description="Consistency checker for Wikipedia Vorlage:Infobox templates",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"WikipediaTemplateConsistencyChecker {__version__}",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--scan",
        action="store_true",
        help="Check all articles that embed the template via the Wikipedia API",
    )
    group.add_argument(
        "--check",
        metavar="TARGET",
        help="Check a single article (title or URL) or a local wikitext file",
    )
    parser.add_argument(
        "--limit",
        type=_positive_int,
        default=None,
        help="Only scan the first N articles (for testing)",
    )
    parser.add_argument(
        "--output",
        default="report.html",
        help="Path for the HTML report when using --scan (default: report.html)",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Ignore the local cache (cache.json) and reload everything",
    )
    parser.add_argument(
        "--overwrite-cache",
        action="store_true",
        help="Force a fresh fetch from Wikipedia for every scanned article, "
        "overwriting their entries in the local cache (cache.json) even if "
        "already present. Use this to refresh outdated cached data -- the "
        "tool suggests it automatically once the cache is 30+ days old",
    )
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open the generated HTML report in the default browser "
        "after the scan finishes (--scan only)",
    )
    parser.add_argument(
        "--fail-on",
        type=_severity,
        metavar="SEVERITY",
        default=DEFAULT_FAIL_ON,
        help="Only show findings with this severity or higher (in the "
        "console and the report), and exit with code 1 if any are left "
        "(one of: low, medium, high, very-high, none). Default: low, i.e. "
        "show every finding and exit with code 1 on any finding. Use "
        "'none' to show every finding but always exit with code 0 when "
        "the run completes. Errors (e.g. article not found) always exit "
        "with code 2",
    )
    parser.add_argument(
        "--disable-rule",
        type=_rule_ids,
        action="append",
        default=[],
        metavar="RULE_ID[,RULE_ID...]",
        help="Don't report findings of these rules (comma-separated, and "
        "the flag can be repeated), e.g. --disable-rule "
        "missing_birthplace,update_outdated. The rule ID is shown next to "
        "each finding in --check output and in the report's Rule column; "
        "the README lists all of them. Disabled findings never cause "
        "exit code 1",
    )
    args = parser.parse_args()
    finding_filter = rules.FindingFilter(
        disabled_rules=frozenset(
            rule_id for ids in args.disable_rule for rule_id in ids
        ),
        fail_on=args.fail_on,
    )

    # args.check is "" (falsy, but not None) when the user passes
    # --check with an empty/whitespace-only value -- reject it
    # explicitly, since the truthiness check below would otherwise
    # silently misinterpret it as "--scan was chosen" instead.
    if args.check is not None and not args.check.strip():
        parser.error("--check TARGET must not be empty")

    if args.check:
        return run_check(args.check, finding_filter=finding_filter)

    output_error = _check_output_path(args.output)
    if output_error:
        parser.error(f"--output: {output_error}")

    return run_scan(
        limit=args.limit,
        output=args.output,
        use_cache=not args.no_cache,
        open_output=args.open,
        overwrite_cache=args.overwrite_cache,
        finding_filter=finding_filter,
    )


if __name__ == "__main__":
    sys.exit(main())
