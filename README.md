# AI Performance Engineering

以 k6 为执行引擎的性能测试控制台。在页面上维护接口、业务流程、负载配置、验收标准和被测环境，查看执行机，点按钮发起压测，查看判定和指标，结果自动存档。

**当前阶段：MVP。** 压测目标是 `https://www.baidu.com`，只允许冒烟级别的小流量（这个被测环境的安全上限：2 并发、每秒 2 次、60 秒）。

## 启动

```bash
scripts/setup.sh     # 首次：uv 同步 Python 依赖，下载 k6 和构建前端用的 Node 到 .tools/（不需要 sudo）
scripts/start.sh     # 后台启动，默认端口 8088；前端产物不存在时会先构建
scripts/stop.sh      # 停止
```

启动后在浏览器打开 `http://<服务器地址>:8088`。

前提：已安装 [uv](https://docs.astral.sh/uv/)。Python 环境和依赖由 uv 管理（`pyproject.toml`、`uv.lock`）。

## 目录

| 目录 | 内容 |
|---|---|
| `perf/` | k6 执行引擎：通用脚本 `runner.js` 和 `core/`（生成 scenarios、阈值、运行记录） |
| `server/` | 后端：Python + FastAPI + SQLite |
| `web/` | 前端：Vue 3 + TypeScript + Element Plus |
| `scripts/` | 环境准备、启动、停止 |
| `docs/` | 文档，从 [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) 开始 |
| `data/`、`results/` | 运行时生成：数据库和每次运行的产物（不入 git） |

## 文档

- 架构与总体说明：[`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)
- MVP 计划与接口约定：[`docs/plans/mvp-plan.md`](docs/plans/mvp-plan.md)、[`docs/plans/mvp-contract.md`](docs/plans/mvp-contract.md)
- 提交记录：[`docs/records/commit-log.md`](docs/records/commit-log.md)
- 技术笔记：[`docs/records/tech-notes.md`](docs/records/tech-notes.md)
