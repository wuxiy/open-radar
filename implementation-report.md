# V0.1.1 实施报告

## 已交付

- Webhook delivery 持久化去重与跨进程文件锁。
- 按操作者/接收仓库的速率与预算预留，带幂等重试和拒绝原因。
- 收录事务 Schema、`pr_creating` 恢复状态、分支查找/幂等 PR 客户端协议。
- 人工合并对账；支持从事务恢复，并保留已合并 PR 中经过校验的项目修改。
- Observation-only Publisher：月度路径白名单、域对象/运行清单校验、纠正目标检查、README 确定性重建和 SHA-256 摘要。
- 本地阻塞修复：重放 processing/completed/failed 事务与 claim fencing、Provider 权威合并和 bot gate、Publisher 基线 CAS/追加与统一 overlay、带回执校验的 sink CAS、单可写分区批量原子提交。
- 临时 Git 仓库离线 E2E Fixture，覆盖 Issue、PR、合并、采集、README 和 Publisher。

## 验证

`PYTHONPATH=src python -m unittest discover -s tests`：84 个测试通过，1 个真实 GitHub API 测试按默认策略跳过；`compileall`、`git diff --check` 和静态审计通过。

## 外部集成边界

当前没有使用 GitHub 写令牌。真实 Issue/PR 写入、分支保护、来源签名和受控远程仓库验收需通过 `AdmissionPRClient`、`PullRequestStateProvider`、`PublisherSink` 的显式集成适配器和授权凭据完成，离线 E2E 不替代该证据。
