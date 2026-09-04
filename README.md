# Open Radar

Open Radar keeps a small, Git-backed catalog of open-source projects and their public GitHub observations. Project metadata lives in reviewed YAML files. Machine observations append to monthly JSONL logs. A deterministic generator turns the current data into Markdown.

The repository contains the V0.1 local core plus offline-safe admission and publishing seams. It does not execute code from third-party repositories, call an LLM, or claim that a deterministic local PR plan is a live GitHub write.

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
  --merge-confirmed \
  --merge-commit-sha <observed-merge-sha> \
  --merged-by maintainer
```

The local CLI reads trusted users from the protected `OPEN_RADAR_TRUSTED_USERS` environment variable and applies durable rate/budget defaults (override with `OPEN_RADAR_ADMISSION_MAX_REQUESTS`, `OPEN_RADAR_ADMISSION_BUDGET_UNITS`, and `OPEN_RADAR_ADMISSION_WINDOW_SECONDS`). Request comments are untrusted context. Label authorization is available to the webhook payload adapter, not as a free-form CLI switch. `--merge-confirmed` now reconciles the prepared transaction with the supplied observed merge SHA and merger; the CLI remains a local/admin path and does not claim to query GitHub itself.

The Issue boundary is exposed as `GitHubWebhookVerifier` in [`src/open_radar/github_webhook.py`](src/open_radar/github_webhook.py). Configure it with the intake repository's numeric GitHub ID. It requires the raw request body, the `X-Hub-Signature-256` value, and an `issues` event; it rejects invalid signatures, cross-repository events, unsupported actions, and malformed Issue forms before creating an `AdmissionRequest`. Keep `OPEN_RADAR_WEBHOOK_SECRET` in the webhook worker's protected configuration. No webhook server or GitHub write operation is included in this local core.

For authorization, hand the verifier result to `AdmissionService.build_verified_event_candidate`; it carries the verified `sender`, `action`, and `label_name` into the policy without allowing callers to re-bind those fields. A labeled event is accepted only when the verified sender is trusted and the changed label is `approved-for-processing`. Pass `DurableReplayStore(root)` to the verifier to persist delivery claims in `data/runs/webhook-deliveries.jsonl`; a replay raises `WebhookReplayError` before a candidate is built.

Use `DurableRateBudgetController` and `AdmissionGuard` to enforce a per-actor, per-intake-repository window. Accepted reservations are durable and keyed by the Issue idempotency key, so a retry does not spend the budget twice. Denials are retained with a reason in `data/runs/admission-usage.jsonl`.

`AdmissionWorkflow.prepare()` turns a verified event into one durable transaction (`data/runs/admission-transactions/YYYY-MM.jsonl`), a deterministic `admission/...` branch, and a `PullRequestPlan` containing only the candidate project file. The journal records `pr_creating` before the provider call, and the `AdmissionPRClient` contract requires `find_by_branch` plus branch-keyed upsert, so a crash can recover a side effect without creating a second PR. `DeterministicAdmissionPRClient` is intentionally offline and produces a stable PR reference; a live GitHub client must implement the narrow protocol under separately authorized credentials. Use `reconcile_merge_from_provider()` with a read-only state adapter to verify the actual merged PR; it requires the recorded PR number/branch, a merge SHA, and a human merger identity before calling the project persistence gate. Repeated merge reconciliation is idempotent.

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
  runs/                  Compact manifests, replay, usage, and admission ledgers
  taxonomy/              Controlled categories and tags
schemas/                 Versioned JSON Schema contracts
src/open_radar/          Domain, provider, storage, controls, workflow, and CLI code
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

Observation publishing is constrained by `ObservationOnlyPublisher`. Its allowlist accepts monthly GitHub observation JSONL, compact run JSONL, and a README carrying the trusted generator marker. It validates domain/schema fields, records a SHA-256 content digest, and rejects project, taxonomy, schema, workflow, traversal, symlink, duplicate-path, malformed-JSONL, and oversized artifacts. The publisher creates a plan or sends it to a narrow sink; it never interprets external text or executes commands. Source signatures and protected-branch enforcement remain deployment-specific checks for the live adapter.

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

`tests/test_admission_pr.py` is the controlled end-to-end fixture: a signed Issue event is deduplicated and budget-checked, converted into one admission transaction/PR plan, reconciled after a human merge, collected, and passed through the observation-only publisher. It uses a temporary repository and deterministic fakes, so it performs no remote writes.

The GitHub Actions workflow runs the offline suite and repository validation with read-only contents permission.

## Current boundary

The local core covers identity resolution, admission candidates, persistent webhook replay deduplication, rate/budget enforcement, durable admission transactions, deterministic PR planning and human-merge reconciliation, project storage, scheduled metadata collection, append-only observations, observation-only publisher isolation, schema and taxonomy validation, and deterministic README generation.

The controlled E2E test is offline and uses deterministic provider/PR fakes. Live GitHub Issue-to-PR writes, protected-branch checks, provenance signatures, and a real authorized test repository still require explicit credentials and an integration run; they are not simulated as complete here.
