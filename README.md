<!-- Improved compatibility of back to top link: See: https://github.com/othneildrew/Best-README-Template/pull/73 -->
<a id="readme-top"></a>

<!-- PROJECT SHIELDS -->
[![Contributors][contributors-shield]][contributors-url]
[![Forks][forks-shield]][forks-url]
[![Stargazers][stars-shield]][stars-url]
[![Issues][issues-shield]][issues-url]
[![License][license-shield]][license-url]
[![Python][python-shield]][python-url]



<!-- PROJECT LOGO -->
<br />
<div align="center">
<h3 align="center">WikipediaTemplateConsistencyChecker</h3>

  <p align="center">
    Finds consistency errors in Wikipedia articles that use Vorlage:Infobox template (such as the
    <a href="https://de.wikipedia.org/wiki/Vorlage:Infobox_Leichtathlet"><code>Infobox Leichtathlet</code></a>)
     — e.g. a death date given despite an "active" status — and helps
    avoid such errors when drafting a new infobox.
    <br />
    <a href="https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/new?labels=bug&title=%5BBug%5D%3A+">Report Bug</a>
    &middot;
    <a href="https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues/new?labels=enhancement&title=%5BFeature%5D%3A+">Request Feature</a>
  </p>
</div>



<!-- TABLE OF CONTENTS -->
<details>
  <summary>Table of Contents</summary>
  <ol>
    <li>
      <a href="#about-the-project">About The Project</a>
      <ul>
        <li><a href="#built-with">Built With</a></li>
      </ul>
    </li>
    <li><a href="#ai-assistance-disclaimer">AI Assistance Disclaimer</a></li>
    <li>
      <a href="#getting-started">Getting Started</a>
      <ul>
        <li><a href="#prerequisites">Prerequisites</a></li>
        <li><a href="#installation">Installation</a></li>
      </ul>
    </li>
    <li>
      <a href="#usage">Usage</a>
      <ul>
        <li><a href="#severity-levels">Severity Levels</a></li>
      </ul>
    </li>
    <li><a href="#running-tests">Running Tests</a></li>
    <li><a href="#troubleshooting">Troubleshooting</a></li>
    <li><a href="#project-structure">Project Structure</a></li>
    <li><a href="#known-limitations">Known Limitations</a></li>
    <li><a href="#rule-validation">Rule Validation</a></li>
    <li><a href="#roadmap">Roadmap</a></li>
    <li><a href="#contributing">Contributing</a></li>
    <li><a href="#license">License</a></li>
    <li><a href="#contact">Contact</a></li>
    <li><a href="#acknowledgments">Acknowledgments</a></li>
  </ol>
</details>



<!-- ABOUT THE PROJECT -->
## About The Project

**WikipediaTemplateConsistencyChecker is currently a technical proof of
concept**, built and validated against a single template so far:
German Wikipedia's [`Vorlage:Infobox Leichtathlet`](https://de.wikipedia.org/wiki/Vorlage:Infobox_Leichtathlet)
(athlete infobox). The underlying approach, however, is not specific to
that one template: parse a template's raw parameters out of the wikitext,
run a set of independent consistency rules against them, and report
whatever doesn't add up. The goal is to grow this into a tool that can be
pointed at other Wikipedia infobox templates as well, each with its own
rule set — see [Roadmap](#roadmap) for which templates and checks are
planned next. Contributions defining rule sets for additional templates
are very welcome; see [Contributing](#contributing).

Infobox Leichtathlet was the natural first target: it's embedded in
roughly 15,000 articles, hand-edited over many years by many different
people, which makes it easy for small, silent inconsistencies to creep
in — a death date next to a status that still says "active", a medal
listed under one competition name in the medal table and a slightly
different name in the medal summary, a national-squad year that predates
the athlete's birth, and so on. None of these break the infobox's
rendering, so they're easy to miss just by looking at the page.

For this template, the tool parses its raw parameters out of the wikitext
and runs a set of independent consistency rules against them, either for
a single article/draft or for every article that embeds the template.
Results are either printed to the console or collected into a single,
sortable, self-contained HTML report.

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Built With

* [![Python][python-badge]][python-url]
* [![Requests][requests-badge]][requests-url]
* [![mwparserfromhell][mwparserfromhell-badge]][mwparserfromhell-url]
* [![MediaWiki API][mediawiki-badge]][mediawiki-url]

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- AI DISCLAIMER -->
## AI Assistance Disclaimer

Large parts of this project's code, its rule set, and this README were
written in collaboration with [Claude](https://claude.com) (Anthropic), an
AI coding assistant, under the direction and review of the maintainer.
AI-assisted rules were validated against a live sample of real Wikipedia
articles before being added (see [Rule Validation](#rule-validation)), but
the tool is not infallible — please review its findings before acting on
them, and feel free to [open an issue](https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues)
if a rule doesn't match how the template is actually used.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- GETTING STARTED -->
## Getting Started

To get a local copy up and running, follow these steps.

### Prerequisites

* **A terminal.** Every command below is typed into a command-line
  terminal, not run by double-clicking a file. On Windows, open
  "PowerShell" or "Terminal" from the Start menu; on macOS, open
  "Terminal" (in Applications > Utilities); on Linux, use your
  distribution's terminal application.
* **Python 3.11 or newer.** Check whether it's already installed, and
  which version, with:
  ```sh
  python --version
  ```
  On macOS/Linux the command is sometimes `python3` instead of `python`
  — if `python --version` fails, try that before assuming Python isn't
  installed. If it's missing or older than 3.11, install it from
  [python.org/downloads](https://www.python.org/downloads/). **On
  Windows, tick "Add python.exe to PATH"** on the first installer screen
  — this is the most common cause of a later "python is not recognized"
  error (see [Troubleshooting](#troubleshooting)).
* **pip**, Python's package manager (installed together with Python
  since version 3.4):
  ```sh
  python -m pip install --upgrade pip
  ```
* *(Optional)* [Git](https://git-scm.com/downloads), only needed for the
  `git clone` command in step 1 below. Without Git, download the code as
  a ZIP instead (see step 1) and skip straight to step 2.

No API key or authentication is required — the tool only ever calls the
public, unauthenticated German Wikipedia API.

### Installation

1. Get the code, either by cloning the repository with Git
   ```sh
   git clone https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker.git
   cd WikipediaTemplateConsistencyChecker
   ```
   or, if Git isn't installed, via the green "Code" → "Download ZIP"
   button on the
   [GitHub project page](https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker),
   then extracting the ZIP and opening a terminal in the extracted
   folder.
2. Install the Python dependencies
   ```sh
   python -m pip install -r requirements.txt
   ```
   (`python -m pip` is used instead of a bare `pip` command so it's
   guaranteed to install into the same Python installation checked in
   the Prerequisites step — see [Troubleshooting](#troubleshooting) if
   `pip` alone doesn't work for you.)
3. *(Windows only, if needed)* If installation fails with an error like
   "Microsoft Visual C++ 14.0 or greater is required" (missing C compiler
   for the optional `mwparserfromhell` speedup extension), install the
   pure-Python variant instead:
   ```powershell
   $env:WITH_EXTENSION = "0"   # PowerShell
   python -m pip install -r requirements.txt
   ```

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- USAGE EXAMPLES -->
## Usage

Check the installed version:

```sh
python main.py --version
```

Scan all articles that embed the template and generate an HTML report:

```sh
python main.py --scan
```

Creates `report.html` with all findings, sorted by severity by default
(click any column header to re-sort, e.g. by article or rule). Open it by
double-clicking it in your file browser, or automatically with `--open`
below. Already fetched articles are cached in `cache.json` so a repeated
run is faster (bypass the cache with `--no-cache`, e.g. if articles have
changed since — deleting `cache.json` has the same effect). A collapsible
list of every scanned article, with its finding count, is always included
at the bottom of the report, collapsed by default. Each severity filter
checkbox shows its finding count, e.g. "high (12)", and the console output
ends with the same counts broken down by severity, e.g.
`Total findings: 12 (Very high: 2, High: 3, Medium: 5, Low: 2)`.

A full scan reads roughly 15,000 articles from the Wikipedia API and
deliberately paces its requests to avoid overloading it, so — especially
on the first run, before `cache.json` is populated — expect it to take
several minutes rather than seconds. This is normal, not a freeze; use
`--limit 50` (below) first if you just want to confirm the tool works.

```sh
python main.py --scan --limit 50     # only scan the first 50 articles
python main.py --scan --open         # open the report when the scan finishes
python main.py --scan --output athletes.html   # custom report file name (default: report.html)
```

Check a single article or a local draft instead:

```sh
python main.py --check "Usain Bolt"
python main.py --check https://de.wikipedia.org/wiki/Usain_Bolt
python main.py --check my_draft.wikitext
```

Findings are printed to the console, followed by the same severity
breakdown as the report (omitted when there are no findings).

The article-title form must match the exact spelling/capitalization of the
Wikipedia page title; if you're unsure, copying the full URL from your
browser's address bar (second example) is the safer option since it
sidesteps that matching entirely.

The last variant checks a local file containing wikitext (e.g. a new infobox
that hasn't been published yet) without any network access to the article
content. To create one: open the draft in Wikipedia's source editor
("Quelltext bearbeiten" / "Edit source"), copy the relevant text — the
whole page, or just the `{{Infobox Leichtathlet ... }}` block — and paste
it into a plain text file (e.g. with Notepad or TextEdit), saved with a
`.wikitext` or `.txt` extension. Plain text only — do not save it as a
`.docx` or similar rich-text/word-processor format.

_For the full rule set and the reasoning behind it, see [`rules.py`](rules.py)
and [Rule Validation](#rule-validation) below._

### Severity Levels

| Level | Meaning |
|---|---|
| **very high** | logical contradiction, virtually always an error (e.g. death date before birth date) |
| **high** | strong indicator of an error, but theoretically explainable |
| **medium** | implausible value, but could be a genuine edge case |
| **low** | missing information or outdated data, more of a hint than an error |

Each rule has a stable, code-friendly `rule_id` (used in `--check` console
output and in `rules.RULE_TITLES`) plus a natural-language title shown in the
HTML report, along with the infobox parameter(s) it flagged.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- TESTING -->
## Running Tests

```sh
python -m pip install -r requirements-dev.txt
python -m pytest
```

The suite (`tests/test_parse.py`, `tests/test_rules.py`,
`tests/test_main.py`) uses real Infobox Leichtathlet snapshots
captured from live articles (`tests/fixtures/`) as well as
hand-crafted edge cases, but does not make any network calls itself
(all `fetch.py` calls are mocked). It's basic coverage -- organized so
every infobox field is exercised by at least one test rather than
every individual rule, and so every CLI flag (`--scan`, `--check`,
`--limit`, `--output`, `--no-cache`, `--open`) is exercised at least
once -- rather than an exhaustive suite.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- TROUBLESHOOTING -->
## Troubleshooting

* **`'python' is not recognized ...`** (Windows) or **`command not
  found: python`** (macOS/Linux) — Python isn't installed, or wasn't
  added to your PATH. Reinstall from
  [python.org/downloads](https://www.python.org/downloads/) and, on
  Windows, tick "Add python.exe to PATH" on the first installer screen;
  on macOS/Linux, try `python3` instead of `python` in every command.
* **`'pip' is not recognized ...`** — use `python -m pip ...` instead of
  a bare `pip ...` command everywhere in this guide.
* **`ModuleNotFoundError: No module named 'requests'`** (or
  `mwparserfromhell`) — the dependency install step was skipped or
  failed silently; re-run
  `python -m pip install -r requirements.txt` from inside the project
  folder and check its output for errors.
* **"Microsoft Visual C++ 14.0 or greater is required"** during install
  (Windows) — see step 3 of [Installation](#installation).
* **`SSLCertVerificationError` / certificate errors** — usually caused by
  a corporate proxy or firewall intercepting HTTPS traffic (common on a
  work laptop). Ask your IT department, or try again on a private
  network/device.
* **`Article '...' not found or has no retrievable wikitext revision.`**
  — double-check the title's spelling/capitalization, or use the full
  article URL instead: `python main.py --check https://de.wikipedia.org/wiki/...`.
* **The scan seems to hang** — a full `--scan` run fetches roughly 15,000
  articles at a deliberately throttled pace and can take several
  minutes, especially before `cache.json` is populated; this is expected.
  Run `python main.py --scan --limit 50` first to confirm the tool works
  before committing to a full scan.
* **Something else / a rule looks wrong** — please
  [open an issue](https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues)
  with the command you ran and the full error message or article title.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- PROJECT STRUCTURE -->
## Project Structure

* `fetch.py` -- access to the MediaWiki API (article list, wikitext,
  categories, existence check for nation templates), with a local cache
* `parse.py` -- extracts the infobox parameters from the wikitext
  (`mwparserfromhell`) and parses (possibly incomplete) date values
* `rules.py` -- the rule set
* `report.py` -- generates the self-contained HTML report
* `templates/` -- HTML templates used by `report.py` (`string.Template`,
  `$placeholder` syntax)
* `main.py` -- command-line entry point
* `tests/` -- automated test suite (pytest), see [Running Tests](#running-tests)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- KNOWN LIMITATIONS -->
## Known Limitations

* Date recognition covers ISO dates (`YYYY-MM-DD`), German free-text dates
  (`12. März 1995`), and plain years. More exotic `{{DATUM|...}}` calls or
  purely numeric partial dates may not be recognized -- in that case the
  affected rule is silently skipped for that article (no false positive, but
  also no check performed).
* The `nation` field is checked both as a bare ISO-3166-1 code (`ETH`, the
  documented form) and as one or more flag template calls (`{{JAM}}`, the
  more common real-world form, including multiple codes for athletes who
  changed nationality). Values that are neither (plain text like
  "Philippinen" or a wikilink) are flagged as low-severity format
  deviations, not as broken.
* The medal-year check reads the "Jahr Ort" argument of each
  `{{Medaillen Sommersport|...}}` call specifically (not the discipline text
  or link targets), to avoid picking up unrelated numbers that merely look
  like years.
* The medal-count cross-check compares individual `medaillen` entries
  against the declared totals in `Medaillenspiegel` per competition (e.g.
  "Olympische Spiele", "Weltmeisterschaften"), matching each side's category
  label after normalizing away naming differences like a `Leichtathletik-`
  prefix or `EM`/`WM` abbreviations (see `parse.normalize_competition_name`).
  A competition listed on only one side is *not* reported as a mismatch --
  that's expected, since `Medaillenspiegel` is conventionally restricted to
  senior top-tier competitions while `medaillen` may additionally list
  junior/youth/indoor/university-level results that were never meant to be
  in the summary table. Only competitions confirmed on both sides are
  compared, so a remaining count mismatch is a much stronger signal than
  before and is kept at high severity.
* The `disziplin` link check only applies to bare, unlinked values -- most
  articles with more than one discipline already hand-write their own
  wikilinks, which the template doesn't touch.

<p align="right">(<a href="#readme-top">back to top</a>)</p>




<!-- ROADMAP -->
## Roadmap

- [ ] Support additional Wikipedia infobox templates, not just `Infobox Leichtathlet`
- [ ] Support English-language template equivalents
- [ ] Cross-language consistency checks (same athlete, different Wikipedia editions)
- [ ] Rule presets/profiles, in addition to the low/medium/high/very-high classification
- [ ] Suggested fixes for detected inconsistencies, not just a description
- [x] Automated test suite (see [`tests/`](tests/) -- basic coverage, not exhaustive)
- [ ] Additional consistency rules

See the [open issues](https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues)
for a full list of proposed features (and known issues).

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTRIBUTING -->
## Contributing

Contributions are what make the open source community such an amazing place
to learn, inspire, and create. Any contributions you make are **greatly
appreciated**.

If you have a suggestion that would make this better, please fork the repo
and create a pull request. You can also simply open an issue with the tag
"enhancement". Each rule in [`rules.py`](rules.py) is a short, independent
function and can be extended or adjusted without affecting the others.
Don't forget to give the project a star! Thanks again!

1. Fork the Project
2. Create your Feature Branch (`git checkout -b feature/AmazingFeature`)
3. Commit your Changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the Branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

<p align="right">(<a href="#readme-top">back to top</a>)</p>

### Top contributors:

<a href="https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/graphs/contributors">
  <img src="https://contrib.rocks/image?repo=cmh-germany/WikipediaTemplateConsistencyChecker" alt="contrib.rocks image" />
</a>



<!-- LICENSE -->
## License

Distributed under the GNU General Public License v3.0. See [`LICENSE`](LICENSE) for more information.

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- CONTACT -->
## Contact

Project Link: [https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker](https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker)

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- ACKNOWLEDGMENTS -->
## Acknowledgments

* [Best-README-Template](https://github.com/othneildrew/Best-README-Template) -- this README is based on it
* [Claude](https://claude.com) (Anthropic) -- AI coding assistant used in developing this project, see [AI Assistance Disclaimer](#ai-assistance-disclaimer)
* [MediaWiki Action API](https://www.mediawiki.org/wiki/API:Main_page)
* [mwparserfromhell](https://github.com/earwig/mwparserfromhell)
* [Vorlage:Infobox Leichtathlet](https://de.wikipedia.org/wiki/Vorlage:Infobox_Leichtathlet) documentation

<p align="right">(<a href="#readme-top">back to top</a>)</p>



<!-- MARKDOWN LINKS & IMAGES -->
[contributors-shield]: https://img.shields.io/github/contributors/cmh-germany/WikipediaTemplateConsistencyChecker.svg?style=for-the-badge
[contributors-url]: https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/graphs/contributors
[forks-shield]: https://img.shields.io/github/forks/cmh-germany/WikipediaTemplateConsistencyChecker.svg?style=for-the-badge
[forks-url]: https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/network/members
[stars-shield]: https://img.shields.io/github/stars/cmh-germany/WikipediaTemplateConsistencyChecker.svg?style=for-the-badge
[stars-url]: https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/stargazers
[issues-shield]: https://img.shields.io/github/issues/cmh-germany/WikipediaTemplateConsistencyChecker.svg?style=for-the-badge
[issues-url]: https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/issues
[license-shield]: https://img.shields.io/github/license/cmh-germany/WikipediaTemplateConsistencyChecker.svg?style=for-the-badge
[license-url]: https://github.com/cmh-germany/WikipediaTemplateConsistencyChecker/blob/main/LICENSE
[python-shield]: https://img.shields.io/badge/python-3.11%2B-blue.svg?style=for-the-badge&logo=python&logoColor=white
[python-url]: https://www.python.org/
[python-badge]: https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white
[requests-badge]: https://img.shields.io/badge/Requests-000000?style=for-the-badge&logoColor=white
[requests-url]: https://requests.readthedocs.io/
[mwparserfromhell-badge]: https://img.shields.io/badge/mwparserfromhell-2E86AB?style=for-the-badge&logoColor=white
[mwparserfromhell-url]: https://github.com/earwig/mwparserfromhell
[mediawiki-badge]: https://img.shields.io/badge/MediaWiki%20API-000000?style=for-the-badge&logo=mediawiki&logoColor=white
[mediawiki-url]: https://www.mediawiki.org/wiki/API:Main_page
