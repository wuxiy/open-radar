# Task Plan: V0.1.1 admission and publishing controls

## Goal

Implement durable replay deduplication, rate/budget controls, admission PR transactions and reconciliation, publisher isolation, and a controlled end-to-end test without requiring live GitHub credentials.

## Phases

- [x] Phase 1: Freeze seams and contracts
- [x] Phase 2: Implement replay ledger and rate/budget guard
- [x] Phase 3: Implement admission transaction, PR plan, and merge reconciliation
- [x] Phase 4: Implement observation-only publisher isolation
- [x] Phase 5: Add controlled offline E2E and update documentation
- [ ] Phase 6: Run full verification, code review, commit, and push

## Key Questions

1. Which state must be durable while keeping payloads and proposals out of the main branch?
2. How can PR and publisher behavior be tested deterministically without external writes?
3. What checks prevent replay, budget bypass, path escape, and forged verification objects?

## Decisions Made

- Use append-only JSONL ledgers with file locking and idempotent keys; store metadata only, not full webhook payloads.
- Keep GitHub side effects behind narrow protocols and provide deterministic local plans/fakes for offline tests.
- Require an observed human merge before final project persistence; reconciliation is idempotent.
- Allow observation-only publisher paths from an explicit allowlist and reject traversal, protected knowledge, and executable content.

## Errors Encountered

- 本地提交已创建为 `dd01b98`；推送到 `origin/main` 时远程连接分别以 HTTP/2 framing error 和无响应失败，需网络恢复后重试。

## Status

**Locally completed** - full verification, dual-axis review, and commit passed; remote push remains pending because the GitHub transport did not respond.
