# ADR-001：架构方向 —— Architecture First，而不是 AI First

- 状态：**Accepted**
- 日期：2026-09-29
- 相关：`research/ai-performance-engineering.md`、`plans/ai-opportunity-map.md`、`ARCHITECTURE.md`

---

## Context

项目目标是"以 k6 为执行引擎的 Performance Engineering 工程框架，并在真实工程流程中寻找 AI 能产生实际价值的位置"。仓库为空，无既有代码与数据。

Phase 0 研究得到以下事实：

1. k6 v2.x 已经提供成熟的执行、协议、指标、阈值能力；它**有意不负责**：Business/Load 分离、SLO 追溯、测试有效性、运行记录、基线对比、分布式结果合并（`research/k6.md`）。
2. k6 2.0 已内置 `k6 x mcp` / `k6 x agent`，k6 Studio 已提供 AI 关联——"AI 写 k6 脚本"已经**商品化**（`research/ai-performance-engineering.md` §1.1–1.3）。
3. 市面上 AI 性能分析功能大多是"基于真实数据的文字"，**没有公开准确率**；有效的分析（分段、CPD、审计）多为非 LLM 方法。
4. 学术上自由形式 LLM RCA 在 OpenRCA 上仅 11.34%；有效方案依赖确定性的证据收集流水线。
5. 社区没有被广泛采用的 k6 框架（`research/k6-ecosystem.md` §5）。

## Problem

先建设什么？如果先做 AI，AI 的输入（结构化运行结果、基线、证据）并不存在；如果先做重平台，会在没有需求的情况下引入大量复杂度。

## Options

### Option A：AI First

以 LLM agent 为中心：自然语言 → 生成 k6 脚本 → 执行 → LLM 分析报告。

- 优点：Demo 快，看起来"智能"。
- 缺点：
  - 重复 `k6 x mcp` / k6 Studio 已提供的能力；
  - 没有 Run Record、基线、有效性判定，AI 分析没有可靠输入，也无法评估对错；
  - 非确定性输出进入判定路径；
  - 爆炸半径（agent 发起负载）；
  - 无法回答"AI 是否真的有价值"。

### Option B：Platform First

一次性建设企业级平台：Web UI、服务端、数据库、插件系统、分布式控制器、Observability 平台、Agent Runtime。

- 优点：看起来完整。
- 缺点：
  - 大部分组件没有真实需求驱动；
  - k6-operator、Prometheus/Grafana、Grafana Cloud 已覆盖其中很多；
  - 维护成本高，迟迟无法真实执行；
  - 研究中的"enterprise framework"类项目（0 star、过度分层）正是此类结果。

### Option C：Architecture First, Evidence-based AI

先建设**薄的确定性 Core**（Business/Load 分离、SLO → Threshold、Validity、Run Record、Verdict、Baseline），在真实目标系统上执行，记录真实痛点；AI 只在经评估证明优于确定性基线的位置引入，并且只读消费 Core 的结构化结果。

- 优点：
  - 每一步都可执行、可验证；
  - Core 产出的 Run Record / Evidence Bundle 正是 AI 所需的输入与评估基础；
  - AI 可整体移除，不影响 Core；
  - 能够给出"AI 在哪里有价值、在哪里没有"的**证据性结论**。
- 缺点：
  - AI 相关成果出现较晚（Phase 4）；
  - 需要纪律：抵制提前抽象与提前 AI。

## Decision

**采用 Option C。**

具体约束：
1. Phase 1–3 **不实现任何 AI 功能**；
2. Core 必须确定性、可测试，且不依赖 Extension 与 AI；
3. AI 永不决定 Verdict、永不在 k6 运行路径中、默认永不发起负载；
4. 自然语言写脚本、关联等能力使用外部现成工具，不自建；
5. AI 候选必须通过 `plans/ai-opportunity-map.md` §5 的 Go/No-Go 条件才进入实现；
6. 从 Phase 1 开始记录 Pain Point Log，作为 AI 决策的数据来源。

## Why

- AI 的价值上限由其输入质量决定。没有 Core，AI 只能"看图说话"；
- "AI 写脚本"已商品化，不构成项目价值；
- 研究显示有效的 AI 模式都是"**确定性系统 + 受约束的 AI 产物 + 验证**"（k6 Studio、RCACopilot、BlazeMeter），这要求先有确定性系统；
- 本项目最终要回答的问题——"AI 在哪里产生了传统自动化无法轻易获得的价值"——只有在有基线可比较时才能回答。

## Consequences

正面：
- Phase 1 即可在真实目标系统上产出可比较的运行结果；
- 架构简单，贡献者容易理解；
- AI 评估有 ground truth（故障注入）与确定性基线。

负面 / 需要承担：
- 短期内项目"看起来没有 AI"；
- 需要维护一套目标系统（QuickPizza、OpenTelemetry Demo）；
- Phase 4 评估可能得出"AI 不值得"的结论——这是可接受且有价值的结果。

## Rejected Alternatives

| 方案 | 拒绝原因 |
|---|---|
| Option A：AI First | 无输入、无评估、重复商品化能力、判定不确定 |
| Option B：Platform First | 无需求驱动、重复现有基础设施、延迟真实执行 |
| 在 k6 之外自研负载引擎 | k6 已成熟且活跃（31.7k★，每 6 周一个 minor） |
| 以 Gatling / Locust 为引擎 | 需求方向已确定为 k6；k6 v2 在协议、生态、operator 上满足需求 |

## Future Reconsideration Conditions

以下任一条件出现时重新评估本 ADR：

1. Phase 3 完成后 Evidence Bundle 已稳定，且 Pain Point Log 显示某环节耗时占比显著 → 按计划进入 Phase 4 评估（不需要修改本 ADR）；
2. 出现公开、可复现的研究证明 LLM 在**原始遥测**上的 RCA 准确率达到实用水平（如 OpenRCA 类 benchmark 显著提升）→ 重新评估 AI 输入边界；
3. k6 或 Grafana 提供了内置的、带评估数据的 AI 分析能力 → 评估直接采用而非自建；
4. 项目目标从"工程框架"变为"产品/平台" → 重新评估 Option B 中的部分组件。
