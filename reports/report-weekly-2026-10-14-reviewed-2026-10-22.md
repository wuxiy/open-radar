# Open Radar 开源项目周报：2026-10-08 至 2026-10-14

审核日期：2026-10-22（北京时间）。这是对原周报候选的回溯审核，能力说明按下列固定版本复核；未运行这些项目的程序，也未复现性能基准。新收录与机器观测均记在审核日，不能用来还原原报告时点的 Star、成熟度或榜单排名。

本期保留 7 个重点候选与 1 个医学影像研究候选。优先研究 DigUp 的多模态检索、Helix Foundry 的快照与查询证据，以及 iPhone Use 的真机操作。以下优先级是研究建议，尚无采用决定。

## 候选与可核验信号

| 项目 | 分类 | 观察期内的信号 | 研究阶段 | 源码许可证 |
| --- | --- | --- | --- | --- |
| [iPhone Use](../data/projects/iphone-use.yaml) | automation | [10/9 v0.3.8](https://github.com/zhongerxin/iPhone-use/releases/tag/v0.3.8)、[10/13 v0.3.12](https://github.com/zhongerxin/iPhone-use/releases/tag/v0.3.12) | researching | [MIT](https://github.com/zhongerxin/iPhone-use/blob/80006885df81531ce7a874b3b0df65980e25e59b/LICENSE) |
| [DigUp](../data/projects/digup.yaml) | ai | 北京时间 [10/10 v0.6.0](https://github.com/ARahim3/DigUp/releases/tag/v0.6.0)、[10/13 v0.6.1](https://github.com/ARahim3/DigUp/releases/tag/v0.6.1) | researching | [MIT](https://github.com/ARahim3/DigUp/blob/92b5a631e1d279ac92ff31c9affd73d5c122d296/LICENSE) |
| [Helix Foundry](../data/projects/helix-foundry.yaml) | data | [10/12 大数据库导入改进](https://github.com/HelixDB/helix-foundry/commit/9780d74c85631a36bfdc545e105ffd7786477e63)，属于提交 | researching | [Apache-2.0](https://github.com/HelixDB/helix-foundry/blob/00d7927d7c08e16c58316e006959f052427e7fa1/LICENSE) |
| [FSearch](../data/projects/fsearch.yaml) | devtools | 北京时间 [10/12 v0.2.0](https://github.com/noahdunnagan/fsearch/releases/tag/v0.2.0)、[10/13 v0.2.1](https://github.com/noahdunnagan/fsearch/releases/tag/v0.2.1) | researching | [MIT](https://github.com/noahdunnagan/fsearch/blob/88e63fdf850cf7749deae8198b187accd21f8ba5/LICENSE) |
| [xtool](../data/projects/xtool.yaml) | devtools | [10/14 输入兼容性修复](https://github.com/xtool-org/xtool/commit/b50173f7b1f7d13297b9c8229079038d47a2bb1d)，历史榜单未证实 | watching | [MIT](https://github.com/xtool-org/xtool/blob/aa6ba75e7df759a84560885a86822dd119da8c55/LICENSE.md) |
| [OTel Collector Contrib](../data/projects/opentelemetry-collector-contrib.yaml) | observability | [10/13 官方文章](https://opentelemetry.io/blog/2026/hostmetrics-process-scraper-rc/)，并非当周发布新版本 | researching | [Apache-2.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/blob/982f20b8a8e8a2569fab3e27cf8b008e8a5080c1/LICENSE) |
| [DataFusion Python](../data/projects/datafusion-python.yaml) | data | [发行目录标注 55.0.0、10/12](https://release-catalog.apache.org/datafusion-python/index.html)，保留目录证据限制 | watching | [Apache-2.0](https://github.com/apache/datafusion-python/blob/878e5d3b8d373bca19671af43e49dfb1890f8da2/LICENSE.txt) |
| [MedMCP](../data/projects/medmcp.yaml) | ai | 既有项目专项研究；[10/13 0.4.2 提交](https://github.com/medmcp/medmcp/commit/7e353ce778708590bb27d2067ec575ad332e4856)，并非新项目首发 | researching | [Apache-2.0](https://github.com/medmcp/medmcp/blob/7e353ce778708590bb27d2067ec575ad332e4856/LICENSE) |

所有项目均为 `decision: undecided`、`tracking: weekly`。原文的 `research / watch / adopt-candidate` 分别转为研究阶段或验证建议，不能直接当作正式采用。源码许可与临床使用许可分别核查。

## 项目价值与待验证问题

### iPhone Use

[固定版本 README](https://github.com/zhongerxin/iPhone-use/blob/80006885df81531ce7a874b3b0df65980e25e59b/README.md) 描述通过本地 MCP、WebDriverAgent 和 USB 操作真实 iPhone，包括读控件树、点击、滑动与文本输入。环境依赖 macOS、完整 Xcode 和 Apple 签名。AirDrop 更新属于操作指引；匿名统计提供关闭开关，不能据此推定所有数据都不外发。

建议用一个页面读取、一次操作和一个确定性断言验证最小真机链路，保留截图与执行记录。Agent 可用于探索并生成步骤，稳定回归仍需验证可重复执行与失败恢复。

### DigUp

[固定版本 README](https://github.com/ARahim3/DigUp/blob/92b5a631e1d279ac92ff31c9affd73d5c122d296/README.md) 描述 EmbeddingGemma 2、llama.cpp 与 SQLite 的多模态向量和关键词检索。图片、PDF 页、视频帧与音频片段可进入索引；代码有独立索引且默认关闭。文件本地处理不等于没有联网依赖，模型下载与更新检查仍需联网。

观察期内的 v0.6.1 主要要求 Apple Silicon 与 macOS 14+。[Windows/Linux beta](https://github.com/ARahim3/DigUp/releases/tag/v0.7.0-beta.1) 于 UTC 10/14 17:22 发布，对应北京时间 10/15 01:22，属于期后更新。截至审核日已有桌面 beta，不能继续写成只支持 Mac，也不能推导为成熟 NAS 服务。后续用固定样本检验跨模态召回、中文输入、增量索引和模型升级成本。

### Helix Foundry

[固定版本指南](https://github.com/HelixDB/helix-foundry/blob/00d7927d7c08e16c58316e006959f052427e7fa1/docs/GUIDE.md) 描述 HelixDB 业务对象与关系、不可变 Parquet 快照、DuckDB 查询和 SQL 结果引用。CDC 作为变化信号，最终仍生成完整快照，尚不能按行级增量引擎估算吞吐。应用面向单人本机，默认只允许 loopback 访问；可选托管模型会改变数据外发边界。

建议研究业务语义映射与“查询结果绑定快照”的设计。接入行业数据前，另验全量快照成本、身份匹配、权限和人工审核流程；文档中的连接器列表不能证明这些环节已经完成。

### FSearch

本期是 [noahdunnagan 的 Rust macOS 搜索工具](https://github.com/noahdunnagan/fsearch/blob/88e63fdf850cf7749deae8198b187accd21f8ba5/README.md)，需要与同名项目区分。它提供文件名模糊搜索、内容 grep、Git 状态过滤和 MCP。Linux/Chromium 基准指 Mac 上的源码数据集，亚毫秒数据仅为作者测试。

它适合先做低成本试用。需要核对文件权限、文本大小与忽略规则造成的漏检，以及大批文件变更时的索引稳定性。索引文件名不代表已索引全部文件内容，尚不标记为采用。

### xtool

[观察期固定 README](https://github.com/xtool-org/xtool/blob/b50173f7b1f7d13297b9c8229079038d47a2bb1d/README.md) 描述 Linux、WSL 和 macOS 上的 SwiftPM iOS 构建、签名、安装及设备操作，XKit 可供其他 SwiftPM 工具集成。它与真机交互工具存在组合研究价值。

后续验证从构建、签名到真机部署的完整链路，并核对 Apple SDK、开发服务和系统版本约束。这些能力尚不能证明完整替代 Xcode 或 XCTest。

### OpenTelemetry Collector Contrib

[10/13 官方文章](https://opentelemetry.io/blog/2026/hostmetrics-process-scraper-rc/) 介绍 hostmetrics process scraper 的版本化指标机制；涉及的 [v0.160.0](https://github.com/open-telemetry/opentelemetry-collector-contrib/releases/tag/v0.160.0) 已于 9/2 发布。当时 `scraper.process.EmitV1SystemConventions` 与 `scraper.process.DontEmitV0SystemConventions` 均默认关闭。

新旧定义共存提供迁移路径，同名指标的属性可能合并，类型冲突优先新类型并告警。它并不自动保证现有查询、仪表盘和告警兼容。建议固定版本与功能门，验证名称、类型、单位、标签及告警结果，再决定迁移。

### Apache DataFusion Python

[固定 README](https://github.com/apache/datafusion-python/blob/878e5d3b8d373bca19671af43e49dfb1890f8da2/README.md) 描述进程内 SQL、DataFrame、Parquet、PyArrow、Python UDF 与 Substrait；[API 指引](https://github.com/apache/datafusion-python/blob/878e5d3b8d373bca19671af43e49dfb1890f8da2/skills/datafusion_python/SKILL.md) 位于 skills 子目录。

[Apache Release Catalog](https://release-catalog.apache.org/datafusion-python/index.html) 标注 Python 55.0.0 于 10/12 发布，但注明资料由 ATR 从归档汇集、尚未经 DataFusion 审核；[下载索引](https://downloads.apache.org/datafusion/) 的修改时间也不能替代正式公告。这里保留为发行目录信号，不宣称 GitHub Release 或 PyPI 上传日期。研究重点是嵌入式分析、Parquet 与数据画像，Python 与 Core 版本及实际工作负载仍需验证。

### MedMCP

[观察期 README](https://github.com/medmcp/medmcp/blob/7e353ce778708590bb27d2067ec575ad332e4856/README.md) 与 [安全说明](https://github.com/medmcp/medmcp/blob/7e353ce778708590bb27d2067ec575ad332e4856/SECURITY.md) 描述影像工具栈、操作审批、工作流重放和执行记录，同时明确软件用于研究，不得用于临床决策。README 推荐 Linux、NVIDIA GPU 和至少 24 GB 显存，运行条件需要单独评估。

源码采用 Apache-2.0，不代表获准临床使用。服务没有身份验证，不能直接暴露端口；可选云模型和外部 MCP 可能将聊天、文件与工具结果发出，默认检查更新也会联网。建议只用脱敏研究样本检查审批、隔离、出网与审计行为，不能据文档推导临床合规或海量影像处理能力。

## 保留的工程洞察

以下是基于候选文档的编辑判断，仍需实测。

- 真机交互与构建部署可分别研究：iPhone Use 提供操作接口，xtool 提供构建和设备部署能力，组合之后仍需要确定性断言与失败证据。
- 本地检索和数据工作空间有不同的验证重点：DigUp 看多模态召回与资源开销，FSearch 看精确搜索覆盖，Helix Foundry 看业务语义、快照成本与权限。
- 关键执行结果需要绑定可核验证据：指标迁移要验证告警与查询，数据分析要保留 SQL 和快照，影像编排要验证审批和工作流重放。

## 审核处理与入库边界

原文的日期窗口跨 ISO 第 41、42 周，本版直接使用日期范围，避免将其写成完整的 2026-W42。第三方趋势文章只作为候选线索；无法独立核验的历史榜单、Star 数及七日增长不写入事实。

删除原文缺少五维评分依据的 84 至 94 分 Radar Score；未建立评分卡，也未更改任何采用决定。未经独立核验的过滤项不收录，相关安全事件与许可证判断不在本版转述。私人项目映射和工作数据也不随公开报告发布。

收录使用现有 `data/projects/`；事实与建议分开写入 [研究证据账本](../research/evidence.jsonl)，不新增 watch 或 adopt-candidate 目录，也不执行外部仓库中的代码或指令。当前机器事实位于 [2026-10 观测账本](../data/observations/github/2026-10.jsonl)，与本报告的历史信号分开保存。

本报告按现有 ReportSnapshot 契约保存内容、摘要和审核时点，`cutoff_at` 为本次审核截止时间，观察窗口仅表示原周报选题范围。配套 JSON 的 `input_digest` 对本次八个项目及其研究证据构成的对象计算：两组分别按 `id`、`evidence_id` 排序，以键名 `projects`、`evidence` 组成 JSON，`ensure_ascii=False`、`sort_keys=True`、`separators=(',', ':')` 编码后取 SHA-256；机器观测不参与这个编辑报告摘要。后续更正应另发新版。
