# Open Radar

Open Radar keeps a small, Git-backed catalog of open-source projects and their public GitHub observations. Project metadata lives in reviewed YAML files. Machine observations append to monthly JSONL logs. A deterministic generator turns the current data into Markdown.

The repository contains the V0.1 local core, offline-safe admission and publishing, V0.2 Change Intelligence and research/reporting, V0.2.5 collection and identity hardening, and the V0.3 offline relationship core. It does not execute code from third-party repositories, call an LLM, or claim that a deterministic local PR plan is a live GitHub write.

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

Add `--write` only for an authorized request when you want the local transaction/PR plan recorded. The command resolves the GitHub repository, records its stable repository ID, checks the controlled taxonomy, and rejects duplicate repository identities. Production writes require an explicitly injected live admission PR adapter; without one, the command fails closed before creating a transaction or consuming replay state. It also fails closed before writing project YAML because a CLI flag cannot establish authoritative merge facts.

```bash
export OPEN_RADAR_TRUSTED_USERS=maintainer

open-radar ingest \
  https://github.com/example-org/radar-demo \
  --write \
  --request-id issue-42 \
  --requester maintainer \
  --intake-repository-id 987654321 \
  --issue-number 42
```

The local CLI reads trusted users from the protected `OPEN_RADAR_TRUSTED_USERS` environment variable and applies durable rate/budget defaults (override with `OPEN_RADAR_ADMISSION_MAX_REQUESTS`, `OPEN_RADAR_ADMISSION_BUDGET_UNITS`, and `OPEN_RADAR_ADMISSION_WINDOW_SECONDS`). Request comments are untrusted context. Label authorization is available to the webhook payload adapter, not as a free-form CLI switch. Merge reconciliation must use `AdmissionWorkflow.reconcile_merge_from_provider()` with a read-only provider that returns the recorded PR number, branch, merge SHA, human merger, and the reviewed project content; the CLI never self-asserts those facts.

The Issue boundary is exposed as `GitHubWebhookVerifier` in [`src/open_radar/github_webhook.py`](src/open_radar/github_webhook.py). Configure it with the intake repository's numeric GitHub ID. It requires the raw request body, the `X-Hub-Signature-256` value, and an `issues` event; it rejects invalid signatures, cross-repository events, unsupported actions, and malformed Issue forms before creating an `AdmissionRequest`. Keep `OPEN_RADAR_WEBHOOK_SECRET` in the webhook worker's protected configuration. No webhook server or GitHub write operation is included in this local core.

For authorization, hand the verifier result to `AdmissionService.build_verified_event_candidate`; it carries the verified `sender`, `action`, and `label_name` into the policy without allowing callers to re-bind those fields. A labeled event is accepted only when the verified sender is trusted and the changed label is `approved-for-processing`. The verifier requires `DurableReplayStore(root)` (or another durable adapter) and persists delivery state in `data/runs/webhook-deliveries.jsonl`; `allow_untracked_replay=True` is reserved for isolated signature tests. Claims move from `processing` to `completed` only after the admission transaction/PR side effect is durable; failed or stale processing claims can be retried, while a completed replay raises `WebhookReplayError`.

Use `DurableRateBudgetController` and `AdmissionGuard` to enforce a per-actor, per-intake-repository window; constructing a Guard without its durable controller is rejected unless an offline test explicitly opts into `allow_unbounded=True`. Accepted webhook reservations are durable and keyed by delivery ID, so only an actual replay is idempotent while distinct Issue lifecycle events still consume budget. Denials are retained with a reason in `data/runs/admission-usage.jsonl`.

`AdmissionWorkflow.prepare()` turns a verified event into one durable transaction (`data/runs/admission-transactions/YYYY-MM.jsonl`), a deterministic `admission/...` branch, and a `PullRequestPlan` containing only the candidate project file. The workflow requires both a durable replay store on the event and an `AdmissionGuard`; uncontrolled mode is available only when explicitly enabled by offline tests. The journal records `pr_creating` before the provider call, and the `AdmissionPRClient` contract requires `find_by_branch` plus branch-keyed upsert, so a crash can recover a side effect without creating a second PR. `DeterministicAdmissionPRClient` is intentionally offline and produces a stable PR reference; a live GitHub client must implement the narrow protocol under separately authorized credentials. Use `reconcile_merge_from_provider()` with a read-only state adapter to verify the actual merged PR; it requires the recorded PR number/branch, a merge SHA, a non-bot human merger identity, and the reviewed project content before calling the project persistence gate. Repeated merge reconciliation is idempotent.

Collect due projects. The client sends read-only requests to the GitHub API. Set `GITHUB_TOKEN` for authenticated rate limits, or pass `--token` directly.

```bash
GITHUB_TOKEN=... open-radar collect \
  --scheduled-at 2026-09-03T00:00:00Z
```

Pass `--project-id radar-demo` when manually refreshing one project; the run manifest records that scope. The collector honors each project's `tracking` value, skips `off`, schedules every associated repository independently, retries 429, 5xx, timeout, and connection errors with bounded backoff, keeps unknown values unknown, appends observations under `data/observations/github/YYYY-MM.jsonl`, and writes one idempotent run manifest per `run_id` under `data/runs/YYYY-MM.jsonl`.

Regenerate a Markdown view from the checked-in data:

```bash
open-radar generate --output README.generated.md
```

Use `--force` only when the destination is an intended generated file. The generator uses [`templates/README.md.j2`](templates/README.md.j2), stable sorting, and no current-time or network input.

Validate project YAML, observation logs, taxonomy, relationships, run manifests, correction chains, and cross-file references:

```bash
open-radar validate
```

`validate` is read-only by default. Add `--record-run` only when you explicitly want its compact run manifest persisted.

Derive deterministic Change Intelligence events from adjacent observation history:

```bash
open-radar detect-changes
```

The command compares only known `facts` and `metrics`, applies versioned thresholds (license and archive changes are high severity; material stars/forks changes are activity events), and appends evidence-bound events under `data/change-events/YYYY-MM.jsonl`. Unknown values do not produce a change. Re-running the command is idempotent by fingerprint; events never mutate project state or invoke an LLM.

Turn actionable change events into review-only analysis proposals. The default output is stdout; `--output` is an explicit PR artifact and never creates a long-lived `data/proposals` directory:

```bash
open-radar propose-analysis --output /tmp/open-radar-proposals.jsonl
```

After human review, append source-bound research records to `research/evidence.jsonl`. Each record distinguishes `fact`, `inference`, and `opinion`, carries a source and input version, and may provide a 0–10 rating for one score dimension. Private contexts are human-maintained under `data/contexts/`:

```bash
open-radar score \
  --project-id radar-demo \
  --context-id open-scope \
  --evaluated-at 2026-09-04T00:00:00Z
```

Scores use the versioned five-dimension RadarScore formula. Missing dimensions (including relevance without a selected context) leave the total blank; no zero-filling or weight reallocation occurs. Scores do not change project state.

`validate` resolves `source_type: observation` references against the observation ledger; URL and commit sources retain their immutable locator/SHA, while opaque snapshot IDs remain external evidence references.

Relationships are reviewed human knowledge in `data/relations/<id>.yaml`, not derived machine state. Each edge has typed `project` or `context` endpoints, a controlled type and permitted direction from `data/taxonomy/relation-types.yaml`, a reason, and one or more recorded research-evidence IDs that bind to every endpoint. Symmetric edges are stored once using canonical endpoint order. Query the immutable catalog view with either typed endpoint:

```bash
open-radar relations --project-id radar-demo
open-radar relations --context-id open-scope
```

The command is read-only and includes the queried endpoint plus its derived `other_endpoint`, so symmetric edges are visible from either side without duplicate storage. It fails closed when a matching edge has unknown endpoints, an unsupported type/direction pair, or evidence not bound to its endpoints. `validate` applies the same checks and also rejects duplicate semantic edges and relation IDs that do not match their filenames.

Freeze a historical report with an explicit cutoff and input version. Reports are write-once Markdown snapshots with matching JSON metadata; reusing an ID with changed content fails:

```bash
open-radar report \
  --cutoff-at 2026-09-04T00:00:00Z \
  --input-version observations:2026-09
```

Reports retain cutoff, input, score, and Prompt versions and do not silently recompute when new observations or contexts arrive. The V0.2.1 implementation is deterministic and offline-only; provider `fetch_changes`, LLM execution, and remote writes remain outside this slice.

## Repository layout

```text
  data/
    observations/github/   Monthly append-only observation logs
    change-events/         Deterministic, evidence-bound change events
    projects/              Human-maintained project YAML
    relations/             Human-maintained, evidence-bound relation YAML
    runs/                  Compact manifests, replay, usage, and admission ledgers
    taxonomy/              Controlled categories, tags, and relation types
    contexts/              Private scoring contexts
research/                 Source-bound human research evidence
reports/                  Write-once historical Markdown and metadata
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

Machine-owned metrics do not belong in project YAML. Project files are stored as `data/projects/<id>.yaml`; the storage layer validates slug IDs and rejects a YAML `id` that does not match its filename. Corrections append a new record with `supersedes` and `correction_reason`; existing history is not rewritten.

Observation publishing is constrained by `ObservationOnlyPublisher`. Its allowlist accepts monthly GitHub observation JSONL, compact run JSONL, deterministic change-event JSONL, and a generated README. Existing machine files require a per-artifact baseline SHA-256 and byte-for-byte append semantics; the plan also carries a stable idempotency key and baseline state digest for a sink-side CAS check. A `PublisherSink` must receive that digest and return a matching `PublisherCommitResult`; a legacy or CAS-rejecting sink fails closed. Historical month partitions are closed: late or future-dated observations are routed to the current writable month while retaining their original timestamps. Multiple artifacts are validated as one overlay before the README is regenerated, so a stale README or cross-file duplicate cannot pass. The publisher rejects project, taxonomy, schema, workflow, traversal, symlink, duplicate-path, malformed-JSONL, and oversized artifacts. It never interprets external text or executes commands. Source signatures and protected-branch enforcement remain deployment-specific checks for the live adapter.

Observation batches are validated in memory and committed through a staged atomic replacement of one writable month partition; a batch spanning multiple partitions is rejected before any write.

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

The validation workflow runs the offline suite and repository validation with read-only `contents` permission. The separate Pages workflow runs only from `main`: its build job has read-only `contents` and `pages` access, validates before rendering a bounded `index.html`/`404.html` Artifact, and the isolated deploy job alone receives `pages: write` and an OIDC token. It has no repository write permission. Enable the repository's Pages source as **GitHub Actions** before the first deployment.

Preview the same bounded artifact locally (the output directory must be new, empty, or contain only a previous Pages artifact when `--force` is supplied):

```bash
PYTHONPATH=src python -m open_radar.cli render-site \
  --root . --output-dir /tmp/open-radar-pages --base-path /open-radar/
```

## Current boundary

The local core covers identity resolution, admission candidates, persistent webhook replay deduplication, rate/budget enforcement, durable admission transactions, deterministic PR planning and human-merge reconciliation, project storage, scheduled metadata collection, append-only observations, deterministic Change Intelligence events, research/scoring/reporting, evidence-bound project/context relationships, observation-only publisher isolation, schema and taxonomy validation, and deterministic README generation.

The controlled E2E test is offline and uses deterministic provider/PR fakes. Live GitHub Issue-to-PR writes, protected-branch checks, provenance signatures, and a real authorized test repository still require explicit credentials and an integration run; they are not simulated as complete here.

This GitHub repository is public, and Pages is public too. The static-artifact allowlist prevents accidental publication through the Pages deployment, but it cannot make checked-in source data private; authoritative private notes must be kept outside this repository.
