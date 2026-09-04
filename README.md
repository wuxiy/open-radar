# Open Radar

Open Radar keeps a small, Git-backed catalog of open-source projects and their public GitHub observations. Project metadata lives in reviewed YAML files. Machine observations append to monthly JSONL logs. A deterministic generator turns the current data into Markdown.

The repository contains the V0.1 local core. It does not execute code from third-party repositories, call an LLM, or pretend that local writes are a GitHub Issue/PR approval flow.

## Install

Open Radar requires Python 3.11 or newer.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
```

The package declares PyYAML, jsonschema, Jinja2, and pytest as its runtime or development dependencies.

## CLI

Run commands from the repository root, or pass another checkout with `--root`.

Build an admission candidate without writing project data:

```bash
open-radar ingest \
  https://github.com/example-org/radar-demo \
  --primary-category devtools \
  --tags automation \
  --discovered-at 2026-09-03T00:00:00Z
```

Add `--write` only after an authorized request has passed review. The command resolves the GitHub repository, records its stable repository ID, checks the controlled taxonomy, and rejects duplicate repository identities.

```bash
export OPEN_RADAR_TRUSTED_USERS=maintainer

open-radar ingest \
  https://github.com/example-org/radar-demo \
  --write \
  --request-id issue-42 \
  --requester maintainer \
  --intake-repository-id 987654321 \
  --issue-number 42 \
  --merge-confirmed
```

The local CLI reads trusted users from the protected `OPEN_RADAR_TRUSTED_USERS` environment variable. Request comments are untrusted context. Label authorization is available to the webhook payload adapter, not as a free-form CLI switch. `--merge-confirmed` is a local gate; the real Issue → admission PR → human merge flow remains integration work.

The Issue boundary is exposed as `GitHubWebhookVerifier` in [`src/open_radar/github_webhook.py`](src/open_radar/github_webhook.py). Configure it with the intake repository's numeric GitHub ID. It requires the raw request body, the `X-Hub-Signature-256` value, and an `issues` event; it rejects invalid signatures, cross-repository events, unsupported actions, and malformed Issue forms before creating an `AdmissionRequest`. Keep `OPEN_RADAR_WEBHOOK_SECRET` in the webhook worker's protected configuration. No webhook server or GitHub write operation is included in this local core.

For authorization, hand the verifier result to `AdmissionService.build_verified_event_candidate`; it carries the verified `sender`, `action`, and `label_name` into the policy without allowing callers to re-bind those fields. A labeled event is accepted only when the verified sender is trusted and the changed label is `approved-for-processing`. Delivery IDs are required at this boundary; durable replay deduplication belongs to the pending admission transaction integration.

Collect due projects. The client sends read-only requests to the GitHub API. Set `GITHUB_TOKEN` for authenticated rate limits, or pass `--token` directly.

```bash
GITHUB_TOKEN=... open-radar collect \
  --scheduled-at 2026-09-03T00:00:00Z
```

The collector honors each project's `tracking` value, skips `off`, retries 429, 5xx, timeout, and connection errors with bounded backoff, keeps unknown values unknown, appends observations under `data/observations/github/YYYY-MM.jsonl`, and writes a run manifest under `data/runs/YYYY-MM.jsonl`.

Regenerate a Markdown view from the checked-in data:

```bash
open-radar generate --output README.generated.md
```

Use `--force` only when the destination is an intended generated file. The generator uses [`templates/README.md.j2`](templates/README.md.j2), stable sorting, and no current-time or network input.

Validate project YAML, observation logs, taxonomy, run manifests, correction chains, and cross-file repository references:

```bash
open-radar validate
```

## Repository layout

```text
data/
  observations/github/   Monthly append-only observation logs
  projects/              Human-maintained project YAML
  runs/                  Compact run manifests
  taxonomy/              Controlled categories and tags
schemas/                 Versioned JSON Schema contracts
src/open_radar/          Domain, provider, storage, workflow, and CLI code
templates/               Trusted README template
tests/                   Offline tests, fixtures, and opt-in API tests
```

Project state uses three independent fields:

| Field | Values |
| --- | --- |
| `research_stage` | `watching`, `researching`, `evaluated` |
| `decision` | `undecided`, `adopt`, `reference`, `reject` |
| `tracking` | `daily`, `weekly`, `monthly`, `off` |

Machine-owned metrics do not belong in project YAML. Corrections append a new record with `supersedes` and `correction_reason`; existing history is not rewritten.

## Test

Run the offline suite without network access:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

The real GitHub API test is opt-in:

```bash
OPEN_RADAR_RUN_GITHUB_INTEGRATION=1 \
GITHUB_TOKEN=... \
PYTHONPATH=src python -m unittest discover -s tests -v
```

The GitHub Actions workflow runs the offline suite and repository validation with read-only contents permission.

## Current boundary

The local core covers identity resolution, admission candidates, project storage, scheduled metadata collection, append-only observations, schema and taxonomy validation, and deterministic README generation.

The GitHub Issue-to-admission-PR flow, human merge gate, observation-only publishing PR, protected-branch automation, provenance signatures, persistent retry recovery, and multi-source providers remain integration work before the full architecture acceptance checklist can pass.
