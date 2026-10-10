# Research：Hoppscotch 哪些能用在本项目

> 研究日期：2026-10-10
> 对象：https://github.com/hoppscotch/hoppscotch ，提交 `63273f8`（2026-09-30），版本 2026.9.0，MIT 许可。只读了源码，没有运行。
> 标记约定：**[事实]** 有来源（仓库内路径；`common/` = `packages/hoppscotch-common/src/`，`data/` = `packages/hoppscotch-data/src/`，`cli/` = `packages/hoppscotch-cli/src/`）；**[判断]** 本项目的结论。
> 本文回答：**Hoppscotch 里哪些可以复用到本项目、怎么复用、哪些不适用。** 已经落地的是文档导入（§2，契约 §3.9）；§3、§4 是待用户选择的候选。

---

## 0. 结论

[判断]

- **定位相同，执行方式不同。** Hoppscotch 是 Postman 式的接口调试工具，前端也是 Vue 3 + TypeScript + Vite，和本项目的接口页定位一致。但它的请求从浏览器、代理、浏览器扩展或桌面端直接发出；本项目的请求一律经 k6 发出，调试和压测共用 `perf/core/interp.js`。所以它的请求执行、拦截器、脚本沙箱、团队同步都用不上。
- **不搬代码，搬规则和交互。** 它的导入器依赖 `postman-collection`、`@apidevtools/swagger-parser`、fp-ts / io-ts 和它自己的数据模型（`@hoppscotch/data`）；输入框和响应查看建在 CodeMirror 6 上。整块搬进来，会把这些依赖一起带进本项目很精简的前端（只有 Element Plus 和 ECharts）。所以复用的是映射规则、边界情况和交互设计，按本项目的模型重写。
- **能复用的分三类：**
  - **文档导入的映射规则**：已经移植（§2）；
  - **编辑器和响应查看的交互**：小改动，建议下一批做（§3）；
  - **设计参考**：密钥变量、命令行的退出码和 JUnit 报告，对应本项目的未决事项，需要用户先定方向（§4）。

| 类别 | 能力 | 结论 |
|---|---|---|
| 已移植 | OpenAPI 3.x / Swagger 2.0 / Postman Collection v2 导入 | 2026-10-10 实现（契约 §3.9），修掉了它导入器的几处已知缺陷（§2.2） |
| 建议下一批 | 批量编辑、请求栏粘贴 cURL、HEAD / OPTIONS、响应体复制 / 下载 / HTML 预览、未定义变量一键加到环境、Ctrl + K 命令面板、发送历史 | §3：前端为主，HEAD / OPTIONS 要改契约 |
| 先定方向 | 密钥变量（凭据）、命令行与 CI、行的启用开关、文件夹级公共请求头 / 认证、导出 OpenAPI | §4：涉及未决事项或已有决定 |
| 不适用 | 前置 / 测试脚本、拦截器与代理、GraphQL 等协议、团队与同步、Mock 服务器、文档发布、29 种语言的代码生成、集合运行器、AI | §5 |

---

## 1. Hoppscotch 是什么 [事实]

- **包**：`hoppscotch-common`（主前端）、`hoppscotch-data`（数据模型和版本迁移）、`hoppscotch-js-sandbox`（脚本沙箱）、`hoppscotch-cli`（`hopp test`）、`hoppscotch-backend`（NestJS + Prisma + PostgreSQL：团队、同步、Mock、文档发布）、`hoppscotch-kernel` / `relay` / `agent` / `desktop`（发请求的几种通道）。
- **变量**：
  - 写法是 `<<name>>`，`$` 开头的是 29 个预置动态变量（`data/predefinedVariables.ts`）。
  - 环境变量有初始值、当前值、secret 标记（`data/environment/v/2.ts`）；另有集合变量和请求变量。
  - 取值顺序：请求 → 集合（深的覆盖浅的）→ 选中的环境 → 全局（`common/helpers/RequestRunner.ts` 210–238）。
- **没有声明式的提取**：从响应里取值存成变量，只能写脚本（`pw` / `hopp` / `pm` 三套 API）。脚本跑在 QuickJS 编译成的 WASM 里（`packages/hoppscotch-js-sandbox`）。
  - 本项目正相反：用提取规则和检查表达，不允许写脚本（ADR-006）。
- **认证可以从集合 / 文件夹继承**：沿祖先链找最近的、类型不是 inherit 的认证；公共请求头从根合并到叶子（`common/newstore/collections.ts` 135–258）。

---

## 2. 已移植：文档导入

### 2.1 Hoppscotch 的做法 [事实]

- **入口和格式**：导入器在 `common/helpers/import-export/import/`：
  - `openapi/index.ts`：Swagger 2.0、OpenAPI 3.0 / 3.1，JSON 或 YAML，可以按地址导入；
  - `postman.ts`：v2.0 / v2.1；
  - `insomnia/`、`har.ts`、`hopp.ts`；
  - 环境文件另有 `postmanEnv.ts` 等。
- **导入方式是全有或全无**：没有勾选这一步，解析完直接进库（`common/components/collections/ImportExport.vue`）。
- **OpenAPI 的映射**：
  - 每个接口写成 `<<baseUrl>>` + 路径，`baseUrl` 做成集合变量，取 `servers[0].url`（`openapi/index.ts` 1160–1207）。
  - `{id}` 换成 `<<id>>`。query、header 参数进对应的表，cookie 参数忽略。
  - 示例值取 `example` > `examples` > `x-example` > `default`。
  - 一个标签一个文件夹。
  - 认证取第一种。
- **Postman 的映射**：
  - 用 `postman-collection` SDK 解析。
  - 文件夹嵌套保留；认证没写时继承；禁用的行保留为未启用。
  - GraphQL 请求体转成 JSON。
  - 脚本只在用户选择时导入（它能执行脚本）。

### 2.2 本项目的改写 [判断]

**按本项目的模型改写：**
- 原地址拆成两半：协议 + 主机对应被测环境的 `baseUrl`（只显示，不建环境）；路径前缀写进接口路径。
- 认证展开成请求头或 query（本项目没有继承）。
- 可选参数不导入（本项目的请求头和 query 没有禁用状态）。
- 不支持的内容不静默丢掉，逐条写进备注。
- 规则表在契约 §3.9。

**它导入器里的缺陷，我们这边已避开：**

| 缺陷 | 出处 | 本项目 |
|---|---|---|
| 只读操作级参数，写在路径级的参数丢失 | `openapi/index.ts` 1248–1284 | 路径级参数与操作级合并，同名的以操作级为准 |
| 请求体只认 11 种精确的媒体类型，`application/json; charset=utf-8`、`*/*`、`+json` 的请求体都会丢 | `data/rest/content-types.ts` 1–13 | 任何 JSON 类的写法都识别 |
| schema 生成示例时不处理 `allOf`；不检查循环引用，递归的 Swagger 2.0 schema 会让导入失败 | `openapi/example-generators/v3.ts` 76；`openapi/index.ts` 541 | `allOf` 合并；递归引用在再次出现处为 `null`；YAML 别名展开计入预算，超限返回 400 |
| 只看文档级的 `servers`，`{变量}` 不替换 | `openapi/index.ts` 1160–1207 | 按操作 > 路径 > 文档的顺序取，变量用默认值替换，相对地址相对文档地址 |
| Postman form-data 的文件项变成空的文本项；x-www-form-urlencoded 里禁用的行被当成启用的导入 | `postman.ts` 408 | 文件项保留为文件项，选好文件就能发；禁用的行不导入，名字写进备注 |
| 不认识的认证方式静默变成"继承" | `postman.ts` 277–384 | 写进备注 |
| 没有勾选和查重 | `ImportExport.vue` | 先预览成树、可以勾选；库里已有同方法同路径的标"已存在"，默认不勾；整批在一个事务里，失败就什么都不建 |

**新增：把 Postman 测试脚本转成提取规则。** Postman 集合最常见的串联写法是：

```js
const r = pm.response.json();
pm.environment.set('token', r.data.token);
```

本项目不执行脚本，但会把这类写法识别出来，转成提取规则（例如 `token ← data.token`）。这样导入后的接口直接就能串起来；脚本本身不导入（ADR-006）。Hoppscotch 没有这一步，因为它能执行脚本，不需要转换。

### 2.3 验证（2026-10-10）

**样本：**
- test_port 的 OpenAPI 3.1（FastAPI 生成）和 Postman v2.1 集合；
- Swagger Petstore 2.0、Petstore 3.0；
- OAI 官方示例：petstore-expanded、uspto、link-example、api-with-examples、webhook-example；
- 自造的边界文档：循环引用、YAML 别名炸弹、Postman v2.0、不带协议的地址。

**结果：**
- **逐个解析**：全部能解析；别名炸弹返回 400。
- **第二个实例**（正式库的拷贝，8099 端口）上检查了导入接口：
  - 整批导入：26 个接口、6 个文件夹；
  - 有一个非法接口时整批拒绝，库里不变；
  - 再次预览，全部标"已存在"。
- **Playwright 走了完整的界面**：
  - 上传文件：35 个接口，9 个标"已存在"，原地址对上了"test_port 测试"环境；
  - 按地址导入；
  - 粘贴坏 YAML 时报错；
  - 导入后树里出现新文件夹并打开第一个接口。
- **端到端**：导入的"登录（表单）"经 k6 发出，用转换来的提取规则拿到 token；"用户列表"带上 `Bearer <token>` 返回 200。

---

## 3. 建议下一批：编辑器和响应查看的交互

[事实] 列来自 Hoppscotch 源码；[判断] 列是对本项目的建议。

**本项目已经有、而且比它强的**（不用学）：
- 路径和参数表的双向同步：它只有"选中文字 → 添加到参数"的右键菜单（`common/services/context-menu/menu/parameter.menu.ts`）。
- 耗时分解：它只有总耗时（`common/helpers/types/HoppRESTResponse.ts`）。
- 变量按状态着色并悬停看值：两边都有。
- Ctrl + Enter 发送、Ctrl + S 保存：两边都有。

**建议做的：**

| 能力 | Hoppscotch [事实] | 本项目现状 | 建议 [判断] | 改动面 |
|---|---|---|---|---|
| 批量编辑 | 参数、请求头、表单可切成文本，一行 `key: value`，`#` 开头表示禁用（`data/rawKeyValue.ts` 167–179） | 只有表格 | 请求头、Query、表单、环境变量表加"批量编辑"，从浏览器开发者工具或文档里整段粘贴 | 前端，`KeyValueEditor` |
| 请求栏粘贴 cURL | URL 栏粘贴以 `curl ` 开头的文本时，打开 cURL 导入并带入内容（`common/components/http/Request.vue` 456–468） | 只能从"新建"菜单进 | 路径框同样处理 | 前端，小 |
| HEAD / OPTIONS 方法 | GET…TRACE 和自定义方法 | 只有 5 种；导入时 HEAD / OPTIONS 只能跳过（test_port 就有一个 HEAD） | 加 HEAD、OPTIONS：引擎本来就用通用的 `http.request`；HEAD 不能设"响应体包含" | 契约、校验、类型、方法颜色 |
| 响应体复制 / 下载 / HTML 预览 | 复制（Ctrl + .）、下载（Ctrl + J）；HTML 用 `sandbox=""` 的 iframe 预览（`common/components/lenses/renderers/HTMLLensRenderer.vue` 97–104） | 只有格式化 / 原文切换 | 加这三个。它的 jq 过滤不学：要在前端再实现一遍 GJSON，和引擎成了两套语义 | 前端，`DebugStepPanel` |
| 未定义变量一键加到环境 | 检查器标出"变量不存在"，带"添加到环境"按钮（`common/services/inspection/inspectors/environment.inspector.ts` 120–147） | 橙色标出、悬停说明 | 悬停提示里加"添加到环境变量"，打开变量表并填好名字 | 前端，小 |
| Ctrl + K 命令面板 | 搜集合、历史、环境和各种操作（`common/services/spotlight/`） | 没有 | 搜接口、业务流程、测试、被测环境、运行记录，回车跳过去；对象多起来以后有用 | 前端，中 |
| 发送历史 | 每次发送后自动记录请求快照、状态码、耗时，可加星，最多 50 条，存本地，不存响应体（`common/newstore/history.ts`） | 调试不留记录 | 只在浏览器里记最近几十次发送的摘要，可以回到当时的请求；和"调试不留运行记录"不冲突，但要用户确认要不要 | 前端，中 |
| 多标签页 | 多请求标签、未保存圆点、关闭确认、持久化（`common/services/tab/`） | 单编辑器 + 自动保存 + 记住位置 | 暂不建议：自动保存已经解决了"切走丢改动"，标签页的收益有限 | — |

---

## 4. 先定方向：涉及未决事项或已有决定

[判断] 以下每一项都动到 `CLAUDE.md` 的未决事项或已有的 ADR，按规矩先由用户决定。

1. **密钥变量（未决事项"凭据"）**
   - Hoppscotch 的做法 [事实]：变量可以标成 secret。写库、同步、导出之前都清空 secret 的值，真实值只存在用户本地（`common/helpers/clientLocalVariables.ts` 23–30）；命令行运行时从进程的环境变量取（`cli/utils/request.ts` 41–67）。
   - 本项目的难点：压测在服务器上跑，k6 必须拿到真实值，所以不能照搬"只存在本地"。
   - 可选方向：环境变量加 secret 标记，值不进快照和可下载的 `plan.json`，运行时经环境变量交给 k6，页面上打码显示；或者值只来自后端进程的环境变量。
2. **命令行与 CI（未决事项"CI 的入口"）**
   - Hoppscotch 的做法 [事实]：`hopp test <集合文件或 id> -e <环境> --reporter-junit`，全部通过退出码 0，否则 1；JUnit 报告里每条断言一个 testcase（`cli/index.ts` 49–102，`cli/utils/reporters/junit.ts`）。
   - 可参考的形态：一个薄命令行，调 `POST /api/runs`、等运行结束、按判定退出，再写一份 JUnit（每条阈值一个 testcase）。这正是 `ARCHITECTURE.md` §3.8 要选的"调后端接口"那条路。
3. **行的启用开关**
   - Hoppscotch 的做法 [事实]：参数、请求头每行可以关掉，关掉的不发。
   - 本项目的 `headers` 是对象（名称 → 值），没有地方放开关。要做就得改成行数组，牵动契约、迁移、引擎的请求头合并和预检。
   - 收益是"临时关掉一个请求头试试"；目前删掉再加回来也能做到。
4. **文件夹级的公共请求头 / 认证**
   - Hoppscotch 的做法 [事实]：集合和文件夹上可以设请求头和认证，请求继承。
   - 本项目的文件夹按设计"只用于分组，不进 plan"，公共请求头放在被测环境上。做这项会改变这条决定，暂不建议。
5. **导出 OpenAPI**
   - Hoppscotch 的做法 [事实]：可以把集合导出成 OpenAPI 3.1（`common/helpers/import-export/export/openapi.ts`）。
   - 和导入配对，能把接口交给别的工具。目前没有这个需求。

---

## 5. 不适用

| 能力 | 为什么不用 [判断] |
|---|---|
| 前置 / 测试脚本（`pw` / `hopp` / `pm`，QuickJS 沙箱） | ADR-006 和 `ARCHITECTURE.md` §12 不做脚本：脚本让变量来源无法静态检查。本项目用提取规则和检查；导入时把 Postman 里最常见的写法转成提取规则（§2.2） |
| 拦截器、代理、浏览器扩展、桌面 agent / relay | 本项目的请求一律经 k6 发出，调试和压测是同一份 `interp.js`；在别处发请求会出现两套语义 |
| GraphQL、WebSocket、SSE、Socket.IO、MQTT | §12"HTTP 以外的协议"：目标系统需要时再做 |
| 团队、工作区、实时同步、登录（NestJS + Prisma） | 登录与权限是条件触发的未决事项（ADR-005）；技术栈也不同 |
| Mock 服务器（后端按保存的示例响应） | 不能当压测目标，"自有目标系统"仍未决；对调试的帮助也有限 |
| 文档发布、AI 对话、29 种语言的代码生成 | 已有"复制为 cURL"；AI 受 §9 约束 |
| 集合运行器（多次迭代、数据文件、逐请求结果） | 业务流程 + 数据集 + 试跑已经覆盖，正式运行的结果由 k6 和判定规则给出 |
| 数据模型版本（verzod） | 本项目用 SQLite 的 `user_version` 迁移 |

---

## 6. 来源

都在 `https://github.com/hoppscotch/hoppscotch/tree/63273f8e599e73f0fb38c0739314e8d46b6bc83d/packages/` 下：

- 导入：`hoppscotch-common/src/helpers/import-export/import/openapi/index.ts`、`openapi/example-generators/v3.ts`、`postman.ts`、`har.ts`、`insomnia/`、`postmanEnv.ts`；`hoppscotch-data/src/rest/content-types.ts`
- 导出：`hoppscotch-common/src/helpers/import-export/export/openapi.ts`
- 编辑器：`hoppscotch-common/src/components/http/Request.vue`、`KeyValue.vue`、`Headers.vue`、`Authorization.vue`；`hoppscotch-data/src/rawKeyValue.ts`
- 响应查看：`hoppscotch-common/src/helpers/lenses/lenses.ts`、`components/lenses/renderers/JSONLensRenderer.vue`、`HTMLLensRenderer.vue`
- 检查器：`hoppscotch-common/src/services/inspection/`
- 历史、标签页、命令面板：`hoppscotch-common/src/newstore/history.ts`、`services/tab/`、`services/spotlight/`
- 变量与密钥：`hoppscotch-data/src/environment/`、`hoppscotch-common/src/helpers/clientLocalVariables.ts`、`services/secret-environment.service.ts`、`helpers/utils/environments.ts`
- 继承：`hoppscotch-common/src/newstore/collections.ts`
- 命令行：`hoppscotch-cli/src/index.ts`、`utils/request.ts`、`utils/reporters/junit.ts`
- 脚本：`hoppscotch-js-sandbox/src/`
