"""Extracts the parameters of an Infobox Leichtathlet embedding from
wikitext, and provides a small helper to parse (possibly incomplete)
date values."""

import re
from collections import namedtuple
from datetime import date

import mwparserfromhell

# Real (German) template name, lowercased -- do not translate.
TEMPLATE_NAMES = {"infobox leichtathlet"}

# German month names, as they appear in the infobox's date fields.
MONTHS = {
    "januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}

# Year is required, month/day may be unknown (None).
DateParts = namedtuple("DateParts", ["year", "month", "day"])


_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _normalize_template_name(name):
    text = _COMMENT_RE.sub("", str(name))
    return text.strip().replace("_", " ").lower()


def find_infobox(wikitext):
    """Returns the first mwparserfromhell template object for Infobox
    Leichtathlet in wikitext, or None."""
    code = mwparserfromhell.parse(wikitext)
    for template in code.filter_templates():
        if _normalize_template_name(template.name) in TEMPLATE_NAMES:
            return template
    return None


def extract_params(template):
    """Converts a template object into a dict {param_name: value_string}.
    Values are returned as raw text (including any wiki links/templates
    they contain), with HTML comments and surrounding whitespace
    stripped. Comments are common right after an empty field (e.g.
    "| karriereende = <!-- Medaillen -->" as a section divider) and
    must not be mistaken for an actual value."""
    params = {}
    for param in template.params:
        name = str(param.name).strip()
        value = _COMMENT_RE.sub("", str(param.value)).strip()
        if value:
            params[name] = value
    return params


def parse_infobox_params(wikitext):
    """Combines find_infobox + extract_params. Returns None if the
    template wasn't found."""
    template = find_infobox(wikitext)
    if template is None:
        return None
    return extract_params(template)


def extract_template_names(value):
    """Returns the names of all top-level {{...}} template calls found
    in a raw field value, e.g. "{{GDR}}<br />{{GER}}" -> ["GDR", "GER"].
    Real-world 'nation' values are almost always a flag template call
    like this rather than a bare ISO-3166 code, despite what the
    template documentation's copy-paste example suggests."""
    if not value:
        return []
    code = mwparserfromhell.parse(value)
    return [str(t.name).strip() for t in code.filter_templates()]


def _iter_medal_entries(value):
    """Yields (color_param, year_place_param, discipline_param) triples
    for every entry across all {{Medaillen Sommersport|...}} calls in a
    'medaillen' field value, per the template's documented copy-paste
    pattern (positional args repeat in groups of 3, after a named
    "Wo=" argument that is excluded here since it isn't positional)."""
    if not value:
        return
    code = mwparserfromhell.parse(value)
    for tmpl in code.filter_templates(recursive=True):
        if _normalize_template_name(tmpl.name) != "medaillen sommersport":
            continue
        positional = sorted(
            (p for p in tmpl.params if str(p.name).strip().isdigit()),
            key=lambda p: int(str(p.name).strip()),
        )
        for i in range(0, len(positional) - 2, 3):
            yield positional[i], positional[i + 1], positional[i + 2]


def extract_medal_years(value):
    """Extracts years specifically from the "Jahr Ort" argument of each
    medal entry. Ignores the discipline/event text and link targets
    entirely, which can otherwise contain unrelated numbers that merely
    look like years (e.g. a typo such as "1950 m Staffel", or a link
    target like "...von 1951 bis 1990...")."""
    years = []
    for _color, year_place, _discipline in _iter_medal_entries(value):
        text = visible_text(str(year_place.value))
        years.extend(int(y) for y in re.findall(r"(1[89]\d{2}|20\d{2})", text))
    return years


_LEICHTATHLETIK_PREFIX_RE = re.compile(r"(?i)leichtathletik[-\s]*")
_WM_EM_RE = re.compile(r"\b(wm|em)\b")
_WM_EM_EXPANSION = {"wm": "weltmeisterschaften", "em": "europameisterschaften"}

# Real-world synonyms that generic normalization (below) can't derive:
# either a genuine rename of the same competition series over time, or
# an abbreviation with a separator (a dot, or none at all) that the
# generic "Leichtathletik-"-stripping / WM|EM-expansion doesn't reach.
_MANUAL_COMPETITION_ALIASES = {
    "olympia": "olympischespiele",
    "olympischesommerspiele": "olympischespiele",
    "olympzwischenspiele": "olympischezwischenspiele",
    "panamerikspiele": "panamerikanischespiele",
    "sommeruniversiade": "universiade",
    # World Athletics renamed the "Junior" age-group championships (EM
    # and WM) to "U20" in 2019; both names denote the same series
    # across an athlete's whole career.
    "junioreneuropameisterschaften": "u20europameisterschaften",
    "juniorenweltmeisterschaften": "u20weltmeisterschaften",
}


def normalize_competition_name(label):
    """Canonicalizes a competition/category label from either
    'Medaillenspiegel' (e.g. "Europameisterschaften") or a medal entry's
    'Wo' value (e.g. "Leichtathletik-EM") into a comparable key, so the
    two fields' competitions can be matched up despite using different
    naming conventions for the same thing.

    Empirically, 'Wo' values are very often prefixed with
    "Leichtathletik-" (the template is shared across many sports) and/or
    abbreviate "Europameisterschaften"/"Weltmeisterschaften" as "EM"/
    "WM", while 'Medaillenspiegel' entries typically do neither -- e.g.
    "Leichtathletik-Hallen-WM" vs. "Hallenweltmeisterschaften". A
    handful of further real-world synonyms that aren't derivable by a
    generic rule (retired age-group naming, "Olympia" vs. "Olympische
    Spiele", ...) are listed explicitly in
    _MANUAL_COMPETITION_ALIASES."""
    if not label:
        return ""
    text = _LEICHTATHLETIK_PREFIX_RE.sub("", label).lower().strip()
    text = text.replace(".", "")
    text = _WM_EM_RE.sub(lambda m: _WM_EM_EXPANSION[m.group(1)], text)
    key = re.sub(r"[-\s]+", "", text)
    return _MANUAL_COMPETITION_ALIASES.get(key, key)


def _category_label_text(value):
    """Renders a raw 'Wo' category value down to a plain competition
    name, for use as a matching label. Real-world 'Wo' values sometimes
    carry more than just the name: a decorative icon link (e.g.
    "[[Datei:Olympic rings ...svg|30px]] [[Olympische Sommerspiele|
    Olympische Spiele]]") or a trailing {{MedaillenLand|...}} call
    noting that some medals in that group were won for a different
    national team. Both must be stripped out, or they corrupt the
    extracted label or leave stray whitespace behind."""
    if not value:
        return ""
    code = mwparserfromhell.parse(value)
    # Non-recursive: removing a top-level template (e.g. {{MedaillenLand
    # | {{DDR}} }}) already takes any nested templates with it, and
    # asking to remove those separately afterwards raises ValueError
    # since they're no longer present in the tree.
    for tmpl in list(code.filter_templates(recursive=False)):
        code.remove(tmpl)
    for link in list(code.filter_wikilinks(recursive=True)):
        title = str(link.title).strip()
        if title.lower().startswith(("datei:", "file:", "bild:", "image:")):
            code.remove(link)
            continue
        display = str(link.text).strip() if link.text else title
        code.replace(link, display)
    return " ".join(str(code).split())


def medal_counts_by_category(value):
    """Groups individual medal entries from a 'medaillen' field by
    competition, using each {{Medaillen Sommersport|Wo=...}} call's 'Wo'
    argument as the category label (in practice, a single call never
    mixes entries from different competitions). Returns
    {category_key: {"label": str, "gold": n, "silber": n, "bronze": n}},
    where category_key is normalize_competition_name(label) and "label"
    is the (cleaned) raw label, kept for display in messages."""
    result = {}
    if not value:
        return result
    code = mwparserfromhell.parse(value)
    for tmpl in code.filter_templates(recursive=True):
        if _normalize_template_name(tmpl.name) != "medaillen sommersport":
            continue
        if not tmpl.has("Wo"):
            continue
        label = _category_label_text(str(tmpl.get("Wo").value))
        if not label:
            continue
        key = normalize_competition_name(label)
        positional = sorted(
            (p for p in tmpl.params if str(p.name).strip().isdigit()),
            key=lambda p: int(str(p.name).strip()),
        )
        entry = result.setdefault(
            key, {"label": label, "gold": 0, "silber": 0, "bronze": 0}
        )
        for i in range(0, len(positional) - 2, 3):
            color = str(positional[i].value).strip().lower()
            if color in entry:
                entry[color] += 1
    return result


def medal_totals_by_category(value):
    """Groups the declared Gold/Silber/Bronze totals from a
    'Medaillenspiegel' field by competition, using each
    {{Medaillenspiegel|Art der Medaillen|Gold|Silber|Bronze}} call's
    first positional argument as the category label. Returns
    {category_key: {"label": str, "gold": n, "silber": n, "bronze": n}},
    same shape as medal_counts_by_category so the two can be compared
    key by key."""
    result = {}
    if not value:
        return result
    code = mwparserfromhell.parse(value)
    for tmpl in code.filter_templates(recursive=True):
        if _normalize_template_name(tmpl.name) != "medaillenspiegel":
            continue
        positional = sorted(
            (p for p in tmpl.params if str(p.name).strip().isdigit()),
            key=lambda p: int(str(p.name).strip()),
        )
        if len(positional) < 4:
            continue
        label = str(positional[0].value).strip()
        if not label:
            continue
        key = normalize_competition_name(label)
        entry = result.setdefault(
            key, {"label": label, "gold": 0, "silber": 0, "bronze": 0}
        )
        for color, param in zip(("gold", "silber", "bronze"), positional[1:4]):
            m = re.match(r"\d+", str(param.value).strip())
            if m:
                entry[color] += int(m.group(0))
    return result


def visible_text(value):
    """Renders wikilinks down to their visible display text, dropping
    the link target. Without this, scanning raw wikitext for e.g. year
    numbers can pick up digits that only appear in a link's target/
    anchor (such as a section link like
    "[[...#...von 1951 bis 1990...|Leipzig 1986]]"), not in what is
    actually displayed."""
    if not value:
        return ""
    code = mwparserfromhell.parse(value)
    for link in code.filter_wikilinks(recursive=True):
        display = str(link.text) if link.text else str(link.title)
        code.replace(link, display)
    return str(code)


_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_GERMAN_DATE_RE = re.compile(
    r"(\d{1,2})\.\s*([A-Za-zäöüÄÖÜß]+)\s+(\d{3,4})"
)
# Leading year only -- deliberately not anchored at the end, since
# fields like nationalkader often trail off with extra context, e.g.
# "2002 {{SVN}}" (switched national team) or "1955-1972" (start-end
# range, where the start year is what we care about).
_YEAR_ONLY_RE = re.compile(r"^(\d{3,4})\b")
_DATUM_TEMPLATE_RE = re.compile(r"\{\{\s*DATUM\s*\|([^}]*)\}\}", re.IGNORECASE)


def parse_date(value):
    """Tries to extract a DateParts tuple from an infobox date value
    (free text, ISO date, or a {{DATUM|...}} template call). Returns
    None if the format isn't recognized -- that is not an error, it
    just means "not evaluable" for date-based rules."""
    if not value:
        return None

    text = value.strip()

    m = _DATUM_TEMPLATE_RE.search(text)
    if m:
        inner = [p.strip() for p in m.group(1).split("|")]
        nums = [p for p in inner if re.match(r"^\d{1,4}$", p)]
        if len(nums) >= 3:
            day, month, year = nums[0], nums[1], nums[2]
            try:
                return DateParts(int(year), int(month), int(day))
            except ValueError:
                pass
        text = re.sub(_DATUM_TEMPLATE_RE, "", text).strip()

    # Resolve wikilinks like [[12. März]] [[1995]] to plain text
    text = re.sub(r"\[\[([^\]|]*\|)?([^\]]*)\]\]", r"\2", text)
    text = text.strip()

    m = _ISO_DATE_RE.match(text)
    if m:
        year, month, day = (int(x) for x in m.groups())
        return DateParts(year, month, day)

    m = _GERMAN_DATE_RE.search(text)
    if m:
        day_str, month_str, year_str = m.groups()
        month = MONTHS.get(month_str.lower())
        if month:
            try:
                return DateParts(int(year_str), month, int(day_str))
            except ValueError:
                return None

    m = _YEAR_ONLY_RE.match(text)
    if m:
        return DateParts(int(m.group(1)), None, None)

    return None


def date_range(parts):
    """Converts DateParts (possibly with unknown month/day) into an
    (earliest_possible_date, latest_possible_date) pair of
    datetime.date. Returns None if no year is known, or the year is
    outside a plausible range."""
    if parts is None or parts.year is None:
        return None
    if not (1850 <= parts.year <= 2100):
        return None

    month_known = parts.month is not None
    day_known = parts.day is not None and month_known

    early_month = parts.month if month_known else 1
    early_day = parts.day if day_known else 1
    late_month = parts.month if month_known else 12

    try:
        early = date(parts.year, early_month, early_day)
    except ValueError:
        return None

    if day_known:
        late_day = parts.day
    else:
        # last day of the (latest possible) month
        if late_month == 12:
            late_day = 31
        else:
            late_day = (date(parts.year, late_month + 1, 1) - date(parts.year, late_month, 1)).days

    try:
        late = date(parts.year, late_month, late_day)
    except ValueError:
        late = date(parts.year, late_month, 28)

    return (early, late)
