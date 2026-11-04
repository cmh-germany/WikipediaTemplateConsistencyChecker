"""Generates a simple, self-contained HTML report from the findings
(no external dependencies such as CDN CSS/JS)."""

import html
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from string import Template

import suppress
from rules import RULE_TITLES, Finding, count_by_severity
from suppress import Suppression, SuppressionStore

SEVERITY_COLORS = {
    "very high": "#c0392b",
    "high": "#e67e22",
    "medium": "#d4ac0d",
    "low": "#7f8c8d",
}

SEVERITY_ORDER = {"very high": 0, "high": 1, "medium": 2, "low": 3}

ARTICLE_URL = "https://de.wikipedia.org/wiki/{}"
TEMPLATE_DOC_URL = "https://de.wikipedia.org/wiki/Vorlage:Infobox_Leichtathlet"

_TEMPLATES_DIR = Path(__file__).parent / "templates"


def _load_template(name: str) -> Template:
    """Reads a $-placeholder template from templates/ next to this file
    (string.Template rather than str.format, so the HTML/CSS/JS in those
    files can use literal `{`/`}` without doubling them up)."""
    return Template((_TEMPLATES_DIR / name).read_text(encoding="utf-8"))


_TEMPLATE = _load_template("report.html")
_ROW_TEMPLATE = _load_template("row.html")
_SCANNED_SECTION_TEMPLATE = _load_template("scanned_section.html")
_SUPPRESSED_SECTION_TEMPLATE = _load_template("suppressed_section.html")
_RULES_SECTION_TEMPLATE = _load_template("rules_section.html")
_RULE_ROW_TEMPLATE = _load_template("rule_row.html")


@dataclass
class SuppressionView:
    """Everything the report needs to show suppressed findings and to
    let the reader add/remove suppressions: the current store (embedded
    so the page can write back the complete file), each article's
    infobox values (to fingerprint findings, see suppress.fingerprint),
    and the findings that were suppressed in this run."""

    store: SuppressionStore = field(default_factory=SuppressionStore)
    path: Path = field(default_factory=suppress.default_path)
    include_suppressed: bool = False
    suppressed: list[tuple[str, Finding, Suppression]] = field(default_factory=list)
    params_by_title: dict[str, dict[str, str]] = field(default_factory=dict)

    def add_article(
        self,
        title: str,
        params: dict[str, str],
        findings: list[Finding],
        suppressed: list[tuple[Finding, Suppression]],
    ) -> None:
        """Records one checked article. Its params are kept only if it
        has findings, since only those need a fingerprint."""
        if findings or suppressed:
            self.params_by_title[title] = params
        self.suppressed.extend(
            (title, finding, suppression) for finding, suppression in suppressed
        )

    def index_of(self, suppression: Suppression) -> int:
        """Position of `suppression` in the store, which the page uses
        to remove or update exactly that entry."""
        return next(
            i for i, s in enumerate(self.store.suppressions) if s is suppression
        )


def _filter_checkbox_html(severity: str, color: str, count: int) -> str:
    """Renders one entry in the severity filter bar. A severity with no
    findings still shows its label (so all severity levels stay
    visible for context), but without a checkbox -- there's nothing
    for it to filter, and hiding the control avoids visual clutter for
    a severity that has no results anyway."""
    label = f'<span class="sev" style="background:{color}">{severity} ({count})</span>'
    if not count:
        return f'<span class="sev-empty">{label}</span>'
    return f'<label><input type="checkbox" value="{severity}" checked> {label}</label>'


def _finding_row_html(
    finding: Finding,
    title: str,
    view: SuppressionView,
    suppression: Suppression | None = None,
) -> str:
    """One finding as a table row, with its suppress checkbox: ticked
    (and tied to its store entry) if `suppression` covers it, otherwise
    carrying what's needed to create a new entry for it."""
    params_html = (
        ", ".join(f"<code>{html.escape(p)}</code>" for p in finding.params) or "&ndash;"
    )
    fingerprint = suppress.fingerprint(finding, view.params_by_title.get(title, {}))
    if suppression is None:
        key = f"new|{finding.rule_id}|{title}|{fingerprint}"
        index = ""
    else:
        index = str(view.index_of(suppression))
        key = f"entry|{index}"
    return _ROW_TEMPLATE.substitute(
        row_class="suppressed-row" if suppression else "",
        key=html.escape(key),
        suppression_index=index,
        fingerprint=fingerprint,
        checked=" checked" if suppression else "",
        reason=html.escape(suppression.reason) if suppression else "",
        severity=html.escape(finding.severity),
        severity_rank=SEVERITY_ORDER[finding.severity],
        color=SEVERITY_COLORS.get(finding.severity, "#999"),
        rule_id=html.escape(finding.rule_id),
        rule_title=html.escape(finding.title),
        rule_sort=html.escape(finding.title.lower()),
        url=ARTICLE_URL.format(html.escape(title.replace(" ", "_"))),
        title=html.escape(title),
        article_sort=html.escape(title.lower()),
        params_html=params_html,
        params_sort=html.escape(", ".join(finding.params).lower()),
        message=html.escape(finding.message),
        message_sort=html.escape(finding.message.lower()),
        note_html=html.escape(finding.note) if finding.note else "&ndash;",
        note_sort=html.escape((finding.note or "").lower()),
    )


def _rules_section_html(view: SuppressionView) -> str:
    """The "Suppress whole rules" form: one row per known rule, ticked
    if suppressions.json suppresses it in every article."""
    whole_rule = {s.rule_id: s for s in view.store.suppressions if s.is_whole_rule}
    rows = []
    for rule_id, rule_title in RULE_TITLES.items():
        suppression = whole_rule.get(rule_id)
        index = "" if suppression is None else str(view.index_of(suppression))
        rows.append(
            _RULE_ROW_TEMPLATE.substitute(
                key=html.escape(f"entry|{index}" if index else f"rule|{rule_id}"),
                suppression_index=index,
                rule_id=html.escape(rule_id),
                rule_title=html.escape(rule_title),
                checked=" checked" if suppression else "",
                reason=html.escape(suppression.reason) if suppression else "",
            )
        )
    return _RULES_SECTION_TEMPLATE.substitute(
        n_suppressed_rules=len(whole_rule),
        n_rules=len(RULE_TITLES),
        rows="\n".join(rows),
    )


def _suppressions_json(store: SuppressionStore) -> str:
    """The store as JSON that is safe inside a <script> element: the
    entries hold article titles and messages derived from wikitext, so
    a "</script>" in them must not end the element early."""
    return store.to_json().replace("<", "\\u003c")


def generate_html_report(
    results: dict[str, list[Finding]],
    output_path: str,
    n_scanned: int | None = None,
    filter_note: str | None = None,
    suppressions: SuppressionView | None = None,
) -> None:
    """results: dict {article_title: list[Finding]} -- must include
    articles with an empty finding list too (not just the ones with
    findings), so the "scanned articles" section can show everything
    that was actually checked. `filter_note` describes an active
    --fail-on/--disable-rule filter, shown in the header so readers
    know the report is partial. `suppressions` holds the suppressed
    findings (listed in their own section, or marked in the main table
    with --include-suppressed) and what the page needs to save changes
    to the suppressions file."""
    n_scanned = n_scanned if n_scanned is not None else len(results)
    view = suppressions or SuppressionView()

    all_rows: list[tuple[Finding, str, Suppression | None]] = [
        (finding, title, None)
        for title, findings in results.items()
        for finding in findings
    ]
    n_findings = len(all_rows)
    suppressed_rows = [
        (finding, title, suppression) for title, finding, suppression in view.suppressed
    ]
    if view.include_suppressed:
        all_rows.extend(suppressed_rows)

    # Default sort: severity, very high first.
    all_rows.sort(key=lambda row: SEVERITY_ORDER[row[0].severity])
    n_articles_with_findings = sum(1 for findings in results.values() if findings)

    rows = [_finding_row_html(f, title, view, s) for f, title, s in all_rows]

    suppressed_section = ""
    suppressed_note = ""
    if view.suppressed and view.include_suppressed:
        suppressed_note = f" (plus {len(view.suppressed)} suppressed, shown greyed out)"
    elif view.suppressed:
        suppressed_note = f" ({len(view.suppressed)} suppressed findings hidden)"
        suppressed_section = _SUPPRESSED_SECTION_TEMPLATE.substitute(
            n_suppressed=len(view.suppressed),
            rows="\n".join(
                _finding_row_html(f, title, view, s)
                for f, title, s in sorted(
                    suppressed_rows, key=lambda row: SEVERITY_ORDER[row[0].severity]
                )
            ),
        )

    scanned_items = "\n".join(
        f'<li><a href="{ARTICLE_URL.format(html.escape(t.replace(" ", "_")))}" '
        f'target="_blank" rel="noopener">{html.escape(t)}</a>'
        + (
            f' <span class="n-findings">({len(findings)} finding(s))</span>'
            if findings
            else ""
        )
        + "</li>"
        for t, findings in sorted(results.items())
    )
    scanned_section = _SCANNED_SECTION_TEMPLATE.substitute(
        n_scanned=len(results),
        items=scanned_items,
    )

    severity_counts = count_by_severity(
        [finding for finding, _, suppression in all_rows if suppression is None]
    )
    filter_checkboxes = "\n".join(
        _filter_checkbox_html(sev, color, severity_counts[sev])
        for sev, color in SEVERITY_COLORS.items()
    )

    html_out = _TEMPLATE.substitute(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_articles_with_findings=n_articles_with_findings,
        n_scanned=n_scanned,
        n_findings=n_findings,
        suppressed_note=suppressed_note,
        template_doc_url=TEMPLATE_DOC_URL,
        filter_note=(
            f'<div class="filter-note">{html.escape(filter_note)}</div>'
            if filter_note
            else ""
        ),
        filter_checkboxes=filter_checkboxes,
        rows="\n".join(rows) if rows else "<tr><td colspan=7>No findings.</td></tr>",
        suppressed_section=suppressed_section,
        rules_section=_rules_section_html(view),
        scanned_section=scanned_section,
        suppressions_path=html.escape(str(view.path)),
        suppressions_json=_suppressions_json(view.store),
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)
