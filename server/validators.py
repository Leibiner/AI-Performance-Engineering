"""定义类资源的字段校验。

每个 validate_* 接收请求体（任意 JSON），返回规范化后的字段字典；
有问题时一次性抛出 400 VALIDATION_FAILED，details 逐条列出原因。
多余的字段（id、createdAt、只读的展示字段等）直接忽略，方便前端把 GET 到的对象改完原样 PUT 回来。
"""

import json
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
EXTRACT_FROM = ("json", "regex", "header", "cookie")
SLO_KEYS = ("p95Ms", "p99Ms", "errorRate", "checksRate")
BODY_TYPES = ("raw", "form", "multipart")  # 接口页上 form 叫 x-www-form-urlencoded，multipart 叫 form-data
PICKS = ("sequential", "random", "perVu")
PICK_LABELS = {"sequential": "按顺序", "random": "随机", "perVu": "每个 VU 固定一行"}
ON_EXHAUSTED = ("recycle", "stop")
ON_EXHAUSTED_LABELS = {"recycle": "循环使用", "stop": "停止测试"}
INIT_LABEL = "初始化（每个 VU 一次）"

# 必须用 fullmatch：match 加 ^…$ 会放过结尾的换行。\w 含中文等各种文字的字母和数字，不含 $
VAR_NAME_RE = re.compile(r"\w+")
VAR_NAME_RULE = "只能由字母（含中文）、数字、下划线组成"


def is_var_name(name: Any) -> bool:
    """变量名规则（契约 §3.1「变量」）：环境变量、提取规则、数据集的列、流程变量、调试的当前值共用。"""
    return isinstance(name, str) and VAR_NAME_RE.fullmatch(name) is not None


def is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def is_int(v: Any) -> bool:
    # 超出 64 位的整数交给 sqlite 会抛 OverflowError，变成 500
    return isinstance(v, int) and not isinstance(v, bool) and -(2**63) <= v < 2**63


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


class Checker:
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
    c = Checker(data)
    out = {"name": c.name()}
    problem = base_url_problem(data.get("baseUrl"))
    if problem:
        c.err(problem)
        out["baseUrl"] = ""
    else:
        # 去掉末尾的 /，接口的 path 以 / 开头，拼起来不会出现 //
        out["baseUrl"] = data["baseUrl"].strip().rstrip("/")
    out["headers"] = c.headers()

    # 环境变量（初始值）：变量名 → 字符串。运行和调试开始时作为初始变量，接口里用 {{变量名}} 引用
    raw_vars = data.get("variables")
    out["variables"] = {}
    if raw_vars is not None:
        if not isinstance(raw_vars, dict):
            c.err("variables（环境变量）必须是对象（变量名 → 值）")
        else:
            for name, value in raw_vars.items():
                if not is_var_name(name.strip()):
                    c.err(f"环境变量名 {name!r} {VAR_NAME_RULE}")
                elif name.strip() in out["variables"]:
                    c.err(f"环境变量名 {name.strip()} 重复")
                elif not isinstance(value, str):
                    c.err(f"环境变量 {name} 的值必须是字符串")
                else:
                    out["variables"][name.strip()] = value

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


def _folder_id(c: Checker, conn: sqlite3.Connection, key: str, label: str) -> int | None:
    """文件夹 id：null 表示根目录；否则必须是存在的文件夹。"""
    value = c.data.get(key)
    if value is None:
        return None
    if not is_int(value):
        c.err(f"{label} 必须是整数或 null")
        return None
    if conn.execute("SELECT 1 FROM folders WHERE id = ?", (value,)).fetchone() is None:
        c.err(f"{label} 指向的文件夹 #{value} 不存在")
        return None
    return value


def validate_folder(data: Any, conn: sqlite3.Connection) -> dict:
    """接口文件夹。parentId 为 null 表示顶层；不能把文件夹放到自己或自己的子孙下面（PUT 时请求体里带 id）。"""
    c = Checker(data)
    out: dict[str, Any] = {"name": c.name(), "note": c.note()}
    parent = _folder_id(c, conn, "parentId", "parentId（上级文件夹）")
    own = data.get("id")
    if parent is not None and is_int(own):
        if parent == own:
            c.err("不能把文件夹放到它自己下面")
        else:
            # 沿上级链往上走，碰到自己就是环
            seen: set[int] = set()
            cursor: int | None = parent
            while cursor is not None and cursor not in seen:
                seen.add(cursor)
                if cursor == own:
                    c.err("不能把文件夹放到它自己的子文件夹下面")
                    break
                row = conn.execute("SELECT parent_id FROM folders WHERE id = ?", (cursor,)).fetchone()
                cursor = row[0] if row else None
    out["parentId"] = parent
    c.done()
    return out


def _stored(conn: sqlite3.Connection, table: str, columns: str, data: dict) -> sqlite3.Row | None:
    """PUT 时这条定义在库里原来的样子（路由把路径上的 id 放进了请求体）；新建时为 None。

    定义之间的引用可以失效（被引用的接口、流程、数据集、文件删掉了也不挡删除，契约 §3.1）：
    已经失效的引用保存时原样保留，不因为别的字段的修改而被拒绝；新增的引用仍然必须指向存在的对象。"""
    own = data.get("id")
    if not is_int(own):
        return None
    return conn.execute(f"SELECT {columns} FROM {table} WHERE id = ?", (own,)).fetchone()


def validate_api(data: Any, conn: sqlite3.Connection) -> dict:
    c = Checker(data)
    out: dict[str, Any] = {"name": c.name()}
    out["folderId"] = _folder_id(c, conn, "folderId", "folderId（所属文件夹）")

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

    body_type = data.get("bodyType")
    if body_type is None:
        body_type = "raw"
    if body_type not in BODY_TYPES:
        c.err("bodyType（请求体类型）必须是 raw / form（x-www-form-urlencoded）/ multipart（form-data）之一")
        body_type = "raw"
    out["bodyType"] = body_type

    # body 和 form 都保存，只发送 bodyType 对应的那一个（切换类型不丢内容）
    body = data.get("body")
    if body is not None and not isinstance(body, str):
        c.err("body 必须是字符串或 null")
        body = None
    out["body"] = body or None
    stored = _stored(conn, "apis", "form", c.data)
    kept_files = {
        item.get("fileId") for item in (json.loads(stored["form"]) if stored else [])
        if isinstance(item, dict) and item.get("type") == "file"
    }
    out["form"] = _form_items(c, conn, data.get("form"), body_type, kept_files)

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
            if not is_var_name(var):
                c.err(f"extracts 第 {i} 项的 var（变量名）必填，{VAR_NAME_RULE}")
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


def _form_items(c: Checker, conn: sqlite3.Connection, items: Any, body_type: str, kept_files: set) -> list[dict]:
    """接口的表单项（契约 §3.1 form）。文本项的 fileId 规范成 null，文件项的 value 规范成空串。

    bodyType 为 raw 时表单只是为了切换类型不丢内容而保留，不发送，所以不要求填完整：名称可以为空，文件项可以还没选文件。"""
    active = body_type != "raw"
    if items is None:
        return []
    if not isinstance(items, list):
        c.err("form（表单项）必须是数组")
        return []
    out: list[dict] = []
    wanted: list[tuple[int, int]] = []  # (第几项, fileId)
    for i, item in enumerate(items, 1):
        where = f"form 第 {i} 项"
        if not isinstance(item, dict):
            c.err(f"{where}必须是对象")
            continue
        name, kind = item.get("name"), item.get("type")
        ok = True
        if not isinstance(name, str) or (active and not name.strip()):
            c.err(f"{where}的 name（字段名）必填")
            ok = False
        if kind == "text":
            value = item.get("value")
            if value is None:
                value = ""
            if not isinstance(value, str):
                c.err(f"{where}的 value 必须是字符串")
                ok = False
            entry = {"name": name, "type": "text", "value": value, "fileId": None}
        elif kind == "file":
            file_id = item.get("fileId")
            if body_type == "form":
                c.err(f"{where}是文件：x-www-form-urlencoded 请求体不能包含文件，上传文件请用 form-data")
                ok = False
            if file_id is None and not active:
                pass
            elif not is_int(file_id):
                c.err(f"{where}是文件，fileId（文件）必填，且必须是整数")
                ok = False
            else:
                wanted.append((i, file_id))
            entry = {"name": name, "type": "file", "value": "", "fileId": file_id}
        else:
            c.err(f"{where}的 type 必须是 text（文本）或 file（文件）")
            ok = False
        if ok:
            out.append(entry)
    if wanted:
        ids = sorted({file_id for _, file_id in wanted})
        marks = ", ".join("?" for _ in ids)
        known = {row[0] for row in conn.execute(f"SELECT id FROM files WHERE id IN ({marks})", ids)}
        for i, file_id in wanted:
            if file_id not in known and file_id not in kept_files:
                c.err(f"form 第 {i} 项引用的文件 #{file_id} 不存在")
    return out


def _flow_steps(c: Checker, raw: Any, key: str, label: str, known: set[int]) -> list[dict]:
    """steps / initSteps：[{apiId, thinkTimeMs}]。label 是提示里对一步的称呼。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        c.err(f"{key} 必须是数组")
        return []
    out = []
    for i, step in enumerate(raw, 1):
        if not isinstance(step, dict):
            c.err(f"{label} {i} 必须是对象")
            continue
        api_id = step.get("apiId")
        think = step.get("thinkTimeMs", 0)
        if think is None:
            think = 0
        ok = True
        if not is_int(api_id):
            c.err(f"{label} {i} 的 apiId 必填，且必须是整数")
            ok = False
        elif api_id not in known:
            c.err(f"{label} {i} 引用的接口 #{api_id} 不存在")
            ok = False
        if not is_num(think) or think < 0:
            c.err(f"{label} {i} 的 thinkTimeMs 必须是不小于 0 的数字")
            ok = False
        if ok:
            out.append({"apiId": api_id, "thinkTimeMs": think})
    return out


def _flow_datasets(c: Checker, conn: sqlite3.Connection, raw: Any, kept: set) -> tuple[list[dict], dict[str, str]]:
    """绑定的数据集。返回 (规范化的绑定, 列名 → 所属数据集的名称)。"""
    if raw is None:
        return [], {}
    if not isinstance(raw, list):
        c.err("datasets（绑定的数据集）必须是数组")
        return [], {}
    known = {row["id"]: row for row in conn.execute("SELECT id, name, columns FROM datasets")}
    out: list[dict] = []
    owners: dict[str, str] = {}
    seen: set[int] = set()
    picks = " / ".join(f"{p}（{PICK_LABELS[p]}）" for p in PICKS)
    endings = " / ".join(f"{e}（{ON_EXHAUSTED_LABELS[e]}）" for e in ON_EXHAUSTED)
    for i, item in enumerate(raw, 1):
        where = f"数据集绑定第 {i} 项"
        if not isinstance(item, dict):
            c.err(f"{where}必须是对象")
            continue
        ds_id, pick, ending = item.get("datasetId"), item.get("pick"), item.get("onExhausted")
        ok = True
        row = None
        if not is_int(ds_id):
            c.err(f"{where}的 datasetId 必填，且必须是整数")
            ok = False
        elif ds_id in seen:
            c.err(f"数据集 #{ds_id} 重复绑定：同一流程里每个数据集只能绑定一次")
            ok = False
        elif ds_id not in known:
            if ds_id in kept:
                seen.add(ds_id)  # 已被删除的数据集：失效绑定原样保留，没有列可查
            else:
                c.err(f"{where}引用的数据集 #{ds_id} 不存在")
                ok = False
        else:
            row = known[ds_id]
            seen.add(ds_id)
        if pick not in PICKS:
            c.err(f"{where}的 pick（取法）必须是 {picks} 之一")
            ok = False
        if ending not in ON_EXHAUSTED:
            c.err(f"{where}的 onExhausted（用完时）必须是 {endings} 之一")
            ok = False
        elif pick == "random" and ending != "recycle":
            c.err(f"{where}：取法为随机（random）时，用完时只能是循环使用（recycle）")
            ok = False
        if row is not None:
            for column in json.loads(row["columns"]):
                if column in owners:
                    c.err(f"数据集“{owners[column]}”和“{row['name']}”都有列 {column}：同一流程绑定的数据集列名不能重复")
                    ok = False
                else:
                    owners[column] = row["name"]
        if ok:
            out.append({"datasetId": ds_id, "pick": pick, "onExhausted": ending})
    return out, owners


def _flow_variables(c: Checker, raw: Any, owners: dict[str, str]) -> list[dict]:
    """流程变量 [{name, value}]：每次迭代按顺序求值一次。"""
    if raw is None:
        return []
    if not isinstance(raw, list):
        c.err("variables（流程变量）必须是数组")
        return []
    out: list[dict] = []
    seen: set[str] = set()
    for i, item in enumerate(raw, 1):
        where = f"流程变量第 {i} 项"
        if not isinstance(item, dict):
            c.err(f"{where}必须是对象")
            continue
        name, value = item.get("name"), item.get("value")
        if isinstance(name, str):
            name = name.strip()
        if value is None:
            value = ""
        ok = True
        if not is_var_name(name):
            c.err(f"{where}的 name（变量名）必填，{VAR_NAME_RULE}")
            ok = False
        elif name in seen:
            c.err(f"流程变量 {name} 重复")
            ok = False
        elif name in owners:
            c.err(f"流程变量 {name} 和数据集“{owners[name]}”的列重名")
            ok = False
        if not isinstance(value, str):
            c.err(f"{where}的 value 必须是字符串")
            ok = False
        if ok:
            seen.add(name)
            out.append({"name": name, "value": value})
    return out


def validate_flow(data: Any, conn: sqlite3.Connection) -> dict:
    c = Checker(data)
    out: dict[str, Any] = {"name": c.name(), "note": c.note()}
    stored = _stored(conn, "flows", "init_steps, steps, datasets", c.data)
    kept_apis = {step.get("apiId") for step in (json.loads(stored["init_steps"]) + json.loads(stored["steps"]) if stored else [])}
    kept_datasets = {b.get("datasetId") for b in (json.loads(stored["datasets"]) if stored else [])}
    known = {row[0] for row in conn.execute("SELECT id FROM apis")} | kept_apis
    out["datasets"], owners = _flow_datasets(c, conn, data.get("datasets"), kept_datasets)
    out["variables"] = _flow_variables(c, data.get("variables"), owners)
    raw_init = data.get("initSteps")
    out["initSteps"] = _flow_steps(c, raw_init, "initSteps", f"{INIT_LABEL}步骤", known)
    reinit = data.get("reinitSec")
    if reinit is not None:
        if not is_num(reinit) or reinit <= 0:
            c.err("reinitSec（重新初始化间隔，秒）必须是正数，或 null 表示不重新初始化")
            reinit = None
        elif not (isinstance(raw_init, list) and raw_init):
            c.err(f"{INIT_LABEL}没有步骤时，reinitSec（重新初始化间隔）必须为 null")
            reinit = None
    out["reinitSec"] = reinit
    out["steps"] = _flow_steps(c, data.get("steps"), "steps", "步骤", known)
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


def _validate_config(c: Checker, model: str, cfg: Any) -> dict:
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
    c = Checker(data)
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
    c = Checker(data)
    out: dict[str, Any] = {"name": c.name(), "note": c.note(), "flows": []}
    flows = data.get("flows")
    if flows is None:
        flows = []
    if not isinstance(flows, list):
        c.err("flows 必须是数组")
    else:
        stored = _stored(conn, "tests", "flows", c.data)
        kept = {item.get("flowId") for item in (json.loads(stored["flows"]) if stored else [])}
        known = {row[0] for row in conn.execute("SELECT id FROM flows")} | kept
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
