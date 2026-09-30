# 提交记录

每次 git 提交在这里记一条：时间、提交号、做了什么。最新的在最上面。

说明：一条记录和它描述的提交在同一次提交里写入，写的时候还不知道自己的提交号，所以**最新一条的提交号在下一次提交时补上**。时间为服务器本地时间（UTC）。

| 时间 | 提交号 | 批次 | 标题 | 做了什么 |
|---|---|---|---|---|
| 2026-09-30 06:05 | （下次提交时补） | MVP 第 0 批 | chore: MVP plan, contract, uv project and local toolchain | 用 uv 初始化 Python 项目（`pyproject.toml`、`uv.lock`、`.python-version`，依赖 FastAPI 和 uvicorn）；新增 `scripts/setup.sh`（`uv sync`，并下载 k6 v2.3.0 和构建前端用的 Node v24.21.0 到 `.tools/`）和 `scripts/env.sh`；新增 `.gitignore`；新增 MVP 计划 `docs/plans/mvp-plan.md` 和三方接口契约 `docs/plans/mvp-contract.md`；新增 `docs/records/`（提交记录、技术笔记） |
| 2026-09-30 05:56 | `a6a37ee` | Phase 0 补充 | docs: add frontend plan, unified viewing entry and CLAUDE.md | `ARCHITECTURE.md` 新增 §8 前端规划，重写 §3.9 统一查看入口；新增 ADR-004（静态报告 + 只读控制台）；同步 roadmap、ADR-001、ADR-003；新增 `CLAUDE.md` |
| 2026-09-29 08:39 | `922e376` | Phase 0 | docs: Phase 0 research and architecture | 首次提交。唯一的架构文档 `docs/ARCHITECTURE.md`；3 份 ADR；路线图和 AI 机会地图；5 份研究记录（k6、k6 生态、性能工程、Observability、AI + 性能测试） |
