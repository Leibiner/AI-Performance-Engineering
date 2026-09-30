# ADR-003：技术基线 —— k6 v2.x、原生 ES Module、无构建步骤、演示目标系统

- 状态：**Accepted，部分被 ADR-005 修订**（2026-09-30）
- 日期：2026-09-29
- 修订：2026-09-30，MVP 按 ADR-005 实现后，下表中以下几行**不再有效**，以 ADR-005 和 `ARCHITECTURE.md` §10 为准：
  - "k6 外部工具：Node.js，仅标准库" → 后端是 Python 3.12 + FastAPI + 标准库 `sqlite3`，依赖由 uv 管理；没有 `tools/` 目录；
  - "前端与只读 API" → 前端是可维护的管理控制台，npm 和构建只在 `web/`；
  - "TypeScript 暂不采用" → 前端用 TypeScript；`perf/` 仍是原生 JS ES Module、无构建；
  - "运行结果存储：本地 JSON 文件，无需数据库" → SQLite 单文件 `data/app.db` + `results/<runId>/` 产物；
  - "Phase 1 目标系统：QuickPizza" → MVP 的目标是 `https://www.baidu.com`，仅冒烟；QuickPizza 因本机没有 Docker 和 sudo 未采用，Consequences 中与 QuickPizza 有关的两条随之失效。
- 仍然有效：k6 v2.x 并固定 minor 版本（已实测定为 v2.3.0）、`perf/` 无构建、扩展与禁用清单、断言方式、OpenTelemetry Demo 作为后续目标系统的候选、TOB 目标系统缺口。下文正文保留原样，作为历史记录。
- 相关：`research/k6.md` §0、§7；`research/k6-ecosystem.md` §1、§4

---

## Context

- k6 当前主版本为 v2（v2.0.0：2026-05-11；最新 v2.3.0：2026-09-21），v2 删除了多项 v1 时代功能；
- k6 原生运行 `.ts`（esbuild 仅剥离类型，不做类型检查），无 npm/Node 模块解析；
- 官方 TypeScript/ES6 模板已归档；
- 当前开发环境：已安装 Node.js；**未安装 k6、Docker、Go**；
- 项目需要一个真实可执行的目标系统，而不是 `GET /hello`。

## Decision

| 项 | 决定 | 理由 |
|---|---|---|
| k6 版本 | **v2.x，锁定 minor**（Phase 1 开始时的最新稳定版），版本写入 Run Record | 稳定性保证覆盖当前与上一主版本；每年一次主版本迁移 |
| 测试代码语言 | **JavaScript ES Module**（k6 原生），不引入构建步骤 | 最少工具链；TS 无类型检查的收益有限 |
| TypeScript | 暂不采用；Phase 2 复核（若需要类型检查则加入 `tsc --noEmit` 作为 lint，而非构建） | 避免过早引入工具链 |
| k6 外部工具（Run 入口、Compare） | **Node.js，仅标准库**（无 npm 依赖） | 与测试代码同语言；环境已具备；零依赖 |
| 前端与只读 API（`web/`、`server/`，Phase 2） | 允许 npm 依赖和构建步骤，仅限这两个目录（ADR-004） | 展示侧与执行侧只通过 Run Record 关联，互不 import |
| 扩展 | 默认不使用；需要时 CI 中关闭自动解析，使用固定版本 `grafana/xk6` 镜像 | 可复现 |
| 禁用 | `k6/experimental/*` 不进入 Core；不使用已删除/归档功能（`externally-controlled`、`k6/experimental/tracing`、`k6/experimental/redis`、xk6-amqp、xk6-disruptor） | 稳定性 |
| 断言 | k6 `check` + 阈值；如需 `expect` 使用 k6 2.0 Assertions（`k6-testing` jslib） | 官方当前推荐；k6chaijs 已废弃 |
| Phase 1 目标系统 | **grafana/quickpizza**（`ghcr.io/grafana/quickpizza-local`，单容器；支持微服务模式与 OTel 埋点） | 为 k6 设计的官方演示系统，轻量 |
| Phase 2–3 目标系统 | **OpenTelemetry Demo**（多语言微服务电商：gRPC、Kafka、缓存、完整 OTel；flagd 提供 15 个故障注入开关） | TOC 真实度更高；故障注入提供 AI 评估的 ground truth |
| 运行结果存储 | 本地 `results/`（git 忽略）JSON 文件；基线文件纳入 git | 无需数据库 |

## Consequences

- Phase 1 前置条件：安装 k6 v2.x 与 Docker（或可访问的 QuickPizza 实例）；
- QuickPizza 的具体 API（登录/token、可用端点）需在 Phase 1 第一步**实测确认** **[推测：本次研究未验证其认证流程细节]**；
- OpenTelemetry Demo 资源消耗较大，Phase 2 需要评估运行环境；
- **TOB 目标系统缺口**：目前没有合适的开源多租户 TOB 演示系统。Phase 2 开始时决定：自建最小多租户 mock 服务，或接入真实内部系统。在此之前 TOB 仅在模型层面验证（`ARCHITECTURE.md` §4.7）。

## Reconsideration Conditions

- k6 发布新主版本 → 迁移评估；
- 团队需要类型检查 → 加入 `tsc --noEmit`；
- QuickPizza 不能表达所需的业务链路 → 提前切换到 OpenTelemetry Demo。
