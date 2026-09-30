"""/api/system、/api/overview（契约 §3.3），以及运行指纹用到的版本信息。"""

import platform
import re
import socket
import subprocess
import threading

from fastapi import APIRouter

from . import config, db
from .resources import RESOURCES

VERDICTS = ("passed", "failed", "invalid", "error", "aborted")

_k6_lock = threading.Lock()
_k6_cache: dict[str, str] = {}  # k6 路径 + 修改时间 → 版本号


def k6_version() -> str | None:
    """执行 `k6 version` 并解析出 v2.3.0 这样的版本号；取不到返回 None。成功的结果按文件缓存。"""
    path = config.k6_bin()
    if path is None:
        return None
    try:
        key = f"{path}:{path.stat().st_mtime_ns}"
    except OSError:
        return None
    with _k6_lock:
        if key in _k6_cache:
            return _k6_cache[key]
        try:
            out = subprocess.run(
                [str(path), "version"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL
            )
        except (OSError, subprocess.SubprocessError):
            return None
        match = re.search(r"\bv\d+\.\d+\.\d+[^\s,()]*", out.stdout or "")
        if out.returncode != 0 or not match:
            return None
        _k6_cache[key] = match.group(0)
        return match.group(0)


def git_sha() -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=config.REPO_ROOT, capture_output=True, text=True, timeout=5, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = (out.stdout or "").strip()
    return sha if out.returncode == 0 and sha else None


def fingerprint() -> dict:
    return {
        "k6Version": k6_version(),
        "pythonVersion": platform.python_version(),
        "gitSha": git_sha(),
        "host": socket.gethostname(),
    }


def running_run_id(conn) -> str | None:
    row = conn.execute(
        "SELECT run_id FROM runs WHERE status = 'running' ORDER BY started_at DESC LIMIT 1"
    ).fetchone()
    return row["run_id"] if row else None


router = APIRouter(prefix="/api", tags=["系统"])


@router.get("/system", summary="系统信息")
def system_info():
    with db.connect() as conn:
        running = running_run_id(conn)
    return {
        "k6Version": k6_version(),
        "pythonVersion": platform.python_version(),
        "dashboardPort": config.DASHBOARD_PORT,
        "runningRunId": running,
    }


@router.get("/overview", summary="概览")
def overview():
    from .runs import list_items  # 避免循环导入

    with db.connect() as conn:
        counts = {res.name: conn.execute(f"SELECT COUNT(*) FROM {res.name}").fetchone()[0] for res in RESOURCES}
        counts["runs"] = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        verdicts = {v: 0 for v in VERDICTS}
        for row in conn.execute("SELECT verdict, COUNT(*) AS n FROM runs WHERE verdict IS NOT NULL GROUP BY verdict"):
            if row["verdict"] in verdicts:
                verdicts[row["verdict"]] = row["n"]
        recent, _ = list_items(conn, limit=10, offset=0)
        running = running_run_id(conn)
    return {"counts": counts, "verdicts": verdicts, "recentRuns": recent, "runningRunId": running}
