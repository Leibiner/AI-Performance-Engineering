# MVP 契约：三方接口约定

> 日期：2026-09-30，2026-10-09 加入调试（§3.5、§4 `debug`、§5.1），2026-10-10 加入测试数据与变量分层（§3.1「变量」、§3.6、§3.7，ADR-006）｜ 适用：MVP（`docs/plans/mvp-plan.md`）
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
                     results/<runId>/datasets/、files/   （用到时才有：本次运行用到的数据集和文件，k6 的输入）
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
| 数据集 | `datasets` | Data：只读数据集（表头即变量名，绑定在业务流程上） |
| 文件 | `files` | 接口请求体里引用的文件（multipart 上传） |
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
| 409 | `CONFLICT` | 已有运行在进行中；非空的文件夹不能删除；已存档的运行不能删除 |
| 413 | `PAYLOAD_TOO_LARGE` | 请求体超过 32 MiB（2026-10-10 加入；数据集和文件本身的上限是 10 MiB，见 §3.6、§3.7） |
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
- `variables`（2026-10-09 加入）：环境变量的**初始值**，变量名 → 字符串，变量名的规则见下文「变量」。运行时每次迭代开始、调试开始时都以它为初始变量，接口里用 `{{变量名}}` 引用；数据集的行、流程变量、提取到的同名变量会覆盖它（分层见下文「变量」）。运行不会回写它

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
  "headers": {}, "bodyType": "raw", "body": null, "form": [],
  "expectStatus": 200, "expectBodyContains": "百度",
  "extracts": [ { "var": "token", "from": "json", "expr": "data.token" } ],
  "note": ""
}
```

- `folderId`：所属文件夹的 id，`null` 表示在根目录；指向不存在的文件夹返回 400。调试接口（§3.5）的内联 `api` 可以不带这个字段
- `method`：`GET | POST | PUT | PATCH | DELETE`
- `path`：以 `/` 开头，拼在环境的 `baseUrl` 后面
- `bodyType`（2026-10-10 加入，省略时为 `raw`）：请求体的类型，决定用 `body` 还是 `form`
  - `raw`：发送 `body`（字符串或 `null`，`null` 即没有请求体）。`body` 以 `{` 或 `[` 开头且请求头里没有 `Content-Type` 时，引擎补 `application/json`
  - `form`：把 `form` 编码成 `application/x-www-form-urlencoded` 发送。顺序按 `form` 的顺序，名称和值按 UTF-8 百分号编码，空格编码为 `+`。**接口自己的** `headers` 里没有 `Content-Type` 时，引擎设为 `application/x-www-form-urlencoded`（被测环境公共请求头里的 `Content-Type` 是给所有接口的默认值，不压过接口选的请求体类型）
  - `multipart`：把 `form` 编码成 `multipart/form-data` 发送，顺序按 `form` 的顺序。引擎**去掉**合并后请求头里的 `Content-Type`（含被测环境的公共请求头），换成带 boundary 的 `multipart/form-data; boundary=…`
- `body`：字符串或 `null`。`bodyType` 不是 `raw` 时保留但不发送（切换类型不丢内容）
- `form`：数组，每项 `{ "name": "file", "type": "text" | "file", "value": "…", "fileId": null }`
  - `name` 必填；`type` 为 `text` 时发送 `value`（字符串），`fileId` 为 `null`
  - `type` 为 `file` 时 `fileId` 必须是已上传的文件（§3.7），`value` 为 `""`；文件名和 `Content-Type` 取文件自己的 `name`、`contentType`
  - `bodyType` 为 `form` 时不能有 `file` 项；`bodyType` 为 `raw` 时 `form` 保留但不发送，也不要求填完整（`name` 可以为空，文件项的 `fileId` 可以为 `null`），切回表单类型保存时才检查
- `path`、`headers` 的值、`body`、`form` 的 `name` 和文本 `value`、`expectBodyContains` 中可以使用 `{{变量名}}` 和 `{{$动态变量}}`，运行时替换（见下文「变量」）
- 发送前，引擎把最终 URL 里的非 ASCII 字符和空白按 UTF-8 百分号编码（`keyword=键盘` → `keyword=%E9%94%AE%E7%9B%98`），已有的 `%XX` 和 ASCII 符号不动；变量值里的 `&`、`/` 等不编码
- `expectBodyContains`：字符串或 `null`
- `extracts[].from`：
  - `json`：`expr` 是 GJSON 路径（k6 `res.json(路径)` 的语法），如 `data.items.0.id`、`data.items.#`（数组长度）、`data.items.#(status=="ok").id`（条件查询）、`data.items.#.id`（全部，得到数组）。也接受 JSONPath 写法：以 `$`、`$.`、`$[` 开头时（`$id` 这种键名不算），或者不含 `#(` 但用了方括号时（如 `data.items[0].id`），引擎先换成 GJSON 写法。键名里的 `.` 写成 `\.`。以前的写法照旧可用：连续的点、开头结尾的点被忽略，数组的 `.length` 等同于 `.#`
  - `regex`：`expr` 是正则，有捕获组时取第 1 个捕获组，没有捕获组时取整个匹配
  - `header`：`expr` 是响应头名称，不区分大小写
  - `cookie`（2026-10-10 加入）：`expr` 是 Cookie 名称。先找这次响应（最后一跳）设置的 Cookie，没有再在这个流程正在用的 Cookie 罐里找：先按这次请求的地址，再按重定向后的最终地址
  - 取到的值是对象或数组时存成 JSON 字符串；取不到（含 `null`）算提取失败
- `usedBy`、`brokenRefs`（2026-10-10 加入，只读，`PUT` 时忽略）：标准的引用字段，见 §3.8。接口被引用时也可以删除，引用它的步骤变成失效引用（见下文「失效引用」）

**业务流程 `/api/flows`**

```json
{
  "id": 1, "name": "下单", "note": "",
  "datasets": [ { "datasetId": 2, "pick": "perVu", "onExhausted": "recycle" } ],
  "variables": [ { "name": "orderNo", "value": "ORD{{$timestampMs}}{{$vu}}" } ],
  "initSteps": [ { "apiId": 3, "thinkTimeMs": 0 } ],
  "reinitSec": null,
  "steps": [ { "apiId": 1, "thinkTimeMs": 500 } ]
}
```

- `steps`：**每次迭代**按顺序执行的步骤，`thinkTimeMs` 是这一步之后的等待时间（不小于 0）
- `initSteps`（2026-10-10 加入，省略时为 `[]`）：**初始化段**，每个 VU 在它的第一次迭代里、`steps` 之前按顺序执行一次。这些步骤提取到的变量和拿到的 Cookie 在这个 VU 之后的迭代里保留（不跨流程、不跨 VU）。初始化段有步骤没通过检查时，本次迭代结束（`steps` 不执行；closed 模型下再等 1 秒，避免登录接口很快失败时无间隔地反复登录），下一次迭代重新执行初始化段
- `reinitSec`：正数或 `null`。距上一次初始化成功超过这么多秒后，下一次迭代重新执行初始化段（换一个新的 Cookie 罐，旧会话的 Cookie 全部丢弃）。`null` 表示不重新执行。`initSteps` 为空时必须是 `null`
- `datasets`（2026-10-10 加入，省略时为 `[]`）：绑定的数据集（§3.6），每次迭代按各自的取法取一行，列名作为变量
  - `datasetId`：必须存在；同一流程里不能重复
  - `pick`：`sequential`（按顺序：所有 VU 共用一个游标，每次迭代取下一行）、`random`（随机：每次迭代随机取一行）、`perVu`（每个 VU 固定一行：适合账号池）
  - `onExhausted`：`recycle`（循环使用）或 `stop`（停止测试，判 `invalid`）。`pick` 为 `random` 时只能是 `recycle`。`sequential` 下"用完"指行都取过一遍；`perVu` 下"用完"指 VU 数超过行数
  - 同一流程绑定的多个数据集，列名不能重复
- `variables`（2026-10-10 加入，省略时为 `[]`）：**流程变量**，每次迭代开始时（取完数据集的行之后、初始化段之前）按顺序求值一次，`value` 里可以引用环境变量、数据集的列、前面的流程变量和动态变量。用途：同一次迭代里多个步骤共用一个生成的值（例如订单号）。`name` 符合变量名规则、不能重复、不能和绑定的数据集的列重名
- `GET` 返回时 `steps` 和 `initSteps` 的每项额外带 `apiName`、`method`、`path`；`datasets` 的每项额外带 `datasetName`、`columns`、`rowCount`；另带标准的引用字段 `usedBy`、`brokenRefs`（§3.8）（都是只读的展示字段，`PUT` 时忽略）
- **失效引用**（2026-10-10 起；之前是被引用就 409 不能删除）：每个定义都可以单独删除，被引用不挡删除，引用它的地方变成失效引用，不级联删除任何东西：
  - 接口被删除：流程里引用它的步骤保留原 `apiId`，`GET` 时这一步的 `apiName`、`method`、`path` 为 `null`
  - 数据集被删除：流程里的绑定保留原 `datasetId`，`datasetName`、`columns`、`rowCount` 为 `null`
  - 业务流程被删除：测试里的这一项保留原 `flowId`，`flowName` 为 `null`
  - 文件被删除：接口 `form` 里的文件项保留原 `fileId`（接口本身没有展示字段，页面按文件列表判断）
  - 保存（`PUT`）时，库里原来就有的失效引用可以原样保留，不因为改别的字段而被拒绝；**新增**的引用仍然必须指向存在的对象（`POST` 时所有引用都必须存在）
  - 带失效引用的流程、测试不能试跑和运行：预检（§3.2 第 1 条、§3.5）逐条指出哪一步、哪一项已被删除，以及怎么修；接口的 form-data 引用了已删除的文件时不能发送。运行记录不受影响（快照）

**变量**（2026-10-10 整理，ADR-006）

一次迭代里的变量按**求值顺序**分层，后写的覆盖先写的同名变量：

| 顺序 | 层 | 来源 | 生命周期 |
|---|---|---|---|
| 1 | 环境变量 | 被测环境的 `variables`（调试单个接口时，页面上的当前值覆盖同名初始值） | 每次迭代重新开始 |
| 2 | 数据集的行 | 流程绑定的数据集，每次迭代按取法取一行，列名 → 值 | 每次迭代 |
| 3 | 流程变量 | 流程的 `variables`，每次迭代求值一次 | 每次迭代 |
| 4 | 初始化段的输出 | `initSteps` 提取到的变量 | 这个 VU 的后续迭代都保留，重新初始化时替换 |
| 5 | 步骤提取 | `steps` 提取到的变量，从提取它的那一步之后可用 | 本次迭代 |

- 引用写法：`{{名称}}`，名称两侧允许空格。变量不存在时原样保留（`{{token}}` 会被原样发出，方便从日志和目标端看出问题；正式运行和流程试跑在预检里就会拒绝这种情况，见 §3.2）
- 变量名：由字母（含中文）、数字、下划线组成，不能以 `$` 开头。环境变量、提取规则、数据集的列、流程变量共用这条规则
- **动态变量** `{{$名称}}`：引擎在每次替换时现算，同一个请求里出现几次就算几次；要在一次迭代里复用同一个值，就把它定义成流程变量。名称不认识时原样保留

| 写法 | 值 |
|---|---|
| `{{$timestamp}}` | 当前 Unix 时间，秒 |
| `{{$timestampMs}}` | 当前 Unix 时间，毫秒 |
| `{{$isoTimestamp}}` | 当前时间，ISO 8601 UTC，如 `2026-10-10T03:15:00.123Z` |
| `{{$date}}`、`{{$date(格式)}}` | 执行机本地时间按格式输出，默认 `yyyy-MM-dd`；括号里的全部内容都是格式（可以有逗号），认 `yyyy` `MM` `dd` `HH` `mm` `ss` `SSS`，其余字符原样输出 |
| `{{$uuid}}`（别名 `{{$guid}}`、`{{$randomUUID}}`） | 随机 UUID v4 |
| `{{$randomInt}}`、`{{$randomInt(最小,最大)}}` | 随机整数，闭区间，默认 0–1000；两个参数都必须是 ±(2^53−1) 以内的整数且最小不大于最大 |
| `{{$randomString}}`、`{{$randomString(长度)}}` | 随机字母数字串，默认长度 8，最长 256 |
| `{{$vu}}` | 当前 VU 的编号（`exec.vu.idInTest`，从 1 开始，整个测试内唯一） |
| `{{$iteration}}` | 当前 VU 在本流程里的迭代序号（`exec.vu.iterationInScenario`，从 0 开始）。`{{$vu}}-{{$iteration}}` 在一次运行内唯一 |
| `{{$runId}}` | 运行 id（调试时是 `dbg-…`） |

- 参数写在括号里，用逗号分隔，参数里不能有花括号和括号；表里没写参数的不接受参数（`{{$uuid()}}` 这种空括号可以）。参数不对时和不认识的名称一样原样保留，正式运行和流程试跑的预检会拒绝。动态变量不进 tag，也不参与判定

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
- `GET` 返回时每个 flow 额外带 `flowName`；另带 `lastRun: { runId, verdict, startedAt } | null`；另带 `brokenRefs`（§3.8）
- 流程被测试引用时也可以删除，测试里的这一项变成失效引用（见上文「失效引用」）；测试、负载配置、环境有运行记录时可以删除（运行里存了快照）

### 3.2 运行 `/api/runs`

| 方法与路径 | 说明 |
|---|---|
| `POST /api/runs` | 发起运行。body：`{ "testId": 1, "profileId": 1, "envId": 1, "executorId": 1, "confirmProd": false, "note": "" }`。`executorId` 可省略，默认用本机执行机。被测环境类型为 `prod` 时必须带 `"confirmProd": true`（只有布尔值 `true` 算确认；不是布尔值返回 400），否则预检不通过。成功返回 201 和运行对象（`status: "running"`） |
| `GET /api/runs?testId=&verdict=&status=&archived=&page=1&pageSize=20` | 列表，按开始时间倒序。返回 `{ "items": [...], "total": 123 }`，列表项不含 `snapshot` 和 `record` |
| `GET /api/runs/:runId` | 详情，含 `snapshot`、`record`、`artifacts` |
| `POST /api/runs/:runId/stop` | 停止正在进行的运行（向 k6 发 SIGINT）。不在运行中返回 409 |
| `PATCH /api/runs/:runId` | 修改 `note` 和 / 或 `archived` |
| `DELETE /api/runs/:runId` | 删除记录和产物目录。运行中或已存档返回 409 |
| `GET /api/runs/:runId/artifacts/:name` | 下载或查看产物。`name` 只能是 `plan.json`、`run-record.json`、`k6-summary.json`、`dashboard.html`、`k6.log`（运行目录里的 `datasets/`、`files/` 是 k6 的输入，不经这个接口提供） |

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

1. 测试、负载配置、环境都存在；测试至少有 1 个流程，每个流程至少有 1 个步骤；测试里的流程、流程里的步骤和数据集绑定都没有失效引用（引用的对象已被删除，见 §3.1「失效引用」），否则逐条指出是哪一项、怎么修
2. 环境的 `baseUrl` 是合法的 http / https 地址
3. 负载配置不超过被测环境的安全上限（只检查不为 `null` 的项）：并发（`vus` 或 `preAllocatedVus`）≤ `maxVus`；到达率（`rate`、`startRate`、各 stage 的 `target`）≤ `maxRate`；总时长 ≤ `maxDurationSec`。被测环境类型为 `prod` 时，请求里必须带 `"confirmProd": true`
4. 负载配置属于 §3.1 的四种形态之一
5. 流程数量不超过并发：closed 模型下 `vus`（以及固定迭代数形态的 `iterations`）不小于测试的流程数量；open 模型下 `preAllocatedVus` 不小于流程数量（每个流程至少要有 1 个 VU）
6. 没有其他运行正在进行（否则 409）
7. k6 可执行文件存在
8. **变量都有来源**（2026-10-10 加入）：测试里每个流程的每个引用都要能在 §3.1「变量」的分层里找到来源，按执行顺序检查：
   - 检查的位置：每一步的 `path`、请求头的值（含被测环境的公共请求头）、`body`（`bodyType` 为 `raw` 时）、`form` 的 `name` 和文本 `value`（`bodyType` 为 `form` / `multipart` 时）、`expectBodyContains`；以及流程变量的 `value`
   - 可用的来源：这次运行的被测环境的 `variables`；流程绑定的数据集的列；流程变量（检查流程变量本身时只算排在它前面的）；初始化段里**排在前面的**步骤的提取（`steps` 可以用初始化段全部的提取）；`steps` 里**排在前面的**步骤的提取。一步自己的提取不算这一步的来源
   - **例外：被测环境公共请求头里的引用**（接口没有用同名请求头覆盖的）只要求这个流程里某一处产出它（任何一层、任何一步），不要求排在这一步前面。公共请求头每一步都带，常见写法是 `Authorization: Bearer {{token}}`、token 由登录步骤提取：登录这一步发出的是未替换的原文，服务端不看，这是无害的。缺的只报一次：`业务流程“下单”使用的被测环境“测试”公共请求头引用了 {{traceId}}，但没有来源：……`
   - `{{$名称}}` 必须是 §3.1 动态变量表里的名称，参数符合表里的规则
   - 不通过时每个缺失的引用一条：`业务流程“下单”第 2 步「查订单」引用了 {{token}}，但没有来源：被测环境“测试”没有这个变量，数据集、流程变量和前面的步骤也不产出它`（初始化段的步骤写"初始化第 N 步"，流程变量写"流程变量 orderNo"）
9. **数据集够用**（2026-10-10 加入）：绑定的数据集都存在、至少 1 行；同一流程绑定的数据集列名不重复，流程变量不和列重名。`onExhausted` 为 `stop` 时：
   - `perVu`：负载配置的总 VU 数（`vus` 或 `preAllocatedVus`）不能超过行数
   - `sequential`：负载配置是固定迭代数形态时，设这个流程按权重分到的迭代数为 n（和 §4 一样用最大余数法），按顺序共用这个数据集的流程有 k 个、它是其中第 offset 个（从 0 起，即 plan 里的 `offset`），它最多用到第 (n − 1) × k + offset 行（从 0 起），要求 (n − 1) × k + offset + 1 ≤ 行数。只检查 `stop` 的绑定：`recycle` 的不会触发数据用完。其他三种形态的迭代数事先不知道，不在预检里拦，运行中用完时按 §5 判 `invalid`
10. **文件不超量**（2026-10-10 加入）：`multipart` 引用的文件都存在；（总 VU 数 + 2）× 用到的文件大小之和 ≤ 2 GiB（k6 每个 VU 各持有一份文件，见 `records/tech-notes.md` §2）

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
  "api": { "name": "查订单", "method": "GET", "path": "/api/orders/{{orderId}}", "headers": {}, "bodyType": "raw", "body": null,
           "form": [], "expectStatus": 200, "expectBodyContains": null, "extracts": [], "note": "" },
  "beforeApiIds": [3],
  "flowId": 3,
  "rows": { "2": 0 }
}
```

- `envId`：被测环境，必填。请求发往它的 `baseUrl`，并带上它的公共请求头
- `confirmProd`：被测环境类型为 `prod` 时必须为 `true`（一次请求也是请求，和发起运行的规则一致）
- `vars`：可选，**只用于调试单个接口**（和 `flowId` 一起给返回 400）。调试的**当前值**（值必须是字符串），覆盖被测环境 `variables` 里的同名初始值。页面按环境保存当前值（只存改过的，没有当前值的变量用初始值），每次调试后把提取到的变量写进当前值，请求里只带当前值，所以连续调试时上一步取到的 token 能直接用于下一步
- `api`：一份接口定义（字段同 §3.1 的接口，**不要求已保存**，页面上正在编辑的内容可以直接发），按单步流程执行；校验失败返回 400，`details` 和保存接口时一致
- `beforeApiIds`（2026-10-10 加入）：可选，**只用于调试单个接口**。已保存的接口 id 数组，最多 5 个、不能重复：先按顺序执行这些接口，再执行 `api`，全部在**同一次迭代**里（同一个 VU、同一个 Cookie 罐），上游提取到的变量直接给后面的步骤用。用途：目标接口依赖上游接口产出的变量（如登录拿 token）。接口不存在返回 422
- `flowId`：已保存的业务流程：先执行初始化段（`initSteps`），再执行 `steps`。**试跑不接受 `vars`**，变量和正式运行一样只来自被测环境的初始值、数据集、流程变量和提取，所以试跑通过的流程，正式运行时变量也都齐全
- `rows`（2026-10-10 加入）：可选，数据集 id（字符串形式的键）→ 行号（从 0 开始的整数）。调试只跑一次迭代，用哪一行由这里指定，不按取法
  - 和 `flowId` 一起：键必须是这个流程绑定的数据集，没给的数据集用第 0 行
  - 和 `api` 一起：给出的数据集都按"用指定的行"参与这次调试，列作为变量（层次在环境变量和当前值之上）
  - 行号超出行数返回 422；数据集不存在返回 422；格式错误返回 400

调试和运行的差别（除此以外行为一致）：

| 项 | 运行 | 调试 |
|---|---|---|
| 负载 | 负载配置 | 固定 1 并发、1 次迭代，最长时长取 60 秒与被测环境 `maxDurationSec` 中的小者 |
| 数据集的行 | 按绑定的取法取 | 用 `rows` 指定的行（默认第 0 行） |
| 初始化段 | 每个 VU 一次 | 每次调试都执行（调试总是一个新的 VU） |
| 变量的当前值 | 不用 | 只在调试单个接口时覆盖初始值；试跑流程不用 |
| 变量来源检查（§3.2 第 8 条） | 有 | 试跑流程有（按调试选的被测环境）；调试单个接口没有，未定义的变量原样发出 |
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
      "key": "f1s1", "name": "百度首页", "phase": "main", "status": "passed",
      "request": { "method": "GET", "url": "https://www.baidu.com/", "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" },
                   "bodyType": "raw", "body": null, "form": null },
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
- `steps[]` 的顺序：初始化段（`phase: "init"`，key 形如 `f1i1`）在前，`steps`（`phase: "main"`，key 形如 `f1s1`）在后。调试单个接口且给了 `beforeApiIds` 时，上游接口和目标接口都是 `main`，**最后一项是目标接口**
- `request.bodyType` 与接口的 `bodyType` 相同。`form` 时 `body` 是编码后的字符串；`multipart` 时 `body` 为 `null`；`raw` 时 `form` 为 `null`，其他两种时 `form` 是变量替换后的各项：文本项 `{ "name", "type": "text", "value" }`，文件项 `{ "name", "type": "file", "fileName", "contentType", "size" }`
- `steps[].status`：`passed`（全部检查通过）、`failed`（有检查未通过；网络错误、超时也算在内，因为状态码检查不会通过）、`skipped`（前面有步骤失败，这一步没有执行，`request`、`response`、`timings` 为 `null`）、`error`（执行这一步时脚本抛出异常，例如地址非法，`error` 为异常文字，`response` 为 `null`）
- `response.body`：文本。`contentType` 不像文本（不是 `text/*`、JSON、XML、JavaScript、表单编码）时不返回正文，`bodyOmitted` 为 `true`、`body` 为 `null`；超过 64 KB 时截断，`bodyTruncated` 为 `true`。`bodyLength` 是截断前的字符数
- `timings` 单位毫秒，对应 k6 的 `res.timings`（`duration` = 发出请求到收完响应，不含 `blocked`）
- `request` 是这一步实际发出的第一个请求（变量已替换、请求头已和环境合并）；有重定向时 `response.finalUrl` 是最后一跳的地址，状态码和响应体也是最后一跳的

错误：

| HTTP 状态 | code | 场景 |
|---|---|---|
| 400 | `VALIDATION_FAILED` | 字段缺失、`api` 与 `flowId` 不是恰好一个、`vars` 的值不是字符串、`vars` 或 `beforeApiIds` 和 `flowId` 一起给、`rows` 格式错误或键不是流程绑定的数据集、`api` 定义不合法（`details` 逐条） |
| 422 | `PREFLIGHT_REJECTED` | 被测环境或流程不存在、流程没有步骤、步骤引用的接口不存在、`beforeApiIds` 里的接口不存在、数据集不存在或行号超出、引用的文件不存在、试跑流程时变量没有来源（§3.2 第 8 条）、`baseUrl` 非法、生产环境没有 `confirmProd: true`、k6 不存在 |
| 409 | `CONFLICT` | 有运行在进行中，或上一次调试还没结束 |
| 500 | `DEBUG_FAILED` | k6 没有产出调试记录（脚本异常、plan 无效、超时）。`details` 是 k6 日志的最后若干行，页面原样显示 |

### 3.6 数据集 `/api/datasets`（2026-10-10 加入）

数据集是只读的表格数据：第一行是表头，列名就是变量名；绑定在业务流程上（§3.1），每次迭代取一行。数据由后端解析和保存，运行时复制进运行目录交给 k6（§4），所以运行中改数据集不影响正在进行的运行。

| 方法与路径 | 说明 |
|---|---|
| `GET /api/datasets` | 列表（不含行数据） |
| `POST /api/datasets` | 新建。body：`{ "name", "note", "csv": "…" }` 或 `{ "name", "note", "contentBase64": "…", "fileName": "users.csv" }`，`csv` 和 `contentBase64` 恰好给一个。返回 201 和对象 |
| `GET /api/datasets/:id` | 详情：对象 + `previewRows`（前 100 行，每行是字符串数组，顺序同 `columns`）。POST、PUT 的响应同详情 |
| `PUT /api/datasets/:id` | 整体替换 `name`、`note`；`csv` / `contentBase64` 可以都不给，表示数据不变（只改名或备注）；给了就整体替换数据 |
| `DELETE /api/datasets/:id` | 删除。被业务流程绑定时也可以删除，那些绑定变成失效引用（§3.1「失效引用」） |
| `GET /api/datasets/:id/csv` | 导出 CSV：UTF-8 带 BOM（Excel 能直接打开）、逗号分隔、`\r\n` 换行，`Content-Type: text/csv; charset=utf-8`。加 `?download=1` 时作为附件下载（文件名为数据集名称 + `.csv`）。页面拿它做文本编辑时要去掉开头的 BOM |
| `POST /api/datasets/preview` | 只解析不保存：body 同 POST 的数据部分（`csv` 或 `contentBase64` + `fileName`），返回 200 `{ "columns", "rowCount", "previewRows", "source" }`；解析不通过返回 400，`details` 和保存时一致 |

```json
{
  "id": 2, "name": "账号池", "note": "",
  "columns": ["username", "password"], "rowCount": 100,
  "sha256": "9f2c…（64 位十六进制）",
  "source": { "fileName": "users.csv", "encoding": "gb18030", "delimiter": "," },
  "usedBy": [ { "kind": "flow", "id": 1, "name": "下单", "where": ["数据集绑定第 1 项"] } ],
  "createdAt": "…", "updatedAt": "…"
}
```

解析规则（后端用 Python `csv` 模块，RFC 4180：引号、`""` 转义、引号里的换行）：

- `contentBase64` 是文件的原始字节：先去掉 UTF-8 BOM 按 UTF-8 严格解码，失败再按 GB18030 解码（Excel 中文版另存的 CSV 是 GBK）。`source.encoding` 记 `utf-8`、`utf-8-sig`（带 BOM）或 `gb18030`。`csv` 是已经解码的文本，去掉开头的 BOM，`source.encoding` 记 `utf-8`，`source.fileName` 为 `null`
- 分隔符：在第一个非空行里数 `,`、`\t`、`;` 出现的次数，取最多的；都没有或打平时用 `,`。记在 `source.delimiter`
- 第一个非空行是表头：列名去掉两端空白后必须符合变量名规则（§3.1「变量」）、不能重复，最多 100 列
- 之后的每一行是数据：空行跳过；字段数必须和表头相同（不通过时列出前 5 个出错的行号，行号按文件里的物理行计，表头是第 1 行）；值是字符串，原样保存，不去空白
- 至少 1 行数据，最多 100,000 行；解码后的文本按 UTF-8 计不超过 10 MiB，`contentBase64` 解码后的字节不超过 10 MiB
- `sha256`：`{"columns": [...], "rows": [[...], ...]}` 按 UTF-8、紧凑 JSON（`ensure_ascii=False`，分隔符 `,` `:`）序列化后的摘要。plan 里带着它，便于确认一次运行用的是哪一版数据
- `usedBy`（只读）：绑定了这个数据集的业务流程，标准格式见 §3.8

### 3.7 文件 `/api/files`（2026-10-10 加入）

接口的 `multipart` 请求体里引用的文件（§3.1 `form` 的 `file` 项）。文件内容存库，运行时复制进运行目录交给 k6（§4）。

| 方法与路径 | 说明 |
|---|---|
| `GET /api/files` | 列表（只有元数据） |
| `POST /api/files` | 上传。body：`{ "name": "avatar.png", "contentType": "image/png", "contentBase64": "…", "note": "" }`。返回 201 和元数据 |
| `GET /api/files/:id` | 元数据 |
| `GET /api/files/:id/content` | 文件内容，`Content-Type` 为文件的 `contentType`；加 `?download=1` 时作为附件下载 |
| `PUT /api/files/:id` | 改 `name`、`contentType`、`note`；`contentBase64` 可省略（内容不变），给了就替换内容 |
| `DELETE /api/files/:id` | 删除。被接口引用时也可以删除，那些文件项变成失效引用（§3.1「失效引用」） |

```json
{
  "id": 3, "name": "avatar.png", "contentType": "image/png", "size": 20480,
  "sha256": "…", "note": "",
  "usedBy": [ { "kind": "api", "id": 7, "name": "上传头像", "where": ["表单第 2 项"] } ],
  "createdAt": "…", "updatedAt": "…"
}
```

- `name`：文件名，必填，不超过 200 个字符，不能包含 `/`、`\` 和控制字符；它就是 multipart 里的 `filename`
- `contentType`：可省略，省略或为空时按文件名的扩展名推断，推断不出用 `application/octet-stream`
- 大小不超过 10 MiB（可以是 0 字节）
- `/content` 的响应带 `X-Content-Type-Options: nosniff` 和 `Content-Security-Policy: sandbox`，上传的 HTML 不会在本站执行脚本
- `usedBy`（只读）：在 `form` 里引用了这个文件的接口（包括 `raw` 时保留的表单），标准格式见 §3.8

### 3.8 引用（2026-10-10 加入）

定义之间按 id 引用。所有引用关系在后端登记一次（`server/references.py` 的 `RELATIONS`）：引用方、字段、被引用方、引用位置的叫法。下面的字段、接口和提示都由它生成，各资源格式一致。

| 引用方 | 字段 | 被引用方 | 位置（`where`） |
|---|---|---|---|
| 业务流程 `flow` | `initSteps[].apiId` | 接口 `api` | `初始化第 N 步` |
| 业务流程 `flow` | `steps[].apiId` | 接口 `api` | `第 N 步` |
| 业务流程 `flow` | `datasets[].datasetId` | 数据集 `dataset` | `数据集绑定第 N 项` |
| 测试 `test` | `flows[].flowId` | 业务流程 `flow` | `第 N 个流程` |
| 接口 `api` | `form[].fileId`（`type` 为 `file`） | 文件 `file` | `表单第 N 项` |

**标准字段**（`GET` 时的只读字段，`PUT` 时忽略）：

- `usedBy`：谁引用了它，`[{ "kind": "flow", "id": 1, "name": "访问首页", "where": ["第 1 步"] }]`。同一个引用方引用多次时合并成一项，`where` 列出全部位置。接口、业务流程、测试、数据集、文件都有（没有被引用时是 `[]`）
- `brokenRefs`：它引用的对象里哪些已被删除，`[{ "kind": "api", "id": 1, "where": ["第 1 步"] }]`。接口、业务流程、测试有（它们是引用方）

**删除影响**：`GET /api/references/:kind/:id`（`kind` 是上表的种类）返回删除这个对象会让哪些引用失效，逐层包含间接受影响的对象：

```json
{ "kind": "api", "id": 1, "name": "百度首页",
  "usedBy": [ { "kind": "flow", "id": 1, "name": "访问首页", "where": ["第 1 步"],
                "usedBy": [ { "kind": "test", "id": 1, "name": "百度首页冒烟", "where": ["第 1 个流程"], "usedBy": [] } ] } ] }
```

种类不认识或对象不存在返回 404。页面删除任何定义之前都用它：`usedBy` 为空时普通确认；不为空时列出这棵树，确认后只删这一个对象。

**失效引用的提示**：预检、试跑、发送遇到失效引用时，提示一律是

`<引用方中文名>“<名称>”<位置>引用的<被引用方中文名> #<id> 已被删除（失效引用）：换一个<被引用方中文名>，或移除这一项`

例如：`业务流程“访问首页”第 1 步引用的接口 #1 已被删除（失效引用）：换一个接口，或移除这一项`。页面上失效引用显示为 `<被引用方中文名>已删除（#<id>）`。

## 4. plan.json（后端 → k6）

后端把发起时的测试、流程、接口、负载配置、环境**展开成一份自包含的 plan**，写到 `results/<runId>/plan.json`，同时作为运行的 `snapshot` 存库。

```json
{
  "schemaVersion": 1,
  "runId": "20260930T101500Z-a1b2c3",
  "test": { "id": 1, "name": "百度首页冒烟" },
  "env": { "id": 1, "name": "百度（仅冒烟）", "type": "prod", "baseUrl": "https://www.baidu.com", "headers": { "User-Agent": "Mozilla/5.0 k6-mvp" }, "variables": {} },
  "profile": { "id": 1, "name": "冒烟", "type": "smoke", "model": "closed", "config": { "vus": 1, "iterations": 10, "maxDurationSec": 30 } },
  "datasets": [
    { "key": "d1", "id": 2, "name": "账号池", "columns": ["username", "password"], "rowCount": 100, "sha256": "…", "file": "datasets/d1.json" }
  ],
  "files": [
    { "key": "u1", "id": 3, "name": "avatar.png", "contentType": "image/png", "size": 20480, "sha256": "…", "file": "files/u1.bin" }
  ],
  "flows": [
    {
      "key": "f1", "name": "访问首页", "weight": 1,
      "datasets": [ { "key": "d1", "pick": "perVu", "onExhausted": "recycle", "stride": 1, "offset": 0 } ],
      "variables": [ { "name": "orderNo", "value": "ORD{{$timestampMs}}{{$vu}}" } ],
      "reinitSec": null,
      "initSteps": [],
      "steps": [
        {
          "key": "f1s1", "name": "百度首页", "method": "GET", "path": "/",
          "headers": {}, "bodyType": "raw", "body": null, "form": [],
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

- `flows[].key`：`f<序号>`；`steps[].key`：`<flowKey>s<序号>`；`initSteps[].key`：`<flowKey>i<序号>`。只用 ASCII，因为要作为 k6 的 scenario 名和 tag 值
- `weight` 已归一化，和为 1
- `env.variables`：被测环境的环境变量初始值，每次迭代开始时的变量；调试时 `debug.vars` 覆盖同名项。旧的快照没有这个字段，引擎按空对象处理
- 以下字段 2026-10-10 加入，都是可选的：旧的快照没有它们，引擎按空数组 / `null` / `raw` 处理，所以 `schemaVersion` 仍为 1
- `datasets`：plan 里所有流程用到的数据集，每个一项，`key` 为 `d<序号>`。行数据**不在 plan 里**，在 `file` 指向的文件里（路径相对 plan.json 所在目录）：一个 JSON 数组，每项是一行（字符串数组，顺序同 `columns`），UTF-8 不带 BOM。引擎在 init 阶段用 `SharedArray` 加载（名字含 `key` 和 `sha256`），所有 VU 共享一份
- `files`：plan 里所有步骤引用的文件，每个一项，`key` 为 `u<序号>`，`file` 指向原始字节。引擎在 init 阶段用 `open(路径, 'b')` 读入（每个 VU 各一份）
- `flows[].datasets`：这个流程绑定的数据集，`key` 指向顶层 `datasets`。每次迭代取行的规则：
  - `sequential`：行号 = `exec.scenario.iterationInTest × stride + offset`。k6 的 `iterationInTest` 按 scenario 各自从 0 开始，所以 plan 里有 k 个流程按顺序共用同一个数据集时，后端给它们 `stride = k`，`offset` 按流程顺序为 0…k−1，各取各的行、互不重复；只有一个流程用时 `stride = 1`、`offset = 0`
  - `perVu`：行号 = `exec.vu.idInTest − 1`（整个测试内唯一）
  - `random`：行号 = `Math.floor(Math.random() × rowCount)`
  - 行号 ≥ `rowCount` 时：`recycle` 对 `rowCount` 取模；`stop` 表示数据用完：本次迭代**不发任何请求**，计数指标 `data_exhausted` 加 1，closed 模型下等待 1 秒再返回（避免空转），open 模型下直接返回；对应的 validity 阈值见 §5
- `flows[].variables`：流程变量，每次迭代取完数据集的行之后按顺序求值
- `flows[].initSteps`：初始化段，结构同 `steps`。引擎为每个 VU、每个流程保存初始化段提取到的变量和一个**这个流程自己的 Cookie 罐**（模块级状态）：状态为空时新建一个罐、执行初始化段（成功才保存），之后这个流程的所有请求都用这个罐，所以会话 Cookie 跨迭代保留；`reinitSec` 到期时丢弃状态，下一次迭代用新罐重新初始化。初始化段的请求带 `phase: "init"` tag，`steps` 的请求带 `phase: "main"`
- 没有初始化段的流程用 k6 默认的 Cookie 罐，每次迭代清空，和以前一样（不用全局的 `noCookiesReset`：那样还得在每次迭代清 Cookie，而 `cookieJar().clear(地址)` 只清这个地址的主机和默认路径，带 `Domain`、非根路径、重定向到别的主机时设置的 Cookie 都清不掉）
- `steps[].bodyType` / `form`：同 §3.1 的接口，只是 `form` 只带要发送的项：`multipart` 时文本项 `{ "name", "type": "text", "value" }`、文件项 `{ "name", "type": "file", "fileKey": "u1" }`（`fileKey` 指向顶层 `files`）；`form` 时只有文本项；`raw` 时为 `[]`（接口里保留但不发送的表单不进 plan，它引用的文件也不加载）
- **运行目录里的输入文件**：后端在启动 k6 之前把数据集写成 `results/<runId>/datasets/<key>.json`、把文件写成 `results/<runId>/files/<key>.bin`。它们随运行一起删除，不进快照（快照就是这份 plan，只带 `sha256` 等元数据）。调试时写在调试目录里，数据集文件只含 `rows` 指定的那一行（`rowCount` 为 1）
- `debug`（可选，只有调试时有，见 §3.5）：`{ "vars": { "token": "abc" }, "bodyLimit": 65536 }`。存在时引擎进入**调试模式**：不等待 `thinkTimeMs`；每一步都保留响应体（最多 `bodyLimit` 个字符）；逐步记录请求、响应、检查和变量；迭代结束后把记录写到 console（§5.1）；`handleSummary` 不写 `run-record.json` 和 `k6-summary.json`。调试的 plan 里 `test.id` 为 `0`、`profile.id` 为 `0`、`profile.name` 为"调试"，`profile.config` 固定为 `{ "vus": 1, "iterations": 1, "maxDurationSec": N }`，`slo` 四项都为 `null`；`runId` 形如 `dbg-20261009T062206Z-6abec2`

### 启动 k6 的方式（后端负责）

```bash
K6_WEB_DASHBOARD=true K6_WEB_DASHBOARD_HOST=127.0.0.1 K6_WEB_DASHBOARD_PORT=5665 \
K6_WEB_DASHBOARD_EXPORT=<输出目录>/dashboard.html K6_WEB_DASHBOARD_PERIOD=1s \
K6_AUTO_EXTENSION_RESOLUTION=false \
k6 run perf/runner.js \
  -e PLAN_FILE=<输出目录>/plan.json \
  -e OUTPUT_DIR=<输出目录> \
  --tag testid=<runId>
```

- 工作目录是仓库根目录；`PLAN_FILE`、`OUTPUT_DIR` 用绝对路径
- `K6_AUTO_EXTENSION_RESOLUTION=false`（2026-10-10 加入，调试同样带）：k6 v2.3.0 遇到不认识的 import 时默认会联网向 Grafana 的构建服务请求下载扩展（实测），关掉它，未知的 import 直接以 107 失败
- 标准输出和标准错误写入 `<输出目录>/k6.log`
- `testid` tag 只在这里设置一次
- **实时仪表盘不能给浏览器用**：联调实测，只要有浏览器连着 `:5665`，k6 跑完后就不会退出（它等页面关闭），也不写 `run-record.json`，运行会一直停在"运行中"。所以仪表盘只监听 `127.0.0.1`，页面上不嵌入也不链接它；运行中的进度由运行对象的 `progress` 字段提供，结束后的图表用导出的 `dashboard.html`
- 仪表盘的环境变量名已在 k6 v2.3.0 实测有效。运行期间监听 `*:5665`，页面在 `/ui/`（访问 `/` 会跳转过去）；k6 退出后端口随之关闭
- `K6_WEB_DASHBOARD_PERIOD`（聚合周期）默认 10s。不设置时，几秒到十几秒的短运行会因为数据点不够而**跳过 HTML 导出**（日志里有一条 warning，退出码不受影响）；设为 `1s` 后，3 秒的运行也能导出。即便如此，`dashboard.html` 仍应当作可选产物处理（运行太短或启动失败时不存在）

### 启动调试的方式（后端负责）

```bash
K6_WEB_DASHBOARD=false K6_AUTO_EXTENSION_RESOLUTION=false \
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
      "scope": "all",
      "reqs": 10, "rps": 1.2, "iterations": 10, "droppedIterations": 0, "vusMax": 1,
      "avg": 120.1, "p50": 110.0, "p90": 170.2, "p95": 182.4, "p99": 201.3, "max": 210.0,
      "errorRate": 0, "checksRate": 1, "dataReceived": 123456, "dataSent": 2345
    },
    "steps": [
      { "flowKey": "f1", "flowName": "访问首页", "stepKey": "f1s1", "stepName": "百度首页", "phase": "main",
        "count": 10, "avg": 120.1, "p50": 110.0, "p95": 182.4, "p99": 201.3, "max": 210.0, "errorRate": 0 }
    ]
  },
  "testDurationMs": 8400
}
```

- 时间类指标单位都是毫秒
- **初始化段不计入总体指标和 SLO**（2026-10-10 加入，ADR-006）：plan 里有任何流程带初始化段时，SLO 阈值改挂在只含 `steps` 请求的子指标上（`http_req_duration{phase:main}`、`http_req_failed{phase:main}`），`label` 写"业务请求 p95 < 2000 ms"等；`overall` 里的 `reqs`、`rps`、`avg`…`max`、`errorRate` 也按这些子指标（和 `http_reqs{phase:main}`）计算，`overall.scope` 为 `"main"`。没有初始化段时和以前一样用全部请求，`scope` 为 `"all"`。`iterations`、`droppedIterations`、`vusMax`、`checksRate`、`dataReceived`、`dataSent` 始终按全部计算（初始化段的检查没通过同样影响检查通过率）。旧的记录没有 `scope`，按 `"all"` 理解
- `steps[]`：先列每个流程的初始化段（`phase: "init"`），再列 `steps`（`phase: "main"`）。旧的记录没有 `phase`，按 `"main"` 理解
- **数据用完**（2026-10-10 加入）：plan 里有 `onExhausted: "stop"` 的数据集绑定时，附加一条 validity 阈值 `data_exhausted` `count==0`（`label`：测试数据没有用完），带 `abortOnFail`：数据一用完，k6 在约 2 秒内停止测试并以 99 退出，`k6Verdict` 为 `invalid`
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

- 顺序和 plan 里的步骤一致（初始化段在前），每个步骤恰好一项；没执行到的以 `status: "skipped"` 出现。每项带 `phase`：`init` 或 `main`
- 数据用完（`stop`）不会在调试里出现：调试的数据集文件只有指定的那一行
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
