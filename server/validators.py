"""定义类资源的字段校验。

每个 validate_* 接收请求体（任意 JSON），返回规范化后的字段字典；
有问题时一次性抛出 400 VALIDATION_FAILED，details 逐条列出原因。
多余的字段（id、createdAt、只读的展示字段等）直接忽略，方便前端把 GET 到的对象改完原样 PUT 回来。
"""

import math
import re
import sqlite3
from typing import Any
from urllib.parse import urlsplit

from .errors import bad_request

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
PROFILE_TYPES = ("smoke", "average", "stress", "spike", "soak", "breakpoint")
MODELS = ("closed", "open")
ENV_TYPES = ("dev", "test", "staging", "prod")
ENV_TYPE_LABELS = {"dev": "开发", "test": "测试", "staging": "预发", "prod": "生产"}
ENV_LIMITS = (
    ("maxVus", "maxVus（并发上限）"),
    ("maxRate", "maxRate（到达率上限，每秒迭代数）"),
    ("maxDurationSec", "maxDurationSec（时长上限，秒）"),
)
EXTRACT_FROM = ("json", "regex", "header")
SLO_KEYS = ("p95Ms", "p99Ms", "errorRate", "checksRate")
_VAR_RE = re.compile(r"^\w+$")


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v: Any) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def base_url_problem(value: Any) -> str | None:
    """baseUrl 合法返回 None，否则返回原因。"""
    if not isinstance(value, str) or not value.strip():
        return "baseUrl 必填"
    if re.search(r"\s", value.strip()):
        return "baseUrl 不能包含空白字符"
    try:
        parts = urlsplit(value.strip())
        host = parts.hostname
        _ = parts.port  # 端口非法时这里会抛 ValueError
    except ValueError:
        return "baseUrl 不是合法的地址"
    if parts.scheme not in ("http", "https") or not host:
        return "baseUrl 必须是合法的 http / https 地址，例如 https://www.example.com"
    return None


class _Checker:
    def __init__(self, data: Any):
        if not isinstance(data, dict):
            raise bad_request("请求体必须是 JSON 对象")
        self.data = data
        self.errors: list[str] = []

    def err(self, msg: str) -> None:
        self.errors.append(msg)

    def done(self) -> None:
        if self.errors:
            raise bad_request("字段校验失败", self.errors)

    def name(self) -> str:
        v = self.data.get("name")
        if not isinstance(v, str) or not v.strip():
            self.err("name（名称）必填，且不能为空")
            return ""
        if len(v.strip()) > 100:
            self.err("name（名称）不能超过 100 个字符")
        return v.strip()

    def note(self) -> str:
        v = self.data.get("note")
        if v is None:
            return ""
        if not isinstance(v, str):
            self.err("note（备注）必须是字符串")
            return ""
        return v

    def headers(self) -> dict[str, str]:
        v = self.data.get("headers")
        if v is None:
            return {}
        if not isinstance(v, dict):
            self.err("headers 必须是对象（请求头名称 → 值）")
            return {}
        out: dict[str, str] = {}
        for key, val in v.items():
            if not key.strip():
                self.err("headers 中有空的请求头名称")
            elif not isinstance(val, str):
                self.err(f"headers.{key} 的值必须是字符串")
            else:
                out[key.strip()] = val
        return out

    def positive(self, key: str, label: str, source: dict | None = None, *, integer: bool = False) -> Any:
        v = (self.data if source is None else source).get(key)
        if integer:
            if not is_int(v) or v <= 0:
                self.err(f"{label}：必填，且必须是正整数")
                return None
        elif not is_num(v) or v <= 0:
            self.err(f"{label}：必填，且必须是正数")
            return None
        return v


def validate_environment(data: Any, conn: sqlite3.Connection) -> dict:
    c = _Checker(data)
    out = {"name": c.name()}
    problem = base_url_problem(data.get("baseUrl"))
    if problem:
        c.err(problem)
        out["baseUrl"] = ""
    else:
        # 去掉末尾的 /，接口的 path 以 / 开头，拼起来不会出现 //
        out["baseUrl"] = data["baseUrl"].strip().rstrip("/")
    out["headers"] = c.headers()

    env_type = data.get("type")
    if env_type not in ENV_TYPES:
        c.err("type（被测环境类型）必填，且必须是 dev（开发）/ test（测试）/ staging（预发）/ prod（生产）之一")
    out["type"] = env_type

    # 三个安全上限：正数，或 null（不限制）。生产环境三项都必须填
    for key, label in ENV_LIMITS:
        value = data.get(key)
        if value is None:
            if env_type == "prod":
                c.err(f"{label}：生产环境必须填写安全上限，不能留空")
        elif not is_num(value) or value <= 0:
            c.err(f"{label}：必须是正数，或留空（null）表示不限制")
            value = None
        out[key] = value
    out["note"] = c.note()
    c.done()
    return out


def validate_api(data: Any, conn: sqlite3.Connection) -> dict:
    c = _Checker(data)
    out: dict[str, Any] = {"name": c.name()}

    method = data.get("method")
    if not isinstance(method, str) or method.strip().upper() not in METHODS:
        c.err("method 必须是 " + " / ".join(METHODS) + " 之一")
        out["method"] = "GET"
    else:
        out["method"] = method.strip().upper()

    path = data.get("path")
    if not isinstance(path, str) or not path.strip().startswith("/"):
        c.err("path 必填，且必须以 / 开头")
        out["path"] = "/"
    else:
        out["path"] = path.strip()

    out["headers"] = c.headers()

    body = data.get("body")
    if body is not None and not isinstance(body, str):
        c.err("body 必须是字符串或 null")
        body = None
    out["body"] = body or None

    status = data.get("expectStatus", 200)
    if not is_int(status) or not 100 <= status <= 599:
        c.err("expectStatus 必须是 100–599 之间的整数")
        status = 200
    out["expectStatus"] = status

    contains = data.get("expectBodyContains")
    if contains is not None and not isinstance(contains, str):
        c.err("expectBodyContains 必须是字符串或 null")
        contains = None
    out["expectBodyContains"] = contains or None

    extracts = data.get("extracts")
    out["extracts"] = []
    if extracts is None:
        extracts = []
    if not isinstance(extracts, list):
        c.err("extracts 必须是数组")
    else:
        seen: set[str] = set()
        for i, item in enumerate(extracts, 1):
            if not isinstance(item, dict):
                c.err(f"extracts 第 {i} 项必须是对象")
                continue
            var, source, expr = item.get("var"), item.get("from"), item.get("expr")
            ok = True
            if not isinstance(var, str) or not _VAR_RE.match(var):
                c.err(f"extracts 第 {i} 项的 var（变量名）必填，只能包含字母、数字、下划线")
                ok = False
            elif var in seen:
                c.err(f"extracts 第 {i} 项的变量名 {var} 重复")
                ok = False
            if source not in EXTRACT_FROM:
                c.err(f"extracts 第 {i} 项的 from 必须是 " + " / ".join(EXTRACT_FROM) + " 之一")
                ok = False
            if not isinstance(expr, str) or not expr.strip():
                c.err(f"extracts 第 {i} 项的 expr 必填")
                ok = False
            if ok:
                seen.add(var)
                out["extracts"].append({"var": var, "from": source, "expr": expr.strip()})

    out["note"] = c.note()
    c.done()
    return out


def validate_flow(data: Any, conn: sqlite3.Connection) -> dict:
    c = _Checker(data)
    out: dict[str, Any] = {"name": c.name(), "note": c.note(), "steps": []}
    steps = data.get("steps")
    if steps is None:
        steps = []
    if not isinstance(steps, list):
        c.err("steps 必须是数组")
    else:
        known = {row[0] for row in conn.execute("SELECT id FROM apis")}
        for i, step in enumerate(steps, 1):
            if not isinstance(step, dict):
                c.err(f"步骤 {i} 必须是对象")
                continue
            api_id = step.get("apiId")
            think = step.get("thinkTimeMs", 0)
            if think is None:
                think = 0
            ok = True
            if not is_int(api_id):
                c.err(f"步骤 {i} 的 apiId 必填，且必须是整数")
                ok = False
            elif api_id not in known:
                c.err(f"步骤 {i} 引用的接口 #{api_id} 不存在")
                ok = False
            if not is_num(think) or think < 0:
                c.err(f"步骤 {i} 的 thinkTimeMs 必须是不小于 0 的数字")
                ok = False
            if ok:
                out["steps"].append({"apiId": api_id, "thinkTimeMs": think})
    c.done()
    return out


# config 的四种形态（契约 §3.1）：model → [(形态名, 字段集合)]
_CONFIG_SHAPES = {
    "closed": [
        ("固定迭代数", {"vus", "iterations", "maxDurationSec"}),
        ("固定并发", {"vus", "durationSec"}),
    ],
    "open": [
        ("固定到达率", {"rate", "durationSec", "preAllocatedVus"}),
        ("阶梯到达率", {"startRate", "stages", "preAllocatedVus"}),
    ],
}


def config_shape_problem(model: Any, cfg: Any) -> str | None:
    """config 的字段组合属于契约的四种形态之一时返回 None，否则返回原因。保存和预检都用它。"""
    if model not in _CONFIG_SHAPES:
        return "model 必须是 closed 或 open"
    if not isinstance(cfg, dict):
        return "config 必须是对象"
    keys = set(cfg.keys())
    shapes = _CONFIG_SHAPES[model]
    if any(keys == fields for _, fields in shapes):
        return None
    allowed = "；或 ".join(f"{label}（{', '.join(sorted(fields))}）" for label, fields in shapes)
    return f"model 为 {model} 时，config 的字段必须恰好是：{allowed}。当前字段：{', '.join(sorted(keys)) or '（空）'}"


def _validate_config(c: _Checker, model: str, cfg: Any) -> dict:
    if not isinstance(cfg, dict):
        c.err("config 必填，且必须是对象")
        return {}
    keys = set(cfg.keys())
    problem = config_shape_problem(model, cfg)
    if problem:
        c.err(problem)
        return {}

    out: dict[str, Any] = {}
    if "vus" in keys:
        out["vus"] = c.positive("vus", "config.vus（并发数）", cfg, integer=True)
    if "iterations" in keys:
        out["iterations"] = c.positive("iterations", "config.iterations（总迭代数）", cfg, integer=True)
        if out["iterations"] and out.get("vus") and out["iterations"] < out["vus"]:
            c.err("config.iterations 不能小于 config.vus（k6 的 shared-iterations 要求）")
    if "maxDurationSec" in keys:
        out["maxDurationSec"] = c.positive("maxDurationSec", "config.maxDurationSec（最长时长，秒）", cfg)
    if "rate" in keys:
        out["rate"] = c.positive("rate", "config.rate（每秒迭代数）", cfg)
    if "durationSec" in keys:
        out["durationSec"] = c.positive("durationSec", "config.durationSec（时长，秒）", cfg)
    if "startRate" in keys:
        start = cfg.get("startRate")
        if not is_num(start) or start < 0:
            c.err("config.startRate（起始到达率）必填，且必须是不小于 0 的数字")
        out["startRate"] = start
    if "stages" in keys:
        stages = cfg.get("stages")
        out["stages"] = []
        if not isinstance(stages, list) or not stages:
            c.err("config.stages 必填，且至少有 1 个阶段")
        else:
            for i, stage in enumerate(stages, 1):
                if not isinstance(stage, dict):
                    c.err(f"config.stages 第 {i} 项必须是对象")
                    continue
                target = stage.get("target")
                if not is_num(target) or target < 0:
                    c.err(f"config.stages 第 {i} 项的 target（目标到达率）必须是不小于 0 的数字")
                duration = c.positive("durationSec", f"config.stages 第 {i} 项的 durationSec（秒）", stage)
                out["stages"].append({"target": target, "durationSec": duration})
    if "preAllocatedVus" in keys:
        out["preAllocatedVus"] = c.positive("preAllocatedVus", "config.preAllocatedVus（预分配 VU 数）", cfg, integer=True)
    return out


def validate_profile(data: Any, conn: sqlite3.Connection) -> dict:
    c = _Checker(data)
    out: dict[str, Any] = {"name": c.name()}
    kind = data.get("type")
    if kind not in PROFILE_TYPES:
        c.err("type 必须是 " + " / ".join(PROFILE_TYPES) + " 之一")
    out["type"] = kind
    model = data.get("model")
    if model not in MODELS:
        c.err("model 必填，且必须是 closed 或 open")
        out["config"] = {}
    else:
        out["config"] = _validate_config(c, model, data.get("config"))
    out["model"] = model
    out["note"] = c.note()
    c.done()
    return out


def validate_test(data: Any, conn: sqlite3.Connection) -> dict:
    c = _Checker(data)
    out: dict[str, Any] = {"name": c.name(), "note": c.note(), "flows": []}
    flows = data.get("flows")
    if flows is None:
        flows = []
    if not isinstance(flows, list):
        c.err("flows 必须是数组")
    else:
        known = {row[0] for row in conn.execute("SELECT id FROM flows")}
        for i, item in enumerate(flows, 1):
            if not isinstance(item, dict):
                c.err(f"flows 第 {i} 项必须是对象")
                continue
            flow_id, weight = item.get("flowId"), item.get("weight", 1)
            ok = True
            if not is_int(flow_id):
                c.err(f"flows 第 {i} 项的 flowId 必填，且必须是整数")
                ok = False
            elif flow_id not in known:
                c.err(f"flows 第 {i} 项引用的业务流程 #{flow_id} 不存在")
                ok = False
            if not is_num(weight) or weight <= 0:
                c.err(f"flows 第 {i} 项的 weight（权重）必须是正数")
                ok = False
            if ok:
                out["flows"].append({"flowId": flow_id, "weight": weight})

    slo_in = data.get("slo")
    if slo_in is None:
        slo_in = {}
    slo: dict[str, Any] = {key: None for key in SLO_KEYS}
    if not isinstance(slo_in, dict):
        c.err("slo 必须是对象")
    else:
        for key in SLO_KEYS:
            v = slo_in.get(key)
            if v is None:
                continue
            if key in ("p95Ms", "p99Ms"):
                if not is_num(v) or v <= 0:
                    c.err(f"slo.{key} 必须是正数（毫秒）或 null")
                    continue
            elif not is_num(v) or not 0 <= v <= 1:
                c.err(f"slo.{key} 必须是 0–1 之间的数字或 null")
                continue
            slo[key] = v
    out["slo"] = slo
    c.done()
    return out


def profile_usage(profile: dict) -> dict:
    """负载配置实际会用到的并发、到达率、总时长，供预检与环境上限比较。"""
    cfg = profile.get("config") or {}
    usage: dict[str, Any] = {"concurrency": None, "rates": [], "durationSec": None}
    if "vus" in cfg:
        usage["concurrency"] = ("vus", cfg["vus"])
    elif "preAllocatedVus" in cfg:
        usage["concurrency"] = ("preAllocatedVus", cfg["preAllocatedVus"])
    if "rate" in cfg:
        usage["rates"].append(("rate", cfg["rate"]))
    if "startRate" in cfg:
        usage["rates"].append(("startRate", cfg["startRate"]))
    stages = cfg.get("stages") or []
    for i, stage in enumerate(stages, 1):
        usage["rates"].append((f"stages 第 {i} 项的 target", stage.get("target")))
    if "maxDurationSec" in cfg:
        usage["durationSec"] = cfg["maxDurationSec"]
    elif "durationSec" in cfg:
        usage["durationSec"] = cfg["durationSec"]
    elif stages:
        usage["durationSec"] = sum(s.get("durationSec") or 0 for s in stages)
    return usage
