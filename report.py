"""Generates a simple, self-contained HTML report from the findings
(no external dependencies such as CDN CSS/JS)."""

import html
from datetime import datetime
from pathlib import Path
from string import Template

from rules import Finding, count_by_severity

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


def generate_html_report(
    results: dict[str, list[Finding]],
    output_path: str,
    n_scanned: int | None = None,
) -> None:
    """results: dict {article_title: list[Finding]} -- must include
    articles with an empty finding list too (not just the ones with
    findings), so the "scanned articles" section can show everything
    that was actually checked."""
    n_scanned = n_scanned if n_scanned is not None else len(results)

    all_rows = []  # (Finding, title) pairs, across all articles
    for title, findings in results.items():
        for finding in findings:
            all_rows.append((finding, title))

    # Default sort: severity, very high first.
    all_rows.sort(key=lambda pair: SEVERITY_ORDER[pair[0].severity])

    n_findings = len(all_rows)
    n_articles_with_findings = sum(1 for findings in results.values() if findings)

    rows = []
    for finding, title in all_rows:
        params_html = (
            ", ".join(f"<code>{html.escape(p)}</code>" for p in finding.params)
            or "&ndash;"
        )
        rows.append(
            _ROW_TEMPLATE.substitute(
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
            )
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

    severity_counts = count_by_severity([finding for finding, _ in all_rows])
    filter_checkboxes = "\n".join(
        _filter_checkbox_html(sev, color, severity_counts[sev])
        for sev, color in SEVERITY_COLORS.items()
    )

    html_out = _TEMPLATE.substitute(
        generated_at=datetime.now().strftime("%Y-%m-%d %H:%M"),
        n_articles_with_findings=n_articles_with_findings,
        n_scanned=n_scanned,
        n_findings=n_findings,
        template_doc_url=TEMPLATE_DOC_URL,
        filter_checkboxes=filter_checkboxes,
        rows="\n".join(rows) if rows else "<tr><td colspan=5>No findings.</td></tr>",
        scanned_section=scanned_section,
    )

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_out)
