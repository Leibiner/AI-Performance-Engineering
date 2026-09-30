# MVP 契约：三方接口约定

> 日期：2026-09-30 ｜ 适用：MVP（`docs/plans/mvp-plan.md`）
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
| k6 实时仪表盘 | `0.0.0.0:5665`（运行期间才有） |
| 数据库 | `data/app.db`（`DATA_DIR` 可改），不入 git |
| 运行产物 | `results/<runId>/`（`RESULTS_DIR` 可改），不入 git |
| k6 可执行文件 | `.tools/bin/k6`（`K6_BIN` 可改） |
| 同时运行数 | **同一时间只允许 1 个运行** |

## 2. 领域模型与文档术语的对应

| 页面上的名称 | 表 | 对应 `ARCHITECTURE.md` 的概念 |
|---|---|---|
| 环境 | `environments` | Environment（含流量上限护栏） |
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
  "id": 1, "name": "百度（仅冒烟）", "baseUrl": "https://www.baidu.com",
  "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" },
  "maxVus": 2, "maxRate": 2, "maxDurationSec": 60,
  "note": "第三方线上站点，只允许冒烟级别流量"
}
```

`maxVus`、`maxRate`（每秒迭代数）、`maxDurationSec` 是硬性上限，三者必填且为正数。

**接口 `/api/apis`**

```json
{
  "id": 1, "name": "百度首页", "method": "GET", "path": "/",
  "headers": {}, "body": null,
  "expectStatus": 200, "expectBodyContains": "百度",
  "extracts": [ { "var": "token", "from": "json", "expr": "data.token" } ],
  "note": ""
}
```

- `method`：`GET | POST | PUT | PATCH | DELETE`
- `path`：以 `/` 开头，拼在环境的 `baseUrl` 后面
- `body`：字符串或 `null`
- `path`、`headers` 的值、`body` 中可以使用 `{{变量名}}`，运行时替换为之前步骤提取到的变量
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
| `POST /api/runs` | 发起运行。body：`{ "testId": 1, "profileId": 1, "envId": 1, "note": "" }`。成功返回 201 和运行对象（`status: "running"`） |
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
  "envId": 1, "envName": "百度（仅冒烟）",
  "status": "running",
  "verdict": null,
  "startedAt": "2026-09-30T10:15:00.000Z", "endedAt": null,
  "exitCode": null,
  "note": "", "archived": false,
  "summary": null,
  "snapshot": { "...": "发起时的 plan（见 §4），保证以后改定义不影响历史" },
  "record": null,
  "artifacts": ["plan.json"]
}
```

- `status`：`running | finished`
- `verdict`：运行中为 `null`；结束后为 `passed | failed | invalid | error | aborted`
- `summary`（结束后，供列表显示）：`{ "reqs": 10, "rps": 1.2, "p95": 182.4, "errorRate": 0, "checksRate": 1 }`
- `record`：最终的 Run Record（§5）
- `archived`：存档标记。所有运行都会自动保存；"存档"表示长期保留，已存档的运行不能删除

**预检**（`POST /api/runs` 时执行，不通过返回 422）：

1. 测试、负载配置、环境都存在；测试至少有 1 个流程，每个流程至少有 1 个步骤
2. 环境的 `baseUrl` 是合法的 http / https 地址
3. 负载配置不超过环境上限：并发（`vus` 或 `preAllocatedVus`）≤ `maxVus`；到达率（`rate`、`startRate`、各 stage 的 `target`）≤ `maxRate`；总时长 ≤ `maxDurationSec`
4. 没有其他运行正在进行（否则 409）
5. k6 可执行文件存在

### 3.3 其他

| 方法与路径 | 返回 |
|---|---|
| `GET /api/system` | `{ "k6Version": "v2.3.0", "pythonVersion": "3.12.2", "dashboardPort": 5665, "runningRunId": null }` |
| `GET /api/overview` | `{ "counts": { "environments": 1, "apis": 1, "flows": 1, "profiles": 3, "tests": 1, "runs": 12 }, "verdicts": { "passed": 8, "failed": 2, "invalid": 1, "error": 0, "aborted": 1 }, "recentRuns": [运行列表项 × 最近 10 条], "runningRunId": null }` |

## 4. plan.json（后端 → k6）

后端把发起时的测试、流程、接口、负载配置、环境**展开成一份自包含的 plan**，写到 `results/<runId>/plan.json`，同时作为运行的 `snapshot` 存库。

```json
{
  "schemaVersion": 1,
  "runId": "20260930T101500Z-a1b2c3",
  "test": { "id": 1, "name": "百度首页冒烟" },
  "env": { "id": 1, "name": "百度（仅冒烟）", "baseUrl": "https://www.baidu.com", "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" } },
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

### 启动 k6 的方式（后端负责）

```bash
K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_HOST=0.0.0.0 K6_WEB_DASHBOARD_PORT=5665 \
K6_WEB_DASHBOARD_EXPORT=<输出目录>/dashboard.html \
k6 run perf/runner.js \
  -e PLAN_FILE=<输出目录>/plan.json \
  -e OUTPUT_DIR=<输出目录> \
  --tag testid=<runId>
```

- 工作目录是仓库根目录；`PLAN_FILE`、`OUTPUT_DIR` 用绝对路径
- 标准输出和标准错误写入 `<输出目录>/k6.log`
- `testid` tag 只在这里设置一次
- 仪表盘相关环境变量的确切名称以 k6 v2.3.0 实际行为为准，由执行引擎一方验证后更新本节

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
- `k6Verdict`：只根据阈值得出。任一 `validity` 不通过 → `invalid`；否则任一 `slo` 不通过 → `failed`；否则 `passed`

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
  "env": { "id": 1, "name": "百度（仅冒烟）", "baseUrl": "https://www.baidu.com" }
}
```

最终 `verdict` 的判定顺序：

| 条件 | verdict |
|---|---|
| 用户点了停止，或 k6 退出码为 105 / 108 | `aborted` |
| `run-record.json` 不存在或无法解析，或退出码不是 0 / 99 / 110 | `error` |
| `k6Verdict` 为 `invalid` | `invalid` |
| `k6Verdict` 为 `failed`，或退出码为 110 | `failed` |
| 其他 | `passed` |

## 6. 对第三方目标的硬性约束

MVP 的压测目标是 `https://www.baidu.com`，这是第三方线上站点，**只允许冒烟级别的流量**：

- 种子数据中的"百度（仅冒烟）"环境上限：`maxVus: 2`、`maxRate: 2`、`maxDurationSec: 60`
- 开发和联调过程中手动运行 k6 时同样遵守：最多 2 个并发，单次不超过 20 次迭代或 15 秒
- 不允许为了"演示压力测试"而调高这个环境的上限
