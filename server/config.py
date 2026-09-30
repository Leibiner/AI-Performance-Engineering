"""运行配置：全部来自环境变量，在导入时读取一次。

| 变量                   | 默认值            | 说明                                   |
|------------------------|-------------------|----------------------------------------|
| DATA_DIR               | ./data            | SQLite 文件 app.db 所在目录            |
| RESULTS_DIR            | ./results         | 运行产物目录，每次运行一个子目录       |
| K6_BIN                 | ./.tools/bin/k6   | k6 可执行文件；只写名字时从 PATH 查找  |
| WEB_DIST               | ./web/dist        | 前端构建产物目录                       |
| K6_WEB_DASHBOARD_PORT  | 5665              | k6 实时仪表盘端口                      |

PORT / HOST 不在这里读取：监听地址由启动命令的 --host / --port 决定。
默认值相对仓库根目录；环境变量给的相对路径相对当前工作目录（启动命令本来就在仓库根目录执行）。
"""

import os
import shutil
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def _dir(env_name: str, default: str) -> Path:
    raw = os.environ.get(env_name, "").strip()
    if raw:
        return Path(raw).expanduser().absolute()
    return REPO_ROOT / default


DATA_DIR = _dir("DATA_DIR", "data")
RESULTS_DIR = _dir("RESULTS_DIR", "results")
WEB_DIST = _dir("WEB_DIST", "web/dist")
DB_PATH = DATA_DIR / "app.db"

# k6 脚本路径相对仓库根目录（k6 的工作目录就是仓库根目录）
K6_SCRIPT = "perf/runner.js"

_K6_RAW = os.environ.get("K6_BIN", "").strip()


def k6_bin() -> Path | None:
    """返回可执行的 k6 路径；不存在或不可执行时返回 None。"""
    if not _K6_RAW:
        path = REPO_ROOT / ".tools" / "bin" / "k6"
    elif os.sep not in _K6_RAW:
        found = shutil.which(_K6_RAW)
        if not found:
            return None
        path = Path(found)
    else:
        path = Path(_K6_RAW).expanduser().absolute()
    if path.is_file() and os.access(path, os.X_OK):
        return path
    return None


def k6_bin_display() -> str:
    return _K6_RAW or str(REPO_ROOT / ".tools" / "bin" / "k6")


try:
    DASHBOARD_PORT = int(os.environ.get("K6_WEB_DASHBOARD_PORT", "5665"))
except ValueError:
    DASHBOARD_PORT = 5665

# 点了停止以后，k6 超过这么多秒还没退出就强制结束
STOP_KILL_AFTER_SEC = 30
