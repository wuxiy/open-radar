<div align="center">

# Open Radar

**Turn reviewed open-source knowledge and public GitHub signals into a technology radar you can trust.**

<img src="assets/banner.webp" alt="Open Radar — a Git-backed technology radar" width="100%">

[![CI](https://github.com/wuxiy/open-radar/actions/workflows/validate.yml/badge.svg)](https://github.com/wuxiy/open-radar/actions/workflows/validate.yml)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-1f1f1f?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-b08d57.svg)](./LICENSE)

[Public catalog](https://wuxiy.github.io/open-radar/) · [Architecture](./open-radar-project-structure.md) · [Catalog design](./docs/public-catalog-design.md)

</div>

---

## What is Open Radar?

Open Radar is a small, Git-backed catalog for evaluating open-source projects over time. Human-reviewed knowledge lives in readable YAML; public GitHub observations are appended to monthly JSONL ledgers; deterministic commands turn both into a catalog, change events, scores, and historical reports.

It is built for maintainers and technical leaders who need a durable answer to “should we adopt, study, or ignore this project?”—without handing that decision to a black box.

## Why it exists

Bookmarks and star counts capture attention, not judgment. Open Radar keeps the parts that matter separate and reviewable:

- **Curate:** people own project identity, classification, research, and decisions.
- **Observe:** machines collect public facts without overwriting reviewed knowledge.
- **Decide:** deterministic analysis preserves the evidence, inputs, and version behind every result.

The repository never executes code from tracked projects. Unknown values stay unknown, external text is treated as untrusted input, and live GitHub writes require a separately authorized adapter.

## Quick start

Open Radar requires Python 3.11 or newer.

```bash
git clone https://github.com/wuxiy/open-radar.git
cd open-radar

python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"

open-radar validate
```

Render the same public-safe catalog deployed to GitHub Pages:

```bash
open-radar render-site \
  --output-dir /tmp/open-radar-pages \
  --base-path /open-radar/
```

The output contains only `index.html` and `404.html`. The renderer exposes a strict allowlist of public fields and loads no remote scripts, fonts, analytics, or images.

## Core workflows

### Add a candidate

Build and validate an admission candidate without changing project data:

```bash
open-radar ingest https://github.com/example-org/radar-demo \
  --primary-category devtools \
  --tags automation \
  --discovered-at 2026-09-03T00:00:00Z
```

`ingest --write` is intentionally fail-closed unless the caller supplies an authorized live PR adapter. A CLI flag cannot assert that a human reviewed or merged a project.

### Collect and detect change

```bash
GITHUB_TOKEN=... open-radar collect \
  --scheduled-at 2026-09-03T00:00:00Z

open-radar detect-changes
open-radar propose-analysis --output /tmp/open-radar-proposals.jsonl
```

Collection follows each repository's tracking cadence, retries bounded transient failures, and keeps unrelated repositories moving when one fails. Change events are evidence-bound, versioned, and idempotent.

### Score, relate, and report

```bash
open-radar score \
  --project-id radar-demo \
  --context-id open-scope \
  --evaluated-at 2026-09-04T00:00:00Z

open-radar relations --project-id radar-demo

open-radar report \
  --cutoff-at 2026-09-04T00:00:00Z \
  --input-version observations:2026-09
```

Scores never silently fill missing dimensions with zero. Relationships require reviewed evidence, and reports are write-once snapshots tied to an explicit cutoff and input version.

## How the data stays trustworthy

| Layer | Owner | Storage | Rule |
| --- | --- | --- | --- |
| Reviewed knowledge | Human | `data/projects/`, `data/relations/`, `research/` | Changes arrive through review |
| Public observations | Machine | `data/observations/`, `data/change-events/` | Append-only and evidence-bound |
| Derived views | Deterministic commands | Catalog and `reports/` | Rebuildable or write-once |

Project state uses three independent fields so research progress never silently becomes an adoption decision:

| Field | Values |
| --- | --- |
| `research_stage` | `watching`, `researching`, `evaluated` |
| `decision` | `undecided`, `adopt`, `reference`, `reject` |
| `tracking` | `daily`, `weekly`, `monthly`, `off` |

Machine metrics never belong in project YAML. Corrections append a new record that names the observation it supersedes; published history is not rewritten.

## Repository map

```text
data/
  projects/              Reviewed project records
  observations/github/   Monthly append-only observations
  change-events/         Deterministic change events
  relations/             Evidence-bound relationships
  taxonomy/              Controlled categories, tags, and relation types
  runs/                  Compact workflow and admission ledgers
research/                 Source-bound research evidence
reports/                  Write-once historical snapshots
schemas/                  Versioned JSON Schema contracts
src/open_radar/            Domain logic, workflows, providers, and CLI
templates/                 Trusted deterministic README template
tests/                     Offline suite and opt-in integration test
```

See the [architecture document](./open-radar-project-structure.md) for the complete contracts, security boundaries, and version roadmap.

## Development

Run the offline suite and repository validation:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
PYTHONPATH=src python -m open_radar.cli validate
```

The real GitHub API test is opt-in and read-only:

```bash
OPEN_RADAR_RUN_GITHUB_INTEGRATION=1 \
GITHUB_TOKEN=... \
PYTHONPATH=src python -m unittest discover -s tests -v
```

The controlled end-to-end fixture uses deterministic providers and a temporary repository. It performs no remote writes.

## Current boundary

The local core covers reviewed admission plans, replay and budget controls, scheduled GitHub metadata collection, append-only observations, deterministic change intelligence, research, scoring, reports, relationships, public catalog rendering, and schema validation.

It does **not** include a live GitHub Issue-to-PR writer, protected-branch verification, provenance signing, or LLM execution. Those capabilities need explicit credentials and deployment-specific controls; the offline fixtures do not pretend they are complete.

This repository and its Pages site are public. Private contexts, notes, or authoritative internal knowledge must live outside this checkout and must never be supplied to the public renderer.

## License

[MIT](./LICENSE) © 2026 [wuxiy](https://github.com/wuxiy)
