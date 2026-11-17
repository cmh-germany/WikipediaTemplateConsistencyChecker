"""Machine-readable JSON output of a --check or --scan run, for CI jobs,
GitHub Actions and scripts that would otherwise have to scrape the
console output or the HTML report.

The document's layout is versioned by FORMAT_VERSION: adding a field
keeps the version, while renaming or removing one (or changing what it
means) bumps it, so consumers can rely on the fields they know.
"""

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

import report
import rules
import suppress
from rules import Finding

FORMAT_VERSION = 1
GENERATOR_NAME = "WikipediaInfoboxConsistencyChecker"
TEMPLATE_NAME = "Vorlage:Infobox Leichtathlet"


@dataclass
class RunInfo:
    """What was run and how, recorded in the document's "run" section
    so a consumer can tell e.g. a filtered run from a complete one."""

    mode: str  # "scan" or "check"
    tool_version: str
    target: str | None = None
    source: str = "wikipedia"  # or "local_file" (--check on a draft)
    limit: int | None = None
    finding_filter: rules.FindingFilter = field(default_factory=rules.FindingFilter)
    suppressed_rules: frozenset[str] = frozenset()
    generated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


def _article_url(title: str, run: RunInfo) -> str | None:
    """A local draft file has no Wikipedia article to link to."""
    if run.source == "local_file":
        return None
    return report.ARTICLE_URL.format(title.replace(" ", "_"))


def _suppression_scope(suppression: suppress.Suppression) -> str:
    if suppression.is_whole_rule:
        return "rule"
    return "finding" if suppression.fingerprint else "article"


def _finding_id(title: str, finding: Finding, fingerprint: str) -> str:
    """Unique within one document. The fingerprint alone isn't enough:
    it only covers the rule and the field values, so a rule firing
    twice on the same fields (e.g. medal_count_mismatch for two
    competitions) shares one fingerprint but differs in its message."""
    payload = json.dumps(
        [title, finding.rule_id, fingerprint, finding.message], ensure_ascii=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _finding_entry(
    title: str,
    finding: Finding,
    view: report.SuppressionView,
    run: RunInfo,
    suppression: suppress.Suppression | None = None,
) -> dict[str, Any]:
    fingerprint = suppress.fingerprint(finding, view.params_by_title.get(title, {}))
    return {
        "id": _finding_id(title, finding, fingerprint),
        "rule_id": finding.rule_id,
        "rule_title": finding.title,
        "severity": finding.severity,
        "message": finding.message,
        "note": finding.note or None,
        "article": title,
        "article_url": _article_url(title, run),
        "params": list(finding.params),
        "fingerprint": fingerprint,
        "suppression": (
            None
            if suppression is None
            else {
                "reason": suppression.reason,
                "scope": _suppression_scope(suppression),
            }
        ),
    }


def _sort_key(entry: dict[str, Any]) -> tuple[int, str, str]:
    return (
        rules.SEVERITY_ORDER[entry["severity"]],
        entry["article"],
        entry["rule_id"],
    )


def build_document(
    results: dict[str, list[Finding]],
    view: report.SuppressionView,
    run: RunInfo,
) -> dict[str, Any]:
    """The JSON document for a run. `results` and `view` are the same
    data the HTML report is generated from (see report.py): every
    checked article with its unsuppressed findings, plus the suppressed
    findings and the infobox values needed to fingerprint them.
    Suppressed findings are always listed (separately), but -- like
    everywhere else -- never counted in the summary."""
    findings = sorted(
        (
            _finding_entry(title, finding, view, run)
            for title, title_findings in results.items()
            for finding in title_findings
        ),
        key=_sort_key,
    )
    suppressed = sorted(
        (
            _finding_entry(title, finding, view, run, suppression)
            for title, finding, suppression in view.suppressed
        ),
        key=_sort_key,
    )
    all_findings = [finding for fs in results.values() for finding in fs]
    finding_filter = run.finding_filter
    return {
        "format_version": FORMAT_VERSION,
        "generator": {"name": GENERATOR_NAME, "version": run.tool_version},
        "generated_at": run.generated_at.isoformat(timespec="seconds"),
        "template": {"name": TEMPLATE_NAME, "url": report.TEMPLATE_DOC_URL},
        "run": {
            "mode": run.mode,
            "target": run.target,
            "source": run.source,
            "limit": run.limit,
            "fail_on": finding_filter.fail_on,
            "disabled_rules": sorted(finding_filter.disabled_rules),
            "suppressed_rules": sorted(run.suppressed_rules),
            "include_suppressed": finding_filter.include_suppressed,
        },
        "summary": {
            "articles_checked": len(results),
            "articles_with_findings": sum(1 for fs in results.values() if fs),
            "findings": len(all_findings),
            "by_severity": rules.count_by_severity(all_findings),
            "suppressed_findings": len(suppressed),
        },
        "articles": [
            {
                "title": title,
                "url": _article_url(title, run),
                "findings": len(title_findings),
            }
            for title, title_findings in sorted(results.items())
        ],
        "findings": findings,
        "suppressed_findings": suppressed,
    }


@dataclass
class JsonOutput:
    """Where to write the document: a file (`path`) or an already open
    text stream such as stdout (`stream`)."""

    path: Path | None = None
    stream: TextIO | None = None

    @property
    def description(self) -> str:
        """Human-readable destination for console messages: the quoted
        absolute file path, or "standard output"."""
        if self.path is None:
            return "standard output"
        return f"'{self.path.resolve()}'"

    def write(self, document: dict[str, Any]) -> None:
        """Writes `document` as indented JSON. To a stream, non-ASCII
        characters are escaped, since a Windows console may not be able
        to encode e.g. article titles with diacritics; files are UTF-8
        as-is. Raises OSError if a file can't be written."""
        if self.path is None:
            if self.stream is None:
                raise ValueError("JsonOutput needs a path or a stream")
            self.stream.write(json.dumps(document, indent=2) + "\n")
            self.stream.flush()
            return
        _write_atomically(
            self.path, json.dumps(document, ensure_ascii=False, indent=2) + "\n"
        )


def _write_atomically(path: Path, text: str) -> None:
    """Writes to a temporary file in the same directory and moves it
    into place with os.replace() (atomic on POSIX and Windows), so a
    script polling for the file never reads a half-written document and
    a failed write leaves an older file intact -- the same approach as
    fetch.save_cache."""
    fd, tmp_path = tempfile.mkstemp(
        dir=path.parent, prefix=f"{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        os.replace(tmp_path, path)
    except BaseException:
        os.remove(tmp_path)
        raise
