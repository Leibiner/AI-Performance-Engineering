# Research：页面名称与侧栏分组的业内依据

> 研究日期：2026-10-10
> 标记约定：**[事实]** 有来源；**[判断]** 本项目结论；**[推测]** 未完全验证。
> 来源都是官方文档。各家控制台要登录才能看，菜单是按文档里"左侧导航栏选择……"这类原句拼出来的，可能不全。标 ✔ 的引文 2026-10-10 逐条打开原文核对过，其余引自调研时读到的原文。
> 本文回答：**页面和侧栏分组该叫什么、业内头部产品怎么叫？** 结论经用户确认（2026-10-10），落在契约 §2 和 `ARCHITECTURE.md` §8.2。以后改名先在这里补依据。

---

## 0. 结论

| 页面实际做什么 | 定名 | 改动 | 主要依据（详见 §1–§3） |
|---|---|---|---|
| 各类数量、判定分布、最近运行 | 概览 | 不改 | 腾讯云压测报告首个页签"概览" ✔；国外 Home |
| 单个 HTTP 请求的定义与调试 | 接口 | 不改 | Apifox、Apipost"接口"，MeterSphere"接口定义"；国外 Request |
| 多个接口串成的操作链 | 业务流程 | 不改 | 阿里"业务会话……具有业务含义" ✔、OpenText "actions of a business process"；不用"场景"（§3） |
| CSV 数据集、请求里上传的文件 | 测试数据 | 不改 | Apifox"测试数据" ✔、Apipost"测试数据"、BlazeMeter "Test Data" |
| 施压方式（open / closed 四种形态） | 施压配置 | 原"负载配置" | 阿里 ✔、腾讯 ✔"施压配置"；华为、MeterSphere ✔"压力配置" |
| 选流程和权重 + 验收标准，从这里发起运行 | 测试 | 不改 | 国外 Test / Test run 最统一；MeterSphere 性能测试下的页面【测试】 ✔ |
| 每次执行：状态、判定、指标、产物、快照 | 运行记录（列表页） | 原"运行" | 国外 Runs / Test runs；不叫"报告"（§3） |
| 被压的目标：地址、类型、请求头、变量、安全上限 | 被测环境 | 不改 | 腾讯"环境管理"、MeterSphere / Apifox"环境"、Postman Environment |
| 运行 k6 的机器 | 施压机 | 原"执行机" | 阿里"施压机" ✔、腾讯报告页签"施压机" ✔；国外 load generator |

侧栏：概览；**业务**（接口、业务流程、测试数据）；**压测**（施压配置、测试、运行记录）；**资源**（被测环境、施压机）。

只改了显示名：表名、接口路径、字段名都不变（`executors`、`profiles`、`runs`）。对象本身仍叫"运行"（发起运行、运行详情、删除运行），只有列表页叫"运行记录"。库里已有的那台机器名叫"本机执行机"，这是数据，没有改；新建库的默认名是"本机施压机"。

---

## 1. 国内产品 [事实]

### 1.1 阿里云 PTS（3.0 为主）

- 菜单：性能测试 › 创建场景 / 场景列表 / 报告列表 / 定时压测 / 数据源。[A1][A2][A3][A4]
- 用户指南的分组：快速入门、**业务场景配置**、**施压配置**（下分"压力来源""压力模型"）、更多设置 ✔ [A5]
- 结构：原文"一个压测场景包含一个或多个并行的业务（即业务会话），每个业务包含一个或多个串行的请求（即API）" ✔ [A1]

| 概念 | 用词 |
|---|---|
| 接口 | 压测API："API是由用户行为触发的一条端上请求" [A1] |
| 业务流程 | 业务会话："业务会话是一组压测API的有序集合（类似于事务），具有业务含义。" ✔ [A1]；2.0 叫"串联链路" [A6] |
| 测试数据 | 菜单"数据源"，页面"参数文件" [A2] |
| 施压方式 | 施压配置 ✔ [A5]；压力模式分"虚拟用户模式""RPS模式"，虚拟用户模式下"设置各业务会话的虚拟用户权重" ✔ [A7] |
| 测试 | 压测场景，施压配置写在场景里 [A1] |
| 运行 | 压测报告（菜单"报告列表"） [A3] |
| 机器 | 施压机："IP数：对应施压机数，单个施压机最大支持500虚拟用户（并发）。"；"如果从施压机监控观察到集群的带宽、CPU或内存已成为瓶颈……" ✔ [A8] |
| 验收标准 | 2.0"SLA定义" [A9]；3.0 发布说明用"性能基线" [A10] |

### 1.2 华为云 CodeArts PerfTest

- 左侧导航：PerfTest测试工程 / JMeter测试工程 / **测试资源** / SLA管理 / 定时压测；进入工程后的页签：测试用例 / 测试任务 / 性能报告；每个用例右侧：用例步骤 / 压力配置 / SLA配置。[H1]–[H5]
- 基本概念（✔ [H6]）：
  - "测试资源指私有资源组。"
  - "测试任务指基于已定义的测试模型发起一次性能测试的活动。"
  - "事务是指用户自定义的操作模型……"
  - "执行机：在压测过程中能够提供自身性能数据的施压目标机器。""调试机：调试执行机的节点。"
- 资源组配置建议（✔ [H7]）："测试资源组包含共享资源组和私有资源组两种类型"；"如需要压测外部服务，请为每一个执行机节点都绑定一个弹性IP。"——执行机是资源组里发起压力的节点，定义原句的措辞可以读成被压的机器。

| 概念 | 用词 |
|---|---|
| 业务流程 | 事务（"事务可以被多个用例复用"） [H8]；用例里分"前置步骤：每个执行线程中，仅执行一次"和"测试步骤" [H4] |
| 测试数据 | 全局变量，"文件变量导入" csv / xlsx [H9] |
| 施压方式 | 压力配置；压力模式有并发、TPS、摸高、浪涌、震荡、智能摸高 [H3] |
| 测试 | 测试用例（步骤 + 压力配置 + SLA）+ 测试任务（选用例，串行或并行执行） [H5] |
| 运行 | 测试报告，页签"性能报告" [H2] |
| 机器 | 测试资源（组）、执行机 ✔ [H6][H7] |
| 验收标准 | SLA："判断性能压测是否异常的重要依据" [H1] |

### 1.3 腾讯云 云压测

- 菜单：云压测 › 项目列表 / 测试场景 / **环境管理** / 定时压测 / 告警联系人。[T1][T2][T3]
- 报告页签：概览、服务明细、检查点明细、脚本信息、多维分析、**施压机**、请求采样 ✔ [T4]

| 概念 | 用词 |
|---|---|
| 被测环境 | 环境管理："环境管理支持用户创建不同的环境变量组" [T2] |
| 接口 | 请求（"在场景编排模块，输入请求描述和请求地址，即可添加 HTTP 请求"） [T5] |
| 业务流程 | 场景里的"场景编排"模块，不是独立对象 [T5] |
| 测试数据 | 文件管理下的"参数文件"，同级有请求文件、协议文件 [T6] |
| 施压方式 | 施压配置："施压配置用于控制压测过程中的流量，来模拟真实业务场景中的流量变化及流量分布。" ✔；压力模式分并发模式、RPS 模式 ✔ [T7] |
| 测试 | 场景 / 测试场景："管理一次压测的配置、资源、生命周期的最小单元" [T3] |
| 运行 | 每次执行叫"压测任务"（"当您触发运行您的压测场景……会为您创建出一个压测任务"），结果叫"压测报表"（实时报表 / 历史报表） ✔ [T4] |
| 机器 | 报告页签"施压机"："在施压机页面，您可查看该压测任务的施压机的基本信息、在压测过程中输出的日志、施压机本身的资源使用状况。" ✔ [T4]；施压配置页正文叫"压测资源"（"压测资源是引擎调度的基本单位"）和"压测机" ✔ [T7] |
| 验收标准 | SLA 配置 [T8] |

### 1.4 MeterSphere（v2）

- 一级模块：我的工作台 / 测试跟踪 / 接口测试 / UI 测试 / 性能测试 / 报表统计 / 项目设置 / 系统设置；性能测试下分首页 / 测试 / 报告。[M1][M2]
- 性能测试页面原文：【性能测试-测试】、【场景配置】【压力配置】【高级配置】、【测试资源池】、"性能测试报告" ✔ [M1]
- 接口叫"接口定义" [M3]；多接口编排叫"场景"（"由一组用例和接口组装而成"），性能测试在【场景配置】里"引用接口自动化场景" [M4][M1]；环境在项目设置里（"HTTP配置：此处可配置环境地址"） [M5]。
- v3 用户手册里没有性能测试模块 [M6]。

### 1.5 Apifox

- 侧边栏：接口管理 / 自动化测试 / 分享文档 / 请求历史 / 项目设置 / 邀请成员 [F1]
- 测试数据："测试数据是一个二维表格，每列代表一个变量，每行包含这些字段的值，用于单次场景用例执行。"入口是"测试数据"标签页 ✔ [F2]；性能测试时有"随机匹配""顺序匹配" [F3]
- 业务流程："原「测试场景」已更名为「场景用例」" [F4]；性能测试直接在场景用例上发起，施压参数是虚拟用户数、运行时间、爬坡时间，没有总称 [F3]
- 环境：环境 / 运行环境，由前置 URL 和变量组成 [F5]

### 1.6 Apipost

环境管理（测试条件里叫"测试环境"）、接口、测试用例（编排）、测试数据（txt / csv）、压测模式（固定模式、爬坡模式）、测试报告 / 压测报告。[P1][P2][P3]

### 1.7 火山引擎

没查到压测类产品的官方文档。

### 1.8 国内汇总

| 概念 | 阿里 PTS | 华为 PerfTest | 腾讯云压测 | MeterSphere v2 | Apifox | Apipost |
|---|---|---|---|---|---|---|
| 被测环境 | — | — | 环境管理 | 环境 | 环境 / 运行环境 | 环境 / 测试环境 |
| 接口 | 压测API | 请求 | 请求 | 接口定义 | 接口 | 接口 |
| 业务流程 | 业务会话 | 事务 | 场景编排 | 场景 | 场景用例 | 测试用例 |
| 测试数据 | 数据源 / 参数文件 | 全局变量 | 参数文件 | CSVDataSet / 文件管理 | 测试数据 | 测试数据 |
| 施压方式 | 施压配置 | 压力配置 | 施压配置 | 压力配置 | — | 压测模式 |
| 测试 | 压测场景 | 测试用例 + 测试任务 | 测试场景 | 性能测试 | 场景用例 | 测试用例 |
| 运行 | 压测报告 | 测试报告 | 压测任务 / 压测报表 | 性能测试报告 | 测试报告 | 测试报告 |
| 机器 | 施压机 | 测试资源 / 执行机 | 压测资源 / 施压机 | 测试资源池 | 运行于 / Runner | — |
| 验收标准 | SLA / 性能基线 | SLA | SLA | — | — | — |
| 编排与压测定义 | 合一 | 分开 | 合一 | 分开 | 合一 | 合一 |

---

## 2. 国外产品 [事实]

导航：

- LoadRunner Enterprise：Home Page / **Test Management**（Tests & Scripts、Runs）/ **Assets**（Analysis template、Monitors）/ **Hosts** / Timeslots / Performance Trending / System Reports ✔ [L1]
- OpenText Core Performance Engineering（原 LoadRunner Cloud）：Home / Load tests / Assets（Scripts、Monitors、Load generator assets、Agents、Network emulations、Script keys、Data files、Templates）/ Results [O1][O2]
- NeoLoad Web（2025.2）：Home / Tests / **Resources**（"manage Zones and Reservations"）/ Test Results / Dashboards / Trends [N1]
- Grafana Cloud k6：Performance › Projects / Settings；Settings › **Execution resources** › Load zones / Static IPs / Environment variables [G1][G2]
- BlazeMeter：Performance › Home / Workspace / Projects / Tests / Reports / Active Runs / Create Test [B1]
- Gatling Enterprise：Home / Tests / Organization / API Tokens / Packages / Dedicated IP Addresses / Private Locations [GA1]
- Postman：侧栏默认 Collections / Environments / … / Datasets / Flows；性能测试在 Collection Runner 里选 Performance [PO1]
- Azure Load Testing：资源左栏有 Tests，test run 在 test 详情里；编辑 test 的页签 Basics / Test plan / Load / Test criteria / Monitoring [Z1]

| 概念 | k6 Cloud | OpenText CPE | LoadRunner Ent. | BlazeMeter | Gatling | NeoLoad | Postman | Azure |
|---|---|---|---|---|---|---|---|---|
| 被测环境 | — | — | — | — | — | Servers | Environment | — |
| 接口 | Request | — | — | Request | Request | Request | Request | HTTP request |
| 业务流程 | Scenario | Script | Script / Vuser group | — | Scenario | User Path | Collection | Test plan |
| 测试数据 | — | Data files | — | Test Data | Feeders | File 变量 | Datafiles / Datasets | CSV input data files |
| 施压方式 | Executor | Load profile | Workload | Load Configuration | Injection profile | Load variation policy | Load profile | Load pattern |
| 测试 | Test | Load test | Performance test | Test | Test | Scenario / Test | — | Test |
| 运行 | Test run | Runs / Results | Test runs | Reports / test run | Run | Test Result | Performance run | Test run |
| 机器 | Load zone | Load generator | Hosts | Location / engine | Location / load generator | Zone / Load Generator | Run method | Test engine |
| 验收标准 | Thresholds | SLA | SLA | Failure Criteria | Acceptance criteria | SLA profile | Pass test if | Fail criteria |

---

## 3. 取舍 [判断]

- **施压机**：腾讯报告的"施压机"页签展示机器的基本信息、日志和资源占用，和本项目这一页的内容一致；阿里也用"施压机"。"执行机"只有华为在用，定义原句可以读成被压的机器；"执行"也说不清执行的是什么。
- **施压配置**：国内阿里、腾讯用"施压配置"，华为、MeterSphere 用"压力配置"，都没有"负载配置"；选"施压配置"和"施压机"成对。所有查到的产品都把施压方式写在测试 / 场景里，没有一家做成能被多个测试复用的独立对象——本项目把它独立出来是 ADR-002"业务与负载分开"的设计，与命名无关。
- **运行记录**：国内多叫"报告"，国外多叫 run。列表里有正在跑、可以停止的运行，详情页运行中显示进度、结束后才是报告；腾讯也把执行（压测任务）和结果（压测报表）分开叫。"运行"单独做菜单名像按钮，补"记录"，也对应架构里的 Run Record。
- **任何页面对象都不用"场景"**：阿里、腾讯的"场景"是整个压测（含施压配置），MeterSphere、Apifox 的"场景"只是接口编排，同一个词有两种意思；而且本项目的 Scenario 专指 k6 的编译产物（`CLAUDE.md`）。
- **测试不改名**：国外 Test / Test run 这一对最统一。阿里、腾讯的"压测场景"和华为的"测试用例"都把施压配置包在里面，本项目的测试不含施压配置（发起运行时才选），借用这些叫法会让人到测试里找施压配置。
- **业务流程不改名**：这个概念业内叫法最分散；阿里"业务会话……具有业务含义"、OpenText "actions of a business process" 都落在"业务"上。
- **分组**：业内常见三块——测试和结果、构成测试的东西、机器等资源，资源放最后（LoadRunner Enterprise 的 Test Management / Assets / Hosts，NeoLoad 的 Tests / Resources，华为左侧单独的"测试资源"，k6 的 Settings › Execution resources）。本项目按 ADR-002 把构成测试的东西分成"业务"和"压测"两组（阿里文档同样分"业务场景配置""施压配置"），组内保持搭建顺序，资源组放最后。组名是这次中文出处最弱的部分："资源"取自华为"测试资源"、NeoLoad Resources、k6 Execution resources。
- **这次没动的页内名词**："验收标准"在三家国内云厂商都叫 SLA，国外有 thresholds / SLA / criteria 三种叫法；要不要统一留给用户决定。

---

## 4. 出处

阿里云 PTS（前缀 `https://help.aliyun.com/zh/pts/`）
- A1 `performance-test-pts-3-0/user-guide/create-a-stress-test-scenario`（发起HTTP接口压测）
- A2 `performance-test-pts-3-0/user-guide/parameter-file`（管理参数文件）
- A3 `performance-test-pts-3-0/user-guide/check-pts-3-report`（查看PTS压测报告）
- A4 `performance-test-pts-3-0/user-guide/scheduled-stress-testing`
- A5 `performance-test-pts-3-0/product-overview/pts-user-guide`
- A6 `performance-test-pts-2-0/user-guide/basic-request-information-1`
- A7 `performance-test-pts-3-0/user-guide/pressure-model`（选择合适的虚拟用户模式和RPS模式）
- A8 `performance-test-pts-3-0/user-guide/specifies-the-number-of-testing-ip-addresses`
- A9 `performance-test-pts-2-0/user-guide/configure-slas`
- A10 `product-overview/2024`

华为云 CodeArts PerfTest
- H1 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0080.html
- H2 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0018.html
- H3 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0106.html
- H4 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0096.html
- H5 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0051.html
- H6 https://support.huaweicloud.com/productdesc-cpts/cpts_productdesc_0004.html
- H7 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0154.html
- H8 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0155.html
- H9 https://support.huaweicloud.com/usermanualnew-cpts/cpts_02_0085.html

腾讯云 云压测
- T1 https://cloud.tencent.com/document/product/1484/68227
- T2 https://www.tencentcloud.com/zh/document/product/1249/67013
- T3 https://www.tencentcloud.com/zh/document/product/1249/67009
- T4 https://cloud.tencent.com/document/product/1484/74052（解读报告）
- T5 https://cloud.tencent.com/document/product/1484/74040
- T6 https://cloud.tencent.com/document/product/1484/74046
- T7 https://cloud.tencent.com/document/product/1484/74041（施压配置）
- T8 https://www.tencentcloud.com/zh/document/product/248/66494

MeterSphere（前缀 `https://metersphere.io/docs/`，证书校验不通过时用 `curl -k` 读）
- M1 `v2.x/user_manual/load_test/load_test/`
- M2 `v2.x/user_manual/load_test/test_report/`
- M3 `v2.x/user_manual/api_test/api_definition/`
- M4 `v2.x/user_manual/api_test/api_automation/`
- M5 `v2.x/user_manual/system_management/workspace/`
- M6 `v3.x/`

Apifox（前缀 `https://docs.apifox.com/`）
- F1 `page-layout`
- F2 `data-driven-testing`
- F3 `performance-testing`
- F4 `new-test-scenario`
- F5 `environments-and-services`

Apipost（前缀 `https://wiki.apipost.cn/docs/`）
- P1 `test/load-testing/`
- P2 `test/test-data/`
- P3 `http/environment-variables/`

国外
- L1 https://admhelp.microfocus.com/lre/en/26.1-26.3/online_help/Content/PC/LoadRunner_Enterprise_UI.htm
- O1 https://admhelp.microfocus.com/lrc/en/26.3/Content/Storm/banner.htm
- O2 https://admhelp.microfocus.com/lrc/en/26.3/Content/Storm/lp_assets.htm
- N1 https://docs.tricentis.com/neoload-web-2025.2/en-us/content/views_and_features/description_of_views.htm
- G1 https://grafana.com/docs/grafana-cloud/testing/k6/projects-and-users/projects/
- G2 https://grafana.com/docs/grafana-cloud/testing/k6/author-run/private-load-zone/
- B1 https://help.blazemeter.com/docs/guide/getting-started-interface.html
- GA1 https://docs.gatling.io/reference/user-guide/overview/
- PO1 https://learning.postman.com/docs/tests-and-scripts/performance-testing/performance-test-configuration
- Z1 https://learn.microsoft.com/en-us/azure/app-testing/load-testing/concept-load-testing-concepts

国外概念文档（§2 表里的其余用词出自这些页面）
- Grafana k6：`https://grafana.com/docs/` 下的 `grafana-cloud/testing/k6/author-run/test-builder/`（Requests、scenario）、`grafana-cloud/testing/k6/author-run/cloud-scripting-extras/cloud-environment-variables/`、`k6/latest/using-k6/scenarios/`（executor）、`k6/latest/using-k6/scenarios/concepts/open-vs-closed/`、`k6/latest/using-k6/thresholds/`
- OpenText CPE：`https://admhelp.microfocus.com/lrc/en/26.3/Content/Storm/` 下的 `t_define_load_test.htm`（测试页签）、`lg-profile.htm`（Load profile）、`loadtest_gen_settings.htm`（Run mode）、`lg-enhance.htm`（SLA）
- LoadRunner Enterprise：`https://admhelp.microfocus.com/lre/en/26.1-26.3/online_help/Content/PC/` 下的 `ui_performance_test_designer_window.htm`、`t_defining_performance_test_workload.htm`（workload、Vuser group）、`ui_testing_hosts_perspective.htm`（Hosts）
- BlazeMeter：`https://help.blazemeter.com/docs/guide/` 下的 `performance-load-configuration.html`、`performance-load-distribution.html`、`private-locations-create.html`、`performance-create-url-api-test.html`、`test-data-what-are-data-entities-data-parameters.html`、`performance-failure-criteria.html`
- Gatling：`https://docs.gatling.io/` 下的 `concepts/`（simulation、assertions）、`concepts/injection/`、`concepts/session/feeders/`、`reference/run-tests/tests/`、`reference/run-tests/tests/no-code/`、`reference/run-tests/tests/optional-config/`、`reference/run-tests/tests/test-as-code/`、`guides/analysis/enterprise-reports/`
- NeoLoad：`https://docs.tricentis.com/` 下的 `neoload-2026.1/en-us/content/reference_guide/servers_tree.htm`、`neoload-2026.2/en-us/content/reference_guide/user_paths_overview.htm`、`neoload-2026.2/en-us/content/reference_guide/create_populations.htm`、`neoload-2026.1/en-us/content/reference_guide/variables_and_fuctions.htm`、`neoload-2026.1/en-us/content/reference_guide/load_variation_policy.htm`、`neoload-2026.1/en-us/content/reference_guide/test_settings.htm`、`neoload-2026.1/en-us/content/reference_guide/service_level_agreement_sla_profiles.htm`、`neoload-web-2025.2/en-us/content/reference_guide/tests_create.htm`
- Postman：`https://learning.postman.com/docs/getting-started/basics/navigating-postman`、`https://learning.postman.com/docs/tests-and-scripts/performance-testing/performance-test-metrics/`
- Azure Load Testing：`https://learn.microsoft.com/en-us/azure/app-testing/load-testing/` 下的 `how-to-create-manage-test-runs`、`how-to-add-requests-to-url-based-test`、`how-to-high-scale-load`、`how-to-define-test-criteria`、`how-to-generate-load-from-multiple-regions`
