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

## V0.1.1 继续实施

- [x] 为 GitHub API 增加限流、5xx 和暂态网络错误的有界重试。
- [x] 固化 AdmissionRequest Schema、授权策略和 Issue 表单边界。
- [x] 增加 GitHub Issue Webhook 的 HMAC 验签和安全 payload 适配器。
- [x] 接入 Issue 授权、收录事务、确定性 PR 计划和人工合并对账门槛。
- [x] 接入持久化 webhook 重放去重、按用户/仓库限速和预算控制。
- [x] 接入 observation-only 发布通道、路径检查和 Publisher 权限隔离。
- [x] 在固定 Fixture 和临时 Git 仓库组成的受控离线环境完成端到端验收并记录测试证据。
- [ ] 使用明确授权的真实 GitHub 测试仓库执行外部 Issue/PR 写入与保护规则验收。

实现边界：本轮不持有 GitHub 写令牌；真实 Provider 通过窄 `AdmissionPRClient` 接口另行接入，离线测试不得伪装成远端写入已完成。

## V0.1 本地阻塞修复

- [x] 重放投递使用 processing/completed/failed 状态，失败与超时可恢复，完成后不可重放。
- [x] 生产入口默认强制 durable replay、rate/budget Guard；无持久化控制仅能显式用于离线测试。
- [x] 合并对账只接受 Provider 返回的权威 PR 与审阅后项目内容，绑定事务身份并保持合并事实不可变。
- [x] 合并对账拒绝 bot actor，Publisher sink 必须接收基线摘要执行 CAS。
- [x] Publisher 对已有机器文件执行基线 SHA-256 CAS 和追加前缀校验，多产物先叠加校验再生成 README。
- [x] 观测批量先完整校验再写入，冲突不会留下批次前半段；补齐时间顺序、主仓库角色和 403 限流重试边界。
- [ ] 真实受控仓库 E2E、分支保护、签名和远端写入仍待显式授权与环境配置。

## V0.2 Change Intelligence

- [x] 定义版本化 `change-event.v1.json`，绑定前后观测证据、规则版本和稳定指纹。
- [x] 对已知 facts/metrics 执行确定性相邻比较；未知值不推断，活动指标使用显著性阈值。
- [x] 持久化变更事件并按指纹幂等，批次先校验再追加，避免重复分析提案。
- [x] 增加 `open-radar detect-changes` CLI 和运行清单校验。
- [x] 由确定性变更事件生成指纹幂等的 review-only `AnalysisProposal`，不落主分支提案目录。

## V0.2.1 研究、评分与历史报告

- [x] 冻结 `research-proposal.v1.json` 与 `research-evidence.v1.json`，区分 fact/inference/opinion 并绑定来源、输入版本和置信度。
- [x] 追加式 `research/evidence.jsonl` 幂等存储；研究证据不写回项目 YAML。
- [x] 实现 `data/contexts/<id>.yaml` 私人上下文契约与存储，评分不改变项目三维状态。
- [x] 实现版本化五维 RadarScore；缺维度时总分缺失，不补零或重分配权重。
- [x] 实现带 cutoff/input/score/Prompt 版本的 write-once 历史报告及 `reports/` 元数据。
- [x] 接入 `propose-analysis`、`score`、`report` CLI 和 `validate` 跨文件引用检查。
- [x] 离线测试覆盖提案、证据、上下文、评分、报告固定性和重复写入。

边界：本轮不接入 Provider `fetch_changes`、LLM 执行、关系图、远程 GitHub 写入或自动修改人工知识。

## V0.2.2 可用性硬化（本轮）

- [x] 生产模式禁止默认离线 PR fake；`ingest --write` 在缺少真实适配器时不得推进事务或消费 replay。
- [x] 运行清单按 `run_id` 幂等写入，校验命令默认只读，并覆盖重试边界。
- [x] YAML/UTF-8/IO 损坏输入统一转换为稳定 CLI 错误，不输出 traceback。
- [x] `score`、`detect-changes`、`propose-analysis` 对未知项目返回失败。
- [x] Wheel 包含 README 模板等运行时资源，安装环境可运行 CLI。
- [x] 权威合并事实约束与回归测试保持有效；远程私有化、分支保护、签名和真实 E2E 继续作为外部门禁，不在本轮直接操作。

验证证据（2026-09-05）：`unittest discover -s tests -q` 通过 125 项（跳过 1 项外部 API 测试）；`compileall` 与 `git diff --check` 通过；解包后的 0.2.2 wheel 通过完整测试并可从 `open_radar/templates/README.md.j2` 渲染 README。

## V0.2.3 多仓库采集（本轮）

- [x] 为项目的每个关联仓库独立计算采集到期时间，附属仓库不再静默缺少观测。
- [x] 单个仓库失败与其他仓库隔离，保留成功记录，并覆盖批量幂等回归测试。

边界：真实 GitHub 写入、受控仓库 E2E、分支保护和签名仍需外部授权。

## V0.2.4 项目级采集范围（本轮）

- [x] `collect --project-id` 只刷新指定项目，并对未知项目稳定失败。
- [x] 采集运行清单记录项目范围，保留全量采集的既有调度、幂等和错误隔离语义。
- [x] 项目级刷新只读取目标 YAML，不被无关项目的损坏文件阻断。

边界：真实 GitHub 写入、受控仓库 E2E、分支保护和签名仍需外部授权。

验证证据（2026-09-05）：`unittest discover -s tests -q` 通过 129 项（跳过 1 项外部 API 测试）；`compileall` 与 `git diff --check` 通过。

## V0.2.5 项目文件身份一致性（本轮）

- [x] `ProjectStore.load/all` 校验 YAML 内 `id` 必须与 `data/projects/<id>.yaml` 文件名一致。
- [x] 增加错名文件回归测试，避免定向读取与全量扫描得到不同项目身份。
- [x] 定向读取先校验项目 ID slug，拒绝路径越界输入。

边界：真实 GitHub 写入、受控仓库 E2E、分支保护和签名仍需外部授权。

验证证据（2026-09-06）：`unittest discover -s tests -q` 通过 131 项（跳过 1 项外部 API 测试）；`compileall` 与 `git diff --check` 通过。

## V0.3 关系图核心（本轮）

- [x] 冻结 `relation.v1.json` 与 `relation-types.v1.json`：项目/上下文类型化端点、关系类型及允许方向、理由和研究证据引用。
- [x] 增加受控 `relation-types` 词表，以及 `data/relations/<id>.yaml` 的原子、幂等写入与文件名/ID 一致性校验。
- [x] 规范化对称关系端点顺序，并拒绝自环和重复语义边。
- [x] 扩展 `validate`，校验关系端点、受控类型/方向组合，以及研究证据与端点的绑定。
- [x] 增加只读 `open-radar relations --project-id|--context-id` 查询，不写入运行清单，并对失效关系失败关闭。
- [x] 覆盖关系契约、存储幂等、对称查询、CLI 只读性、上下文文件身份和跨文件失败路径。

边界：不引入图数据库、自动关系推断、LLM、项目合并迁移或远程 GitHub 写入；关系仍是人工审核后提交的知识。

验证证据（2026-09-08）：`PYTHONPATH=src:/private/tmp/open-radar-test-deps python3 -m unittest discover -s tests -q` 通过 142 项（跳过 1 项外部 API 测试）；根目录 `validate`、`compileall` 与 `git diff --check` 通过；无依赖构建生成 `open_radar-0.3.0-py3-none-any.whl`，并在脱离源码目录的路径中确认包含 `open_radar.relations` 与版本 `0.3.0`。

## 收录：Apache Maka（本轮）

- [x] 核验公开 GitHub 身份、Apache-2.0 许可证、稳定仓库 ID 与受控 taxonomy。
- [x] 新增最小人工项目记录：`watching / undecided / weekly`，不填充未经研究的结论。
- [x] 通过只读 GitHub 采集写入首条机器观测，并生成临时 Catalog 预览。
- [x] 运行完整离线测试、全仓库校验和差异检查。

验证证据（2026-09-08）：GitHub 只读采集在一次短暂失败后重试成功，写入 `maka` 的首条观测；临时 Catalog 预览显示 Apache Maka、4,963 Stars 与 `2026-09-08T03:44:15Z`。`PYTHONPATH=src:/private/tmp/open-radar-test-deps python3 -m unittest discover -s tests -q` 通过 142 项（跳过 1 项外部 API 测试），`open-radar validate` 与 `git diff --check` 通过。

## 收录：DeepTutor（本轮）

- [x] 核验公开 GitHub 身份、Apache-2.0 许可证、稳定仓库 ID 与受控 taxonomy。
- [x] 新增最小人工项目记录：`watching / undecided / weekly`，不填充未经研究的结论。
- [x] 通过只读 GitHub 采集写入首条机器观测，并生成临时 Catalog 预览。
- [x] 运行完整离线测试、全仓库校验和差异检查。

验证证据（2026-09-10）：GitHub 只读采集写入 `deep-tutor` 的首条观测；临时 Catalog 预览显示 DeepTutor、39,144 Stars 与 `2026-09-10T03:48:10Z`。`PYTHONPATH=src:/private/tmp/open-radar-test-deps python3 -m unittest discover -s tests -q` 通过 142 项（跳过 1 项外部 API 测试），`open-radar validate` 与 `git diff --check` 通过。

## 公开 Catalog Pages（本轮）

- [x] 冻结仅公开派生字段：项目名、仓库 URL、分类、研究阶段、跟踪频率、Stars 与观测时间。
- [x] 实现独立 HTML 渲染器、可访问的 `404.html` 和纯输出 CLI。
- [x] 添加仅从 `main` 部署的 Pages 工作流，先运行测试和校验再上传 Artifact。
- [x] 覆盖 HTML 转义、字段白名单、输出覆盖保护与 CLI，并核验 Artifact 不含原始数据。
- [x] 提交、推送并启用 GitHub Pages 的 Actions 发布源。

验证证据（2026-09-10）：`PYTHONPATH=src:/private/tmp/open-radar-test-deps python3 -m unittest discover -s tests -q` 通过 148 项（跳过 1 项外部 API 测试）；`validate`、`compileall` 与 `git diff --check` 通过。临时 Artifact 只含 `index.html` 和 `404.html`，不含私有字段或源数据，并确认项目 Pages 路径的 404 返回链接为 `/open-radar/`。交叉复审已关闭权限拆分、字段白名单、输出目录封闭性与根路径回退问题。

部署证据（2026-09-10）：提交 `4803fee` 推送到 `main` 后，[Deploy public catalog](https://github.com/wuxiy/open-radar/actions/runs/34452947840) 的 build 与 deploy 均成功。已启用 GitHub Actions Pages 发布源；`https://wuxiy.github.io/open-radar/` 返回 200，未知路径返回自定义 `404.html` 与 404 状态。

## 收录：Ansible（本轮）

- [x] 核验公开 GitHub 身份、GPL-3.0 许可证、稳定仓库 ID 与受控 taxonomy。
- [x] 新增最小人工项目记录：`watching / undecided / weekly`，不填充未经研究的结论。
- [x] 通过只读 GitHub 采集写入首条机器观测，并生成临时 Catalog 预览。
- [x] 运行完整离线测试、全仓库校验和差异检查。

验证证据（2026-09-12）：GitHub 只读采集写入 `ansible` 的首条观测：GPL-3.0、70,661 Stars、24,336 Forks 与 `2026-09-12T06:33:41Z`。临时公开 Catalog 预览显示 Ansible、`automation`、每周跟踪与该观测时间。`PYTHONPATH=src:/private/tmp/open-radar-deps-20260912 python -m unittest discover -s tests -q` 通过 147 项（跳过 1 项外部 API 测试）；`validate`、`compileall` 与 `git diff --check` 通过。
