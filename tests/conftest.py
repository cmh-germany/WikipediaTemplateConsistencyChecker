"""Shared fixtures: real Infobox Leichtathlet wikitext pulled from live
German Wikipedia articles (see tests/fixtures/), captured 2026-08-01.
Used across test_parse.py and test_rules.py so parsing and rule
behavior are both exercised against real-world formatting quirks
(messy trailing markup, bare vs. templated nation codes, multiple
flag templates, year-only dates, ...), not just hand-built minimal
cases."""

import os

import pytest

import parse
import throttle

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(autouse=True)
def isolated_throttle_lock_file(tmp_path, monkeypatch):
    """Points throttle.LOCK_FILE at a throwaway path for every test, so
    the suite never reads or writes the real, machine-wide pacing state
    shared with actual runs of the tool."""
    path = tmp_path / "api.lock"
    monkeypatch.setattr(throttle, "LOCK_FILE", path)
    return path


def load_fixture(name):
    path = os.path.join(FIXTURES_DIR, name)
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def bolt_wikitext():
    return load_fixture("usain_bolt.wikitext")


@pytest.fixture
def owens_wikitext():
    return load_fixture("jesse_owens.wikitext")


@pytest.fixture
def mihambo_wikitext():
    return load_fixture("malaika_mihambo.wikitext")


@pytest.fixture
def drechsler_wikitext():
    return load_fixture("heike_drechsler.wikitext")


@pytest.fixture
def bolt_params(bolt_wikitext):
    return parse.parse_infobox_params(bolt_wikitext)


@pytest.fixture
def owens_params(owens_wikitext):
    return parse.parse_infobox_params(owens_wikitext)


@pytest.fixture
def mihambo_params(mihambo_wikitext):
    return parse.parse_infobox_params(mihambo_wikitext)


@pytest.fixture
def drechsler_params(drechsler_wikitext):
    return parse.parse_infobox_params(drechsler_wikitext)
