# Notes: V0.1.1 continuation

## Existing contracts

- `AdmissionRequest.idempotency_key` is `github:{intake_repository_id}:issue-{issue_number}`.
- `VerifiedIssueEvent.is_verified()` is an object-bound guard backed by the webhook verifier registry.
- `AdmissionService.admit(..., merge_confirmed=True)` is the current local persistence gate.
- The architecture requires one candidate, one transaction, one admission PR, explicit human merge, observation-only machine publishing, and no long-lived proposals directory.

## Implementation boundary

Live GitHub writes are not authorized or configured in this workspace. The implementation will expose narrow provider protocols, generate deterministic PR plans, persist transaction state, and exercise the complete flow with controlled fakes. A live adapter can be added later behind the same seams.

## Evidence

- Durable replay claims are written to `data/runs/webhook-deliveries.jsonl`; malformed or rejected envelopes do not consume a delivery id.
- Accepted rate/budget reservations and denials are written to `data/runs/admission-usage.jsonl`; retries reuse a scoped idempotency key.
- Admission state is append-only in `data/runs/admission-transactions/YYYY-MM.jsonl` and validated by `admission-transaction.v1.json`.
- The controlled E2E fixture initializes a temporary Git repository and covers signed event, replay retry, budget reuse, deterministic PR, merge reconciliation, collection, README generation, and publisher path checks.
