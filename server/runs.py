"""运行（契约 §3.2、§4、§5）：预检 → 组装 plan → 启动 k6 → 等待退出 → 补全 Run Record → 存档。

同一时间只允许 1 个运行。进程句柄放在内存里（所以服务只能单进程运行），
“是否有运行在进行中”以库里的 status 为准。
"""

import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import Response

from . import config, db, executors
from .errors import ApiError, bad_request, conflict, not_found
from .resources import APIS, ENVIRONMENTS, FLOWS, PROFILES, TESTS, get_obj
from .system import VERDICTS, fingerprint, running_run_id
from .validators import base_url_problem, config_shape_problem, is_int, is_num, profile_usage

log = logging.getLogger("uvicorn.error")

RUN_ID_RE = re.compile(r"^\d{8}T\d{6}Z-[0-9a-f]{6}$")

# 产物白名单：文件名 → Content-Type。顺序也是 artifacts 数组的顺序
ARTIFACTS = {
    "plan.json": "application/json",
    "run-record.json": "application/json",
    "k6-summary.json": "application/json",
    "dashboard.html": "text/html; charset=utf-8",
    "k6.log": "text/plain; charset=utf-8",
}

# k6 的退出码（契约 §5）
EXIT_OK = (0, 99, 110)  # 正常结束 / 阈值未通过 / 脚本调用 exec.test.fail()
EXIT_ABORTED = (105, 108)  # 外部中断 / 脚本调用 test.abort()

_LIST_COLUMNS = (
    "run_id, test_id, test_name, profile_id, profile_name, env_id, env_name, env_type, "
    "executor_id, executor_name, status, verdict, "
    "started_at, ended_at, exit_code, note, archived, stop_requested, summary"
)


# ---------- 进程状态 ----------

class _Active:
    def __init__(self, run_id: str, proc: subprocess.Popen):
        self.run_id = run_id
        self.proc = proc
        self.thread: threading.Thread | None = None
        self.stop_sent = False
        self.reason: str | None = None  # 非用户触发的中止原因（例如服务关闭）


_start_lock = threading.Lock()  # 串行化“检查是否有运行 → 登记 → 启动”
_state_lock = threading.Lock()
_active: _Active | None = None


def run_dir(run_id: str) -> Path:
    return config.RESULTS_DIR / run_id


def _list_artifacts(run_id: str) -> list[str]:
    folder = run_dir(run_id)
    return [name for name in ARTIFACTS if (folder / name).is_file()]


def _progress(run_id: str) -> str | None:
    """运行中的进度：取 k6.log 末尾最新的一行 `running (...)`。

    k6 用回车刷新进度条，所以同时按回车和换行切分。只读文件末尾一小段。
    """
    path = run_dir(run_id) / "k6.log"
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 4096))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None
    for line in reversed(tail.replace("\r", "\n").split("\n")):
        line = line.strip()
        if line.startswith("running ("):
            return line
    return None


def _to_obj(row, *, full: bool) -> dict:
    obj = {
        "runId": row["run_id"],
        "testId": row["test_id"], "testName": row["test_name"],
        "profileId": row["profile_id"], "profileName": row["profile_name"],
        "envId": row["env_id"], "envName": row["env_name"], "envType": row["env_type"],
        "executorId": row["executor_id"], "executorName": row["executor_name"],
        "status": row["status"],
        "verdict": row["verdict"],
        "startedAt": row["started_at"], "endedAt": row["ended_at"],
        "exitCode": row["exit_code"],
        "note": row["note"], "archived": bool(row["archived"]),
        "stopRequested": bool(row["stop_requested"]),
        "progress": _progress(row["run_id"]) if row["status"] == "running" else None,
        "summary": db.loads(row["summary"]),
    }
    if full:
        obj["snapshot"] = db.loads(row["snapshot"])
        obj["record"] = db.loads(row["record"])
    obj["artifacts"] = _list_artifacts(row["run_id"])
    return obj


def _require(conn, run_id: str):
    row = None
    if RUN_ID_RE.match(run_id):
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        raise not_found(f"运行 {run_id} 不存在")
    return row


def list_items(conn, *, where: str = "", params: tuple = (), limit: int, offset: int) -> tuple[list[dict], int]:
    total = conn.execute(f"SELECT COUNT(*) FROM runs {where}", params).fetchone()[0]
    rows = conn.execute(
        f"SELECT {_LIST_COLUMNS} FROM runs {where} ORDER BY started_at DESC, run_id DESC LIMIT ? OFFSET ?",
        params + (limit, offset),
    ).fetchall()
    return [_to_obj(r, full=False) for r in rows], total


# ---------- 预检与 plan ----------

def _fmt(value: Any) -> str:
    return f"{value:g}" if is_num(value) else str(value)


def _limit_problems(profile: dict, env: dict) -> list[str]:
    """负载配置与被测环境的安全上限比较。上限为 null 表示不限制，跳过那一项。"""
    problems = []
    usage = profile_usage(profile)
    where = f"被测环境“{env['name']}”的安全上限"
    if env["maxVus"] is not None and usage["concurrency"]:
        field, value = usage["concurrency"]
        if not is_num(value) or value > env["maxVus"]:
            problems.append(f"并发 {_fmt(value)}（{field}）超过{where} maxVus = {_fmt(env['maxVus'])}")
    if env["maxRate"] is not None:
        for field, value in usage["rates"]:
            if not is_num(value) or value > env["maxRate"]:
                problems.append(f"到达率每秒 {_fmt(value)} 次（{field}）超过{where} maxRate = {_fmt(env['maxRate'])}")
    if env["maxDurationSec"] is not None:
        duration = usage["durationSec"]
        if not is_num(duration) or duration > env["maxDurationSec"]:
            problems.append(f"总时长 {_fmt(duration)} 秒超过{where} maxDurationSec = {_fmt(env['maxDurationSec'])}")
    return problems


def _preflight(conn, test_id: int, profile_id: int, env_id: int, executor_id: int | None, confirm_prod: bool):
    """预检里不涉及“是否已有运行”和 k6 的部分。通过时返回 (test, profile, env, 执行机, 展开的流程)，否则抛 422。"""
    details: list[str] = []
    test = get_obj(conn, TESTS, test_id)
    profile = get_obj(conn, PROFILES, profile_id)
    env = get_obj(conn, ENVIRONMENTS, env_id)
    executor = executors.find(conn, executor_id)  # executor_id 为 None 时取本机执行机
    if test is None:
        details.append(f"测试 #{test_id} 不存在")
    if profile is None:
        details.append(f"负载配置 #{profile_id} 不存在")
    if env is None:
        details.append(f"被测环境 #{env_id} 不存在")
    if executor is None:
        details.append("没有可用的执行机" if executor_id is None else f"执行机 #{executor_id} 不存在")

    expanded = []
    if test is not None:
        if not test["flows"]:
            details.append(f"测试“{test['name']}”没有选择任何业务流程")
        for item in test["flows"]:
            flow = get_obj(conn, FLOWS, item["flowId"])
            if flow is None:
                details.append(f"测试引用的业务流程 #{item['flowId']} 不存在")
                continue
            if not flow["steps"]:
                details.append(f"业务流程“{flow['name']}”没有任何步骤")
            steps = []
            for index, step in enumerate(flow["steps"], 1):
                api = get_obj(conn, APIS, step["apiId"])
                if api is None:
                    details.append(f"业务流程“{flow['name']}”第 {index} 步引用的接口 #{step['apiId']} 不存在")
                    continue
                steps.append((step, api))
            expanded.append((item, flow, steps))

    if env is not None:
        problem = base_url_problem(env["baseUrl"])
        if problem:
            details.append(f"被测环境“{env['name']}”的 {problem}")
        if env["type"] == "prod" and not confirm_prod:
            details.append(
                f"被测环境“{env['name']}”是生产环境，生产环境需要二次确认：请确认后在请求里带上 \"confirmProd\": true 再发起"
            )
    if profile is not None:
        shape_problem = config_shape_problem(profile["model"], profile["config"])
        if shape_problem:
            details.append(f"负载配置“{profile['name']}”不属于支持的四种形态：{shape_problem}")
        else:
            if env is not None:
                details.extend(_limit_problems(profile, env))
            # 执行引擎把每个流程编成一个 k6 scenario，并发和迭代数按权重拆成整数，每个流程至少分到 1；
            # 不够分时 k6 在初始化阶段就以 107 退出。closed 看 vus（固定迭代数形态还看 iterations），open 看 preAllocatedVus。
            flow_count = len(test["flows"]) if test is not None else 0
            labels = {"vus": "并发数", "iterations": "迭代数", "preAllocatedVus": "预分配 VU 数"}
            for key, label in labels.items():
                value = profile["config"].get(key)
                if is_num(value) and value < flow_count:
                    details.append(
                        f"负载配置的{label} {key} = {_fmt(value)}，小于测试里的业务流程数量 {flow_count}，"
                        "无法给每个流程至少分配 1"
                    )

    if details:
        raise ApiError(422, "PREFLIGHT_REJECTED", "预检不通过，运行没有发起", details)
    return test, profile, env, executor, expanded


def _build_plan(run_id: str, test: dict, profile: dict, env: dict, expanded: list) -> dict:
    total_weight = sum(item["weight"] for item, _, _ in expanded)
    flows = []
    for i, (item, flow, steps) in enumerate(expanded, 1):
        flow_key = f"f{i}"
        flows.append({
            "key": flow_key,
            "name": flow["name"],
            "weight": item["weight"] / total_weight,
            "steps": [
                {
                    "key": f"{flow_key}s{j}",
                    "name": api["name"],
                    "method": api["method"],
                    "path": api["path"],
                    "headers": api["headers"],
                    "body": api["body"],
                    "expectStatus": api["expectStatus"],
                    "expectBodyContains": api["expectBodyContains"],
                    "extracts": api["extracts"],
                    "thinkTimeMs": step["thinkTimeMs"],
                }
                for j, (step, api) in enumerate(steps, 1)
            ],
        })
    return {
        "schemaVersion": 1,
        "runId": run_id,
        "test": {"id": test["id"], "name": test["name"]},
        "env": {
            "id": env["id"], "name": env["name"], "type": env["type"],
            "baseUrl": env["baseUrl"].rstrip("/"), "headers": env["headers"],
        },
        "profile": {
            "id": profile["id"], "name": profile["name"], "type": profile["type"],
            "model": profile["model"], "config": profile["config"],
        },
        "flows": flows,
        "slo": test["slo"],
    }


def _write_json(path: Path, data: Any) -> None:
    """先写临时文件再改名，避免别人读到写了一半的内容。"""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ---------- 启动、等待、收尾 ----------

def _spawn(run_id: str, k6: Path) -> subprocess.Popen:
    out = run_dir(run_id)
    env = os.environ.copy()
    env.update({
        "K6_WEB_DASHBOARD": "true",
        # 只监听本机：k6 在有浏览器连着实时仪表盘时不会退出，所以不对外开放，
        # 开着它只是为了在结束时导出 dashboard.html。
        "K6_WEB_DASHBOARD_HOST": "127.0.0.1",
        "K6_WEB_DASHBOARD_PORT": str(config.DASHBOARD_PORT),
        "K6_WEB_DASHBOARD_EXPORT": str(out / "dashboard.html"),
        # 聚合周期默认 10s，短运行会因为数据点不够而跳过 HTML 导出（契约 §4）
        "K6_WEB_DASHBOARD_PERIOD": "1s",
    })
    cmd = [
        str(k6), "run", config.K6_SCRIPT,
        "-e", f"PLAN_FILE={out / 'plan.json'}",
        "-e", f"OUTPUT_DIR={out}",
        "--tag", f"testid={run_id}",
    ]
    # 追加方式打开，服务自己往里写说明行时不会和 k6 的输出互相覆盖
    with open(out / "k6.log", "ab") as logfile:
        return subprocess.Popen(
            cmd,
            cwd=config.REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            # 独立的会话：在终端里按 Ctrl+C 停服务时，k6 不会同时从终端收到一次 SIGINT。
            # k6 收到第二次中断信号会立刻强退、不写 summary，所以信号只能由服务发一次。
            start_new_session=True,
        )


def _append_log(run_id: str, line: str) -> None:
    try:
        with open(run_dir(run_id) / "k6.log", "ab") as f:
            f.write(f"\n[server {db.now_iso()}] {line}\n".encode("utf-8"))
    except OSError:
        pass


def _read_k6_record(run_id: str) -> tuple[dict | None, str | None]:
    path = run_dir(run_id) / "run-record.json"
    if not path.is_file():
        return None, "k6 没有生成 run-record.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"run-record.json 无法解析：{exc}"
    if not isinstance(data, dict) or data.get("k6Verdict") not in ("passed", "failed", "invalid"):
        return None, "run-record.json 无法解析：缺少有效的 k6Verdict"
    return data, None


def _decide(stop_requested: bool, exit_code: int | None, k6_record: dict | None, problem: str | None) -> tuple[str, str]:
    """最终 verdict 的判定顺序（契约 §5），同时给出一句原因。"""
    if stop_requested:
        return "aborted", "用户请求停止"
    if exit_code in EXIT_ABORTED:
        return "aborted", f"k6 被中断（退出码 {exit_code}）"
    if k6_record is None:
        suffix = "" if exit_code is None else f"（k6 退出码 {exit_code}）"
        return "error", f"{problem}{suffix}"
    if exit_code not in EXIT_OK:
        return "error", f"k6 异常退出（退出码 {exit_code}）"
    if k6_record["k6Verdict"] == "invalid":
        return "invalid", "有效性阈值未通过，本次测试结果不可信"
    if k6_record["k6Verdict"] == "failed":
        return "failed", "SLO 阈值未通过"
    if exit_code == 110:
        return "failed", "脚本把本次运行标记为失败（退出码 110）"
    return "passed", "全部阈值通过"


def _summary_of(record: dict) -> dict | None:
    metrics = record.get("metrics")
    overall = metrics.get("overall") if isinstance(metrics, dict) else None
    if not isinstance(overall, dict):
        return None
    return {key: overall.get(key) for key in ("reqs", "rps", "p95", "errorRate", "checksRate")}


def _finalize(
    run_id: str,
    exit_code: int | None,
    *,
    forced: tuple[str, str] | None = None,
    reason: str | None = None,
    samples: dict | None = None,
) -> None:
    """k6 退出后：读 run-record.json，补全为最终 Run Record，回写文件并更新库。"""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
    if row is None:
        return
    k6_record, problem = _read_k6_record(run_id)
    verdict, why = forced or _decide(bool(row["stop_requested"]), exit_code, k6_record, problem)
    if reason and verdict == "aborted" and not row["stop_requested"]:
        why = reason
    ended_at = db.now_iso()
    snapshot = db.loads(row["snapshot"]) or {}
    plan_test, plan_profile, plan_env = (snapshot.get(k) or {} for k in ("test", "profile", "env"))

    record = dict(k6_record) if k6_record else {
        "schemaVersion": 1, "runId": run_id, "k6Verdict": None,
        "thresholds": [], "metrics": None, "testDurationMs": None,
    }
    record.update({
        "verdict": verdict,
        "verdictReason": why,
        "exitCode": exit_code,
        "window": {"start": row["started_at"], "end": ended_at},
        "fingerprint": fingerprint(),
        "test": {"id": plan_test.get("id"), "name": plan_test.get("name")},
        "profile": {"id": plan_profile.get("id"), "name": plan_profile.get("name"), "model": plan_profile.get("model")},
        "env": {
            "id": plan_env.get("id"), "name": plan_env.get("name"),
            "type": plan_env.get("type") or row["env_type"], "baseUrl": plan_env.get("baseUrl"),
        },
        # 执行机在运行期间的资源占用：只作信息展示，不参与判定
        "executor": executors.record_block(row["executor_id"], row["executor_name"], samples),
    })
    folder = run_dir(run_id)
    if folder.is_dir():
        try:
            _write_json(folder / "run-record.json", record)
        except OSError:
            log.exception("回写 run-record.json 失败：%s", run_id)
    summary = _summary_of(record)
    with db.connect() as conn:
        conn.execute(
            "UPDATE runs SET status = 'finished', verdict = ?, exit_code = ?, ended_at = ?, "
            "summary = ?, record = ?, pid = NULL WHERE run_id = ?",
            (verdict, exit_code, ended_at, db.dumps(summary) if summary else None, db.dumps(record), run_id),
        )
    log.info("运行 %s 结束：verdict=%s exitCode=%s（%s）", run_id, verdict, exit_code, why)


def _wait(active: _Active) -> None:
    """后台线程：等 k6 退出，然后收尾。无论如何都要把库里的状态改成 finished。"""
    global _active
    # 采样器的生命周期完全包在这个线程里：这里启动，k6 一退出就停。
    # 它只提供附带信息，启动失败、停不下来、取不到结果都不能耽误收尾
    sampler = None
    try:
        sampler = executors.Sampler()
        sampler.start()
    except Exception:  # noqa: BLE001
        log.exception("运行 %s：启动执行机采样失败（不影响运行）", active.run_id)
    exit_code = active.proc.wait()
    samples = None
    try:
        if sampler is not None:
            sampler.stop()
            samples = sampler.result()
    except Exception:  # noqa: BLE001
        log.exception("运行 %s：读取执行机采样结果失败（不影响收尾）", active.run_id)
    try:
        _finalize(active.run_id, exit_code, reason=active.reason, samples=samples)
    except Exception:  # noqa: BLE001
        log.exception("运行 %s 收尾失败", active.run_id)
        try:
            with db.connect() as conn:
                conn.execute(
                    "UPDATE runs SET status = 'finished', verdict = 'error', exit_code = ?, ended_at = ?, pid = NULL "
                    "WHERE run_id = ? AND status = 'running'",
                    (exit_code, db.now_iso(), active.run_id),
                )
        except Exception:  # noqa: BLE001
            log.exception("运行 %s 标记为 error 也失败了", active.run_id)
    finally:
        with _state_lock:
            if _active is active:
                _active = None


def _force_kill(active: _Active) -> None:
    if active.proc.poll() is None:
        log.warning("运行 %s 在收到 SIGINT 后 %s 秒仍未退出，强制结束", active.run_id, config.STOP_KILL_AFTER_SEC)
        _append_log(active.run_id, "k6 没有在限定时间内退出，已强制结束")
        try:
            os.killpg(active.proc.pid, signal.SIGKILL)
        except OSError:
            active.proc.kill()


def _orphan_alive(pid: int, run_id: str) -> bool:
    """pid 对应的进程还在，并且确实是这次运行的 k6（命令行里带着 runId，防止 pid 被别的进程复用）。"""
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().decode("utf-8", "replace")
    except OSError:
        return False
    return run_id in cmdline


def _stop_orphan(pid: int, run_id: str) -> None:
    """服务被强杀时 k6 会变成孤儿进程继续发请求、占着仪表盘端口。让它停下来，并等它写完产物。"""
    if not _orphan_alive(pid, run_id):
        return
    log.warning("运行 %s 遗留的 k6 进程 %s 仍在运行，发送 SIGINT 并等待它退出", run_id, pid)
    _append_log(run_id, "服务重启时发现 k6 进程仍在运行，已发送 SIGINT")
    try:
        os.kill(pid, signal.SIGINT)
        for _ in range(100):  # 最多等 10 秒
            if not _orphan_alive(pid, run_id):
                return
            time.sleep(0.1)
        log.warning("运行 %s 遗留的 k6 进程 %s 没有退出，强制结束", run_id, pid)
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def recover_stale() -> None:
    """服务启动时调用：上次服务被中断时还在 running 的记录，标记为 finished + error。"""
    with db.connect() as conn:
        rows = conn.execute("SELECT run_id, pid FROM runs WHERE status = 'running'").fetchall()
    for row in rows:
        run_id = row["run_id"]
        if row["pid"]:
            _stop_orphan(row["pid"], run_id)
        _finalize(run_id, None, forced=("error", "服务中断：上次服务停止时这个运行还没有结束，结果不完整"))
        log.warning("运行 %s 在上次服务中断时未结束，已标记为 error", run_id)


def shutdown() -> None:
    """服务关闭时调用：不留下孤儿 k6 进程。"""
    with _state_lock:
        active = _active
    if active is None or active.proc.poll() is not None:
        return
    log.warning("服务关闭，正在停止运行 %s", active.run_id)
    active.reason = "服务关闭时运行被中止"
    if not active.stop_sent:
        active.stop_sent = True
        _append_log(active.run_id, "服务关闭，已向 k6 发送 SIGINT")
        active.proc.send_signal(signal.SIGINT)
    try:
        active.proc.wait(timeout=8)  # scripts/stop.sh 等 10 秒后会强杀整个服务，要赶在那之前
    except subprocess.TimeoutExpired:
        _force_kill(active)
    if active.thread is not None:
        active.thread.join(timeout=10)


# ---------- 路由 ----------

router = APIRouter(prefix="/api/runs", tags=["运行"])


@router.post("", status_code=201, summary="发起运行")
def create_run(payload: Any = Body(...)):
    global _active
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    problems = [f"{key} 必填，且必须是整数" for key in ("testId", "profileId", "envId") if not is_int(payload.get(key))]
    note = payload.get("note")
    if note is None:
        note = ""
    if not isinstance(note, str):
        problems.append("note（备注）必须是字符串")
    executor_id = payload.get("executorId")  # 可省略，默认本机执行机
    if executor_id is not None and not is_int(executor_id):
        problems.append("executorId 必须是整数；省略时使用本机执行机")
    confirm_prod = payload.get("confirmProd")
    if confirm_prod is not None and not isinstance(confirm_prod, bool):
        problems.append("confirmProd 必须是 true 或 false")
    if problems:
        raise bad_request("字段校验失败", problems)

    with _start_lock:
        with db.connect() as conn:
            test, profile, env, executor, expanded = _preflight(
                conn, payload["testId"], payload["profileId"], payload["envId"], executor_id, confirm_prod is True
            )
            running = running_run_id(conn)
        if running:
            raise conflict(f"已有运行在进行中（{running}），同一时间只允许 1 个运行。请等它结束或先停止它")
        k6 = config.k6_bin()
        if k6 is None:
            raise ApiError(
                422, "PREFLIGHT_REJECTED", "预检不通过，运行没有发起",
                [f"k6 可执行文件不存在或不可执行：{config.k6_bin_display()}（先执行 scripts/setup.sh，或设置 K6_BIN）"],
            )

        now = datetime.now(timezone.utc)
        run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
        started_at = db.iso(now)
        plan = _build_plan(run_id, test, profile, env, expanded)
        folder = run_dir(run_id)
        folder.mkdir(parents=True, exist_ok=False)
        _write_json(folder / "plan.json", plan)

        with db.connect() as conn:
            conn.execute(
                "INSERT INTO runs (run_id, test_id, test_name, profile_id, profile_name, env_id, env_name, env_type, "
                "executor_id, executor_name, status, started_at, note, snapshot) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'running', ?, ?, ?)",
                (run_id, test["id"], test["name"], profile["id"], profile["name"], env["id"], env["name"], env["type"],
                 executor["id"], executor["name"], started_at, note, db.dumps(plan)),
            )

        try:
            proc = _spawn(run_id, k6)
        except OSError as exc:
            _append_log(run_id, f"启动 k6 失败：{exc}")
            _finalize(run_id, None, forced=("error", f"启动 k6 失败：{exc}"))
            raise ApiError(500, "INTERNAL", f"启动 k6 失败：{exc}。这次运行已记为 error（{run_id}）") from exc

        active = _Active(run_id, proc)
        with db.connect() as conn:
            conn.execute("UPDATE runs SET pid = ? WHERE run_id = ?", (proc.pid, run_id))
            row = _require(conn, run_id)
        with _state_lock:
            _active = active
        active.thread = threading.Thread(target=_wait, args=(active,), name=f"k6-wait-{run_id}", daemon=True)
        active.thread.start()
        log.info("运行 %s 已启动：k6 pid=%s", run_id, proc.pid)
        return _to_obj(row, full=True)


def _int_param(name: str, raw: str | None, default: int | None) -> int | None:
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        raise bad_request("请求参数格式错误", [f"查询参数 {name}：必须是整数"]) from None


@router.get("", summary="运行列表")
def list_runs(
    testId: str | None = None,
    verdict: str | None = None,
    status: str | None = None,
    archived: str | None = None,
    page: str | None = None,
    pageSize: str | None = None,
):
    # 参数都按字符串接收：契约里的 ?testId=&verdict= 这种空值表示“不筛选”，不能当成格式错误
    clauses: list[str] = []
    params: list[Any] = []

    test_id = _int_param("testId", testId, None)
    if test_id is not None:
        clauses.append("test_id = ?")
        params.append(test_id)

    if verdict and verdict.strip():
        wanted = [v.strip() for v in verdict.split(",") if v.strip()]
        bad = [v for v in wanted if v not in VERDICTS]
        if bad:
            raise bad_request("请求参数格式错误", ["查询参数 verdict：必须是 " + " / ".join(VERDICTS) + " 之一（可用逗号分隔多个）"])
        clauses.append(f"verdict IN ({', '.join('?' for _ in wanted)})")
        params.extend(wanted)

    if status and status.strip():
        if status.strip() not in ("running", "finished"):
            raise bad_request("请求参数格式错误", ["查询参数 status：必须是 running 或 finished"])
        clauses.append("status = ?")
        params.append(status.strip())

    if archived and archived.strip():
        flag = archived.strip().lower()
        if flag not in ("true", "false", "1", "0"):
            raise bad_request("请求参数格式错误", ["查询参数 archived：必须是 true 或 false"])
        clauses.append("archived = ?")
        params.append(1 if flag in ("true", "1") else 0)

    page_no = _int_param("page", page, 1)
    size = _int_param("pageSize", pageSize, 20)
    if page_no < 1 or size < 1:
        raise bad_request("请求参数格式错误", ["查询参数 page、pageSize：必须是不小于 1 的整数"])
    size = min(size, 500)

    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    with db.connect() as conn:
        items, total = list_items(conn, where=where, params=tuple(params), limit=size, offset=(page_no - 1) * size)
    return {"items": items, "total": total}


@router.get("/{run_id}", summary="运行详情")
def get_run(run_id: str):
    with db.connect() as conn:
        return _to_obj(_require(conn, run_id), full=True)


@router.post("/{run_id}/stop", summary="停止运行")
def stop_run(run_id: str):
    with db.connect() as conn:
        row = _require(conn, run_id)
    with _state_lock:
        active = _active if _active is not None and _active.run_id == run_id else None
        alive = active is not None and active.proc.poll() is None
        if row["status"] != "running" or not alive:
            raise conflict("这个运行不在进行中，不能停止")
        if not active.stop_sent:
            active.stop_sent = True
            with db.connect() as conn:
                conn.execute("UPDATE runs SET stop_requested = 1 WHERE run_id = ?", (run_id,))
            _append_log(run_id, "用户请求停止，已向 k6 发送 SIGINT")
            active.proc.send_signal(signal.SIGINT)
            timer = threading.Timer(config.STOP_KILL_AFTER_SEC, _force_kill, args=(active,))
            timer.daemon = True
            timer.start()
            log.info("运行 %s：用户请求停止", run_id)
    with db.connect() as conn:
        return _to_obj(_require(conn, run_id), full=True)


@router.patch("/{run_id}", summary="修改备注或存档标记")
def patch_run(run_id: str, payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    sets: list[str] = []
    params: list[Any] = []
    problems: list[str] = []
    if "note" in payload:
        if isinstance(payload["note"], str):
            sets.append("note = ?")
            params.append(payload["note"])
        else:
            problems.append("note（备注）必须是字符串")
    if "archived" in payload:
        if isinstance(payload["archived"], bool):
            sets.append("archived = ?")
            params.append(1 if payload["archived"] else 0)
        else:
            problems.append("archived（存档）必须是 true 或 false")
    if not problems and not sets:
        problems.append("至少要提供 note 或 archived 其中之一")
    if problems:
        raise bad_request("字段校验失败", problems)
    with db.connect() as conn:
        _require(conn, run_id)
        conn.execute(f"UPDATE runs SET {', '.join(sets)} WHERE run_id = ?", params + [run_id])
        return _to_obj(_require(conn, run_id), full=True)


@router.delete("/{run_id}", summary="删除运行")
def delete_run(run_id: str):
    with db.connect() as conn:
        row = _require(conn, run_id)
        if row["status"] == "running":
            raise conflict("运行还在进行中，不能删除。请先停止它")
        if row["archived"]:
            raise conflict("已存档的运行不能删除。请先取消存档")
        conn.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
    # run_id 已经过格式校验，目录一定在 RESULTS_DIR 之下
    shutil.rmtree(run_dir(run_id), ignore_errors=True)
    return {"ok": True}


@router.get("/{run_id}/artifacts/{name}", summary="查看或下载产物")
def get_artifact(run_id: str, name: str, download: str | None = None):
    if name not in ARTIFACTS:
        raise not_found("不支持的产物名称。只能是 " + "、".join(ARTIFACTS))
    with db.connect() as conn:
        _require(conn, run_id)
    path = run_dir(run_id) / name
    if not path.is_file():
        raise not_found(f"运行 {run_id} 没有产物 {name}（可能还没生成）")
    # 一次读完再返回：k6.log 在运行中会继续增长，按文件流式返回会和 Content-Length 对不上
    headers = {"Cache-Control": "no-store"}
    if download and download.strip().lower() in ("1", "true"):
        headers["Content-Disposition"] = f'attachment; filename="{run_id}-{name}"'
    return Response(content=path.read_bytes(), media_type=ARTIFACTS[name], headers=headers)
