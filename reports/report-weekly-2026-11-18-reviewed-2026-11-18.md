# Open Radar 开源项目周报：2026-11-12 至 2026-11-18（W47 选期）

审核截止：2026-11-18 23:50（UTC+08:00；UTC 15:50）。此为对原周报的回溯审核与入库提案。日期范围跨 ISO 周边界，不表示完整 ISO 第 47 周。固定版本文档、许可证及官方发布/提交已核对，未运行上游程序、未做性能复测，也没有伪造历史机器观测。

## Top Picks

- **LoopForge**：P0 research，面向可控的 Agent 研发交付和状态管理。
- **Open Code Review**：P0 adopt-candidate，先以 Java 代码变更评估真实收益。
- **Plannotator**：P0 adopt-candidate，优先改进人工审核交互。
- **PageIndex**：P0 research，补充结构化文档检索能力。

## 候选与可核验信号

| 项目 | 建议 / 优先级 | 官方信号（UTC） | 源码许可 |
| --- | --- | --- | --- |
| [LoopForge](../data/projects/loopforge.yaml) | research / P0 | [2026-11-17 v0.4.0](https://github.com/Tencent/LoopForge/releases/tag/v0.4.0) | [MIT 主体，第三方组件按各自许可](https://github.com/Tencent/LoopForge/blob/f8dcd1eb315c4604c4cfe7db2432ddeaaa3fc7e5/LICENSE) |
| [Open Code Review](../data/projects/open-code-review.yaml) | adopt-candidate / P0 | [2026-11-18 v1.13.12](https://github.com/alibaba/open-code-review/releases/tag/v1.13.12) | [Apache-2.0](https://github.com/alibaba/open-code-review/blob/5d6552adafb6cbedfb54793214b777cd134dc97b/LICENSE) |
| [Plannotator](../data/projects/plannotator.yaml) | adopt-candidate / P0 | [2026-11-18 v0.29.0](https://github.com/backnotprop/plannotator/releases/tag/v0.29.0) | [MIT OR Apache-2.0（package.json；两个许可文件）](https://github.com/backnotprop/plannotator/blob/d478ccf9c0b2b9a0ede1f68dc15c5485e80fb71d/LICENSE-MIT) |
| [PageIndex](../data/projects/pageindex.yaml) | research / P0 | [2026-11-17 v0.7.1](https://github.com/VectifyAI/PageIndex/releases/tag/v0.7.1) | [MIT（源码）](https://github.com/VectifyAI/PageIndex/blob/340b8535a219ea448c4c0f5bdd354761449b55b3/LICENSE) |
| [Astryx](../data/projects/astryx.yaml) | research / P1 | [2026-11-14 v0.7.16](https://github.com/meta/astryx/releases/tag/v0.7.16) | [MIT](https://github.com/meta/astryx/blob/af049a4e6ddd6abfb8dfcea1a3d29ec177b08acf/LICENSE) |
| [FineType](../data/projects/finetype.yaml) | research / P1 | [2026-11-18 DuckDB 只读加载修复（提交）](https://github.com/meridian-online/finetype/commit/f377ba2f7fbf37deacc42705df4506d32e2c2108) | [MIT](https://github.com/meridian-online/finetype/blob/f377ba2f7fbf37deacc42705df4506d32e2c2108/LICENSE) |
| [E2E](../data/projects/e2e.yaml) | research / P1 | [2026-11-13 e2e@0.23.1](https://github.com/e2e-inc/e2e/releases/tag/e2e%400.23.1) | [Apache-2.0](https://github.com/e2e-inc/e2e/blob/847a09e6dbd39e09c8941ddcc903003c61412d81/LICENSE) |
| [Arcane](../data/projects/arcane.yaml) | watch / P1 | [2026-11-15 v3.0.1](https://github.com/getarcaneapp/arcane/releases/tag/v3.0.1) | [BSD-3-Clause](https://github.com/getarcaneapp/arcane/blob/0f8f283645e812a867fec6d7291dd69ee44522b3/LICENSE) |

Plannotator 另有 [Apache 许可](https://github.com/backnotprop/plannotator/blob/d478ccf9c0b2b9a0ede1f68dc15c5485e80fb71d/LICENSE-APACHE)，[package.json](https://github.com/backnotprop/plannotator/blob/d478ccf9c0b2b9a0ede1f68dc15c5485e80fb71d/package.json) 标注双许可。LoopForge GitHub 元数据返回 NOASSERTION，固定 LICENSE 明确主体 MIT，附带第三方归属条款，故不把 NOASSERTION 当成许可证缺失。许可证核查不涵盖全部依赖和商用服务条款。

## 第三方热度（非机器观测）

[Trend 2026-11-17 快照](https://trend.ondo.sh/github/2026-11-17/en.html) 记录 Open Code Review 日榜 #3、LoopForge #4、Arcane #6，Astryx 七日增 7,775 Star；[GitStock 2026-11-18 周榜](https://gitstock.org/trending/weekly/2026-11-18) 记录 Plannotator 周榜 #2、周增 2,926 Star，Astryx 周榜 #4。不同抓取时刻的排名可能不同（例如 [Trends MCP 11/17](https://www.trendsmcp.ai/trending/github-trending-november-17-2026)），因此仅引用特定快照，不宣称全天统一排名。原文其他热度数字和综合 Momentum Score 不作为正式事实入账；不生成 Star 增量观测或 Radar Score。

## 研究价值与待验证问题

### LoopForge — research / P0

仓库：[Tencent/LoopForge](https://github.com/Tencent/LoopForge)；[固定 README](https://github.com/Tencent/LoopForge/blob/f8dcd1eb315c4604c4cfe7db2432ddeaaa3fc7e5/README.md)。

**解决问题与架构（文档事实）：** 自托管 Coding Agent 工作区与交付流程；README 描述可重复 SOP、沙箱工作区、脚本和人工确认，支持 CodeBuddy、Codex 与 Claude Code。

**验证计划（意见）：** 对比现有 Agent 编排器：用非生产任务验证审批、失败恢复、状态持久化与交付证据。

**成熟度与风险：** 检查审批绕过、执行隔离、并发任务以及节点环境变量中的凭证暴露；不以厂商自述证明安全。

### Open Code Review — adopt-candidate / P0

仓库：[alibaba/open-code-review](https://github.com/alibaba/open-code-review)；[固定 README](https://github.com/alibaba/open-code-review/blob/5d6552adafb6cbedfb54793214b777cd134dc97b/README.md)。

**解决问题与架构（文档事实）：** 确定性评审流水线结合 LLM Agent，面向 Git 变更提供行级评论与多语言规则。

**验证计划（意见）：** 用 20 个去敏 Java 历史变更评估检出、误报、定位准确性、成本与模型外发边界。

**成熟度与风险：** 内部应用规模为厂商自述；不能替代 SAST、单测及人工评审。只用批准的模型与测试源码。

### Plannotator — adopt-candidate / P0

仓库：[backnotprop/plannotator](https://github.com/backnotprop/plannotator)；[固定 README](https://github.com/backnotprop/plannotator/blob/d478ccf9c0b2b9a0ede1f68dc15c5485e80fb71d/README.md)。

**解决问题与架构（文档事实）：** 面向 Agent 的计划、文档、交互产物与代码 diff 审阅界面，可将标注反馈给 Agent。

**验证计划（意见）：** 分别在 Codex 和 Claude Code 的非敏感任务中验证 Plan → Review → Execute，以及反馈是否绑定被审版本。

**成熟度与风险：** 核查分享链接、权限、数据外发与反馈版本绑定；有审批 UI 不等于有强制执行门禁。

### PageIndex — research / P0

仓库：[VectifyAI/PageIndex](https://github.com/VectifyAI/PageIndex)；[固定 README](https://github.com/VectifyAI/PageIndex/blob/340b8535a219ea448c4c0f5bdd354761449b55b3/README.md)。

**解决问题与架构（文档事实）：** 面向长文档的树状索引及推理式检索；README 区分 SDK 本地与云模式。

**验证计划（意见）：** 用 10 份公开或脱敏长文档与 30 个有标准出处的问题，对照 WeKnora 等向量检索的定位、引用准确率、延迟与成本。

**成熟度与风险：** 本地模式仍可能依赖外部模型 API；树路由可能遗漏章节，作者性能宣称未独立复现。

### Astryx — research / P1

仓库：[meta/astryx](https://github.com/meta/astryx)；[固定 README](https://github.com/meta/astryx/blob/af049a4e6ddd6abfb8dfcea1a3d29ec177b08acf/README.md)。

**解决问题与架构（文档事实）：** 面向人和 Agent 的 React 19+ / StyleX 设计系统，README 列出组件、主题、CLI 与 Storybook，并明确为 Beta。

**验证计划（意见）：** 用少量组件验证设计 Token、主题、无障碍与 Agent 生成一致性；对照 shadcn/ui，不以迁移为前提。

**成熟度与风险：** Beta 接口可能变化；需要验证现有前端及小程序适配，内部应用规模不代表外部生态成熟。

### FineType — research / P1

仓库：[meridian-online/finetype](https://github.com/meridian-online/finetype)；[固定 README](https://github.com/meridian-online/finetype/blob/f377ba2f7fbf37deacc42705df4506d32e2c2108/README.md)。

**解决问题与架构（文档事实）：** Rust 语义类型推断与转换契约，提供 DuckDB 扩展，支持列级画像及通过 arcform 接入 MCP；README 标记 Early Release。

**验证计划（意见）：** 测试脱敏医疗字段的列级类型、误分类、空值和不可转换异常；医学编码判断另用标准字典。

**成熟度与风险：** 医疗类型、中文地区格式和转换保真度需独立验证；本周未确认正式 Release，不宣称高增长。

### E2E — research / P1

仓库：[e2e-inc/e2e](https://github.com/e2e-inc/e2e)；[固定 README](https://github.com/e2e-inc/e2e/blob/847a09e6dbd39e09c8941ddcc903003c61412d81/README.md)。

**解决问题与架构（文档事实）：** Web 与移动端测试框架：自然语言 Agent 操作可与 locator 和确定性断言混用；README 描述验证后录制、重放动作。

**验证计划（意见）：** 在测试应用验证执行器、重复执行、UI 变化、失败证据及与 Playwright 的能力差异。

**成熟度与风险：** 重放不保证等价行为；验证开源与商业边界、模型调用成本、测试数据外发和平台支持。

### Arcane — watch / P1

仓库：[getarcaneapp/arcane](https://github.com/getarcaneapp/arcane)；[固定 README](https://github.com/getarcaneapp/arcane/blob/0f8f283645e812a867fec6d7291dd69ee44522b3/README.md)。

**解决问题与架构（文档事实）：** 现代 Docker 管理 Web 界面，README 指明 main 为 v3，2.x 有独立维护分支。

**验证计划（意见）：** 对照现有 NAS 容器管理：Compose、访问控制、备份恢复、操作审计与日常管理成本。

**成熟度与风险：** v3 刚发布；高权限 Docker Socket 可能等价于宿主机控制。先在隔离环境测试，不开放公网。


## 跨项目工程洞察

1. **Agentic SDLC**：将任务编排、执行运行时、质量门禁和人工决策分解成职责独立的层。LoopForge、Open Code Review 与 Plannotator 可作为组合研究对象，不假定原生互通。
2. **知识与数据**：树状检索与向量检索是互补方案；语义类型推断与标准字典、人工规则需结合。对于医疗指南和数据治理，仅使用公开/脱敏材料，执行安全门禁，不能由模型替代专业决策。
3. **Agent-ready UI**：组件目录、Design Token、可访问性和组件文档应共同约束生成结果，不以迁移现有框架为前提。
4. **测试与运维**：Agent 探索与确定性断言并存；运行时资源权限独立于 UI。容器管理需明确 Docker Socket 信任边界。
5. **供应链**：[SecurityWeek 11/18 报道](https://www.securityweek.com/microsoft-agent-framework-releases-poisoned-with-credential-stealer/) 提及 PyPI agent-framework 恶意发行事件。作为外部报告保留，未独立验证攻击细节；不据此宣称本批候选受影响。任何 Agent 插件试用前应检查许可证、发布来源、依赖、安装脚本、权限、密钥与出网；未知项保持 unknown。当前 Schema 不新增安全字段，相关检查保留为审核建议。

## 入库边界

八个项目均使用现有 category/tag，不增加词表；研究与试用候选映射为 `research_stage: researching`，观察候选为 `watching`；均为 `decision: undecided`、`tracking: weekly`。P0/P1 和 adopt-candidate 是报告中的建议，不是新状态或已采用事实。

数据集不包含私有项目上下文、内网地址、医疗原始数据、个人资料或凭证。事实与建议分别追加至 [研究证据账本](../research/evidence.jsonl)。本期无独立医疗科技 / 可观测性新候选，不凑数。已有项目或未选定候选不重复入库，未生成观测或分数。

配套 JSON 遵循 ReportSnapshot 契约。cutoff_at 是审核截止而非回填的历史采样时间；input_digest 对本次 8 个项目与 24 条证据计算：分别依 id / evidence_id 排序，键为 projects / evidence，JSON UTF-8、ensure_ascii=False、sort_keys=True、separators=(',', ':')，SHA-256。后续修订另发版本，不覆盖旧报告。
