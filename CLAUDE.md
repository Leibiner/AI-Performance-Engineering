# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 当前状态

**MVP 已完成并可运行**（2026-09-30）：一个以 k6 为执行引擎的性能测试管理控制台。在页面上维护接口、业务流程、负载配置、验收标准、环境，从页面发起和停止压测，查看判定和指标，结果自动存档。

- 已实现和未实现的能力以 `docs/ARCHITECTURE.md` §1.1 状态表为准；MVP 相对 Phase 0 原设计的出入见 §1.2。
- 基线对比、趋势、CI、Prometheus / Grafana、Trace、Evidence Bundle、分布式、任何 AI 功能都**还没有实现**，不要当成已有能力来用或引用。
- 不要主动开始下一个阶段的实现；不要提前创建空目录（规划中的目录见 `ARCHITECTURE.md` §5.2 末尾的表）。
- 2026-10-09 加入**调试**：接口页是 Postman 式工作台，能把正在编辑的接口用真实 k6 发送一次看响应；业务流程页能试跑一次迭代；支持从 cURL 导入接口。OpenAPI / Postman Collection 导入**未做**。
- 2026-10-09 加入**环境变量**（`environments.variables`，表结构版本 4）：初始值进 plan 的 `env.variables`，每次迭代从它开始；调试的当前值按环境存在浏览器里，提取到的变量自动写回。接口页请求头显示继承自环境的请求头。
- 2026-10-09 加入**接口文件夹**（`folders` 表，可嵌套；`apis.folder_id`，表结构版本 3）：只用于页面分组，不进 plan、不影响运行；非空文件夹不能删。

## 命令

都在仓库根目录执行。

```bash
# 环境准备（首次，或升级 k6 / Node 版本后）：uv sync，并把 k6 和 Node 下载到 .tools/，不需要 sudo
scripts/setup.sh

# 启动 / 停止服务（后台运行，默认 0.0.0.0:8088；前端产物不存在时会先构建）
scripts/start.sh            # 加 --build 强制重新构建前端；端口用 PORT 环境变量改
scripts/stop.sh             # 日志在 logs/server.log

# 后端开发启动（前台）。只能单进程，不要加 --workers
uv run uvicorn server.main:app --host 0.0.0.0 --port 8088

# 前端构建（npm run build 包含 vue-tsc 类型检查）
source scripts/env.sh && cd web && npm ci && npm run build

# 前端开发服务器：5180 端口，/api 代理到本机 8088（要先启动后端）
source scripts/env.sh && cd web && npm run dev

# 不发请求，检查一份 plan 能否被引擎接受，并查看生成的 options
source scripts/env.sh && k6 inspect perf/runner.js -e PLAN_FILE=<plan.json 的绝对路径>

# 手动用真实 k6 跑一份 plan（只能冒烟级别，见下文；两个路径都必须是绝对路径）
source scripts/env.sh && k6 run perf/runner.js -e PLAN_FILE=<绝对路径>/plan.json -e OUTPUT_DIR=<绝对路径> --tag testid=<runId>

# 手动以调试模式跑一份带 debug 段的 plan（后端就是这么启动的；调试记录在 debug-console.log 里，每行一个 JSON，取 msg 字段）
source scripts/env.sh && K6_WEB_DASHBOARD=false k6 run perf/runner.js -e PLAN_FILE=<绝对路径>/plan.json -e OUTPUT_DIR=<绝对路径> --no-thresholds --no-usage-report --quiet --log-format=json --console-output=<绝对路径>/debug-console.log

# 不对外发请求地验证后端的运行编排和各个判定分支：用假 k6。行为由环境变量控制
# （FAKE_K6_SLEEP / FAKE_K6_EXIT / FAKE_K6_VERDICT / FAKE_K6_NO_RECORD / FAKE_K6_NO_SAMPLES，见脚本开头），
# 每次运行前还会 source 一次 $FAKE_K6_CONF 指向的文件，所以换判定分支不用重启服务
K6_BIN=server/dev/fake-k6.sh uv run uvicorn server.main:app --host 0.0.0.0 --port 8088
```

没有 lint 和单元测试命令（见下文"禁止过度测试"）。接口文档在 `http://<地址>:8088/api/docs`。示例 plan 在 `perf/examples/`。

后端读取的环境变量：`DATA_DIR`（默认 `./data`）、`RESULTS_DIR`（`./results`）、`K6_BIN`（`./.tools/bin/k6`）、`WEB_DIST`（`./web/dist`）、`K6_WEB_DASHBOARD_PORT`（5665）。

## 环境与依赖

- **Python 只用 uv**：依赖写在 `pyproject.toml`，版本锁在 `uv.lock`。加依赖用 `uv add`，运行用 `uv run`。不要用 pip，不要手动激活或修改 `.venv/`。
- **Node 和 k6 用 `.tools/` 里的**：先 `source scripts/env.sh` 把它们放到 PATH 最前面。系统自带的 Node 是 v18，已停止维护，不要用。版本固定在 `scripts/setup.sh` 开头（k6 v2.3.0、Node v24.21.0），升级只改那里。
- uv 只管 Python；前端依赖用 npm，只存在于 `web/`。`perf/` 没有 npm，没有构建。
- 本机没有 sudo 和 Docker。不要写依赖它们的方案。
- `typescript` 固定为 `~6.0.3`（7.x 与 `vue-tsc` 不兼容），不要升级。
- `.tools/`、`.venv/`、`data/`、`results/`、`logs/`、`web/dist/`、`web/node_modules/` 都不入 git。

## 三部分如何协作

| 目录 | 是什么 | 入口 |
|---|---|---|
| `perf/` | k6 执行引擎：通用脚本读取 `plan.json` 解释执行；`core/` 生成 scenarios、阈值、Run Record | `perf/runner.js` |
| `server/` | 后端：Python 3.12 + FastAPI + 标准库 `sqlite3`。增删改查、预检、启动和停止 k6、最终判定、存档、托管前端 | `server/main.py` |
| `web/` | 前端：Vue 3 + TypeScript + Vite + Element Plus + ECharts，9 个页面 | `web/src/router.ts` |

一次运行的路径：页面 `POST /api/runs` → 后端预检 → 把测试、流程、接口、负载配置、环境展开成 `results/<runId>/plan.json`（同时作为快照存库）→ 启动 k6 子进程 → `handleSummary` 写 `run-record.json` → 后端按退出码和 `k6Verdict` 得出最终判定，补全 Run Record 后存库。完整的数据流见 `ARCHITECTURE.md` §3.4。`results/<runId>/` 里只有 5 个产物：`plan.json`、`run-record.json`、`k6-summary.json`、`dashboard.html`、`k6.log`，产物接口只认这 5 个文件名（`server/runs.py` 的 `ARTIFACTS`）。

调试的路径：页面 `POST /api/debug`（一份接口定义或一个流程 id + 被测环境）→ 后端组装成 1 并发、1 次迭代、带 `debug` 段的 plan，写到 `results/_debug/<debugId>/` → 以调试模式启动 k6（`--no-thresholds --quiet --log-format=json --console-output=…`，不开仪表盘）→ 引擎迭代结束时把逐步记录 `console.log` 成一行 JSON → 后端解析后同步返回，目录读完即删（`server/debug.py`）。调试不留运行记录，和运行互斥（`server/runs.py` 的 `claim_debug_slot`）。约定见契约 §3.5、§4 `debug`、§5.1。

**三部分之间的唯一约定是 `docs/plans/mvp-contract.md`**（REST 接口、`plan.json`、`run-record.json`、退出码、判定顺序）。**改接口先改契约，再改代码**；`web/src/api/types.ts` 要和契约保持一致。

- `server/` 不 import `perf/`：两边只通过 `plan.json`、命令行参数、退出码和 `results/` 里的文件交互。
- 前端页面只通过 `web/src/api/` 访问后端，不直接写 fetch。
- **前端面向有经验的用户**：页面上不写说明性文案（页头描述、表单提示、区块副标题、长空状态），只保留安全警示（生产确认、超出安全上限）和错误信息；代码注释只写不显而易见的约束，不写文件头叙述、分节线和复述代码的注释。
- 业务流程是数据，不是代码：新增流程不加文件。`runner.js` 只导出一个执行函数 `runFlow`，用 scenario 名（= 流程的 `key`）找回对应的流程。每一步按 `{{变量}}` 替换 → 发请求 → check → 提取变量 → 等待 `thinkTimeMs` 执行；变量的作用域是一次迭代，某一步的 check 没通过时本次迭代剩下的步骤不再执行（`perf/core/interp.js`）。
- 数据在 `data/app.db`（SQLite 单文件）。种子数据在 `server/seed.py`，只在全新的库里写一次；改了种子要删库才会生效。
- **改表结构要写迁移，不能删库**：库里有用户的真实数据。表结构版本记在 `PRAGMA user_version`，在 `server/db.py` 里把 `SCHEMA_VERSION` 加 1 并加一段迁移（备份 → 一个事务内迁移 → 写版本号），先在库的拷贝上验证，再重启正式服务。迁移前会自动备份到 `data/app.db.v<旧版本>.bak`（已存在则不覆盖）；迁移后不能直接回退旧代码，要先用备份还原。
- **两种"环境"不要混用**：**执行机**（`executors`）是安装了本项目、实际运行 k6 的机器，目前只有本机一台，不能新增和删除；**被测环境**（`environments`）是被压测的目标，有类型 `dev / test / staging / prod`。被测环境上的 `maxVus`、`maxRate`、`maxDurationSec` 是**安全上限**（只在预检时用来拒绝超限的运行），不是负载配置。

**负载配置的 4 种形态。** `config` 的字段组合必须恰好是下表之一（保存和预检都用 `server/validators.py` 的 `config_shape_problem` 校验）；`perf/core/compose.js` 把每个流程编译成一个同名的 k6 scenario，多个流程按权重拆分并发或到达率：

| `model` | `config` 必须恰好是这些字段 | 编译成的 k6 executor |
|---|---|---|
| `closed` | `vus`、`iterations`、`maxDurationSec` | `shared-iterations` |
| `closed` | `vus`、`durationSec` | `constant-vus` |
| `open` | `rate`、`durationSec`、`preAllocatedVus` | `constant-arrival-rate` |
| `open` | `startRate`、`stages`、`preAllocatedVus` | `ramping-arrival-rate` |

## 必须遵守的约束

**对百度只允许冒烟流量。** MVP 的压测目标 `https://www.baidu.com` 是第三方线上站点：

- 种子环境"百度（仅冒烟）"的类型是生产（`prod`），安全上限是 2 并发、每秒 2 次、60 秒，由后端预检强制执行。**不得调高这个环境的上限，也不得把它改成非生产类型**（非生产类型可以不设上限），也不要为了"演示压力测试"新建一个指向第三方站点的宽松环境。
- 被测环境是生产时，`POST /api/runs` 必须带 `"confirmProd": true`；页面上是一次必须点的确认。
- 手动运行 k6 时同样遵守：最多 2 个并发，单次不超过 20 次迭代或 15 秒。
- 不要绕过后端预检直接对外加压。验证后端逻辑用假 k6，检查 plan 用 `k6 inspect`。
- 百度的 `/s` 会 302 到验证码页，不要用作示例；首页 `/` 可用。

**调试不另写请求逻辑。** 调试和压测必须走同一份 `perf/core/interp.js`（调试只是 plan 多了 `debug` 段）。不要在后端用 Python 直接发请求来"调试"，那会出现两套语义，调试通过而压测失败。对生产环境（含百度）调试同样要 `confirmProd: true`，一次请求也是请求。

**页面和 Grafana 都不计算判定。** 判定只由确定性规则算出：`perf/core/summary.js` 按阈值类别得出 `k6Verdict`，`server/runs.py` 结合退出码和停止请求得出最终判定（`ARCHITECTURE.md` §4.5）。前端只展示后端返回的结果。`invalid`（测试本身不可信）优先于 `failed`（系统不达标），两者在界面上必须明确区分。

**不要让浏览器连 k6 实时仪表盘。** 只要有浏览器连着 `:5665`，k6 跑完后就不会退出，也不写 summary，运行会一直停在"运行中"。仪表盘只监听 `127.0.0.1`，页面上不嵌入也不链接它；运行中的进度来自 `k6.log`，结束后的图表用导出的 `dashboard.html`。

**业务与负载分开。** 接口和流程的数据模型里不能出现并发、到达率、时长；负载配置里不能出现地址和业务逻辑；它们只在后端组装 plan 时相遇。负载配置必须显式声明 `model: open | closed`。"Scenario" 只指 k6 Scenario，它是 `compose.js` 的编译产物，不手写、不在页面上维护。

**`perf/core/` 不认识任何具体的被测系统**，只依赖 k6 内置模块，不 import `k6/x/*` 或 `k6/experimental/*`。`testid` tag 只在后端启动 k6 时设置一次。ID 类数据和页面上的中文名称不进 tag。

**执行机采样只展示，不参与判定。** 运行期间后端每秒采样本机 CPU 和内存，写进 Run Record 的 `executor`。是否在执行机过载时判 `invalid`、阈值多少，未决，不要自行加进判定。

**同一时间只允许 1 个运行；后端只能单进程。** 正在运行的 k6 进程句柄在内存里。向 k6 发信号只能发一次 SIGINT：第二次会让它强制退出且不写 summary；点停止后 30 秒还没退出才强杀。重启后端会中止正在进行的运行：关闭时向 k6 发 SIGINT，启动时把库里仍是"运行中"的记录标为 `error` 并停掉遗留的 k6 进程（`server/runs.py` 的 `shutdown` / `recover_stale`），所以有运行在进行时不要重启服务。

**禁止过度测试。** 这是用户的决定：不写单元测试套件，不引入测试框架（pytest、vitest、Playwright 等）。验证靠真实运行：引擎用真实 k6 做冒烟，后端用假 k6 走各个判定分支，前端以 `npm run build` 通过为准，最后端到端跑一次。

**提交。** 提交到 `main`。每次提交在 `docs/records/commit-log.md` 最上面记一条（上一条的提交号在这次补上）；过程中用到的技术要点、踩到的坑记入 `docs/records/tech-notes.md`，只记已经验证过的内容。**`git push` 由用户执行**，在 agent 会话里执行会卡在凭据上。

**AI 的硬约束。** 目前没有任何 AI 功能。AI 永不决定判定，不在 k6 运行路径中，不发起压测，不读原始时序；`POST /api/runs` 是给人用的，不向 agent 或 MCP 暴露。是否实现 AI 由 Phase 4 的评估决定（`docs/plans/ai-opportunity-map.md` §5 的 Go / No-Go 条件）。

**不做清单**见 `ARCHITECTURE.md` §12。常见的越界请求：统一协议接口、插件系统、自建监控大盘、多个运行并行、给流程加分支和循环、静态报告、调高百度环境的上限。遇到时先指出与现有决定的冲突（多数对应 ADR-005 的复议条件），由用户决定。

## k6 版本注意事项

基线是 **k6 v2.3.0**。网上大量资料是 v0.x / v1 时代的，以下功能已删除或归档，不要使用：`externally-controlled` executor、`k6/experimental/tracing`、`k6/experimental/redis`、`--no-summary`、xk6-amqp、xk6-disruptor、xk6-output-timescaledb、k6chaijs。

实测过的行为（细节在 `docs/records/tech-notes.md` §2）：

- `handleSummary` 拿到的仍是旧结构（顶层 `metrics`、`root_group`、`options`、`state`）；新结构要显式加 `--new-machine-readable-summary`。
- 子指标（如 `http_req_duration{step:f1s1}`）只有被阈值引用才会出现在 summary 里，所以每个步骤都有占位阈值。
- `handleSummary` 在独立的运行时里执行，看不到 VU 里给模块变量赋的值；VU 也不能写文件。VU 要交出结构化数据只能 `console.log`，配合 `--console-output=<文件>` 和 `--log-format=json` 单独落盘（调试记录就是这么出来的）。
- 退出码：0 阈值全过；99 有阈值未过（未达标和测试无效都是 99）；107 plan 无效或脚本异常；105 被中断。后端另外认得 110（脚本调用 `exec.test.fail()`，判 `failed`）和 108（`test.abort()`，判 `aborted`）。最终判定顺序：有停止请求或 105 / 108 → `aborted`；没有 `run-record.json` 或其他退出码 → `error`；然后按 `k6Verdict` 得 `invalid` / `failed` / `passed`（`server/runs.py` 的 `_decide`）。
- `open()` 的相对路径相对脚本所在目录，所以 `PLAN_FILE` 必须是绝对路径。
- 到达率必须是整数，小数到达率用 `timeUnit` 换算。

研究阶段的结论和来源见 `docs/research/k6.md` 与 `docs/research/k6-ecosystem.md`。

## 文档结构与维护规则

```text
docs/ARCHITECTURE.md   L1 唯一的架构与总体说明；与其他文档冲突时以它为准
docs/decisions/        L2 ADR-001–005：为什么这样设计（ADR-004 的"只读"已被 ADR-005 取代）
docs/plans/            L2 roadmap.md、mvp-plan.md、mvp-contract.md（三方接口约定）、ai-opportunity-map.md
docs/records/          L2 commit-log.md（提交记录）、tech-notes.md（技术笔记）
docs/research/         L3 研究记录与来源；只作为依据，不随实现频繁更新
```

- **架构说明只保留一份**。新的架构内容写进 `ARCHITECTURE.md`，不要新建平行的架构文档。接口字段级的细节只写在 `mvp-contract.md`，不在 `ARCHITECTURE.md` 里重复。
- 代码改动影响到架构时，同步 `ARCHITECTURE.md`：§1.1 状态表、§5.2 目录树、§8（页面和接口）、§10 技术基线、§11 路线图摘要、§12 不做清单，以及 `plans/roadmap.md`。
- §1.1 状态表必须如实反映"已实现 / 未实现"。没做的能力要标"规划，未实现"，不能把设计写成已有能力。
- 改变已有决定时新增或修订 ADR，而不是只改正文。被取代的 ADR 不删除，在开头标明被哪份 ADR 取代。
- 其他文档按章节号引用 `ARCHITECTURE.md`（如 `§4.7`、`§5.2`、`§6`、`§8.5`）。调整章节后，用 grep 检查并修正这些引用。
- 研究文档里被实测推翻的 [推测]，改成实测结论并注明日期。
- 文档语言：中文为主，技术名词保留英文；图用 Mermaid；研究类结论标注 **[事实]**（带来源）/ **[判断]** / **[推测]**。

## 未决事项

动到相关设计前先向用户确认：

- **自有目标系统**：百度只能冒烟，不能产生性能结论。需要一个可以自由加压的目标（本机没有 Docker 和 sudo，QuickPizza 没有采用）。
- **登录与权限**：现在没有，服务监听 `0.0.0.0`，被测环境的类型和安全上限可以在页面上修改。多人使用或暴露到不可信网络之前必须先做（ADR-005）。
- **目标地址白名单**：非生产类型的被测环境可以不设上限，而任何合法地址都能建成被测环境。要不要限制"只有白名单里的域名才允许不设上限"。
- **执行机过载是否判 `invalid`**：现在只展示采样结果。
- **CI 的入口和平台**：没有命令行入口。是让 CI 调用后端接口，还是"plan 文件 + 命令行"（`ARCHITECTURE.md` §3.8）；平台未定。
- **基线、历史、实验记录的存储形态**：放数据库，还是放 git 以保留审核（`ARCHITECTURE.md` §3.7）。
- **流程的表达力**：需要分支、循环、轮询或数据集时，是扩展数据模型，还是引入手写 JS 模块作为第二种流程类型（ADR-005）。
- **TOB 目标系统**：自建多租户 mock 还是接入真实系统。
