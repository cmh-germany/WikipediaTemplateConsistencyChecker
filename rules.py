"""Consistency rules for the Infobox Leichtathlet parameters.

Each rule is a standalone function `check_*(ctx) -> list[Finding]`. New
rules can simply be added and registered in ALL_RULES without touching
existing rules.
"""

import re
from dataclasses import dataclass, field
from datetime import date

from parse import (
    date_range,
    extract_medal_years,
    extract_template_names,
    medal_counts_by_category,
    medal_totals_by_category,
    parse_date,
)

VERY_HIGH = "very high"
HIGH = "high"
MEDIUM = "medium"
LOW = "low"

SEVERITY_ORDER = {VERY_HIGH: 0, HIGH: 1, MEDIUM: 2, LOW: 3}

VALID_STATUS_CODES = {"a", "g", "n", "p", "u", "v", "z"}

# Vorlage:Status Sportler's #switch also happens to fall through to
# outputting {{{1}}} verbatim for anything it doesn't recognize, which
# means these spelled-out German words render correctly by coincidence
# even though they're not the documented single-letter codes.
STATUS_FULL_WORDS = {
    "aktiv": "a",
    "gesperrt": "g",
    "nicht aktiv": "n",
    "pausierend": "p",
    "unbekannt": "u",
    "verstorben": "v",
    "zurückgetreten": "z",
}


# Natural-language rule names for the HTML report, keyed by the
# internal rule_id (which stays a stable, code-friendly identifier used
# in --check console output and for filtering/linking). Falls back to
# the raw rule_id itself if a title is missing here, so a forgotten
# entry never breaks the report.
RULE_TITLES = {
    "death_date_with_non_deceased_status": (
        "Death date given despite non-deceased status"
    ),
    "status_deceased_without_death_date": "Deceased status without a death date",
    "status_code_spelled_out": "Status code spelled out instead of abbreviated",
    "invalid_status_code": "Invalid status code",
    "deceased_but_living_person_category": (
        "Deceased but still in the living-people category"
    ),
    "death_date_before_birth_date": "Death date before birth date",
    "birth_date_in_future": "Birth date in the future",
    "death_date_in_future": "Death date in the future",
    "career_end_before_birth_date": "Career end before birth date",
    "career_end_despite_active": "Career end given despite active status",
    "implausible_age_at_death": "Implausible age at death",
    "national_squad_before_birth": "National squad year before birth",
    "national_squad_implausibly_young": "Implausibly young national squad start",
    "height_comma_format": "Height uses a comma instead of a plain number",
    "weight_comma_format": "Weight uses a comma instead of a plain number",
    "height_not_numeric": "Height is not a plain number",
    "weight_not_numeric": "Weight is not a plain number",
    "height_implausible": "Implausible height",
    "weight_implausible": "Implausible weight",
    "nation_nonstandard_format": "Nation field in a non-standard format",
    "nation_code_unknown": "Unknown nation code",
    "discipline_link_unknown": "Unknown discipline link",
    "medal_count_mismatch": "Medal count mismatch",
    "medal_before_birth": "Medal year before birth",
    "medal_implausibly_young": "Implausibly young age at first medal",
    "missing_birthplace": "Missing birthplace",
    "update_outdated": "Outdated update despite active status",
}


def rule_title(rule_id):
    return RULE_TITLES.get(rule_id, rule_id)


@dataclass
class Finding:
    rule_id: str
    severity: str
    message: str
    params: list = field(default_factory=list)

    @property
    def title(self):
        return rule_title(self.rule_id)


@dataclass
class Context:
    """Bundles all the inputs a rule might need."""

    params: dict
    categories: list = field(default_factory=list)
    today: date = None
    nation_exists: dict = None  # {"Vorlage:GER": True, ...}, optional
    discipline_exists: dict = None  # {"100-Meter-Lauf": True, ...}, optional

    def get(self, key):
        return self.params.get(key, "").strip()


def _today(ctx):
    return ctx.today or date.today()


# ---------------------------------------------------------------------
# Status / death date
# ---------------------------------------------------------------------


def check_death_date_with_non_deceased_status(ctx):
    status = ctx.get("status").lower()
    if ctx.get("sterbedatum") and status and status != "v":
        return [
            Finding(
                "death_date_with_non_deceased_status",
                HIGH,
                f"Death date (sterbedatum) is given, but status='{ctx.get('status')}' "
                "(not 'v'). Vorlage:Status Sportler will still render "
                "'verstorben' automatically, but the status field itself is "
                "stale and should be updated to 'v'.",
                params=["sterbedatum", "status"],
            )
        ]
    return []


def check_status_deceased_without_death_date(ctx):
    status = ctx.get("status").lower()
    if status == "v" and not ctx.get("sterbedatum"):
        return [
            Finding(
                "status_deceased_without_death_date",
                VERY_HIGH,
                "status=v (deceased), but no death date (sterbedatum) is given.",
                params=["status", "sterbedatum"],
            )
        ]
    return []


def check_invalid_status_code(ctx):
    status = ctx.get("status")
    if not status:
        return []
    normalized = status.lower()
    if normalized in VALID_STATUS_CODES:
        return []
    if normalized in STATUS_FULL_WORDS:
        return [
            Finding(
                "status_code_spelled_out",
                LOW,
                f"status='{status}' spells out the German word instead of "
                f"using the documented single-letter code "
                f"('{STATUS_FULL_WORDS[normalized]}'). Renders correctly by "
                "coincidence (Vorlage:Status Sportler falls back to "
                "displaying the raw value), but should be normalized.",
                params=["status"],
            )
        ]
    return [
        Finding(
            "invalid_status_code",
            VERY_HIGH,
            f"status='{status}' is not a valid code (allowed: a, g, n, p, u, "
            "v, z) and doesn't match a known spelled-out status word either "
            "-- the infobox will likely display this raw text as-is.",
            params=["status"],
        )
    ]


def check_deceased_but_living_person_category(ctx):
    status = ctx.get("status").lower()
    if status == "v" and any("Lebende Personen" in c for c in ctx.categories):
        return [
            Finding(
                "deceased_but_living_person_category",
                HIGH,
                "status=v (deceased), but the article is still categorized "
                "under 'Kategorie:Lebende Personen' (living people).",
                params=["status"],
            )
        ]
    return []


# ---------------------------------------------------------------------
# Date comparisons
# ---------------------------------------------------------------------


def check_death_date_before_birth_date(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    death = date_range(parse_date(ctx.get("sterbedatum")))
    if birth and death and death[1] < birth[0]:
        return [
            Finding(
                "death_date_before_birth_date",
                VERY_HIGH,
                f"Death date ({ctx.get('sterbedatum')}) is before the "
                f"birth date ({ctx.get('geburtstag')}).",
                params=["geburtstag", "sterbedatum"],
            )
        ]
    return []


def check_birth_date_in_future(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    if birth and birth[0] > _today(ctx):
        return [
            Finding(
                "birth_date_in_future",
                VERY_HIGH,
                f"Birth date ({ctx.get('geburtstag')}) is in the future.",
                params=["geburtstag"],
            )
        ]
    return []


def check_death_date_in_future(ctx):
    death = date_range(parse_date(ctx.get("sterbedatum")))
    if death and death[0] > _today(ctx):
        return [
            Finding(
                "death_date_in_future",
                VERY_HIGH,
                f"Death date ({ctx.get('sterbedatum')}) is in the future.",
                params=["sterbedatum"],
            )
        ]
    return []


def check_career_end_before_birth_date(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    end = date_range(parse_date(ctx.get("karriereende")))
    if birth and end and end[1] < birth[0]:
        return [
            Finding(
                "career_end_before_birth_date",
                VERY_HIGH,
                f"Career end ({ctx.get('karriereende')}) is before the "
                f"birth date ({ctx.get('geburtstag')}).",
                params=["geburtstag", "karriereende"],
            )
        ]
    return []


def check_career_end_despite_active(ctx):
    status = ctx.get("status").lower()
    if status == "a" and ctx.get("karriereende"):
        return [
            Finding(
                "career_end_despite_active",
                HIGH,
                "Career end date is given, but status=a (active).",
                params=["karriereende", "status"],
            )
        ]
    return []


def check_implausible_age_at_death(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    death = date_range(parse_date(ctx.get("sterbedatum")))
    if not (birth and death):
        return []
    min_age = (death[0] - birth[1]).days / 365.25
    max_age = (death[1] - birth[0]).days / 365.25
    if max_age < 0:
        return []  # already reported by check_death_date_before_birth_date
    if min_age > 115 or max_age < 10:
        return [
            Finding(
                "implausible_age_at_death",
                HIGH,
                f"Computed age at death is implausible "
                f"(between {min_age:.0f} and {max_age:.0f} years).",
                params=["geburtstag", "sterbedatum"],
            )
        ]
    return []


def check_national_squad_before_birth(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    squad = date_range(parse_date(ctx.get("nationalkader")))
    if not (birth and squad):
        return []
    if squad[1] < birth[0]:
        return [
            Finding(
                "national_squad_before_birth",
                VERY_HIGH,
                f"National squad year ({ctx.get('nationalkader')}) is "
                f"before the birth year ({ctx.get('geburtstag')}).",
                params=["geburtstag", "nationalkader"],
            )
        ]
    age_at_squad = (squad[0] - birth[1]).days / 365.25
    if 0 <= age_at_squad < 10:
        return [
            Finding(
                "national_squad_implausibly_young",
                MEDIUM,
                f"National squad membership starting at approx. age "
                f"{age_at_squad:.0f} seems implausibly young.",
                params=["geburtstag", "nationalkader"],
            )
        ]
    return []


# ---------------------------------------------------------------------
# Plausibility of numeric values
# ---------------------------------------------------------------------


def check_height_weight_plausibility(ctx):
    findings = []
    for field_name, label, unit, lo, hi in (
        ("groesse", "height", "cm", 100, 250),
        ("gewicht", "weight", "kg", 30, 250),
    ):
        raw = ctx.get(field_name)
        if not raw:
            continue
        if "," in raw:
            findings.append(
                Finding(
                    f"{label}_comma_format",
                    MEDIUM,
                    f"{field_name}='{raw}' contains a comma -- per "
                    "documentation, numbers should be given without a comma.",
                    params=[field_name],
                )
            )
            continue
        # Only take the leading run of digits (e.g. "166<ref>...</ref>"
        # -> 166). Stripping all non-digits from the whole string would
        # also pick up unrelated digits from trailing markup, such as a
        # citation URL, and silently produce a nonsense number.
        m = re.match(r"\s*(\d+)", raw)
        if not m:
            findings.append(
                Finding(
                    f"{label}_not_numeric",
                    LOW,
                    f"{field_name}='{raw}' is not recognizable as a plain number.",
                    params=[field_name],
                )
            )
            continue
        value = int(m.group(1))
        if not (lo <= value <= hi):
            findings.append(
                Finding(
                    f"{label}_implausible",
                    MEDIUM,
                    f"{field_name}={value} {unit} is outside the plausible "
                    f"range ({lo}-{hi} {unit}).",
                    params=[field_name],
                )
            )
    return findings


_BARE_NATION_CODE_RE = re.compile(r"^[A-Z]{2,4}(-\d{3,4})?$")


def nation_codes_to_check(nation):
    """Returns the template-name candidates worth existence-checking for
    a raw 'nation' field value: extracted {{XXX}} calls, or the value
    itself if it looks like a bare ISO-3166-1-style code. Shared between
    check_nation_code and the scan/check drivers, which need the same
    list to pre-fetch Vorlage: existence via the API."""
    if not nation:
        return []
    codes = extract_template_names(nation)
    if codes:
        return codes
    if _BARE_NATION_CODE_RE.match(nation):
        return [nation]
    return []


def check_nation_code(ctx):
    """The 'nation' field is documented as a bare ISO-3166-1 alpha-3
    code (e.g. "ETH"), which the template auto-wraps into a flag
    template call via {{#ifexist:Vorlage:{{{nation}}}|{{{{{nation}}}}}|
    ...}}. In practice it is just as often written as an already-
    expanded flag template call directly, like "{{JAM}}" -- sometimes
    several, for athletes who changed nationality
    ("{{GDR}}<br />{{GER}}"). Both forms are valid and checked for
    existence; only values that are neither (plain text / a wikilink,
    e.g. "Philippinen" or "[[NS-Staat|Deutsches Reich]]") deviate from
    the documented convention, even though they still render fine."""
    nation = ctx.get("nation")
    if not nation:
        return []

    codes = nation_codes_to_check(nation)
    if not codes:
        return [
            Finding(
                "nation_nonstandard_format",
                LOW,
                f"nation='{nation}' is neither a {{{{XXX}}}} flag "
                "template call nor a bare ISO-3166-1 alpha-3 code as "
                "documented -- it's plain text or a wikilink.",
                params=["nation"],
            )
        ]

    if ctx.nation_exists is None:
        return []
    findings = []
    for code in codes:
        template_title = f"Vorlage:{code}"
        if ctx.nation_exists.get(template_title) is False:
            findings.append(
                Finding(
                    "nation_code_unknown",
                    MEDIUM,
                    f"nation='{nation}' -- 'Vorlage:{code}' does not exist, "
                    "the infobox will likely display the raw code instead of "
                    "a flag/country name.",
                    params=["nation"],
                )
            )
    return findings


def discipline_candidate(disziplin):
    """Returns disziplin itself if it's a bare, unlinked value worth an
    existence check, else None. The template only auto-links
    'disziplin' via {{#ifexist:{{{disziplin}}}|[[{{{disziplin}}}]]|
    {{{disziplin}}}}} when the value is a single bare title (no
    wikilink already in it) -- most articles with multiple disciplines
    already hand-write their own wikilinks (e.g.
    "[[100-Meter-Lauf|100 m]], [[200-Meter-Lauf|200 m]]"), for which
    this auto-link mechanism is irrelevant and shouldn't be checked."""
    if disziplin and "[[" not in disziplin:
        return disziplin
    return None


def check_discipline_link(ctx):
    disziplin = discipline_candidate(ctx.get("disziplin"))
    if not disziplin or ctx.discipline_exists is None:
        return []
    if ctx.discipline_exists.get(disziplin) is False:
        return [
            Finding(
                "discipline_link_unknown",
                LOW,
                f"disziplin='{disziplin}' does not match an existing "
                "article, the infobox will show it as plain unlinked text "
                "-- possibly a typo.",
                params=["disziplin"],
            )
        ]
    return []


def check_medal_count_mismatch(ctx):
    """Cross-checks the individual medal entries in 'medaillen' against
    the declared totals in 'Medaillenspiegel', competition by
    competition (e.g. "Olympische Spiele", "Weltmeisterschaften"), by
    matching each side's category label via
    parse.normalize_competition_name -- see there for why the two
    fields need normalizing before they're comparable at all (different
    abbreviations, a "Leichtathletik-" prefix on one side only, ...).

    Only competitions present on BOTH sides are compared. It is common,
    and not a data error, for a competition to appear on only one side:
    'Medaillenspiegel' is conventionally restricted to senior top-tier
    competitions, while 'medaillen' may additionally list junior/youth/
    indoor/university-level results that were never meant to be
    reflected in the summary table (e.g. Usain Bolt's Commonwealth
    Games and Youth World Championships golds are listed in 'medaillen'
    but not counted in his Medaillenspiegel totals). Those competitions
    are simply not cross-checked, rather than reported as missing.

    Once a competition is confirmed present on both sides, a per-color
    count mismatch is a much stronger signal than the old grand-total
    check (it can no longer be explained away by differing competition
    tiers), so this is kept at high rather than medium confidence."""
    medaillen = ctx.get("medaillen")
    spiegel = ctx.get("Medaillenspiegel")
    if not medaillen or not spiegel:
        return []
    actual = medal_counts_by_category(medaillen)
    declared = medal_totals_by_category(spiegel)
    findings = []
    for key in sorted(set(actual) & set(declared)):
        actual_entry = actual[key]
        declared_entry = declared[key]
        diffs = [
            f"{color} {actual_entry[color]} vs. {declared_entry[color]}"
            for color in ("gold", "silber", "bronze")
            if actual_entry[color] != declared_entry[color]
        ]
        if not diffs:
            continue
        findings.append(
            Finding(
                "medal_count_mismatch",
                HIGH,
                f"'{declared_entry['label']}': medal count mismatch between "
                f"'medaillen' and 'Medaillenspiegel' ({', '.join(diffs)}, "
                "individual medals listed vs. declared total).",
                params=["medaillen", "Medaillenspiegel"],
            )
        )
    return findings


def check_medal_year_before_birth(ctx):
    birth = date_range(parse_date(ctx.get("geburtstag")))
    if not birth:
        return []
    years = extract_medal_years(ctx.get("medaillen"))
    if not years:
        return []
    earliest_medal = min(years)
    age_at_first_medal = earliest_medal - birth[1].year
    if age_at_first_medal < 0:
        return [
            Finding(
                "medal_before_birth",
                HIGH,
                f"Earliest year found in the medals section "
                f"({earliest_medal}) is before the birth year.",
                params=["geburtstag", "medaillen"],
            )
        ]
    if age_at_first_medal < 10:
        return [
            Finding(
                "medal_implausibly_young",
                MEDIUM,
                f"Earliest year found in the medals section "
                f"({earliest_medal}) implies an age of only about "
                f"{age_at_first_medal} years.",
                params=["geburtstag", "medaillen"],
            )
        ]
    return []


# ---------------------------------------------------------------------
# Completeness / recency (low priority)
# ---------------------------------------------------------------------


def check_missing_birthplace(ctx):
    if not ctx.get("geburtsort") and not ctx.get("geburtsland"):
        return [
            Finding(
                "missing_birthplace",
                LOW,
                "Neither birthplace (geburtsort) nor birth country "
                "(geburtsland) is given.",
                params=["geburtsort", "geburtsland"],
            )
        ]
    return []


def check_outdated_update_while_active(ctx):
    status = ctx.get("status").lower()
    update = date_range(parse_date(ctx.get("update")))
    if status == "a" and update:
        age_years = (_today(ctx) - update[1]).days / 365.25
        if age_years > 5:
            return [
                Finding(
                    "update_outdated",
                    LOW,
                    f"status=a (active), but the last update "
                    f"({ctx.get('update')}) is more than {age_years:.0f} "
                    "years old.",
                    params=["status", "update"],
                )
            ]
    return []


ALL_RULES = [
    check_death_date_with_non_deceased_status,
    check_status_deceased_without_death_date,
    check_invalid_status_code,
    check_deceased_but_living_person_category,
    check_death_date_before_birth_date,
    check_birth_date_in_future,
    check_death_date_in_future,
    check_career_end_before_birth_date,
    check_career_end_despite_active,
    check_implausible_age_at_death,
    check_national_squad_before_birth,
    check_height_weight_plausibility,
    check_nation_code,
    check_discipline_link,
    check_medal_count_mismatch,
    check_medal_year_before_birth,
    check_missing_birthplace,
    check_outdated_update_while_active,
]


def run_all_checks(
    params, categories=None, today=None, nation_exists=None, discipline_exists=None
):
    ctx = Context(
        params=params,
        categories=categories or [],
        today=today,
        nation_exists=nation_exists,
        discipline_exists=discipline_exists,
    )
    findings = []
    for rule in ALL_RULES:
        findings.extend(rule(ctx))
    findings.sort(key=lambda f: SEVERITY_ORDER[f.severity])
    return findings
