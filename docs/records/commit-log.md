# 提交记录

每次 git 提交在这里记一条：时间、提交号、做了什么。最新的在最上面。

说明：一条记录和它描述的提交在同一次提交里写入，写的时候还不知道自己的提交号，所以**最新一条的提交号在下一次提交时补上**。时间为服务器本地时间（UTC）。

| 时间 | 提交号 | 批次 | 标题 | 做了什么 |
|---|---|---|---|---|
| 2026-09-30 06:48 | （下次提交时补） | MVP 第 3 批 | docs: sync architecture docs with the MVP implementation | `ARCHITECTURE.md` 按实际实现整体改写（状态表、MVP 相对原设计的出入、架构图、目录树、前端改为管理控制台、未实现部分标注为规划）；新增 ADR-005（管理控制台、数据驱动的流程、uv + Python 后端、SQLite、Vue、百度冒烟目标及其代价）；ADR-001 至 ADR-004 加修订 / 被取代说明；`roadmap.md` 加 MVP 与原 Phase 1、2 的对应；`research/k6.md` 把 summary 结构的推测改为实测结论；`CLAUDE.md` 改为真实可用的命令和约束；契约加入执行机与被测环境类型的约定（实现在下一批） |
| 2026-09-30 06:28 | `c37c57a` | MVP 第 1、2 批 | feat: MVP console (k6 engine, FastAPI backend, Vue frontend) | **执行引擎** `perf/`：通用 k6 脚本 `runner.js` 读取 plan.json 解释执行；`core/` 生成 scenarios、阈值、Run Record；3 份示例 plan。**后端** `server/`：FastAPI + sqlite3，六张表和种子数据，五类定义的增删改查，运行的预检、启动、停止、判定、存档、产物，托管前端。**前端** `web/`：Vue 3 + Element Plus，8 个页面（概览、环境、接口、业务流程、负载配置、测试、运行列表、运行详情）。**联调**：修复"浏览器连着 k6 实时仪表盘时 k6 不退出"（仪表盘改为只监听本机，进度改由后端从日志提取）；新增 `scripts/start.sh`、`stop.sh`；契约和技术笔记按实测更新 |
| 2026-09-30 05:59 | `bc58457` | MVP 第 0 批 | chore: MVP plan, contract, uv project and local toolchain | 用 uv 初始化 Python 项目（`pyproject.toml`、`uv.lock`、`.python-version`，依赖 FastAPI 和 uvicorn）；新增 `scripts/setup.sh`（`uv sync`，并下载 k6 v2.3.0 和构建前端用的 Node v24.21.0 到 `.tools/`）和 `scripts/env.sh`；新增 `.gitignore`；新增 MVP 计划 `docs/plans/mvp-plan.md` 和三方接口契约 `docs/plans/mvp-contract.md`；新增 `docs/records/`（提交记录、技术笔记） |
| 2026-09-30 05:56 | `a6a37ee` | Phase 0 补充 | docs: add frontend plan, unified viewing entry and CLAUDE.md | `ARCHITECTURE.md` 新增 §8 前端规划，重写 §3.9 统一查看入口；新增 ADR-004（静态报告 + 只读控制台）；同步 roadmap、ADR-001、ADR-003；新增 `CLAUDE.md` |
| 2026-09-29 08:39 | `922e376` | Phase 0 | docs: Phase 0 research and architecture | 首次提交。唯一的架构文档 `docs/ARCHITECTURE.md`；3 份 ADR；路线图和 AI 机会地图；5 份研究记录（k6、k6 生态、性能工程、Observability、AI + 性能测试） |
