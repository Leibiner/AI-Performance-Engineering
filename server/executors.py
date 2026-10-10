"""施压机（契约 §3.3）：安装了本项目、实际运行 k6 的机器。目前只有运行后端的这一台。

库里只存 name、kind、note；主机名、内存、负载这些每次请求时实时采集，只用标准库
（/proc、os、platform、shutil、socket），取不到的给 null。
另外提供运行期间的资源采样器：每秒采一次本机 CPU 和内存占用，只作信息展示，不参与判定。
"""

import logging
import os
import platform
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from . import config, db
from .errors import bad_request, not_found
from .system import k6_version, running_run_id

log = logging.getLogger("uvicorn.error")


# ---------- 实时采集 ----------

def _safe(fn, default=None):
    try:
        return fn()
    except Exception:  # noqa: BLE001 —— 采集信息失败不应该让接口报错
        return default


def _meminfo() -> dict[str, int]:
    """/proc/meminfo，单位 kB。"""
    out: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])
    return out


def _mem_mb(key: str) -> int | None:
    value = _safe(_meminfo, {}).get(key)
    return None if value is None else round(value / 1024)


def _os_name() -> str | None:
    def from_os_release() -> str | None:
        for line in Path("/etc/os-release").read_text().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip().strip('"') or None
        return None

    return _safe(from_os_release) or _safe(lambda: f"{platform.system()} {platform.release()}".strip() or None)


def _primary_ip() -> str | None:
    """本机对外的 IP：让系统为一个 UDP 套接字选路，看它用了哪个本地地址。connect 不会真的发包。"""
    def by_route() -> str | None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))  # 192.0.2.0/24 是文档保留网段，只用来触发选路
            return sock.getsockname()[0]

    def by_hostname() -> str | None:
        ip = socket.gethostbyname(socket.gethostname())
        return None if ip.startswith("127.") else ip

    return _safe(by_route) or _safe(by_hostname)


_uv_lock = threading.Lock()
_uv_cache: list[str] = []


def _uv_version() -> str | None:
    """`uv --version` → 0.11.18。成功的结果缓存（进程存活期间 uv 不会变）。"""
    with _uv_lock:
        if _uv_cache:
            return _uv_cache[0]
        uv = os.environ.get("UV") or shutil.which("uv")  # `uv run` 会把自己的路径放进环境变量 UV
        if not uv:
            return None
        out = subprocess.run([uv, "--version"], capture_output=True, text=True, timeout=10, stdin=subprocess.DEVNULL)
        match = re.search(r"\d+\.\d+\.\d+[^\s()]*", out.stdout or "")
        if out.returncode != 0 or not match:
            return None
        _uv_cache.append(match.group(0))
        return match.group(0)


def _disk_free_gb() -> float | None:
    path = config.RESULTS_DIR if config.RESULTS_DIR.exists() else config.REPO_ROOT
    return round(shutil.disk_usage(path).free / 1024**3, 1)


def host_facts() -> dict:
    """写进 Run Record 的那几项不随时间变化的信息。"""
    return {
        "host": _safe(socket.gethostname),
        "cpuCores": _safe(os.cpu_count),
        "memTotalMb": _mem_mb("MemTotal"),
    }


def _describe(row, running: str | None) -> dict:
    k6 = _safe(config.k6_bin)
    facts = host_facts()
    return {
        "id": row["id"], "name": row["name"], "kind": row["kind"], "note": row["note"],
        "host": facts["host"], "ip": _primary_ip(),
        "os": _os_name(), "arch": _safe(platform.machine) or None,
        "cpuCores": facts["cpuCores"], "memTotalMb": facts["memTotalMb"], "memAvailableMb": _mem_mb("MemAvailable"),
        "loadAvg1": _safe(lambda: round(os.getloadavg()[0], 2)), "diskFreeGb": _safe(_disk_free_gb),
        "k6Version": _safe(k6_version), "k6Path": str(k6) if k6 else None,
        "pythonVersion": platform.python_version(), "uvVersion": _safe(_uv_version),
        "projectDir": str(config.REPO_ROOT), "resultsDir": str(config.RESULTS_DIR), "dataDir": str(config.DATA_DIR),
        "status": "running" if running else "idle", "runningRunId": running,
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


# ---------- 给运行用的 ----------

def find(conn, executor_id: int | None):
    """按 id 找施压机；id 为 None 时返回本机施压机。找不到返回 None。"""
    if executor_id is None:
        return conn.execute("SELECT * FROM executors WHERE kind = 'local' ORDER BY id LIMIT 1").fetchone()
    return conn.execute("SELECT * FROM executors WHERE id = ?", (executor_id,)).fetchone()


def _cpu_times() -> tuple[int, int]:
    """/proc/stat 第一行 → (总时间, 空闲时间)，单位是时钟滴答。"""
    with open("/proc/stat", encoding="ascii") as f:
        fields = f.readline().split()
    # cpu user nice system idle iowait irq softirq steal guest guest_nice；guest 已经算在 user 里
    values = [int(v) for v in fields[1:9]]
    return sum(values), values[3] + values[4]


class Sampler:
    """运行期间每秒采样一次本机 CPU 和内存占用。

    CPU 占用是 /proc/stat 相邻两次读数的差值（整机、所有核合计）；内存占用是
    (MemTotal - MemAvailable) / MemTotal。只累计平均值和最大值，不保存每个样本。
    采样在自己的守护线程里，任何异常都只会让采样停下，不会影响运行的收尾。
    """

    def __init__(self, interval: float = 1.0):
        self._interval = interval
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="executor-sampler", daemon=True)
        self._samples = 0
        self._cpu_sum = 0.0
        self._cpu_n = 0
        self._cpu_max: float | None = None
        self._mem_max: float | None = None

    def start(self) -> None:
        try:
            self._thread.start()
        except Exception:  # noqa: BLE001
            log.exception("启动施压机采样线程失败（不影响运行）")

    def _run(self) -> None:
        try:
            previous = _safe(_cpu_times)
            while not self._stop.wait(self._interval):
                got = False
                current = _safe(_cpu_times)
                if previous and current and current[0] > previous[0]:
                    total = current[0] - previous[0]
                    busy = total - (current[1] - previous[1])
                    pct = max(0.0, min(100.0, busy / total * 100))
                    self._cpu_sum += pct
                    self._cpu_n += 1
                    self._cpu_max = pct if self._cpu_max is None else max(self._cpu_max, pct)
                    got = True
                previous = current or previous
                mem = _safe(_meminfo, {})
                if mem.get("MemTotal") and mem.get("MemAvailable") is not None:
                    pct = (mem["MemTotal"] - mem["MemAvailable"]) / mem["MemTotal"] * 100
                    self._mem_max = pct if self._mem_max is None else max(self._mem_max, pct)
                    got = True
                if got:
                    self._samples += 1
        except Exception:  # noqa: BLE001
            log.exception("施压机采样出错，已停止采样（不影响运行）")

    def stop(self) -> None:
        """让采样线程结束。最多等 2 秒，不会卡住调用方。"""
        try:
            self._stop.set()
            if self._thread.is_alive():
                self._thread.join(timeout=2)
        except Exception:  # noqa: BLE001
            pass

    def result(self) -> dict:
        def r1(value: float | None) -> float | None:
            return None if value is None else round(value, 1)

        return {
            "cpuAvgPct": r1(self._cpu_sum / self._cpu_n) if self._cpu_n else None,
            "cpuMaxPct": r1(self._cpu_max),
            "memMaxPct": r1(self._mem_max),
            "samples": self._samples,
        }


EMPTY_SAMPLES = {"cpuAvgPct": None, "cpuMaxPct": None, "memMaxPct": None, "samples": 0}


def record_block(executor_id: Any, executor_name: Any, samples: dict | None) -> dict:
    """最终 Run Record 里的 executor 对象。"""
    block = {"id": executor_id, "name": executor_name or None}
    block.update(_safe(host_facts, {"host": None, "cpuCores": None, "memTotalMb": None}))
    block.update(samples or EMPTY_SAMPLES)
    return block


# ---------- 路由 ----------

router = APIRouter(prefix="/api/executors", tags=["施压机"])


def _require(conn, executor_id: int):
    row = find(conn, executor_id)
    if row is None:
        raise not_found(f"施压机 #{executor_id} 不存在")
    return row


@router.get("", summary="施压机列表")
def list_executors():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM executors ORDER BY id").fetchall()
        running = running_run_id(conn)
    return [_describe(row, running) for row in rows]


@router.get("/{executor_id}", summary="施压机详情")
def get_executor(executor_id: int):
    with db.connect() as conn:
        row = _require(conn, executor_id)
        running = running_run_id(conn)
    return _describe(row, running)


@router.put("/{executor_id}", summary="修改施压机的名称和备注")
def update_executor(executor_id: int, payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    with db.connect() as conn:
        row = _require(conn, executor_id)
        problems: list[str] = []
        # 只认 name 和 note，其余字段是实时采集的，前端把整个对象原样送回来也没关系
        name = payload.get("name", row["name"])
        note = payload.get("note", row["note"])
        if note is None:
            note = ""
        if not isinstance(name, str) or not name.strip():
            problems.append("name（名称）必填，且不能为空")
        elif len(name.strip()) > 100:
            problems.append("name（名称）不能超过 100 个字符")
        if not isinstance(note, str):
            problems.append("note（备注）必须是字符串")
        if problems:
            raise bad_request("字段校验失败", problems)
        conn.execute(
            "UPDATE executors SET name = ?, note = ?, updated_at = ? WHERE id = ?",
            (name.strip(), note, db.now_iso(), executor_id),
        )
        row = _require(conn, executor_id)
        running = running_run_id(conn)
    return _describe(row, running)
