# Task Plan: V0.1 local blocker closure

## Goal

修复 V0.1 本地验证暴露的阻塞：重放事务状态、权威合并、Publisher CAS/追加校验、批量写入原子性，并保持离线测试可重复。

## Phases

- [x] Phase 1: Freeze seams and contracts
- [x] Phase 2: Make replay claim/complete/fail transactional
- [x] Phase 3: Enforce provider-authoritative merge identity and terminal states
- [x] Phase 4: Add Publisher baseline CAS, append-only checks, and overlay validation
- [x] Phase 5: Make observation batch validation atomic and close related local invariants
- [x] Phase 6: Update tests/docs, run verification, dual-axis review, and commit

## Key Questions

1. Which state must be durable while keeping payloads and proposals out of the main branch?
2. How can PR and publisher behavior be tested deterministically without external writes?
3. What checks prevent replay, budget bypass, path escape, and forged verification objects?

## Decisions Made

- Use append-only JSONL ledgers with file locking and idempotent keys; store metadata only, not full webhook payloads.
- Keep GitHub side effects behind narrow protocols and provide deterministic local plans/fakes for offline tests.
- Require an observed human merge before final project persistence; reconciliation is idempotent.
- Allow observation-only publisher paths from an explicit allowlist and reject traversal, protected knowledge, and executable content.

## Status

**Complete** - local blocker fixes, documentation, tests, and dual-axis review are complete; real remote E2E remains explicitly out of scope.

## V0.2 Change Intelligence

- [x] 冻结 `change-event.v1.json`，绑定前后观测证据、规则版本和稳定指纹。
- [x] 实现确定性字段比较、未知值跳过和活动指标显著性阈值。
- [x] 实现指纹幂等的变更事件账本、批量预校验和 `detect-changes` CLI。
- [x] 接入 Publisher/validate 的 Schema 与项目仓库引用检查。
- [ ] Provider `fetch_changes`、分析提案、研究证据、评分/上下文和报告仍待后续迭代。

**V0.2 首个切片完成** - 事件检测与持久化已在离线环境验证；本轮不生成 LLM 分析提案，也不执行远程写入。
