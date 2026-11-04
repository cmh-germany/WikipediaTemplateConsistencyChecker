"""Persistent suppression of known false-positive findings.

Suppressions live in `suppressions.json` in the current working
directory and are created/removed from the HTML report (see
templates/report.html) or by hand. Each entry has one of three scopes:

* only `rule_id`: the whole rule, in every article (such rules aren't
  even run, see main.py)
* `rule_id` + `article`: that rule in that one article
* `rule_id` + `article` + `fingerprint`: one specific finding, for as
  long as the infobox fields it is about keep their current values
"""

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from rules import RULE_TITLES, Finding

SUPPRESSIONS_FILENAME = "suppressions.json"
FORMAT_VERSION = 1

_FIELDS = ("rule_id", "article", "fingerprint", "message", "reason", "created")


class SuppressionFileError(Exception):
    """suppressions.json exists but can't be used. Carries a
    plain-language message meant to be shown to the user as-is."""


@dataclass(frozen=True)
class Suppression:
    """One entry of suppressions.json. `message` is informational only
    (so a human reading the file knows what was suppressed) and is never
    used for matching."""

    rule_id: str
    article: str | None = None
    fingerprint: str | None = None
    message: str = ""
    reason: str = ""
    created: str = ""

    @property
    def is_whole_rule(self) -> bool:
        return self.article is None

    def to_dict(self) -> dict[str, str]:
        """The entry as stored in the file, leaving out empty fields so
        hand-written entries and saved ones look alike."""
        return {key: value for key, value in asdict(self).items() if value}


def default_path() -> Path:
    return Path.cwd() / SUPPRESSIONS_FILENAME


def fingerprint(finding: Finding, params: dict[str, str]) -> str:
    """Identifies `finding` by its rule and the current values of the
    infobox fields it is about, so a suppression lapses as soon as
    someone edits those fields. Deliberately not based on the message:
    some messages change on their own over time (update_outdated states
    an age that grows every year). Values are hashed rather than stored,
    since fields like `medaillen` hold a whole medal table. A finding
    without params (none at the time of writing) falls back to its
    message."""
    if finding.params:
        values = [
            [name, params.get(name, "").strip()] for name in sorted(finding.params)
        ]
        payload = json.dumps([finding.rule_id, values], ensure_ascii=False)
    else:
        payload = json.dumps([finding.rule_id, finding.message], ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


@dataclass
class SuppressionStore:
    """All suppressions loaded from (or about to be saved to) the
    suppressions file."""

    suppressions: list[Suppression] = field(default_factory=list)

    @property
    def suppressed_rules(self) -> frozenset[str]:
        """Rule IDs suppressed in every article (whole-rule entries)."""
        return frozenset(s.rule_id for s in self.suppressions if s.is_whole_rule)

    def match(
        self, article: str, finding: Finding, params: dict[str, str]
    ) -> Suppression | None:
        """The suppression covering `finding` in `article`, if any --
        the most specific one, so the report shows the reason given for
        exactly this finding rather than a broader one."""
        candidates = [
            s
            for s in self.suppressions
            if s.rule_id == finding.rule_id and s.article in (None, article)
        ]
        if not candidates:
            return None
        finding_print = fingerprint(finding, params)
        for suppression in candidates:
            if suppression.article and suppression.fingerprint == finding_print:
                return suppression
        for suppression in candidates:
            if suppression.article and suppression.fingerprint is None:
                return suppression
        return next((s for s in candidates if s.is_whole_rule), None)

    def partition(
        self, article: str, findings: list[Finding], params: dict[str, str]
    ) -> tuple[list[Finding], list[tuple[Finding, Suppression]]]:
        """Splits `findings` into (active findings, suppressed findings
        paired with the suppression that matched them)."""
        active: list[Finding] = []
        suppressed: list[tuple[Finding, Suppression]] = []
        for finding in findings:
            if suppression := self.match(article, finding, params):
                suppressed.append((finding, suppression))
            else:
                active.append(finding)
        return active, suppressed

    def to_json(self) -> str:
        return json.dumps(
            {
                "version": FORMAT_VERSION,
                "suppressions": [s.to_dict() for s in self.suppressions],
            },
            ensure_ascii=False,
            indent=2,
        )


def _parse_entry(entry: object, index: int) -> Suppression:
    """Validates one entry of the "suppressions" list. Raises a
    ValueError describing the problem in plain language; load() adds
    the file path and how to fix it."""
    where = f"entry {index + 1}"
    if not isinstance(entry, dict):
        raise ValueError(f"{where} is not an object ({{...}})")
    if unknown := sorted(set(entry) - set(_FIELDS)):
        raise ValueError(f"{where} has unknown field(s): {', '.join(unknown)}")
    for key, value in entry.items():
        if not isinstance(value, str):
            raise ValueError(f'{where}: "{key}" must be text in quotes')
    rule_id = entry.get("rule_id", "").strip()
    if not rule_id:
        raise ValueError(f'{where} has no "rule_id"')
    if rule_id not in RULE_TITLES:
        raise ValueError(
            f"{where} names an unknown rule ID '{rule_id}' (see the list of "
            "rule IDs in the README)"
        )
    if entry.get("fingerprint") and not entry.get("article"):
        raise ValueError(f'{where} has a "fingerprint" but no "article"')
    return Suppression(
        rule_id=rule_id,
        article=entry.get("article") or None,
        fingerprint=entry.get("fingerprint") or None,
        message=entry.get("message", ""),
        reason=entry.get("reason", ""),
        created=entry.get("created", ""),
    )


def load(path: Path) -> SuppressionStore:
    """Reads the suppressions file. A missing file just means nothing is
    suppressed yet. A broken one raises SuppressionFileError instead of
    being treated as empty (unlike the cache, see fetch.py): this is
    data the user wrote, and silently ignoring it would make every
    suppressed finding reappear without explanation."""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return SuppressionStore()
    except (OSError, UnicodeDecodeError) as exc:
        raise SuppressionFileError(
            f"Could not read the suppressions file '{path}': {exc}."
        ) from exc
    try:
        data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("suppressions"), list):
            raise ValueError('it must contain a "suppressions" list')
        suppressions = [
            _parse_entry(entry, index)
            for index, entry in enumerate(data["suppressions"])
        ]
    except ValueError as exc:  # json.JSONDecodeError is a ValueError too
        raise SuppressionFileError(
            f"The suppressions file '{path}' is invalid: {exc}. Fix it in a "
            "text editor, or save it again from the HTML report, or delete "
            "it to start over (see 'Suppressing False Positives' in the "
            "README)."
        ) from exc
    return SuppressionStore(suppressions)
