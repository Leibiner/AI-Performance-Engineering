# Research：K6 生态、真实项目组织方式与对比工具

> 研究日期：2026-09-29
> 标记约定：**[事实]** 有来源；**[判断]** 本项目结论；**[推测]** 未完全验证。
> GitHub 数据取自 `api.github.com`（部分因限流改取页面数据，为近似值）。
> 本文回答：**生态中哪些东西可以直接用？别人是怎么组织 k6 项目的？哪些模式值得借鉴？**

---

## 0. 结论先行

| # | 结论 | 类型 |
|---|---|---|
| 1 | **不存在被广泛采用的社区 k6 框架**。最高星项目 87 stars 且 2023 年后停更。这个方向没有可以整体照搬的范式。 | 事实 + 判断 |
| 2 | Grafana 官方建议"业务流与 workload 分离"（`config/workloads.js` + `scenarios/`），但**只是代码约定**：没有 schema，没有校验。 | 事实 + 判断 |
| 3 | **Gatling** 是"业务流 / 注入模型 / 协议配置"三者正交的最佳参考，且 Open/Closed 模型是显式一等概念。 | 事实 + 判断 |
| 4 | 官方 TypeScript / ES6 模板与 k6-learn **已归档**；k6 原生运行 `.ts`，无需 Webpack/Babel。 | 事实 |
| 5 | xk6 活跃维护（v1.4.14），`grafana/xk6` Docker 镜像可在无 Go 环境的 CI 中构建扩展二进制。 | 事实 |
| 6 | 大批 `grafana/*` 扩展仓库被迁往 `grafana-cold-storage` 并归档：amqp、timescaledb、dashboard、disruptor、browser、grpc。 | 事实 |
| 7 | k6-operator 已 GA（v1.6.0），但阈值与 summary **按 runner 分散**，OSS 用户必须自建聚合。 | 事实 |
| 8 | k6 Studio 已**确定性地**自动化 录制 → 关联 → 参数化 → 脚本，AI 只是"提出关联规则"。它的负载模型非常简单（2 个 executor）。 | 事实 + 判断 |

---

## 1. grafana/xk6

- **[事实]** [grafana/xk6](https://github.com/grafana/xk6)：301 stars，最近 push 2026-09-25，最新 v1.4.14（2026-09-22）。
- **[事实]** 命令：`build`（`--with module@ver`）、`new`、`run`、`x`、`lint`（13 项合规检查）、`test`、`sync`、`version`。
- **[事实]** Docker 镜像 `grafana/xk6`（semver tag），无需 Go 工具链即可构建。
- **[事实]** 扩展注册中心 [registry.k6.io](https://registry.k6.io/registry.json)（源：[k6-extension-registry](https://github.com/grafana/k6-extension-registry)），分 official / partner / community 层级。
- **[事实]** 自动扩展解析在**本地 `k6 run` 也生效**（k6 ≥ 1.2，v2 默认开启），通过 k6build 服务下载匹配二进制并缓存。不支持 Output 扩展、私有扩展、stdin（[extensions/run](https://grafana.com/docs/k6/latest/extensions/run/)）。
- **[推测]** k6build 是否可自托管、对应环境变量，未确认。

**[判断]** CI 与内网环境：关闭自动解析，使用固定版本 `grafana/xk6` 镜像构建二进制并记录版本。

---

## 2. 扩展状态（2026-09-29）

| 扩展 | 状态 | Stars | 最近 push | 层级 | 是否在核心 |
|---|---|---|---|---|---|
| grafana/xk6-sql（+ driver-mysql/postgres） | 活跃 | 190 | 2026-09-21 | Official | 否 |
| mostafa/xk6-kafka | 活跃，兼容 k6 v2 | 218 | 2026-09-08 | Community | 否 |
| grafana/xk6-kafka | **新的纯 Go 实现，v0.x** | ~0 | 2026-09-24 | 待定 | 否 |
| grafana/xk6-redis | 活跃 | 38 | 2026-09-24 | Official | **v2 从核心移除**，改为 `k6/x/redis` |
| grafana/xk6-tcp | 新（v0.2.0） | 4 | 2026-09-24 | Official | 否 |
| grafana/xk6-mqtt | 新（v0.2.0） | 8 | 2026-09-23 | Official | 否 |
| grafana/xk6-faker | 活跃 | 118 | 2026-09-23 | Official | 否 |
| grafana/xk6-output-influxdb | 活跃（InfluxDB v2） | 83 | 2026-09-23 | Output（不可自动解析） | 否 |
| xk6-amqp | **归档**（cold-storage） | 26 | 2023-12 | — | 否 |
| xk6-output-timescaledb | **归档** | 34 | — | — | 否 |
| xk6-disruptor | **归档**（文档目录仍列出） | 117 | 2026-02-12 | — | 否 |
| xk6-dashboard | 归档 | 479 | — | — | **是**：`web-dashboard` |
| xk6-browser | 归档 | 358 | — | — | **是**：`k6/browser` |
| xk6-grpc | 归档 | 11 | — | — | **是**：`k6/net/grpc` streaming |

来源：GitHub API、[k6 extensions explore](https://grafana.com/docs/k6/latest/extensions/explore/)、[xk6-sql](https://github.com/grafana/xk6-sql)。

**[判断]**
- 混沌 / 故障注入：不依赖 xk6-disruptor，未来使用 Chaos Mesh / Litmus 或目标系统自带的故障开关。
- Kafka：mostafa/xk6-kafka 是当前唯一成熟选择；grafana/xk6-kafka 需要观察，到真实需要时再决策。

---

## 3. grafana/k6-operator

- **[事实]** [k6-operator](https://github.com/grafana/k6-operator)：804 stars，v1.6.0（2026-08），k6 2.0 同期宣布 1.0 GA；v1.5 起基于 k6 v2。
- **[事实]** CRD：`TestRun`（执行一次测试）、`PrivateLoadZone`（注册为 Grafana Cloud load zone，需要 Cloud 账号）。
- **[事实]** `parallelism: n` 创建 **n+2 个 Job**：initializer（校验脚本）、starter（统一释放）、n 个 runner（暂停启动）。Runner 中途重启将永远收不到启动信号，operator 会无限等待（[issue #304](https://github.com/grafana/k6-operator/issues/304)）。
- **[事实]** 脚本来源：ConfigMap（~1MiB 限制，多文件用 `k6 archive` 打 tar）/ PVC / localFile。
- **[事实]** "Each k6 instance evaluates Thresholds independently"；"k6 reports the metrics individually for each instance"。聚合 issue [#413](https://github.com/grafana/k6-operator/issues/413) 已关闭但未提供聚合功能。

**[判断]** k6-operator 负责"把负载分到多个 Pod"，**不负责结果**。本项目若进入分布式阶段，Result 层（全局阈值、合并百分位）必须由项目提供，或采用 Grafana Cloud。

---

## 4. 官方 jslib、模板与项目结构建议

- **[事实]** jslib（[列表](https://grafana.com/docs/k6/latest/javascript-api/jslib/)）：`httpx`（带 baseURL/header 的 session 封装）、`utils`（`uuidv4`、`randomIntBetween`）、`testing`（Playwright 风格 `expect`，即 k6 2.0 Assertions API，soft 模式 exit code 110）、`http-instrumentation-tempo`、`http-instrumentation-pyroscope`、`aws`、`totp`；**k6chaijs 已废弃**。
- **[事实]** `grafana/k6-template-typescript`（306 stars）、`k6-template-es6`、`k6-learn`（443 stars）**已归档**。
- **[事实]** Grafana 博客 [Organizing your Grafana k6 performance testing suite](https://grafana.com/blog/organizing-your-grafana-k6-performance-testing-suite-best-practices-to-get-started/) 建议：
  - 结构：`config/{workloads.js, settings.js}`、`scenarios/{e2e, apis}/`、`tests/{smoke-*.js, pre/, prod/}`；
  - 实践：config 模块化（workload、threshold、环境）、scenario 可复用且与 metric 等测试概念解耦、**一个测试一个目标**、**tags 优于 groups**、面向对象 **API client**、带可观测性的错误处理包装。
- **[事实]** 官方示例 [Reuse and re-run tests](https://grafana.com/docs/k6/latest/examples/get-started-with-k6/reuse-and-re-run-tests/)：`main.js` 导入业务函数，`config.js` 导出 `thresholdsSettings / smokeWorkload / breakingWorkload`；命名 `smoke-get-api.js`、`load-get-api.js`、`stress-get-api.js`，每个文件以不同 workload 导入同一业务流。

**[判断]** 官方已经认可"业务流 ⟂ workload"的分离方向。本项目在此基础上补上：**明确的 Open/Closed 选择、Profile 校验、SLO 数据化、有效性阈值、Run 记录**。

---

## 5. 真实社区项目

| 项目 | 规模/活跃 | 结构 | 业务/负载分离 | 主要问题 |
|---|---|---|---|---|
| [go-automate/k6-typescript-framework](https://github.com/go-automate/k6-typescript-framework) | 87★，2023-04 停更 | `actions/roles/`（按角色调用动作）、`tests/soak.test.ts` | 负载写在测试文件里 | Webpack/Babel 时代，已过时 |
| [SwissLife-OSS/K6-MultiScenario-template](https://github.com/SwissLife-OSS/K6-MultiScenario-template) | 56★，2024-10 | 单文件多 scenario，`exec` → 函数 | 仅在 `options.scenarios` 内分离 | 单体文件、无环境配置 |
| [autom8ion/k6-agentic](https://github.com/autom8ion/k6-agentic) | 0★，11 commits | `config/`（SLO profile + smoke/load/stress/soak/spike 工厂）、`lib/journeys/`、`lib/{http,db}`、`data/` | **`buildOptions()` 组合 journey × profile，分离最清晰** | 玩具目标、无数据清理；"agentic" 仅指用 Claude Code 编写，运行时无 LLM |
| [jwcastillo/k6-enterprise-framework](https://github.com/jwcastillo/k6-enterprise-framework) | 0★ | `src/{core,helpers,patterns,metrics,observability,reporting,...}` + `clients/<name>/` | profile JSON + CLI | **过度设计**，与采用度不匹配 |
| [Kong/kong-gateway-performance-benchmark](https://github.com/Kong/kong-gateway-performance-benchmark) | 16★，2026-07 | Terraform EKS + k6-operator + Prometheus/Grafana | 负载通过 shell 位置参数 | 负载模型无类型、无业务抽象 |

**[判断] 共同缺陷**：
1. Load Profile 是无 schema 的 JS 对象，Open/Closed 选择是隐式的；
2. 测试数据没有生命周期（无 seed/cleanup、分布式唯一性）；
3. 没有处理 runner 级阈值/summary 分裂；
4. 环境配置散落在 `__ENV`、JSON、`.env`；
5. 关联（correlation）手写；
6. 没有 需求 → SLO → Threshold 的可追溯性；
7. 没有"测试有效性"判定。

**[判断] 借鉴**：k6-agentic 的 `journey × profile` 组合方式；Grafana 博客的 API client + tags 实践。
**[判断] 不借鉴**：enterprise-framework 式的一次性全量分层；bundler 依赖；shell 位置参数式负载配置。

---

## 6. 对比工具：业务流 vs 负载模型

| 工具 | 业务流 | 负载模型 | 协议配置 | Open/Closed | 分离程度 |
|---|---|---|---|---|---|
| **Gatling** | `scenario(...)` | `setUp(scn.injectOpen(...) / injectClosed(...))` | `.protocols(...)` | **显式一等** | ★★★ 三者正交 |
| Locust | `User` / `@task` / `TaskSet` | `LoadTestShape.tick()` | User 类中 | 默认 Closed | ★★ |
| JMeter | Sampler / Controller | Thread Group | 同一棵树 | Arrival thread group 可选 | ★ 嵌套在同一 .jmx |
| **k6** | 导出函数 | `options.scenarios.<name>.executor` | 模块 import | executor 隐含 | ★★ 机制存在，但不强制 |

来源：[Gatling injection](https://docs.gatling.io/concepts/injection/)、[Locust custom shape](https://docs.locust.io/en/stable/custom-load-shape.html)。

**[判断]** 本项目在 k6 之上复刻 Gatling 的分离思想：**Flow（业务）⟂ Load Profile（注入）⟂ Environment（目标/协议配置）**，且 Load Profile 必须显式声明 `model: open | closed`。

### Grafana Cloud k6 vs 自托管

- **[事实]** Grafana Cloud Free 含 500 VUh/月。
- **[判断]** Cloud 提供：跨负载机聚合阈值与指标、多区域 load zone、历史与对比、Cloud Insights（规则化审计）。自托管需要自行完成：聚合、全局阈值、趋势存储。
- **[判断]** 本项目**不绑定 Cloud**，但数据模型（runId、tag、Result）保持与 Cloud 兼容，使未来可以选择。

---

## 7. k6 Studio：确定性自动化的对照组

- **[事实]** [grafana/k6-studio](https://github.com/grafana/k6-studio)：543 stars，v2.1.0（2026-08-11）；v2.0.0（2026-07-31）浏览器录制与 **AI autocorrelation GA**。
- **[事实]** 流水线：Recorder（代理/浏览器 → HAR）→ Generator（规则）→ Validator（回放调试）。
- **[事实]** Generator 的**确定性规则**：Verification（状态码 check）、Correlation（Begin-End / JSON path / Regex 提取 + 替换）、Parameterization、Custom code。负载配置仅支持 `ramping-vus / shared-iterations`。
- **[事实]** AI autocorrelation：由 Grafana Assistant 检测动态值（session/CSRF token、资源 ID）并**生成关联规则**；需要 Grafana Cloud 登录（早期版本需 OpenAI key）（[whats-new](https://grafana.com/whats-new/2026-08-19-k6-studio-20--browser-test-authoring-and-autocorrelation-are-generally-available/)）。

**[判断] 对本项目的意义**：
1. "录制 → 脚本"已被确定性工具很好地解决，**本项目不重复造这个轮子**。
2. AI 在 Studio 中的正确位置：输出**受约束的声明式规则**，由确定性引擎执行，由回放验证，由人逐条审核。这是后续本项目考虑 AI 时的参考模式。
3. Studio 不覆盖的空白：多业务流混合、负载建模、数据生命周期、分布式结果、SLO 可追溯性。这些才是本项目的领域。

---

## 8. 对本项目的启示

1. k6 v2.x + 原生 ES Module（TS 可选），**无构建步骤**。
2. **Flow ⟂ Load Profile ⟂ Environment** 三者分离，Profile 显式声明 Open/Closed，运行前校验。
3. SLO 测试默认 arrival-rate；Closed 模型需要显式理由。
4. CI 中扩展二进制固定版本构建，不依赖自动解析。
5. 避开归档扩展（disruptor、amqp、timescaledb）。
6. 分布式阶段必须有项目自己的结果聚合层，或使用 Cloud。
7. 数据生命周期（seed、分片、cleanup）是差异化能力。
8. 断言使用 k6 2.0 Assertions（`k6-testing` jslib），不用 k6chaijs；tags 优于 groups。
9. 不重复实现 k6 Studio 已解决的录制/关联问题。
