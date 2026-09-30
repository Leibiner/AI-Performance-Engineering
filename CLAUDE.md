# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 当前状态

**仓库目前只有文档，没有任何代码。** Phase 0（研究与架构）已完成，Phase 1 尚未开始。因此现在没有 build / lint / test 命令。

不要主动开始下一个 Phase 的实现；不要提前创建空目录。每个阶段只创建 `docs/ARCHITECTURE.md` §5.2 中标注给该阶段（`[P1]`、`[P2]`…）的部分。

Phase 1 的运行前提尚未具备：本机没有安装 k6 和 Docker。

## 计划中的命令（Phase 1 实现后才可用）

```bash
# 运行一个测试：同一个 test 换 profile 不改代码
node tools/run.mjs --system quickpizza --test shop --profile smoke --env local
node tools/run.mjs --system quickpizza --test shop --profile average --env local --rate 50

# 只校验脚本能否解析并输出 options（不发请求）
k6 inspect perf/systems/quickpizza/tests/shop.test.js
```

`run.mjs` 的退出码：0 passed / 1 failed / 2 invalid / 3 error / 4 aborted / 5 预检被拒绝 / 6 相对基线回归。CI 只认这张表，不直接依赖 k6 的退出码。

实现这些命令时，以 `docs/ARCHITECTURE.md` §3.5、§3.8、§5.4 为准，并在实现后更新本节。

## 文档结构与维护规则

```text
docs/ARCHITECTURE.md   L1 唯一的架构与总体说明；与其他文档冲突时以它为准
docs/decisions/        L2 ADR：为什么这样设计
docs/plans/            L2 roadmap.md（阶段、验收、停止条件）、ai-opportunity-map.md
docs/research/         L3 研究记录与来源；只作为依据，不随实现频繁更新
```

- **架构说明只保留一份**。新的架构内容写进 `ARCHITECTURE.md`，不要新建平行的架构文档。
- 改动 `ARCHITECTURE.md` 时要同步：§1 状态表、§5.2 目录树、§11 路线图摘要、§12 不做清单、`plans/roadmap.md`，必要时新增 ADR。
- 其他文档按章节号引用 `ARCHITECTURE.md`（如 `§4.7`、`§5.2`、`§6`、`§8`）。插入或调整顶级章节后，用 grep 检查并修正这些引用。
- §1 状态表必须如实反映"已完成 / 未实现"，不能把设计写成已有能力。
- 文档语言：中文为主，技术名词保留英文；图用 Mermaid；研究类结论标注 **[事实]**（带来源）/ **[判断]** / **[推测]**。
- 改变已有决定时新增或修订 ADR，而不是只改正文。

## 架构要点（实现时必须遵守）

完整内容见 `docs/ARCHITECTURE.md`，以下是跨多个章节才能看出的核心约束。

**项目定位**：以 k6 v2.x 为执行引擎的 Performance Engineering 框架。项目不重新实现、也不包装 k6 API，只在两处工作：生成 `options`（输入端），以及用 `handleSummary` + `tools/run.mjs` 把一次运行变成 Run Record（输出端）。

**术语**：业务场景叫 **Flow**。"Scenario" 只指 k6 Scenario，它是 Composer 的编译产物，不手写，所以没有 `scenarios/` 目录。

**Business Model ≠ Load Model**，两条线只在 Composer 交汇：

- 业务线：Service（做什么）→ Flow（顺序）→ Flow Mix（比例）
- 负载线：Load Profile（形状、`model: open | closed`）→ Executor → VU
- Flow / Service 中不能出现 executor、VU、rate、duration；Profile 中不能出现 URL 或业务逻辑。

**代码分层**（依赖只能向下）：

- `perf/core/`（L0）只依赖 k6 内置模块，不认识任何业务系统，不 import `k6/x/*` 或 `k6/experimental/*`
- `perf/profiles/`（L1）纯数据，所有被测系统共用
- `perf/systems/<sys>/`（L2/L3）services、flows、data、metrics、slo、env、tests
- `tools/`：Node.js，仅标准库；与 `perf/` 只通过 CLI 参数和 `results/` 文件交互，互不 import
- `web/`、`server/`（Phase 2）：展示侧，只通过 Run Record（`schemas/run-record.schema.json`）与执行侧关联；npm 和构建步骤只允许出现在这两个目录

**判定（Verdict）**：`passed / failed / invalid / error / aborted`，由确定性规则计算。阈值分两类：SLO 阈值（系统是否达标）和 validity 阈值（本次测试是否可信，如 `dropped_iterations`）。`invalid` 优先于 `failed`。

**数据规则**：选数据只用 `exec.vu.idInTest` 和 `exec.scenario.iterationInTest`，禁止用 `__VU` / `idInInstance`（分布式下不唯一）。ID 类数据不进 tag。`testid` tag 只在 Run 入口设置一次。

**负载模型**：SLO 验证默认用 arrival-rate（open）；选 closed 要写明理由。

**展示层只读**：Web 控制台和 Grafana 都不计算判定、不写 Run Record、不触发压测。每类数据只有一个事实来源：判定在 Run Record，时序在 Prometheus，调用链在 Tempo。

**AI 的硬约束**：Phase 1–3 不实现任何 AI 功能。AI 永不决定 Verdict，不在 k6 运行路径中，不发起压测，不读原始时序；只读消费 Run Record / Evidence Bundle。是否实现由 Phase 4 的评估决定（`docs/plans/ai-opportunity-map.md` §5 的 Go/No-Go 条件）。

**不做清单**见 `ARCHITECTURE.md` §12。常见的越界请求：统一协议接口、插件系统、Flow 的 YAML DSL、自建监控大盘、页面触发压测。遇到时先指出与现有决定的冲突。

## k6 版本注意事项

基线是 **k6 v2.x**（研究时最新为 v2.3.0）。网上大量资料是 v0.x / v1 时代的，以下功能已删除或归档，不要使用：`externally-controlled` executor、`k6/experimental/tracing`、`k6/experimental/redis`、`--no-summary`、xk6-amqp、xk6-disruptor、xk6-output-timescaledb、k6chaijs。

细节和来源见 `docs/research/k6.md` 与 `docs/research/k6-ecosystem.md`。

## 未决事项

动到相关设计前先向用户确认：

- **存储形态**：Run Record 存文件，还是从 Phase 2 起把运行汇总存入 PostgreSQL（`ARCHITECTURE.md` §3.9）
- **CI 平台**：GitHub Actions / GitLab CI / Jenkins，Phase 2 决定
- **前端技术栈**：React + TypeScript + Vite + Ant Design + ECharts 是推荐方案，Phase 2 开始时复核（ADR-004）
- **TOB 目标系统**：自建多租户 mock 还是接入真实系统，Phase 2 决定
- **Phase 1 需要实测的两项**：k6 v2 的 `handleSummary` 数据结构；QuickPizza 的登录 / token 流程
