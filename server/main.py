"""应用入口。启动（在仓库根目录）：

    uv run uvicorn server.main:app --host 0.0.0.0 --port 8088

只能单进程运行（不要加 --workers）：正在运行的 k6 进程句柄在内存里。
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse

from . import config, datasets, db, debug, errors, executors, files, resources, runs, seed, system

log = logging.getLogger("uvicorn.error")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if db.init():
        seed.seed()
        log.info("全新的数据库，已写入种子数据：%s", config.DB_PATH)
    db.mark_initialized()
    runs.recover_stale()
    debug.cleanup_leftovers()
    log.info("数据库：%s ｜ 运行产物：%s ｜ k6：%s", config.DB_PATH, config.RESULTS_DIR, config.k6_bin() or "（未找到）")
    yield
    runs.shutdown()


app = FastAPI(
    title="AI Performance Engineering · 后端",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url=None,
    openapi_url="/api/openapi.json",
)

# 数据集和文件的上限是 10 MiB；base64 和 JSON 转义之后也远小于 32 MiB
app.add_middleware(errors.BodyLimit, limit=32 * 1024 * 1024)
errors.install(app)  # 内含兜底 500 的中间件，必须在 CORS 之前注册
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for router in resources.routers:
    app.include_router(router)
app.include_router(datasets.router)
app.include_router(files.router)
app.include_router(runs.router)
app.include_router(debug.router)
app.include_router(executors.router)
app.include_router(system.router)


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
def api_not_found(rest: str, request: Request):
    raise errors.not_found(f"接口不存在：{request.method} /api/{rest}")


_NO_DIST_HINT = (
    "后端已启动，但前端还没有构建（找不到 {dist}）。\n"
    "请在 web/ 目录执行 npm run build，然后刷新本页；接口文档见 /api/docs 。\n"
)


@app.api_route("/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def spa(full_path: str):
    """托管前端构建产物；找不到文件时回退到 index.html，由前端路由处理。"""
    if full_path == "api":
        raise errors.not_found("接口不存在：/api")
    dist = config.WEB_DIST
    if not dist.is_dir():
        status = 200 if full_path == "" else 404
        return PlainTextResponse(_NO_DIST_HINT.format(dist=dist), status_code=status)
    root = dist.resolve()
    if full_path:
        target = (root / full_path).resolve()
        if target.is_relative_to(root) and target.is_file():
            return FileResponse(target)
        # 带哈希的静态资源找不到就是 404，不要拿 index.html 顶替
        if full_path.startswith("assets/"):
            return PlainTextResponse("文件不存在\n", status_code=404)
    index = root / "index.html"
    if index.is_file():
        return FileResponse(index, headers={"Cache-Control": "no-cache"})
    return PlainTextResponse(_NO_DIST_HINT.format(dist=dist), status_code=404)
