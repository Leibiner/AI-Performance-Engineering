"""调试（契约 §3.5）：把一个接口或一个业务流程用真实 k6 跑一次迭代，返回每一步的请求、响应、检查和变量。

和运行共用执行引擎（perf/runner.js 的调试模式）和 plan 组装（plan.py），所以调试里看到的就是压测时会发生的事。
与运行的差别：不留运行记录、不开仪表盘、不评估阈值、不采样执行机；数据集只写指定的那一行；
产物目录 results/_debug/<debugId>/（含输入文件）读完即删。调试与运行互斥（runs.claim_debug_slot）。
"""

import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Body

from . import config, datasets, db, files, runs, validators
from .errors import ApiError, bad_request
from .plan import FlowSpec, build_plan, expand_flow, write_inputs
from .resources import APIS, ENVIRONMENTS, FLOWS, get_obj
from .validators import VAR_NAME_RULE, base_url_problem, is_int, is_num, is_var_name
from .variables import source_problems

log = logging.getLogger("uvicorn.error")

DEBUG_DIR_NAME = "_debug"
BODY_LIMIT = 65536  # 返回给页面的响应体上限（字符）
MAX_DURATION_SEC = 60  # 调试 plan 的 maxDurationSec；被测环境的时长上限更小时取更小的
K6_TIMEOUT_SEC = 90  # k6 超过这么久还没退出：SIGINT
KILL_AFTER_SEC = 10  # SIGINT 后再等这么久：SIGKILL
LOG_TAIL_LINES = 30
MAX_BEFORE_APIS = 5
_DATASET_KEY_RE = re.compile(r"0|[1-9][0-9]*")


def debug_root() -> Path:
    return config.RESULTS_DIR / DEBUG_DIR_NAME


def cleanup_leftovers() -> None:
    """服务启动时调用：上次服务中断时没来得及删的调试目录，这里清掉。"""
    root = debug_root()
    if not root.is_dir():
        return
    for child in root.iterdir():
        shutil.rmtree(child, ignore_errors=True)


# ---------- 请求体 ----------

def _parse_payload(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    problems: list[str] = []
    env_id = payload.get("envId")
    if not is_int(env_id):
        problems.append("envId（被测环境）必填，且必须是整数")
    confirm_prod = payload.get("confirmProd")
    if confirm_prod is not None and not isinstance(confirm_prod, bool):
        problems.append("confirmProd 必须是 true 或 false")

    api_input = payload.get("api")
    flow_id = payload.get("flowId")
    if (api_input is None) == (flow_id is None):
        problems.append("api（接口定义）和 flowId（业务流程）必须恰好给一个")
    if flow_id is not None and not is_int(flow_id):
        problems.append("flowId 必须是整数")
    if api_input is not None and not isinstance(api_input, dict):
        problems.append("api 必须是对象（接口定义）")

    # 当前值只用于调试单个接口：试跑流程的变量和正式运行一样只有那几层来源，试跑通过才说明正式运行时变量齐全
    raw_vars = payload.get("vars")
    variables: dict[str, str] = {}
    if raw_vars is not None:
        if flow_id is not None:
            problems.append("vars（变量的当前值）只用于调试单个接口；试跑业务流程时变量和正式运行一样，不能带 vars")
        elif not isinstance(raw_vars, dict):
            problems.append("vars（变量的当前值）必须是对象（变量名 → 字符串）")
        else:
            for name, value in raw_vars.items():
                if not is_var_name(name):
                    problems.append(f"vars 里的变量名 {name!r} {VAR_NAME_RULE}")
                elif not isinstance(value, str):
                    problems.append(f"vars.{name} 的值必须是字符串")
                else:
                    variables[name] = value

    raw_before = payload.get("beforeApiIds")
    before: list[int] = []
    if raw_before is not None:
        if flow_id is not None:
            problems.append("beforeApiIds（先执行的上游接口）只用于调试单个接口，试跑业务流程时不能给")
        elif not isinstance(raw_before, list) or not all(is_int(v) for v in raw_before):
            problems.append("beforeApiIds（先执行的上游接口）必须是接口 id（整数）的数组")
        elif len(raw_before) > MAX_BEFORE_APIS:
            problems.append(f"beforeApiIds（先执行的上游接口）最多 {MAX_BEFORE_APIS} 个")
        elif len(set(raw_before)) != len(raw_before):
            problems.append("beforeApiIds（先执行的上游接口）里有重复的接口")
        else:
            before = list(raw_before)

    raw_rows = payload.get("rows")
    rows: dict[int, int] = {}
    if raw_rows is not None:
        if not isinstance(raw_rows, dict):
            problems.append("rows 必须是对象（数据集 id → 行号）")
        else:
            for key, value in raw_rows.items():
                if not _DATASET_KEY_RE.fullmatch(key) or not is_int(int(key)):
                    problems.append(f"rows 的键 {key!r} 必须是数据集 id 的字符串形式，例如 \"2\"")
                elif not is_int(value) or value < 0:
                    problems.append(f"rows.{key} 必须是不小于 0 的整数（行号，从 0 开始）")
                else:
                    rows[int(key)] = value
    if problems:
        raise bad_request("字段校验失败", problems)
    return {
        "envId": env_id, "confirmProd": confirm_prod is True, "vars": variables,
        "api": api_input, "beforeApiIds": before, "flowId": flow_id, "rows": rows,
    }


# ---------- 预检与 plan ----------

def _row_problem(ds: dict, row: int) -> str | None:
    if row >= ds["rowCount"]:
        return f"数据集“{ds['name']}”只有 {ds['rowCount']} 行，rows 里的行号 {row}（从 0 开始，即第 {row + 1} 行）超出范围"
    return None


def _api_spec(conn, req: dict, details: list[str]) -> tuple[FlowSpec, dict]:
    """调试单个接口：beforeApiIds 的接口在前、目标接口最后，同一个流程同一次迭代；rows 给的数据集按指定的行参与。"""
    try:
        api = validators.validate_api(req["api"], conn)
    except ApiError as exc:
        raise ApiError(400, "VALIDATION_FAILED", "接口定义不合法，没有发送", exc.details) from exc
    steps: list[tuple[dict, Any]] = []
    for api_id in req["beforeApiIds"]:
        upstream = get_obj(conn, APIS, api_id)
        if upstream is None:
            details.append(f"beforeApiIds 里的接口 #{api_id} 不存在")
            continue
        steps.append((upstream, 0))
    steps.append((api, 0))

    loaded = datasets.load_many(conn, list(req["rows"]))
    bindings: list[dict] = []
    owners: dict[str, str] = {}
    for ds_id, row in req["rows"].items():
        ds = loaded.get(ds_id)
        if ds is None:
            details.append(f"rows 里的数据集 #{ds_id} 不存在")
            continue
        problem = _row_problem(ds, row)
        if problem:
            details.append(problem)
            continue
        for column in ds["columns"]:
            if column in owners:
                details.append(f"数据集“{owners[column]}”和“{ds['name']}”都有列 {column}，不能同时用于这次调试")
            else:
                owners[column] = ds["name"]
        # 只写指定的那一行，按顺序取到的就是它
        bindings.append({"dataset": ds, "pick": "sequential", "onExhausted": "recycle"})
    spec = FlowSpec(name=api["name"], weight=1, steps=steps, datasets=bindings)
    return spec, {"kind": "api", "name": api["name"]}


def _flow_spec(conn, req: dict, env: dict | None, details: list[str]) -> tuple[FlowSpec | None, dict]:
    """试跑业务流程：初始化段 + steps，和正式运行一样做变量来源检查（按调试选的被测环境）。"""
    flow = get_obj(conn, FLOWS, req["flowId"])
    if flow is None:
        details.append(f"业务流程 #{req['flowId']} 不存在")
        return None, {}
    bound = {b["datasetId"] for b in flow["datasets"]}
    unbound = [ds_id for ds_id in req["rows"] if ds_id not in bound]
    if unbound:
        raise bad_request(
            "字段校验失败",
            [f"rows 里的数据集 #{ds_id} 没有绑定在业务流程“{flow['name']}”上" for ds_id in unbound],
        )
    spec, complete = expand_flow(conn, flow, 1, details, {})
    for b in spec.datasets:
        problem = _row_problem(b["dataset"], req["rows"].get(b["dataset"]["id"], 0))
        if problem:
            details.append(problem)
            complete = False
    if complete:
        details.extend(datasets.binding_problems(spec.name, spec.datasets, spec.variables))
        if env is not None:
            details.extend(source_problems(spec.name, env, spec.init_steps, spec.steps, spec.datasets, spec.variables))
    return spec, {"kind": "flow", "id": flow["id"], "name": flow["name"]}


def _preflight(conn, req: dict) -> tuple[dict, FlowSpec, dict, dict[int, int], dict[int, dict]]:
    """通过时返回 (被测环境, 流程, source, 每个数据集用的行, 用到的文件)；否则抛 400 / 422。"""
    details: list[str] = []
    env = get_obj(conn, ENVIRONMENTS, req["envId"])
    if env is None:
        details.append(f"被测环境 #{req['envId']} 不存在")
    else:
        problem = base_url_problem(env["baseUrl"])
        if problem:
            details.append(f"被测环境“{env['name']}”的 {problem}")
        if env["type"] == "prod" and not req["confirmProd"]:
            details.append(
                f"被测环境“{env['name']}”是生产环境，调试也会真实地发出请求，需要二次确认：请确认后在请求里带上 \"confirmProd\": true"
            )
        if env["maxVus"] is not None and is_num(env["maxVus"]) and env["maxVus"] < 1:
            details.append(f"被测环境“{env['name']}”的并发上限 maxVus = {env['maxVus']} 小于 1，连 1 个并发的调试也不允许")

    if req["api"] is not None:
        spec, source = _api_spec(conn, req, details)
    else:
        spec, source = _flow_spec(conn, req, env, details)

    used_files: dict[int, dict] = {}
    if spec is not None:
        used_files, file_problems = files.load_for_steps(conn, spec.apis())
        details.extend(file_problems)
    if config.k6_bin() is None:
        details.append(f"k6 可执行文件不存在或不可执行：{config.k6_bin_display()}（先执行 scripts/setup.sh，或设置 K6_BIN）")
    if details:
        raise ApiError(422, "PREFLIGHT_REJECTED", "预检不通过，没有发送", details)
    assert env is not None and spec is not None
    rows = {b["dataset"]["id"]: req["rows"].get(b["dataset"]["id"], 0) for b in spec.datasets}
    return env, spec, source, rows, used_files


def _build_plan(debug_id: str, env: dict, spec: FlowSpec, used_files: dict[int, dict], rows: dict[int, int],
                variables: dict) -> tuple[dict, Any]:
    max_duration = MAX_DURATION_SEC
    if env["maxDurationSec"] is not None and is_num(env["maxDurationSec"]) and env["maxDurationSec"] < max_duration:
        max_duration = env["maxDurationSec"]
    return build_plan(
        debug_id,
        test={"id": 0, "name": "调试"},
        env=env,
        profile={
            "id": 0, "name": "调试", "type": "smoke", "model": "closed",
            "config": {"vus": 1, "iterations": 1, "maxDurationSec": max_duration},
        },
        flows=[spec],
        slo={"p95Ms": None, "p99Ms": None, "errorRate": None, "checksRate": None},
        files=used_files,
        debug={"vars": variables, "bodyLimit": BODY_LIMIT},
        debug_rows=rows,
    )


# ---------- 启动 k6、读结果 ----------

def _spawn(folder: Path, k6: Path) -> subprocess.Popen:
    env = os.environ.copy()
    env["K6_WEB_DASHBOARD"] = "false"  # 调试不开仪表盘，也就不占端口、不会被浏览器拖住
    env["K6_AUTO_EXTENSION_RESOLUTION"] = "false"  # 不认识的 import 不联网下载扩展（契约 §4）
    cmd = [
        str(k6), "run", config.K6_SCRIPT,
        "-e", f"PLAN_FILE={folder / 'plan.json'}",
        "-e", f"OUTPUT_DIR={folder}",
        "--no-thresholds", "--no-usage-report", "--quiet",
        "--log-format=json", f"--console-output={folder / 'debug-console.log'}",
    ]
    with open(folder / "k6.log", "ab") as logfile:
        return subprocess.Popen(
            cmd,
            cwd=config.REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )


def _wait(proc: subprocess.Popen) -> tuple[int | None, bool]:
    """等 k6 退出。返回 (退出码, 是否超时)。超时：发一次 SIGINT，再不退就强杀。"""
    try:
        return proc.wait(timeout=K6_TIMEOUT_SEC), False
    except subprocess.TimeoutExpired:
        pass
    log.warning("调试的 k6 进程 %s 超过 %s 秒没有退出，发送 SIGINT", proc.pid, K6_TIMEOUT_SEC)
    try:
        proc.send_signal(signal.SIGINT)
        return proc.wait(timeout=KILL_AFTER_SEC), True
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except OSError:
            proc.kill()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        return proc.returncode, True


def _read_trace(folder: Path) -> dict | None:
    """从 --console-output 的文件里取最后一行 debugTrace（契约 §5.1）。"""
    path = folder / "debug-console.log"
    try:
        # 只按 \n 切：splitlines() 还会在 U+0085、U+2028、\x1c 等字符处断行，而响应体里的这些字符在 JSON 日志里不转义，
        # 一行调试记录会被切碎（上传二进制文件、目标原样回显时实测出现过）
        lines = path.read_text(encoding="utf-8", errors="replace").split("\n")
    except OSError:
        return None
    for line in reversed(lines):
        line = line.strip()
        if not line or "debugTrace" not in line:
            continue
        try:
            msg = json.loads(line).get("msg")
            trace = json.loads(msg).get("debugTrace") if isinstance(msg, str) else None
        except (ValueError, AttributeError):
            continue
        if isinstance(trace, dict) and isinstance(trace.get("steps"), list):
            return trace
    return None


def _log_tail(folder: Path) -> list[str]:
    out: list[str] = []
    for name in ("k6.log", "debug-console.log"):
        try:
            text = (folder / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.replace("\r", "\n").split("\n"):
            line = raw.strip()
            if not line or "debugTrace" in line:
                continue
            # --log-format=json 时每行是 JSON，只取人能读的部分
            try:
                obj = json.loads(line)
                if isinstance(obj, dict) and "msg" in obj:
                    level = obj.get("level", "")
                    err = obj.get("error")
                    line = f"[{level}] {obj['msg']}" + (f"：{err}" if err else "")
            except ValueError:
                pass
            out.append(line)
    return out[-LOG_TAIL_LINES:]


# ---------- 路由 ----------

router = APIRouter(prefix="/api/debug", tags=["调试"])


@router.post("", summary="调试接口或试跑业务流程")
def run_debug(payload: Any = Body(...)):
    req = _parse_payload(payload)
    with db.connect() as conn:
        env, spec, source, rows, used_files = _preflight(conn, req)
    k6 = config.k6_bin()
    assert k6 is not None  # _preflight 已确认

    now = datetime.now(timezone.utc)
    debug_id = f"dbg-{now.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"
    runs.claim_debug_slot(debug_id)
    folder = debug_root() / debug_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
        plan, inputs = _build_plan(debug_id, env, spec, used_files, rows, req["vars"])
        (folder / "plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        write_inputs(folder, inputs)

        started = time.monotonic()
        try:
            proc = _spawn(folder, k6)
        except OSError as exc:
            raise ApiError(500, "DEBUG_FAILED", f"启动 k6 失败：{exc}") from exc
        exit_code, timed_out = _wait(proc)
        duration_ms = round((time.monotonic() - started) * 1000)

        trace = _read_trace(folder)
        if trace is None:
            tail = _log_tail(folder)
            if timed_out:
                message = f"调试超时：k6 在 {K6_TIMEOUT_SEC} 秒内没有结束，已被终止"
            elif exit_code == 107:
                message = "调试失败：k6 没有产出调试记录（plan 无效或脚本异常，退出码 107）。常见原因：提取规则里的正则表达式写错"
            else:
                message = f"调试失败：k6 没有产出调试记录（退出码 {exit_code}）"
            raise ApiError(500, "DEBUG_FAILED", message, tail or ["（k6 没有输出任何日志）"])

        step_list = trace["steps"]
        final_vars = trace.get("vars") if isinstance(trace.get("vars"), dict) else {}
        return {
            "debugId": debug_id,
            "ok": bool(step_list) and all(isinstance(s, dict) and s.get("status") == "passed" for s in step_list),
            "env": {"id": env["id"], "name": env["name"], "type": env["type"], "baseUrl": env["baseUrl"]},
            "source": source,
            "durationMs": duration_ms,
            "exitCode": exit_code,
            "steps": step_list,
            "vars": final_vars,
        }
    finally:
        runs.release_debug_slot(debug_id)
        shutil.rmtree(folder, ignore_errors=True)
