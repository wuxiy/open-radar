# 架构评审与文档修订

日期：2026-09-03。

范围：根据本次 41 轮架构问答修订[架构文档](../open-radar-project-structure.md)，记录最终决策与 V0.1 验收标准。仅修改文档，不实现代码，不提交或推送，不更改仓库可见性、权限、密钥或 GitHub 工作流。

## 本次计划

- [x] 回顾原文、全部确认记录和仓库状态。
- [x] 确认项目没有 `tasks/lessons.md` 或 `rules/` 细则文件。
- [x] 将重复或被替代的决定归并为最终模型。
- [x] 重写架构文档，区分 V0.1、可选增强和后续能力。
- [x] 建立问答决策索引及未执行的产品验收清单。
- [x] 检查 Markdown 结构、链接、示例与决策覆盖。
- [x] 运行中文标点检查并复核改动范围。
- [x] 记录验证结果与复盘，交付文档。

## 决策归并

- 第 17 问最终采用 `research_stage / decision / tracking`，替代第 2 问的双字段建议。Issue 流程状态仍与项目状态分离。
- 第 16 问的分级采集保留，但频率由第 17 问的 `tracking` 控制。研究进度和使用决定只提供默认建议，不能暗中改写跟踪级别。
- 第 6 问明确保存规范化事实，不保留完整 API 响应。第 22 问的纠正写入当前月，历史月文件继续只读。
- 第 13、18 问共同形成一套版本化 Schema 契约，不重复创建两套模式。
- 第 39 问统一将私人结构化数据放在 `data/` 下；研究和报告保留独立目录，代码与数据逻辑隔离。
- 第 40 问限定 V0.1 范围。评分、变化分析、关系、上下文和历史报告的确认表示接受长期边界，不表示本次或首版必须实现。
- 第 37 问确认的是目标私有部署，不代表已经修改远端可见性。第 41 问确认的是未来产品验收，不代表已经运行通过。

## 问答决策索引

编号对应本次问答。重复和被后续替代的决定仍保留索引，正文只保留最终规则。

| 编号 | 已确认决定及最终处理 | 正文位置 | 阶段 |
|---|---|---|---|
| D01 | 人工知识、外部观测、派生视图分离 | [数据权威](../open-radar-project-structure.md#data-layers) | V0.1 |
| D02 | 研究进度与处置决定分开；字段方案由 D17 替代 | [三维状态](../open-radar-project-structure.md#state-taxonomy) | 已归并 |
| D03 | 逻辑项目为实体，GitHub 仓库是外部资源 | [项目身份](../open-radar-project-structure.md#project-model) | V0.1 |
| D04 | 有限容量、人工精选，衡量研究与工程决策价值 | [产品定位](../open-radar-project-structure.md#purpose) | V0.1 |
| D05 | Agent 只提案，不能覆盖已审核知识 | [所有权](../open-radar-project-structure.md#data-layers) | V0.1 |
| D06 | Git 自包含，按月追加规范化观测 | [观测日志](../open-radar-project-structure.md#observations) | V0.1 |
| D07 | 单主分类、多标签、扁平项目目录 | [分类](../open-radar-project-structure.md#state-taxonomy) | V0.1 |
| D08 | 评分与状态解耦，维度 0 到 10，总分 0 到 100 | [评分契约](../open-radar-project-structure.md#future-analysis) | 后续 |
| D09 | 确定性变化检测后再触发分析 | [变化分析](../open-radar-project-structure.md#future-analysis) | 后续 |
| D10 | 不可信仓库只读，不执行外部代码与指令 | [安全边界](../open-radar-project-structure.md#security) | V0.1，后续沿用 |
| D11 | 一候选、一事务、一收录 PR，重试复用 | [收录事务](../open-radar-project-structure.md#admission) | V0.1 |
| D12 | 主仓库展示、逐仓库观测、无隐式聚合 | [多仓库规则](../open-radar-project-structure.md#project-model) | V0.1 |
| D13 | Schema 先行、版本化迁移和 CI 校验 | [数据契约](../open-radar-project-structure.md#contracts) | V0.1，按功能扩展 |
| D14 | 受控 taxonomy，Agent 只能提议新增词条 | [分类词表](../open-radar-project-structure.md#state-taxonomy) | V0.1 |
| D15 | V0.1 仅收录关联公开 GitHub 仓库的项目 | [来源范围](../open-radar-project-structure.md#purpose) | V0.1 |
| D16 | 日、周、月和停止采集；与 D17 合并确定最终调度规则 | [采集策略](../open-radar-project-structure.md#collection) | V0.1 |
| D17 | 三维状态：research_stage、decision、tracking | [最终状态](../open-radar-project-structure.md#state-taxonomy) | V0.1 |
| D18 | 拒绝未知字段、强验证、显式迁移；与 D13 合并 | [数据契约](../open-radar-project-structure.md#contracts) | 已归并 |
| D19 | 研究结论绑定证据、版本、时间和置信度 | [研究契约](../open-radar-project-structure.md#future-analysis) | 可选增强及后续 |
| D20 | 机器数据可自动合并，认知内容需人工审核，混合 PR 不自动合并 | [双通道发布](../open-radar-project-structure.md#publishing) | V0.1 |
| D21 | 并行读取、单写入器、按批发布 | [并发模型](../open-radar-project-structure.md#collection) | V0.1 |
| D22 | 错误观测追加纠正，不篡改历史 | [纠正记录](../open-radar-project-structure.md#observations) | V0.1 |
| D23 | 收录不等待深度研究，两流程独立 | [收录与研究](../open-radar-project-structure.md#admission) | V0.1，后续沿用 |
| D24 | 仓库 ID 去重可自动化，逻辑项目合并需人工迁移 | [重复与合并](../open-radar-project-structure.md#project-model) | V0.1 基础约束 |
| D25 | 不可变可读 slug 为本地主键 | [本地身份](../open-radar-project-structure.md#project-model) | V0.1 |
| D26 | 受信用户或维护者授权后才执行，设置速率和预算限制 | [入口授权](../open-radar-project-structure.md#admission) | V0.1 |
| D27 | Collector、Analyzer、Publisher 权限与环境分离 | [执行隔离](../open-radar-project-structure.md#security) | V0.1，Analyzer 可选 |
| D28 | 历史报告发布后固定，当前视图可重建 | [生成与出版](../open-radar-project-structure.md#derived) | 报告后续实现 |
| D29 | 独立、受控、可验证的关系边 | [关系模型](../open-radar-project-structure.md#future-analysis) | 后续 |
| D30 | Relevance 按私人上下文评估，全局值由显式策略派生 | [上下文评分](../open-radar-project-structure.md#future-analysis) | 后续 |
| D31 | 自动 Scout 不属于 V0.1 | [范围](../open-radar-project-structure.md#mvp) | 后续 |
| D32 | 无 LLM 仍可基础收录，失败不编造结果 | [降级策略](../open-radar-project-structure.md#admission) | V0.1 |
| D33 | 长期保存紧凑运行清单，不保存完整日志 | [运行清单](../open-radar-project-structure.md#runs) | V0.1 |
| D34 | 未审核提案留在 PR，主分支不设长期 proposals 目录 | [提案保留](../open-radar-project-structure.md#runs) | V0.1 |
| D35 | 统一 Python 包和薄 CLI，复用领域规则 | [实现结构](../open-radar-project-structure.md#implementation) | V0.1 |
| D36 | 单一 GitHub Provider 和窄接口，不提前建插件框架 | [适配边界](../open-radar-project-structure.md#implementation) | V0.1 |
| D37 | 私有权威仓库，公开内容需筛选与脱敏 | [隐私边界](../open-radar-project-structure.md#purpose) | 目标部署，未操作远端 |
| D38 | README 和已发布报告进 Git，机器索引和缓存不提交 | [生成物策略](../open-radar-project-structure.md#derived) | V0.1，报告后续 |
| D39 | 同一私有仓库起步，代码与私人数据隔离 | [目录结构](../open-radar-project-structure.md#implementation) | V0.1 |
| D40 | 首版只完成授权 URL 到观测与 README 的完整流程 | [首版交付](../open-radar-project-structure.md#mvp) | V0.1 |
| D41 | 完整流程、幂等、恢复、权限和一致性是交付门槛 | [验收标准](../open-radar-project-structure.md#acceptance) | 产品实施后验证 |

## 原稿结构调整记录

- 原第 1、20、21 节的定位、价值与命名合并到产品定位，保留 Open Radar 名称，删除重复宣言。
- 原第 3 到 6 节的分类、状态、目录和 YAML 替换为最终分层模型及三维状态；旧指标混入项目文件的示例不再保留。
- 原第 7、10 节的收录与更新分别归入事务和调度，补充重试、纠正及发布边界。
- 原第 8、11、13、15、18、19 节的 Agent 职责、变化、报告、运行时、演进与自研项目关联按首版范围和后续契约合并，保留独有能力说明，不将它们列为首版工作。
- 原第 9 节的评分权重保留，统一分值尺度并移除与状态直接对应的阈值表。
- 原第 12、14、16、17 节的生成、技术栈、MVP 和不做范围归入对应章节。
- 数据示例改为明确标注的虚构项目，避免把占位仓库 ID、指标或评分写成外部事实。
- `README.md` 保持不变，本次不生成产品展示页，不创建目标目录树中的实现文件。

## V0.1 验收清单

下面均为未来产品验收，不属于本次文档检查，不因架构确认而勾选。

- [ ] 在明确授权的受控测试仓库完成 Issue → 收录 PR → 人工合并 → 观测 PR → README。
- [ ] 重复触发、并发重复候选、中断重试不产生重复项目、收录 PR 或观测。
- [ ] API 限流、超时、部分采集失败可恢复，不把未知值或失败写成零指标。
- [ ] 无 LLM 或 LLM 失败时可创建基础收录 PR；人工补齐必需字段后可合并。
- [ ] 机器数据通道无法绕过必需检查修改人工知识、配置、Schema 或工作流。
- [ ] 外部指令和脚本不被执行，伪造、过期或越界 Artifact 被拒绝。
- [ ] Schema、唯一性、主仓库数量、taxonomy 与跨文件引用验证通过。
- [ ] 月份关闭、迟到记录、重复观测和纠正链行为符合契约。
- [ ] 固定输入生成相同 README，CI 重新生成后无差异。
- [ ] 离线 Fixture 测试无需网络；真实 API、迁移身份和权限通过显式集成测试验证。

## 上线前配置与前提

具体数值和平台能力未在问答中验证，不虚构已支持容量或默认预算。

- [ ] 确认权威仓库的实际可见性；如需修改，另行授权。
- [ ] 选择活跃容量、采集窗口、速率限制、API 和 LLM 预算。
- [ ] 确认 Artifact 保留期及不含敏感内容的日志字段。
- [ ] 验证来源签名或证明机制、Bot 凭据、保护规则和自动合并条件。
- [ ] 确认测试仓库、凭据和允许的外部写入范围。
- [ ] 在编写功能前冻结相应 Schema，在实现时锁定并验证依赖版本。

## 文档验证与复盘

本次文档修订已完成，验证日期为 2026-09-03。架构原稿由 1245 行整理为 493 行，41 轮问答均有索引，重复和被替代的决定已归并。

| 检查 | 结果 |
|---|---|
| Markdown 结构 | 两份文档的代码块闭合、标题空行和显式锚点检查通过 |
| 本地链接 | 43 个相对链接及锚点全部可解析 |
| 数据示例 | YAML、JSONL 语法通过；项目与仓库引用、三维枚举、未知值语义符合正文 |
| 评分公式 | 权重合计为 1，满分输入归一化为 100 |
| 决策与验收状态 | D01 到 D41 各出现一次；10 项未来产品验收仍未勾选 |
| 中文标点 | 两份文档通过 write 技能的 `check-punctuation.sh --lang zh` 检查 |
| 空白与改动范围 | 两份未跟踪文档的 `git diff --no-index --check` 无空白错误输出；已跟踪文件无变化 |

结构和示例验证使用临时 Ruby 检查器；原稿副本与检查器均放在仓库外的临时目录，没有加入产品代码。对未跟踪文件使用 no-index 比较；存在内容差异时返回 1，检查以没有空白错误诊断为准。

架构文档 SHA-256：

```text
45dc66e64c3a55a9f1395b0be60841dd9ba6b15ffff50c938deccef7df9bf179
```

复盘：本次主要风险是把早期状态建议与最终模型混用，以及把长期契约误当成首版任务。正文以三维状态、显式采集级别和最小交付范围为准，同时说明当前 Schema、目录和命令均未实现。

当前仓库没有应用代码或产品测试框架。上述检查不等于正式 Schema 校验、真实 API 测试、权限验证或端到端验收。本次未调用 GitHub 或 LLM 服务，未修改 README、实现代码及远端设置，未提交或推送。

## V0.1 实施阶段

开始日期：2026-09-03。以下项目属于架构确认后的实施工作，不回勾上面的文档复盘清单。

- [x] 实现身份解析、项目与观测契约、追加式存储和确定性 README 生成。
- [x] 添加 CLI：`ingest`、`collect`、`generate`、`validate`。
- [x] 添加脱离网络的单元测试，以及显式启用的 API 集成测试入口。
- [x] 添加 JSON Schema、受控 taxonomy、示例 Fixture 和项目测试命令。
- [x] 按红、绿循环完成每个公共接口，再运行完整测试套件。
- [x] 使用 `code-review` 检查实现，修复发现的问题；已保留需后续集成的发布边界。
- [x] 复核工作区后提交并推送实现。
