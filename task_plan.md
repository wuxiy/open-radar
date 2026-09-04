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
- [x] 由确定性变更事件生成指纹幂等的 review-only `AnalysisProposal`，不落主分支提案目录。

## V0.2.1 研究、评分与历史报告

- [x] 冻结研究提案/证据 Schema，研究记录区分事实、推断、观点并绑定来源与输入版本。
- [x] 接入追加式研究证据账本、私人 Context、五维 RadarScore 和缺维度缺失总分规则。
- [x] 接入 cutoff/input/score/Prompt 版本化的 write-once 历史报告。
- [x] 接入 `propose-analysis`、`score`、`report` CLI、Schema 与跨文件验证。
- [x] 运行离线全量测试并完成双轴代码审查后提交。

**状态**：实现、审查与离线验证完成；Provider `fetch_changes`、LLM、关系和远程写入仍在范围外。

**V0.2.1 首个分析切片完成** - 事件提案、证据、评分和历史报告已在离线环境验证；本轮不执行 LLM 或远程写入。
