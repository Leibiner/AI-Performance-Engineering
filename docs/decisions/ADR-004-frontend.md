# ADR-004：前端 —— 静态报告 + 只读 Web 控制台，分阶段引入

- 状态：**Accepted**（技术选型在 Phase 2 开始时复核）
- 日期：2026-09-30
- 相关：`ARCHITECTURE.md` §3.9、§8；修订 ADR-001 中"不做 Web UI"的部分；对 ADR-003"无构建步骤"增加例外

---

## Context

Phase 0 的最初设计把 "Web UI" 整体列为不做，查看结果依赖三样东西：终端输出、`report.md`、Grafana。后续讨论暴露出三个问题：

1. **数据分散**：结论在文件里，曲线在 Grafana 里，历史在另一个目录里，除了跑压测的人，其他人很难看懂一次运行的结果。
2. **以 Grafana 作为唯一入口并不合适**：Grafana 擅长时序，不擅长"按运行"组织的数据（运行列表、阈值结果、判定、对比）。原方案要靠 Infinity 数据源读 JSON 文件，这个依赖没有验证过。
3. **项目需要明确的前端规划**：没有前端，开发人员和负责人无法自助查看性能状态。

同时，ADR-001 拒绝 "Platform First" 的理由仍然成立：一次性建设带编排、用户、权限的压测平台，没有需求支撑，而且页面触发压测有爆炸半径。

## Options

### Option A：不做前端，继续用 Grafana + Markdown

- 优点：零开发量。
- 缺点：按运行组织的数据在 Grafana 中体验差；依赖未验证的插件；非工程师难以使用。

### Option B：完整的压测平台前端

页面上编排测试、发起和停止压测、编辑 SLO 和 Profile、用户与权限。

- 优点：功能完整。
- 缺点：需要执行器、登录、权限、审计等一整套后端；页面触发有爆炸半径；SLO 和 Profile 脱离 git 后失去审核与版本；与 "Architecture First" 冲突。

### Option C：分阶段的只读前端

- F0（Phase 1）：单文件静态 HTML 报告，由 `tools/report.mjs` 生成；
- F1（Phase 2）：只读 Web 控制台（单页应用 + 只读 API）；时序曲线嵌入 Grafana 面板；
- F2（Phase 3）：趋势、证据视图、测试目录；
- F3（条件触发）：页面发起压测，必须带护栏，且只是调用 CI，不自建执行器；
- F4（Phase 5）：AI 建议面板，仅当 Phase 4 评估通过。

## Decision

**采用 Option C。**

约束：

1. 前端和 API **只读**：不计算判定和回归，不写 Run Record，不调用 k6；
2. 前端只通过只读 API 访问数据；执行侧与展示侧之间唯一的契约是 Run Record（`schemas/run-record.schema.json`）；
3. 时序曲线由 Grafana 提供，前端不重画监控大盘；
4. SLO、Profile、Flow、基线的修改始终走 git 和 PR；
5. 前端和 API 可以整体移除，执行、判定、CI 不受影响；
6. npm 依赖和构建步骤只允许出现在 `web/` 和 `server/`，`perf/` 和 `tools/` 仍遵守 ADR-003。

技术选型（推荐）：React + TypeScript + Vite + Ant Design + ECharts；API 用 Node.js。

## Why

- 统一入口应该围绕"运行"组织，这是 Grafana 的弱项、专用前端的强项；
- 只读前端的开发和维护成本可控，不需要登录、权限、执行器；
- F0 不需要任何基础设施，Phase 1 就能交付可读的报告；
- 把"发起压测"留在 CLI 和 CI，执行路径只有一条，判定和门禁保持确定。

## Consequences

正面：

- 每次运行有一个固定的链接，CI 通知、报告、实验记录都可以指向它；
- 去掉了对 Grafana Infinity 插件的依赖；
- 存储形态（文件或 PostgreSQL）被 API 隔离，前端不受影响。

负面 / 需要承担：

- Phase 2 增加一个需要部署和维护的 Web 服务；
- 引入前端工具链（npm、构建）和 Run Record schema 的版本管理；
- Grafana 面板嵌入需要配置允许嵌入并解决认证，Phase 2 开始时验证；不可行则退回带参数的链接。

## Rejected Alternatives

| 方案 | 拒绝原因 |
|---|---|
| Option A：只用 Grafana + Markdown | 按运行组织的数据体验差；依赖未验证插件 |
| Option B：完整平台前端 | 无需求支撑；爆炸半径；定义脱离 git |
| 前端直接读文件或数据库 | 存储形态未定，耦合后更换存储要改前端 |
| 前端通过 API 代理查询 Prometheus 并自己画曲线 | 重复 Grafana 已有的能力 |

## Future Reconsideration Conditions

- F1 上线后访问量很低（大家只看 CI 通知和 report.html）→ 不做 F2，保留 F0 / F1；
- 采用 Grafana Cloud k6 → 评估用其自带界面替代 F1 的部分页面；
- 非工程师需要自助发起压测，或 CLI / CI 触发成为瓶颈 → 启动 F3，并先落实护栏（`ARCHITECTURE.md` §8.8）；
- Grafana 面板嵌入不可行 → 退回链接方式，并重新评估是否在前端画少量关键曲线。
