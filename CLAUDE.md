# CLAUDE.md

Guidance for Claude Code (and any other AI assistant) working in this repository.

## Project Overview

WikipediaTemplateConsistencyChecker finds consistency errors in German Wikipedia
article templates (currently only `Vorlage:Infobox Leichtathlet` template, e.g. a death date
given despite an "active" status), either for a single article/draft or across
all ~15,000 articles embedding the template. See [`README.md`](README.md) for
the full description, usage, severity levels, and known limitations — read it
before making non-trivial changes, and keep it in sync with the code (see
[Documentation](#documentation) below).

The program and all documentation, comments, commit messages, and CLI output
are in **English**, even though the target Wikipedia and its templates are
German-language.

## Project Structure

See [README.md](README.md#project-structure) for the file layout.

When adding a genuinely new concern (e.g. support for a second infobox
template), prefer a new module over growing an existing one into a grab-bag.
For anything smaller, extend the module that already owns that concern.

## Environment

* Python 3.11+ only. Use the local virtual environment (`.venv`).
* Install dependencies: `python -m pip install -r requirements-dev.txt`
  (pulls in `requirements.txt` plus test/lint tooling).

## Code Style

* Target Python 3.11+ and write modern, idiomatic, readable code: f-strings,
  `pathlib` over `os.path` in new code, `match` statements where they're
  clearer than an `if`/`elif` chain, built-in generics (`list[str]`, `dict[str,
  int]`) rather than `typing.List`/`typing.Dict`, dataclasses for simple data
  containers, walrus operator where it removes real duplication — but never
  cleverness for its own sake. Readability beats brevity.
* Follow PEP 8. `ruff format` is the formatter and is the final word on
  layout — don't hand-format against it.
* **Type hints are required on all public functions and methods** (parameters
  and return type). Private helpers (leading underscore) should be typed too
  whenever it aids readability, but it's not mandatory.
* **Docstrings are required on all public classes and on any function whose
  behavior isn't obvious from its name and signature** — in particular, explain
  *why* when a function works around a non-obvious constraint (see
  `main.py`'s `_positive_int` and `_check_output_path` for the tone/level of
  detail expected: short, focused on the non-obvious reasoning, not restating
  the code). Trivial one-line functions don't need one.
* Existing code predates some of these conventions (e.g. missing type hints).
  When you touch a function for another reason, it's fine to add hints/a
  docstring while you're there — but don't do drive-by rewrites of unrelated
  code just to backfill style.
* Use `is`/`is not` when comparing with `None`, `True`, or `False`; prefer
  list/dict comprehensions, generator expressions, and `enumerate()` over
  manually-managed index/counter variables.
* Use context managers (`with`) for file and other resource handling instead
  of manual open/close.

### Function design

* Keep each function to a single responsibility; prefer returning early over
  nesting the main logic inside conditionals.
* Never use a mutable object (list, dict, set) as a default argument value —
  use `None` and construct the mutable default inside the function body.
* Five or fewer parameters is the target; beyond that, group related values
  into a dataclass rather than adding more positional/keyword arguments.

### Class design

* Keep each class to a single responsibility with a simple `__init__`; if the
  class is just a data container, use `@dataclass` instead of hand-writing it.
* Prefer composition over inheritance.
* Use `@property` for computed attributes rather than a getter-style method.

## Error Handling

* Never swallow an exception silently — at minimum log it; a bare `except:`
  (or `except Exception:` used as a catch-all) is not acceptable where a
  specific exception type is known.
* Catch the specific exception type you expect and can meaningfully handle,
  not a broad type that also hides unrelated bugs.
* Error messages must be meaningful and actionable — see [CLI
  Design](#cli-design) for the additional bar CLI-facing errors must clear.

## Security

* This tool only ever reads public Wikipedia content (`fetch.py`); it does
  not currently need credentials. If a future change introduces any secret,
  token, or API key, it must come from an environment variable or a local,
  `.gitignore`d file — never be hard-coded or committed.
* Never log or print a URL, header, or other value that could carry a secret
  (e.g. an API key in a query string).

## Linting, Formatting & Type Checking

Run these before considering any change finished:

```sh
ruff format .
ruff check .
mypy .
```

Fix everything both tools report for lines you touched; don't suppress
warnings with blanket `# noqa` / `# type: ignore` — narrow, justified
exceptions (with a short comment explaining why) are fine when a rule
genuinely doesn't apply.

## Testing

* **Run the full test suite after every change**, not just tests you think
  are related:
  ```sh
  python -m pytest
  ```
  All tests must pass before a change is considered done.
* **Add tests for every new feature, CLI flag, or rule** — don't leave new
  functionality uncovered. Follow the existing suite's approach: real
  Infobox Leichtathlet snapshots in `tests/fixtures/` plus hand-crafted edge
  cases, no real network calls (`fetch.py` is mocked).
* When fixing a bug, add a regression test that fails before the fix and
  passes after.
* **Aim for >80% coverage on business logic** (`parse.py`, `rules.py`,
  `report.py`, and `main.py`'s `run_check`/`run_scan`) — check with:
  ```sh
  python -m pytest --cov=. --cov-report=term-missing
  ```
  (requires `pytest-cov`, see `requirements-dev.txt`). Argument-parsing
  boilerplate and `__main__` guards don't need to be chased for coverage's
  own sake — focus on the logic that decides what's flagged and how.

## CLI Design

* All functionality is exposed via CLI flags in `main.py` (`argparse`) — this
  tool is meant to be usable by non-developers, not just as a library.
* Keep flag names consistent and few: reuse an existing flag's name and
  meaning for the same concept elsewhere rather than inventing a synonym
  (e.g. `--output` always means "path to write a report to"). Prefer
  long, descriptive `--flag-names` over single-letter shortcuts — this is a
  low-frequency, occasionally-used tool, not a daily-driver CLI where typing
  speed matters.
* Every flag needs clear `help=` text usable by someone without programming
  background, and errors from bad input (see `_positive_int`,
  `_check_output_path`) should say in plain language what was wrong and,
  where possible, how to fix it — the target audience includes non-developer
  Wikipedia editors, per the [Troubleshooting section of the
  README](README.md#troubleshooting).
* Don't add a new flag for something that can be inferred or reasonably
  defaulted — every flag is a small tax on the non-developer users this tool
  is for.

## Git Workflow

* When starting work on a GitHub issue, first `git fetch origin` and pull all
  changes from the `main` branch. Then create a new branch named after the
  issue (e.g. `20-cli-argument---overwrite-cache-flag-with-cache-age-detection`
  for
  https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/20).
  All commits for that issue happen on this branch.
* Commit in small, focused, logically-independent steps rather than one
  large commit per task — each commit should represent one coherent change
  that could be reviewed on its own. Split by logical change, not by file:
  e.g. one commit per rule/behavior fixed, not one commit for "all the fixes"
  plus one for "all the READMEs". Tests always get their own commit,
  separate from the implementation they cover.
* Write clear, descriptive commit messages in English: a concise summary
  line (imperative mood, e.g. "Add medal-year range check"), and, when the
  *why* isn't obvious from the diff alone, a body of **at most three bullet
  points** — if it doesn't fit in three, the commit is probably doing too
  much and should be split instead of the message padded out.
* Don't mix formatting-only changes with behavioral changes in the same
  commit.

## Documentation

* `README.md` is the primary entry point for developers and users and should
  stay thorough: when you add a flag, rule, module, or limitation, update the
  corresponding README section (Usage, Severity Levels, Project Structure,
  Known Limitations, Roadmap) in the same change, not as a follow-up.
* If a new rule was validated against live articles, follow the existing
  "Rule Validation" convention described in the README.
