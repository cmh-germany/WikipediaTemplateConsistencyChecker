"""Generates a simple, self-contained HTML report from the findings
(no external dependencies such as CDN CSS/JS)."""

import html
from datetime import datetime

SEVERITY_COLORS = {
    "very high": "#c0392b",
    "high": "#e67e22",
    "medium": "#d4ac0d",
    "low": "#7f8c8d",
}

SEVERITY_ORDER = {"very high": 0, "high": 1, "medium": 2, "low": 3}

ARTICLE_URL = "https://de.wikipedia.org/wiki/{}"
TEMPLATE_DOC_URL = "https://de.wikipedia.org/wiki/Vorlage:Infobox_Leichtathlet"

_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Infobox Leichtathlet -- Consistency Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 2em; color: #222; }}
  h1 {{ margin-bottom: 0.2em; }}
  .meta {{ color: #555; margin-bottom: 1.5em; }}
  .filters {{ margin-bottom: 1em; }}
  .filters label {{ margin-right: 1.2em; cursor: pointer; user-select: none; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ text-align: left; padding: 0.5em 0.7em; border-bottom: 1px solid #ddd; vertical-align: top; }}
  th {{ background: #f5f5f5; position: sticky; top: 0; cursor: pointer; user-select: none; white-space: nowrap; }}
  th::after {{ content: ""; display: inline-block; width: 1em; }}
  th.sort-asc::after {{ content: "\\25B2"; }}
  th.sort-desc::after {{ content: "\\25BC"; }}
  tr:hover {{ background: #fafafa; }}
  .sev {{ display: inline-block; padding: 0.15em 0.6em; border-radius: 0.8em; color: white; font-size: 0.85em; white-space: nowrap; }}
  .rule-id {{ color: #999; font-size: 0.8em; }}
  code {{ background: #f0f0f0; padding: 0.1em 0.35em; border-radius: 0.3em; font-size: 0.9em; }}
  a {{ color: #2c5aa0; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .scanned-section {{ margin-top: 2em; }}
  .scanned-section summary {{ cursor: pointer; font-weight: bold; }}
  .scanned-list {{ columns: 3; column-gap: 2em; margin-top: 1em; }}
  .scanned-list li {{ break-inside: avoid; }}
  .n-findings {{ color: #999; }}
</style>
</head>
<body>
<h1>Infobox Leichtathlet -- Consistency Report</h1>
<div class="meta">
  Generated on {generated_at} &middot;
  {n_articles_with_findings} of {n_scanned} checked articles have findings &middot;
  {n_findings} findings in total &middot;
  Rules based on <a href="{template_doc_url}" target="_blank" rel="noopener">Vorlage:Infobox Leichtathlet</a>
</div>
<div class="filters">
  {filter_checkboxes}
</div>
<table id="report-table">
<thead>
<tr>
  <th class="sort-asc">Severity</th>
  <th>Rule</th>
  <th>Article</th>
  <th>Parameters</th>
  <th>Message</th>
</tr>
</thead>
<tbody>
{rows}
</tbody>
</table>
{scanned_section}
<script>
(function() {{
  var table = document.getElementById('report-table');
  var tbody = table.tBodies[0];
  var headers = Array.from(table.querySelectorAll('thead th'));
  var state = {{ col: 0, dir: 1 }};

  function sortBy(colIndex, dir) {{
    var rows = Array.from(tbody.rows);
    rows.sort(function(a, b) {{
      var av = a.cells[colIndex].dataset.sort || '';
      var bv = b.cells[colIndex].dataset.sort || '';
      var an = parseFloat(av), bn = parseFloat(bv);
      var isNumeric = /^-?\\d+(\\.\\d+)?$/.test(av) && /^-?\\d+(\\.\\d+)?$/.test(bv);
      var cmp = isNumeric ? (an - bn) : av.localeCompare(bv);
      return cmp * dir;
    }});
    rows.forEach(function(r) {{ tbody.appendChild(r); }});
  }}

  headers.forEach(function(th, idx) {{
    th.addEventListener('click', function() {{
      var dir = (state.col === idx) ? -state.dir : 1;
      state = {{ col: idx, dir: dir }};
      sortBy(idx, dir);
      headers.forEach(function(h) {{ h.classList.remove('sort-asc', 'sort-desc'); }});
      th.classList.add(dir === 1 ? 'sort-asc' : 'sort-desc');
    }});
  }});
}})();

document.querySelectorAll('.filters input[type=checkbox]').forEach(function(cb) {{
  cb.addEventListener('change', function() {{
    var active = Array.from(document.querySelectorAll('.filters input:checked')).map(function(c) {{ return c.value; }});
    document.querySelectorAll('#report-table tbody tr').forEach(function(row) {{
      row.style.display = active.includes(row.dataset.severity) ? '' : 'none';
    }});
  }});
}});
</script>
</body>
</html>
"""

_ROW_TEMPLATE = """<tr data-severity="{severity}">
  <td data-sort="{severity_rank}"><span class="sev" style="background:{color}">{severity}</span></td>
  <td data-sort="{rule_sort}">{rule_title} <span class="rule-id">({rule_id})</span></td>
  <td data-sort="{article_sort}"><a href="{url}" target="_blank" rel="noopener">{title}</a></td>
  <td data-sort="{params_sort}">{params_html}</td>
  <td data-sort="{message_sort}">{message}</td>
</tr>
"""


_SCANNED_SECTION_TEMPLATE = """<details class="scanned-section">
<summary>{n_scanned} scanned article(s)</summary>
<ul class="scanned-list">
{items}
</ul>
</details>
"""


def generate_html_report(results, output_path, n_scanned=None):
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
        params_html = ", ".join(
            f"<code>{html.escape(p)}</code>" for p in finding.params
        ) or "&ndash;"
        rows.append(_ROW_TEMPLATE.format(
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
        ))

    scanned_items = "\n".join(
        f'<li><a href="{ARTICLE_URL.format(html.escape(t.replace(" ", "_")))}" '
        f'target="_blank" rel="noopener">{html.escape(t)}</a>'
        + (f' <span class="n-findings">({len(findings)} finding(s))</span>' if findings else "")
        + "</li>"
        for t, findings in sorted(results.items())
    )
    scanned_section = _SCANNED_SECTION_TEMPLATE.format(
        n_scanned=len(results), items=scanned_items,
    )

    filter_checkboxes = "\n".join(
        f'<label><input type="checkbox" value="{sev}" checked> '
        f'<span class="sev" style="background:{color}">{sev}</span></label>'
        for sev, color in SEVERITY_COLORS.items()
    )

    html_out = _TEMPLATE.format(
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
