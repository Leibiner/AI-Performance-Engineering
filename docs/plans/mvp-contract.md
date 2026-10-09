# MVP 契约：三方接口约定

> 日期：2026-09-30，2026-10-09 加入调试（§3.5、§4 `debug`、§5.1）｜ 适用：MVP（`docs/plans/mvp-plan.md`）
> 本文是执行引擎（`perf/`）、后端（`server/`）、前端（`web/`）之间的**唯一约定**。三方并行开发，任何一方发现约定不够用或有问题，先改本文，再改代码。

---

## 1. 总体结构

```text
浏览器（Windows）
   │  http://192.168.0.136:8088
   ▼
server/（Python 3.12 + FastAPI + sqlite3，依赖由 uv 管理）
   ├─ 静态托管 web/dist
   ├─ /api/*  增删改查 + 发起 / 停止运行
   ├─ data/app.db          SQLite：定义 + 运行存档
   └─ 发起运行时：生成 plan.json → 启动 k6 子进程
                                   │
                                   ▼
                     k6 run perf/runner.js   （读取 plan.json）
                                   │  只请求 plan.env.baseUrl
                                   ▼
                     results/<runId>/{plan.json, run-record.json, k6-summary.json, dashboard.html, k6.log}
```

| 项 | 值 |
|---|---|
| 服务地址 | `0.0.0.0:8088`（环境变量 `PORT`、`HOST` 可改） |
| 启动命令 | `uv run uvicorn server.main:app --host 0.0.0.0 --port 8088`（在仓库根目录执行） |
| k6 实时仪表盘 | `127.0.0.1:5665`，**只监听本机、不对外开放**（原因见 §4）。开启它只是为了在结束时导出 `dashboard.html` |
| 数据库 | `data/app.db`（`DATA_DIR` 可改），不入 git |
| 运行产物 | `results/<runId>/`（`RESULTS_DIR` 可改），不入 git |
| k6 可执行文件 | `.tools/bin/k6`（`K6_BIN` 可改） |
| 同时运行数 | **同一时间只允许 1 个运行** |

## 2. 领域模型与文档术语的对应

| 页面上的名称 | 表 | 对应 `ARCHITECTURE.md` 的概念 |
|---|---|---|
| 执行机 | `executors` | Load Generator：安装了本项目、实际运行 k6 的机器 |
| 被测环境 | `environments` | Environment：被测系统的某个环境（开发 / 测试 / 预发 / 生产），含安全上限 |
| 接口 | `apis` | Service 中的一个请求 |
| 业务流程 | `flows` | Flow（按顺序执行的接口步骤） |
| 负载配置 | `profiles` | Load Profile（显式 `model: open / closed`） |
| 测试 | `tests` | Test Definition（Flow Mix + SLO） |
| 运行 | `runs` | Run + Run Record + Verdict |

业务（接口、流程）与负载（负载配置）仍然分开维护，只在发起运行时由后端组装成 plan，再由 `perf/core/compose.js` 生成 k6 的 scenarios 和 thresholds。

## 3. REST API

基础路径 `/api`。请求和响应都是 JSON，字段用 camelCase，时间用 ISO 8601 UTC 字符串。

错误响应统一为：

```json
{ "error": { "code": "VALIDATION_FAILED", "message": "人能读懂的中文说明", "details": ["可选的逐条原因"] } }
```

| HTTP 状态 | code | 场景 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 字段缺失或格式错误 |
| 404 | `NOT_FOUND` | 资源不存在 |
| 409 | `CONFLICT` | 已有运行在进行中；被引用的资源不能删除；已存档的运行不能删除 |
| 422 | `PREFLIGHT_REJECTED` | 预检不通过（`details` 逐条列出原因） |
| 500 | `INTERNAL` | 其他 |

### 3.1 定义类资源（统一的增删改查）

每个资源都有：`GET /api/<res>`（返回数组）、`POST /api/<res>`、`GET /api/<res>/:id`、`PUT /api/<res>/:id`（整体替换）、`DELETE /api/<res>/:id`。

所有资源都带 `id`（整数）、`createdAt`、`updatedAt`。

**环境 `/api/environments`**

```json
{
  "id": 1, "name": "百度（仅冒烟）", "type": "prod", "baseUrl": "https://www.baidu.com",
  "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" },
  "variables": { "tenant": "demo" },
  "maxVus": 2, "maxRate": 2, "maxDurationSec": 60,
  "note": "第三方线上站点，只允许冒烟级别流量"
}
```

- `headers`：公共请求头，每个请求都带；接口自己的同名请求头（名称不区分大小写）覆盖它
- `variables`（2026-10-09 加入）：环境变量的**初始值**，变量名 → 字符串，变量名只能是字母、数字、下划线。运行时每次迭代开始、调试开始时都以它为初始变量，接口里用 `{{变量名}}` 引用；步骤提取到的同名变量在本次迭代内覆盖它。运行不会回写它

- 这里的"环境"指**被测环境**（被测系统部署在哪里），不是执行机（§3.3）。
- `type`：`dev`（开发）、`test`（测试）、`staging`（预发）、`prod`（生产），必填。
- `maxVus`、`maxRate`（每秒迭代数）、`maxDurationSec` 是**安全上限**：保护被测环境的护栏，不是负载配置。不管选哪个负载配置，超过上限就被预检拒绝。
  - 每项为正数或 `null`，`null` 表示不限制。
  - `type` 为 `prod` 时三项都必填（不能为 `null`）；其他类型可以留空。

**文件夹 `/api/folders`**（接口的分组，可嵌套，例如"项目 → 模块"；2026-10-09 加入）

```json
{ "id": 3, "name": "订单模块", "parentId": 1, "note": "" }
```

- `parentId`：上级文件夹的 id，`null` 表示顶层。不能是自己或自己的子孙（PUT 时后端据路径里的 id 校验，返回 400）
- 非空的文件夹（还有子文件夹或接口）不能删除，返回 409 并逐条列出
- 文件夹只用于页面上的分组，不进 plan.json，也不影响运行

**接口 `/api/apis`**

```json
{
  "id": 1, "folderId": null, "name": "百度首页", "method": "GET", "path": "/",
  "headers": {}, "body": null,
  "expectStatus": 200, "expectBodyContains": "百度",
  "extracts": [ { "var": "token", "from": "json", "expr": "data.token" } ],
  "note": ""
}
```

- `folderId`：所属文件夹的 id，`null` 表示在根目录；指向不存在的文件夹返回 400。调试接口（§3.5）的内联 `api` 可以不带这个字段
- `method`：`GET | POST | PUT | PATCH | DELETE`
- `path`：以 `/` 开头，拼在环境的 `baseUrl` 后面
- `body`：字符串或 `null`
- `path`、`headers` 的值、`body`、`expectBodyContains` 中可以使用 `{{变量名}}`，运行时替换为环境变量或之前步骤提取到的变量
- 发送前，引擎把最终 URL 里的非 ASCII 字符和空白按 UTF-8 百分号编码（`keyword=键盘` → `keyword=%E9%94%AE%E7%9B%98`），已有的 `%XX` 和 ASCII 符号不动；变量值里的 `&`、`/` 等不编码
- `expectBodyContains`：字符串或 `null`
- `extracts[].from`：`json`（`expr` 是点号路径，如 `data.items.0.id`）、`regex`（`expr` 是正则，取第 1 个捕获组）、`header`（`expr` 是响应头名称）

**业务流程 `/api/flows`**

```json
{
  "id": 1, "name": "访问首页", "note": "",
  "steps": [ { "apiId": 1, "thinkTimeMs": 500 } ]
}
```

`GET` 返回时每个 step 额外带 `apiName`、`method`、`path`（只读，方便显示）。接口被流程引用时不能删除（409）。

**负载配置 `/api/profiles`**

```json
{
  "id": 1, "name": "冒烟", "type": "smoke", "model": "closed",
  "config": { "vus": 1, "iterations": 10, "maxDurationSec": 30 },
  "note": ""
}
```

- `type`：`smoke | average | stress | spike | soak | breakpoint`（仅作分类标签）
- `model`：`closed` 或 `open`，必填
- `config` 的四种形态（后端校验，其他组合拒绝）：

| model | 形态 | 字段 | 对应 executor |
|---|---|---|---|
| closed | 固定迭代数 | `vus`, `iterations`, `maxDurationSec` | `shared-iterations` |
| closed | 固定并发 | `vus`, `durationSec` | `constant-vus` |
| open | 固定到达率 | `rate`（每秒迭代数）, `durationSec`, `preAllocatedVus` | `constant-arrival-rate` |
| open | 阶梯到达率 | `startRate`, `stages: [{ "target": 2, "durationSec": 30 }]`, `preAllocatedVus` | `ramping-arrival-rate` |

**测试 `/api/tests`**

```json
{
  "id": 1, "name": "百度首页冒烟", "note": "",
  "flows": [ { "flowId": 1, "weight": 1 } ],
  "slo": { "p95Ms": 2000, "p99Ms": null, "errorRate": 0.01, "checksRate": 0.99 }
}
```

- `flows[].weight`：正数，后端不要求和为 1，组装 plan 时归一化
- `slo` 各字段可为 `null`（表示不设该项）
- `GET` 返回时每个 flow 额外带 `flowName`；另带 `lastRun: { runId, verdict, startedAt } | null`
- 流程被测试引用时不能删除（409）；测试、负载配置、环境有运行记录时可以删除（运行里存了快照）

### 3.2 运行 `/api/runs`

| 方法与路径 | 说明 |
|---|---|
| `POST /api/runs` | 发起运行。body：`{ "testId": 1, "profileId": 1, "envId": 1, "executorId": 1, "confirmProd": false, "note": "" }`。`executorId` 可省略，默认用本机执行机。被测环境类型为 `prod` 时必须带 `"confirmProd": true`（只有布尔值 `true` 算确认；不是布尔值返回 400），否则预检不通过。成功返回 201 和运行对象（`status: "running"`） |
| `GET /api/runs?testId=&verdict=&status=&archived=&page=1&pageSize=20` | 列表，按开始时间倒序。返回 `{ "items": [...], "total": 123 }`，列表项不含 `snapshot` 和 `record` |
| `GET /api/runs/:runId` | 详情，含 `snapshot`、`record`、`artifacts` |
| `POST /api/runs/:runId/stop` | 停止正在进行的运行（向 k6 发 SIGINT）。不在运行中返回 409 |
| `PATCH /api/runs/:runId` | 修改 `note` 和 / 或 `archived` |
| `DELETE /api/runs/:runId` | 删除记录和产物目录。运行中或已存档返回 409 |
| `GET /api/runs/:runId/artifacts/:name` | 下载或查看产物。`name` 只能是 `plan.json`、`run-record.json`、`k6-summary.json`、`dashboard.html`、`k6.log` |

运行对象：

```json
{
  "runId": "20260930T101500Z-a1b2c3",
  "testId": 1, "testName": "百度首页冒烟",
  "profileId": 1, "profileName": "冒烟",
  "envId": 1, "envName": "百度（仅冒烟）", "envType": "prod",
  "executorId": 1, "executorName": "本机执行机",
  "status": "running",
  "verdict": null,
  "startedAt": "2026-09-30T10:15:00.000Z", "endedAt": null,
  "exitCode": null,
  "note": "", "archived": false,
  "summary": null,
  "snapshot": { "...": "发起时的 plan（见 §4），保证以后改定义不影响历史" },
  "record": null,
  "stopRequested": false,
  "progress": "running (05.0s), 1/1 VUs, 7 complete and 0 interrupted iterations",
  "artifacts": ["plan.json", "k6.log"]
}
```

- `status`：`running | finished`
- `verdict`：运行中为 `null`；结束后为 `passed | failed | invalid | error | aborted`
- `summary`（结束后，供列表显示）：`{ "reqs": 10, "rps": 1.2, "p95": 182.4, "errorRate": 0, "checksRate": 1 }`
- `record`：最终的 Run Record（§5）
- `archived`：存档标记。所有运行都会自动保存；"存档"表示长期保留，已存档的运行不能删除
- `stopRequested`：用户已请求停止但 k6 还没退出时为 `true`
- `progress`：运行中为 k6 日志里最新的一行进度文本（刚启动时可能为 `null`）；结束后为 `null`。前端靠轮询这个字段显示进度
- `artifacts`：当前实际存在的产物文件名。`dashboard.html` 是可选的，运行太短或被中止时可能没有

返回约定：定义类资源的 POST 返回 201 和对象，PUT 返回 200 和对象，DELETE 返回 200 和 `{"ok": true}`。运行的 stop、PATCH 返回完整运行对象，DELETE 返回 `{"ok": true}`。产物地址加 `?download=1` 时作为附件下载。

**预检**（`POST /api/runs` 时执行，不通过返回 422）：

1. 测试、负载配置、环境都存在；测试至少有 1 个流程，每个流程至少有 1 个步骤
2. 环境的 `baseUrl` 是合法的 http / https 地址
3. 负载配置不超过被测环境的安全上限（只检查不为 `null` 的项）：并发（`vus` 或 `preAllocatedVus`）≤ `maxVus`；到达率（`rate`、`startRate`、各 stage 的 `target`）≤ `maxRate`；总时长 ≤ `maxDurationSec`。被测环境类型为 `prod` 时，请求里必须带 `"confirmProd": true`
4. 负载配置属于 §3.1 的四种形态之一
5. 流程数量不超过并发：closed 模型下 `vus`（以及固定迭代数形态的 `iterations`）不小于测试的流程数量；open 模型下 `preAllocatedVus` 不小于流程数量（每个流程至少要有 1 个 VU）
6. 没有其他运行正在进行（否则 409）
7. k6 可执行文件存在

测试、负载配置或环境不存在也算预检不通过，返回 422。

### 3.3 执行机 `/api/executors`

执行机是安装了本项目、实际运行 k6 的机器。目前只有一台：运行后端服务的这台机器（`kind: "local"`），由后端在建库时自动创建。多台执行机属于分布式执行，尚未实现，所以没有新增和删除接口。

| 方法与路径 | 说明 |
|---|---|
| `GET /api/executors` | 返回数组（目前恒为 1 项） |
| `GET /api/executors/:id` | 单个 |
| `PUT /api/executors/:id` | 只能改 `name` 和 `note`：没给的那项保持原值，其余字段忽略（前端把整个对象原样送回也可以） |

```json
{
  "id": 1, "name": "本机执行机", "kind": "local", "note": "",
  "host": "主机名", "ip": "192.168.0.136",
  "os": "Ubuntu 24.04.4 LTS", "arch": "x86_64",
  "cpuCores": 4, "memTotalMb": 15900, "memAvailableMb": 7000,
  "loadAvg1": 0.35, "diskFreeGb": 99.1,
  "k6Version": "v2.3.0", "k6Path": "/abs/.tools/bin/k6",
  "pythonVersion": "3.12.2", "uvVersion": "0.11.18",
  "projectDir": "/abs/仓库根目录", "resultsDir": "/abs/results", "dataDir": "/abs/data",
  "status": "idle", "runningRunId": null,
  "createdAt": "2026-09-30T06:00:00.000Z", "updatedAt": "2026-09-30T06:00:00.000Z"
}
```

- `name`、`note` 存库，可修改；其余字段每次请求时实时采集，取不到的给 `null`
- `status`：`idle | running`
- 内存和磁盘按 1024 进制换算（MiB、GiB）

**运行期间的执行机采样**：运行期间后端每秒采样一次本机 CPU 和内存占用，结束时写进最终 Run Record：

```json
"executor": {
  "id": 1, "name": "本机执行机", "host": "主机名", "cpuCores": 4, "memTotalMb": 15900,
  "cpuAvgPct": 12.3, "cpuMaxPct": 41.0, "memMaxPct": 55.2, "samples": 9
}
```

- CPU 占用是整机所有核合计的百分比；采样间隔 1 秒，所以不到 1 秒的运行没有样本
- 没有采到样本时三个百分比为 `null`、`samples` 为 0
- 目前只作为信息展示，**不参与判定**
- plan.json 的 `env` 和最终 Run Record 的 `env` 都带 `type` 字段

**旧运行**：加入执行机和环境类型之前的运行，库里的 `envType`、`executorId`、`executorName` 在迁移时已经补上，但它们的 `snapshot.env`、`record.env` 没有 `type`，`record` 里也没有 `executor`（存档不回改）。前端读这几处时要容忍不存在。

### 3.4 其他

| 方法与路径 | 返回 |
|---|---|
| `GET /api/system` | `{ "k6Version": "v2.3.0", "pythonVersion": "3.12.2", "dashboardPort": 5665, "runningRunId": null }`（`dashboardPort` 仅供排查，前端不使用） |
| `GET /api/overview` | `{ "counts": { "environments": 1, "apis": 1, "flows": 1, "profiles": 3, "tests": 1, "executors": 1, "runs": 12 }, "verdicts": { "passed": 8, "failed": 2, "invalid": 1, "error": 0, "aborted": 1 }, "recentRuns": [运行列表项 × 最近 10 条], "runningRunId": null }` |

### 3.5 调试 `/api/debug`

调试 = 用真实 k6 把一个接口或一个业务流程**跑一次迭代**（1 并发、1 次迭代），把每一步实际发出的请求、收到的响应、检查结果和提取到的变量原样返回给页面。它走的是和压测完全相同的执行代码（`perf/core/interp.js`），所以调试里看到的变量替换、请求头合并、检查和提取结果，就是压测时会发生的事。

| 方法与路径 | 说明 |
|---|---|
| `POST /api/debug` | 同步执行，k6 退出后才返回（通常 1–3 秒；最长 90 秒）。成功返回 200 和调试结果 |

请求体（`api` 和 `flowId` **恰好给一个**）：

```json
{
  "envId": 1,
  "confirmProd": true,
  "vars": { "token": "abc" },
  "api": { "name": "查订单", "method": "GET", "path": "/api/orders/{{orderId}}", "headers": {}, "body": null,
           "expectStatus": 200, "expectBodyContains": null, "extracts": [], "note": "" },
  "flowId": 3
}
```

- `envId`：被测环境，必填。请求发往它的 `baseUrl`，并带上它的公共请求头
- `confirmProd`：被测环境类型为 `prod` 时必须为 `true`（一次请求也是请求，和发起运行的规则一致）
- `vars`：可选，调试的**当前值**（值必须是字符串），覆盖被测环境 `variables` 里的同名初始值。页面按环境保存当前值（只存改过的，没有当前值的变量用初始值），每次调试后把提取到的变量写进当前值，请求里只带当前值，所以连续调试时上一步取到的 token 能直接用于下一步；试跑流程时它是迭代开始前的初值，会被后续步骤提取到的同名变量覆盖
- `api`：一份接口定义（字段同 §3.1 的接口，**不要求已保存**，页面上正在编辑的内容可以直接发），按单步流程执行；校验失败返回 400，`details` 和保存接口时一致
- `flowId`：已保存的业务流程，按它的步骤顺序执行

调试和运行的差别（除此以外行为一致）：

| 项 | 运行 | 调试 |
|---|---|---|
| 负载 | 负载配置 | 固定 1 并发、1 次迭代，最长时长取 60 秒与被测环境 `maxDurationSec` 中的小者 |
| 等待时间 `thinkTimeMs` | 等待 | **不等待** |
| 响应体 | 用不到时不保留 | 保留，最多 64 KB（`bodyTruncated` 标出被截断） |
| 某一步检查不通过 | 本次迭代余下步骤不执行 | 同样不执行，余下步骤以 `status: "skipped"` 返回 |
| 阈值、判定、Run Record、运行记录、产物、仪表盘、执行机采样 | 有 | **都没有**。调试不进运行列表，产物目录读完即删 |
| 与其他运行的关系 | 同一时间 1 个 | 有运行在进行时不能调试（409）；调试进行中不能发起运行（409）；同一时间只允许 1 个调试 |

响应（200）：

```json
{
  "debugId": "dbg-20261009T062206Z-6abec2",
  "ok": true,
  "env": { "id": 1, "name": "百度（仅冒烟）", "type": "prod", "baseUrl": "https://www.baidu.com" },
  "source": { "kind": "api", "name": "百度首页" },
  "durationMs": 812,
  "exitCode": 0,
  "steps": [
    {
      "key": "f1s1", "name": "百度首页", "status": "passed",
      "request": { "method": "GET", "url": "https://www.baidu.com/", "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" }, "body": null },
      "response": {
        "status": 200, "statusText": "200 OK", "finalUrl": "https://www.baidu.com/",
        "headers": { "Content-Type": "text/html; charset=utf-8" }, "contentType": "text/html; charset=utf-8",
        "bodyLength": 227310, "body": "<!DOCTYPE html>…", "bodyTruncated": true, "bodyOmitted": false
      },
      "timings": { "durationMs": 120.3, "blockedMs": 1.2, "lookingUpMs": 0.4, "connectingMs": 10.1, "tlsMs": 20.5,
                   "sendingMs": 0.1, "waitingMs": 80.2, "receivingMs": 9.4 },
      "error": null,
      "checks": [ { "name": "[f1s1] 状态码为 200", "ok": true }, { "name": "[f1s1] 响应包含「百度」", "ok": true } ],
      "extracted": [ { "var": "word", "from": "json", "expr": "q", "ok": true, "value": "k6" } ],
      "vars": { "word": "k6" }
    }
  ],
  "vars": { "word": "k6" }
}
```

- `ok`：所有步骤 `status` 都是 `passed`
- `source`：调试的对象。`{ "kind": "api", "name" }` 或 `{ "kind": "flow", "id", "name" }`
- `durationMs`：后端从启动 k6 到它退出的墙钟时间（含 k6 启动开销，不是响应时间）；`exitCode`：k6 退出码（调试不评估阈值，正常为 0）
- `steps[]` 的结构就是引擎写出的调试记录（§5.1），后端不改内容；`vars` 是迭代结束时的全部变量
- `steps[].status`：`passed`（全部检查通过）、`failed`（有检查未通过；网络错误、超时也算在内，因为状态码检查不会通过）、`skipped`（前面有步骤失败，这一步没有执行，`request`、`response`、`timings` 为 `null`）、`error`（执行这一步时脚本抛出异常，例如地址非法，`error` 为异常文字，`response` 为 `null`）
- `response.body`：文本。`contentType` 不像文本（不是 `text/*`、JSON、XML、JavaScript、表单编码）时不返回正文，`bodyOmitted` 为 `true`、`body` 为 `null`；超过 64 KB 时截断，`bodyTruncated` 为 `true`。`bodyLength` 是截断前的字符数
- `timings` 单位毫秒，对应 k6 的 `res.timings`（`duration` = 发出请求到收完响应，不含 `blocked`）
- `request` 是这一步实际发出的第一个请求（变量已替换、请求头已和环境合并）；有重定向时 `response.finalUrl` 是最后一跳的地址，状态码和响应体也是最后一跳的

错误：

| HTTP 状态 | code | 场景 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 字段缺失、`api` 与 `flowId` 不是恰好一个、`vars` 的值不是字符串、`api` 定义不合法（`details` 逐条） |
| 422 | `PREFLIGHT_REJECTED` | 被测环境或流程不存在、流程没有步骤、步骤引用的接口不存在、`baseUrl` 非法、生产环境没有 `confirmProd: true`、k6 不存在 |
| 409 | `CONFLICT` | 有运行在进行中，或上一次调试还没结束 |
| 500 | `DEBUG_FAILED` | k6 没有产出调试记录（脚本异常、plan 无效、超时）。`details` 是 k6 日志的最后若干行，页面原样显示 |

## 4. plan.json（后端 → k6）

后端把发起时的测试、流程、接口、负载配置、环境**展开成一份自包含的 plan**，写到 `results/<runId>/plan.json`，同时作为运行的 `snapshot` 存库。

```json
{
  "schemaVersion": 1,
  "runId": "20260930T101500Z-a1b2c3",
  "test": { "id": 1, "name": "百度首页冒烟" },
  "env": { "id": 1, "name": "百度（仅冒烟）", "type": "prod", "baseUrl": "https://www.baidu.com", "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" }, "variables": {} },
  "profile": { "id": 1, "name": "冒烟", "type": "smoke", "model": "closed", "config": { "vus": 1, "iterations": 10, "maxDurationSec": 30 } },
  "flows": [
    {
      "key": "f1", "name": "访问首页", "weight": 1,
      "steps": [
        {
          "key": "f1s1", "name": "百度首页", "method": "GET", "path": "/",
          "headers": {}, "body": null,
          "expectStatus": 200, "expectBodyContains": "百度",
          "extracts": [],
          "thinkTimeMs": 500
        }
      ]
    }
  ],
  "slo": { "p95Ms": 2000, "p99Ms": null, "errorRate": 0.01, "checksRate": 0.99 }
}
```

- `flows[].key`：`f<序号>`；`steps[].key`：`<flowKey>s<序号>`。只用 ASCII，因为要作为 k6 的 scenario 名和 tag 值
- `weight` 已归一化，和为 1
- `env.variables`：被测环境的环境变量初始值，每次迭代开始时的变量；调试时 `debug.vars` 覆盖同名项。旧的快照没有这个字段，引擎按空对象处理
- `debug`（可选，只有调试时有，见 §3.5）：`{ "vars": { "token": "abc" }, "bodyLimit": 65536 }`。存在时引擎进入**调试模式**：不等待 `thinkTimeMs`；每一步都保留响应体（最多 `bodyLimit` 个字符）；逐步记录请求、响应、检查和变量；迭代结束后把记录写到 console（§5.1）；`handleSummary` 不写 `run-record.json` 和 `k6-summary.json`。调试的 plan 里 `test.id` 为 `0`、`profile.id` 为 `0`、`profile.name` 为"调试"，`profile.config` 固定为 `{ "vus": 1, "iterations": 1, "maxDurationSec": N }`，`slo` 四项都为 `null`；`runId` 形如 `dbg-20261009T062206Z-6abec2`

### 启动 k6 的方式（后端负责）

```bash
K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_HOST=127.0.0.1 K6_WEB_DASHBOARD_PORT=5665 \
K6_WEB_DASHBOARD_EXPORT=<输出目录>/dashboard.html K6_WEB_DASHBOARD_PERIOD=1s \
k6 run perf/runner.js \
  -e PLAN_FILE=<输出目录>/plan.json \
  -e OUTPUT_DIR=<输出目录> \
  --tag testid=<runId>
```

- 工作目录是仓库根目录；`PLAN_FILE`、`OUTPUT_DIR` 用绝对路径
- 标准输出和标准错误写入 `<输出目录>/k6.log`
- `testid` tag 只在这里设置一次
- **实时仪表盘不能给浏览器用**：联调实测，只要有浏览器连着 `:5665`，k6 跑完后就不会退出（它等页面关闭），也不写 `run-record.json`，运行会一直停在"运行中"。所以仪表盘只监听 `127.0.0.1`，页面上不嵌入也不链接它；运行中的进度由运行对象的 `progress` 字段提供，结束后的图表用导出的 `dashboard.html`
- 仪表盘的环境变量名已在 k6 v2.3.0 实测有效。运行期间监听 `*:5665`，页面在 `/ui/`（访问 `/` 会跳转过去）；k6 退出后端口随之关闭
- `K6_WEB_DASHBOARD_PERIOD`（聚合周期）默认 10s。不设置时，几秒到十几秒的短运行会因为数据点不够而**跳过 HTML 导出**（日志里有一条 warning，退出码不受影响）；设为 `1s` 后，3 秒的运行也能导出。即便如此，`dashboard.html` 仍应当作可选产物处理（运行太短或启动失败时不存在）

### 启动调试的方式（后端负责）

```bash
K6_WEB_DASHBOARD=false \
k6 run perf/runner.js \
  -e PLAN_FILE=<调试目录>/plan.json \
  -e OUTPUT_DIR=<调试目录> \
  --no-thresholds --no-usage-report --quiet \
  --log-format=json --console-output=<调试目录>/debug-console.log
```

- 调试目录是 `results/_debug/<debugId>/`，k6 退出、后端读完记录后整个删除；服务启动时清掉上次遗留的
- 不开仪表盘，不设 `testid` tag，不评估阈值（`--no-thresholds`，所以退出码正常为 0；107 仍表示 plan 无效或脚本异常）
- `--console-output` 把脚本里 `console.log` 的内容单独写到一个文件，`--log-format=json` 让每行是一个 JSON 对象（`msg` 字段是原文），后端从这个文件取调试记录（§5.1）；标准输出和标准错误仍写 `k6.log`，只在失败时用来给出原因
- 超时：k6 90 秒还没退出就发一次 SIGINT，再等 10 秒不退就强杀，返回 500 `DEBUG_FAILED`

## 5. 运行产物（k6 → 后端）

`perf/runner.js` 的 `handleSummary` 写两个文件：

- `<OUTPUT_DIR>/k6-summary.json`：k6 原始 summary 数据
- `<OUTPUT_DIR>/run-record.json`：下面的结构

```json
{
  "schemaVersion": 1,
  "runId": "20260930T101500Z-a1b2c3",
  "k6Verdict": "passed",
  "thresholds": [
    { "metric": "http_req_duration", "expr": "p(95)<2000", "kind": "slo", "ok": true, "label": "全部请求 p95 < 2000 ms" },
    { "metric": "http_req_failed", "expr": "rate<0.01", "kind": "slo", "ok": true, "label": "错误率 < 1%" },
    { "metric": "checks", "expr": "rate>=0.99", "kind": "validity", "ok": true, "label": "检查通过率 ≥ 99%" }
  ],
  "metrics": {
    "overall": {
      "reqs": 10, "rps": 1.2, "iterations": 10, "droppedIterations": 0, "vusMax": 1,
      "avg": 120.1, "p50": 110.0, "p90": 170.2, "p95": 182.4, "p99": 201.3, "max": 210.0,
      "errorRate": 0, "checksRate": 1, "dataReceived": 123456, "dataSent": 2345
    },
    "steps": [
      { "flowKey": "f1", "flowName": "访问首页", "stepKey": "f1s1", "stepName": "百度首页",
        "count": 10, "avg": 120.1, "p50": 110.0, "p95": 182.4, "p99": 201.3, "max": 210.0, "errorRate": 0 }
    ]
  },
  "testDurationMs": 8400
}
```

- 时间类指标单位都是毫秒
- `thresholds[].kind`：
  - `slo`：系统是否达标（来自 `plan.slo`）
  - `validity`：本次测试是否可信（`checks` 通过率；open 模型下的 `dropped_iterations`）
  - 只为了让 k6 在 summary 里输出分步骤指标而加的占位阈值**不出现在这个数组里**
- `plan.slo.checksRate` 为 `null` 时，仍然附加 `checks` 的 validity 阈值，下限取默认值 0.99
- 没有样本时用 `null` 而不是 0：某个步骤一次请求都没发出（例如前一步的检查没通过，本次迭代提前结束）时，该步骤的 `count` 为 0，`avg / p50 / p95 / p99 / max / errorRate` 为 `null`；整个运行没有发出任何请求时，`overall` 里的时间类字段和 `errorRate`、`checksRate` 同样为 `null`
- `steps[].count` 是这一步发出的 HTTP 请求数；被自动跟随的重定向每一跳各算一次
- `k6Verdict`：只根据阈值得出。任一 `validity` 不通过 → `invalid`；否则任一 `slo` 不通过 → `failed`；否则 `passed`

### 5.1 调试记录（k6 → 后端，只在调试模式）

plan 带 `debug` 时，引擎在**迭代结束时**（无论成功、失败还是中途异常）执行一次：

```js
console.log(JSON.stringify({ debugTrace: { steps: [...], vars: {...} } }))
```

经 `--console-output` + `--log-format=json`，文件里是一行 `{"level":"info","msg":"{\"debugTrace\":…}","source":"console","time":"…"}`；后端取最后一行含 `debugTrace` 的 `msg` 解析。`steps[]` 每项的字段见 §3.5 的响应示例，要点：

- 顺序和 plan 里的步骤一致，每个步骤恰好一项；没执行到的以 `status: "skipped"` 出现
- `checks[].name` 和压测时写进 k6 `checks` 指标的名称相同（`[步骤 key] 状态码为 200` 等）
- `extracted[]` 每条提取规则一项：`ok` 表示取到了值；`value` 是存进变量的字符串（对象会被 `JSON.stringify`），没取到为 `null`
- `vars` 是这一步之后的全部变量快照；最外层的 `vars` 是迭代结束时的
- 调试模式下 `handleSummary` 返回空对象：不写 `run-record.json`、`k6-summary.json`，也不打印摘要

为什么用 console 而不是 `handleSummary`：k6 在独立的运行时里执行 `handleSummary`，VU 里给模块变量赋的值它看不到；VU 代码也不能写文件。console 是 VU 把一段结构化数据交给外界的唯一通道。

### 后端补全为最终 Run Record

k6 退出后，后端读取 `run-record.json`，补上以下字段，回写文件并存库：

```json
{
  "verdict": "passed",
  "exitCode": 0,
  "window": { "start": "2026-09-30T10:15:00.000Z", "end": "2026-09-30T10:15:09.000Z" },
  "fingerprint": { "k6Version": "v2.3.0", "pythonVersion": "3.12.2", "gitSha": "a6a37ee", "host": "主机名" },
  "test": { "id": 1, "name": "百度首页冒烟" },
  "profile": { "id": 1, "name": "冒烟", "model": "closed" },
  "env": { "id": 1, "name": "百度（仅冒烟）", "type": "prod", "baseUrl": "https://www.baidu.com" },
  "executor": { "id": 1, "name": "本机执行机", "host": "主机名", "cpuCores": 4, "memTotalMb": 15900, "cpuAvgPct": 12.3, "cpuMaxPct": 41.0, "memMaxPct": 55.2, "samples": 9 }
}
```

`executor` 的含义见 §3.3。

最终 `verdict` 的判定顺序：

| 条件 | verdict |
|---|---|
| 用户点了停止，或 k6 退出码为 105 / 108 | `aborted` |
| `run-record.json` 不存在或无法解析，或退出码不是 0 / 99 / 110 | `error` |
| `k6Verdict` 为 `invalid` | `invalid` |
| `k6Verdict` 为 `failed`，或退出码为 110 | `failed` |
| 其他 | `passed` |

最终 Run Record 还带一个 `verdictReason`：一句中文，说明判定的原因（如"全部阈值通过""SLO 阈值未通过""用户请求停止"）。没有 `run-record.json` 时后端写一份骨架（`thresholds: []`、`metrics: null`），保证 `record` 总是存在。

## 6. 对第三方目标的硬性约束

MVP 的压测目标是 `https://www.baidu.com`，这是第三方线上站点，**只允许冒烟级别的流量**：

- 种子数据中的"百度（仅冒烟）"环境上限：`maxVus: 2`、`maxRate: 2`、`maxDurationSec: 60`
- 开发和联调过程中手动运行 k6 时同样遵守：最多 2 个并发，单次不超过 20 次迭代或 15 秒
- 不允许为了"演示压力测试"而调高这个环境的上限
