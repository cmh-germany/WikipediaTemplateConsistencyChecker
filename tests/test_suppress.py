"""Tests for suppress.py: the suppressions file format (loading,
validation, plain-language errors), finding fingerprints, matching the
three suppression scopes, and persistence of added/removed entries."""

import json
from dataclasses import replace

import pytest

import suppress
from rules import Finding
from suppress import Suppression, SuppressionFileError, SuppressionStore

PARAMS = {"status": "a", "sterbedatum": "2020-01-01", "geburtsort": "Berlin"}
FINDING = Finding(
    "death_date_with_non_deceased_status",
    "high",
    "sterbedatum is set, but status=a.",
    params=["sterbedatum", "status"],
)


def _write(path, data) -> None:
    path.write_text(
        data if isinstance(data, str) else json.dumps(data), encoding="utf-8"
    )


# ---------------------------------------------------------------------
# fingerprint
# ---------------------------------------------------------------------


def test_fingerprint_is_stable():
    assert suppress.fingerprint(FINDING, PARAMS) == suppress.fingerprint(
        FINDING, dict(PARAMS)
    )


def test_fingerprint_changes_when_an_involved_field_changes():
    edited = {**PARAMS, "sterbedatum": "2021-01-01"}
    assert suppress.fingerprint(FINDING, PARAMS) != suppress.fingerprint(
        FINDING, edited
    )


def test_fingerprint_ignores_unrelated_fields_and_whitespace():
    edited = {**PARAMS, "geburtsort": "Hamburg", "status": " a "}
    assert suppress.fingerprint(FINDING, PARAMS) == suppress.fingerprint(
        FINDING, edited
    )


def test_fingerprint_ignores_message_changes():
    # update_outdated's message states an age that grows every year; a
    # suppression must survive that.
    reworded = replace(FINDING, message="more than 7 years old")
    assert suppress.fingerprint(FINDING, PARAMS) == suppress.fingerprint(
        reworded, PARAMS
    )


def test_fingerprint_differs_between_rules_on_same_fields():
    other = replace(FINDING, rule_id="career_end_despite_active")
    assert suppress.fingerprint(FINDING, PARAMS) != suppress.fingerprint(other, PARAMS)


def test_fingerprint_without_params_falls_back_to_message():
    bare = Finding("missing_birthplace", "low", "m1")
    assert suppress.fingerprint(bare, {}) != suppress.fingerprint(
        replace(bare, message="m2"), {}
    )


# ---------------------------------------------------------------------
# match / partition / suppressed_rules
# ---------------------------------------------------------------------


def test_match_none_when_store_empty():
    assert SuppressionStore().match("Athlete", FINDING, PARAMS) is None


def test_match_single_finding_suppression():
    entry = Suppression(
        FINDING.rule_id, "Athlete", suppress.fingerprint(FINDING, PARAMS)
    )
    store = SuppressionStore([entry])
    assert store.match("Athlete", FINDING, PARAMS) is entry
    assert store.match("Other Athlete", FINDING, PARAMS) is None


def test_match_lapses_once_the_field_is_edited():
    entry = Suppression(
        FINDING.rule_id, "Athlete", suppress.fingerprint(FINDING, PARAMS)
    )
    edited = {**PARAMS, "sterbedatum": "2021-01-01"}
    assert SuppressionStore([entry]).match("Athlete", FINDING, edited) is None


def test_match_rule_in_one_article_ignores_field_values():
    entry = Suppression(FINDING.rule_id, "Athlete")
    edited = {**PARAMS, "sterbedatum": "2021-01-01"}
    store = SuppressionStore([entry])
    assert store.match("Athlete", FINDING, edited) is entry
    assert store.match("Other Athlete", FINDING, PARAMS) is None


def test_match_whole_rule_applies_to_every_article():
    entry = Suppression(FINDING.rule_id)
    assert SuppressionStore([entry]).match("Anyone", FINDING, PARAMS) is entry


def test_match_other_rule_does_not_match():
    entry = Suppression("missing_birthplace")
    assert SuppressionStore([entry]).match("Athlete", FINDING, PARAMS) is None


def test_match_prefers_most_specific_entry():
    whole = Suppression(FINDING.rule_id, reason="whole")
    article = Suppression(FINDING.rule_id, "Athlete", reason="article")
    exact = Suppression(
        FINDING.rule_id,
        "Athlete",
        suppress.fingerprint(FINDING, PARAMS),
        reason="exact",
    )
    assert (
        SuppressionStore([whole, article, exact]).match("Athlete", FINDING, PARAMS)
        is exact
    )
    without_exact = SuppressionStore([whole, article])
    assert without_exact.match("Athlete", FINDING, PARAMS) is article


def test_partition_splits_active_and_suppressed():
    other = Finding("missing_birthplace", "low", "no birthplace")
    entry = Suppression(FINDING.rule_id, "Athlete")
    active, suppressed = SuppressionStore([entry]).partition(
        "Athlete", [FINDING, other], PARAMS
    )
    assert active == [other]
    assert suppressed == [(FINDING, entry)]


def test_suppressed_rules_only_lists_whole_rule_entries():
    store = SuppressionStore(
        [
            Suppression("missing_birthplace"),
            Suppression("update_outdated", "Athlete"),
        ]
    )
    assert store.suppressed_rules == {"missing_birthplace"}


# ---------------------------------------------------------------------
# load: format and validation
# ---------------------------------------------------------------------


def test_default_path_is_in_working_directory(tmp_path):
    # conftest.py makes the test's tmp_path the working directory.
    assert suppress.default_path() == tmp_path / "suppressions.json"


def test_load_missing_file_is_empty_store(tmp_path):
    assert suppress.load(tmp_path / "suppressions.json") == SuppressionStore()


def test_load_valid_file(tmp_path):
    path = tmp_path / "suppressions.json"
    _write(
        path,
        {
            "version": 1,
            "suppressions": [
                {"rule_id": "missing_birthplace", "reason": "not needed"},
                {
                    "rule_id": "medal_count_mismatch",
                    "article": "Usain Bolt",
                    "fingerprint": "abc123",
                    "message": "3 vs. 2",
                    "created": "2026-11-04",
                },
            ],
        },
    )
    store = suppress.load(path)
    assert store.suppressions == [
        Suppression("missing_birthplace", reason="not needed"),
        Suppression(
            "medal_count_mismatch",
            "Usain Bolt",
            "abc123",
            message="3 vs. 2",
            created="2026-11-04",
        ),
    ]


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("{not json", "is invalid"),
        ([], 'must contain a "suppressions" list'),
        ({"suppressions": {}}, 'must contain a "suppressions" list'),
        ({"suppressions": ["x"]}, "entry 1 is not an object"),
        ({"suppressions": [{"reason": "x"}]}, 'entry 1 has no "rule_id"'),
        (
            {"suppressions": [{"rule_id": "bogus_rule"}]},
            "unknown rule ID 'bogus_rule'",
        ),
        (
            {"suppressions": [{"rule_id": "missing_birthplace", "articel": "X"}]},
            "unknown field(s): articel",
        ),
        (
            {"suppressions": [{"rule_id": "missing_birthplace", "article": 5}]},
            '"article" must be text',
        ),
        (
            {"suppressions": [{"rule_id": "missing_birthplace", "fingerprint": "a"}]},
            'has a "fingerprint" but no "article"',
        ),
    ],
)
def test_load_invalid_file_raises_plain_language_error(tmp_path, content, expected):
    path = tmp_path / "suppressions.json"
    _write(path, content)
    with pytest.raises(SuppressionFileError) as exc_info:
        suppress.load(path)
    message = str(exc_info.value)
    assert expected in message
    assert str(path) in message


def test_load_invalid_file_says_how_to_fix_it(tmp_path):
    path = tmp_path / "suppressions.json"
    _write(path, "{not json")
    with pytest.raises(SuppressionFileError, match="delete it to start over"):
        suppress.load(path)


def test_load_non_utf8_file_raises(tmp_path):
    path = tmp_path / "suppressions.json"
    path.write_bytes(b"\xff\xfe\x00broken")
    with pytest.raises(SuppressionFileError, match="Could not read"):
        suppress.load(path)


# ---------------------------------------------------------------------
# Persistence: what the report saves is what the next run loads
# ---------------------------------------------------------------------


def test_to_json_round_trip_after_adding_suppressions(tmp_path):
    path = tmp_path / "suppressions.json"
    store = SuppressionStore([Suppression("missing_birthplace", reason="noise")])
    store.suppressions.append(
        Suppression(
            FINDING.rule_id,
            "Athlete",
            suppress.fingerprint(FINDING, PARAMS),
            message=FINDING.message,
            created="2026-11-04",
        )
    )
    path.write_text(store.to_json(), encoding="utf-8")

    loaded = suppress.load(path)

    assert loaded == store
    assert loaded.match("Athlete", FINDING, PARAMS) is not None


def test_to_json_round_trip_after_removing_a_suppression(tmp_path):
    path = tmp_path / "suppressions.json"
    entry = Suppression(FINDING.rule_id, "Athlete")
    store = SuppressionStore([Suppression("missing_birthplace"), entry])
    path.write_text(store.to_json(), encoding="utf-8")

    store.suppressions.remove(entry)
    path.write_text(store.to_json(), encoding="utf-8")

    assert suppress.load(path).match("Athlete", FINDING, PARAMS) is None


def test_to_json_leaves_out_empty_fields():
    data = json.loads(SuppressionStore([Suppression("missing_birthplace")]).to_json())
    assert data == {"version": 1, "suppressions": [{"rule_id": "missing_birthplace"}]}
