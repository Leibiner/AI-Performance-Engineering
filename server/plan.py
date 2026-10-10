"""plan.json 的组装（契约 §4），运行和调试共用；以及把用到的数据集、文件写进运行目录（k6 的输入）。

行数据和文件内容不进 plan（plan 会被每个 VU 各解析一次），plan 里只有元数据和相对路径。
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from . import datasets, references
from .resources import APIS, get_obj

DATASETS_DIR = "datasets"
FILES_DIR = "files"


@dataclass
class FlowSpec:
    """一个要进 plan 的业务流程，接口和数据集都已经取出来。"""
    name: str
    weight: float
    steps: list[tuple[dict, Any]]  # (接口定义, thinkTimeMs)
    init_steps: list[tuple[dict, Any]] = field(default_factory=list)
    datasets: list[dict] = field(default_factory=list)  # [{"dataset": datasets.load_many 的一项, "pick", "onExhausted"}]
    variables: list[dict] = field(default_factory=list)
    reinit_sec: Any = None

    def apis(self) -> list[dict]:
        return [api for api, _ in self.init_steps + self.steps]


@dataclass
class Inputs:
    """写进运行目录的输入文件：相对 plan.json 的路径 → 内容。"""
    datasets: dict[str, str] = field(default_factory=dict)
    files: dict[str, bytes] = field(default_factory=dict)


def expand_flow(conn, flow: dict, weight: float, details: list[str], cache: dict[int, dict]) -> tuple[FlowSpec, bool]:
    """按已保存的业务流程取出接口和数据集。找不到的逐条追加到 details；第二个返回值表示是否全部取到。"""
    name = flow["name"]
    complete = True
    if not flow["steps"]:
        details.append(f"业务流程“{name}”没有任何步骤")
        complete = False

    # 失效引用（引用的接口、数据集已被删除）的提示由引用登记表统一生成（契约 §3.8）
    broken = references.broken_messages(references.Lookup(conn), "flow", flow, name)
    if broken:
        details.extend(broken)
        complete = False

    def resolve(items: list[dict]) -> list[tuple[dict, Any]]:
        out = []
        for step in items:
            api = get_obj(conn, APIS, step["apiId"])
            if api is not None:
                out.append((api, step["thinkTimeMs"]))
        return out

    init_steps = resolve(flow.get("initSteps") or [])
    steps = resolve(flow["steps"])
    wanted = flow.get("datasets") or []
    loaded = datasets.load_many(conn, [b["datasetId"] for b in wanted], cache)
    bindings = []
    for binding in wanted:
        ds = loaded.get(binding["datasetId"])
        if ds is None:
            continue
        bindings.append({"dataset": ds, "pick": binding["pick"], "onExhausted": binding["onExhausted"]})
    spec = FlowSpec(
        name=name, weight=weight, steps=steps, init_steps=init_steps, datasets=bindings,
        variables=flow.get("variables") or [], reinit_sec=flow.get("reinitSec"),
    )
    return spec, complete


def normalized_weights(weights: list[float]) -> list[float]:
    """按和归一化。逐个相加而不用 sum()：Python 3.12 的 sum() 对浮点数做补偿求和，和引擎的 reduce 可能差最后一位。"""
    total = 0
    for w in weights:
        total += w
    return [w / total for w in weights]


def env_entry(env: dict) -> dict:
    return {
        "id": env["id"], "name": env["name"], "type": env["type"],
        "baseUrl": env["baseUrl"].rstrip("/"), "headers": env["headers"],
        "variables": env.get("variables") or {},
    }


def _step(key: str, api: dict, think: Any, file_key: Callable[[int], str]) -> dict:
    body_type = api.get("bodyType") or "raw"
    items = api.get("form") or []
    # 只有发送的那种请求体需要 form；raw 的 form 不发送，不带进 plan，也就不会让引擎去加载它引用的文件
    if body_type == "multipart":
        form = [
            {"name": it["name"], "type": "file", "fileKey": file_key(it["fileId"])} if it["type"] == "file"
            else {"name": it["name"], "type": "text", "value": it["value"]}
            for it in items
        ]
    elif body_type == "form":
        form = [{"name": it["name"], "type": "text", "value": it["value"]} for it in items if it["type"] == "text"]
    else:
        form = []
    return {
        "key": key,
        "name": api["name"],
        "method": api["method"],
        "path": api["path"],
        "headers": api["headers"],
        "bodyType": body_type,
        "body": api["body"],
        "form": form,
        "expectStatus": api["expectStatus"],
        "expectBodyContains": api["expectBodyContains"],
        "extracts": api["extracts"],
        "thinkTimeMs": think,
    }


def build_plan(
    run_id: str,
    *,
    test: dict,
    env: dict,
    profile: dict,
    flows: list[FlowSpec],
    slo: dict,
    files: dict[int, dict],
    debug: dict | None = None,
    debug_rows: dict[int, int] | None = None,
) -> tuple[dict, Inputs]:
    """组装 plan，同时给出要写进运行目录的输入文件。

    files：步骤里 multipart 引用的文件（files.load_for_steps 的结果）。
    debug_rows：调试时每个数据集用哪一行（数据集 id → 行号）；给了就只写那一行，plan 里 rowCount 为 1。
    """
    inputs = Inputs()
    ds_entries: list[dict] = []
    ds_keys: dict[int, str] = {}
    file_entries: list[dict] = []
    file_keys: dict[int, str] = {}

    def dataset_key(ds: dict) -> str:
        if ds["id"] not in ds_keys:
            key = f"d{len(ds_keys) + 1}"
            path = f"{DATASETS_DIR}/{key}.json"
            if debug_rows is None:
                text, count = ds["rowsJson"], ds["rowCount"]
            else:
                row = json.loads(ds["rowsJson"])[debug_rows[ds["id"]]]
                text, count = json.dumps([row], ensure_ascii=False, separators=(",", ":")), 1
            ds_keys[ds["id"]] = key
            inputs.datasets[path] = text
            ds_entries.append({
                "key": key, "id": ds["id"], "name": ds["name"], "columns": ds["columns"],
                "rowCount": count, "sha256": ds["sha256"], "file": path,
            })
        return ds_keys[ds["id"]]

    def file_key(file_id: int) -> str:
        if file_id not in file_keys:
            f = files[file_id]
            key = f"u{len(file_keys) + 1}"
            path = f"{FILES_DIR}/{key}.bin"
            file_keys[file_id] = key
            inputs.files[path] = f["data"]
            file_entries.append({
                "key": key, "id": f["id"], "name": f["name"], "contentType": f["contentType"],
                "size": f["size"], "sha256": f["sha256"], "file": path,
            })
        return file_keys[file_id]

    # k6 的 iterationInTest 按 scenario 各自从 0 开始。k 个流程按顺序共用一个数据集时，
    # 第 i 个取 iterationInTest × k + i 行，互不重复（契约 §4）
    sharers = Counter(b["dataset"]["id"] for spec in flows for b in spec.datasets if b["pick"] == "sequential")
    taken: Counter = Counter()

    weights = normalized_weights([spec.weight for spec in flows])
    plan_flows = []
    for i, spec in enumerate(flows, 1):
        flow_key = f"f{i}"
        bindings = []
        for b in spec.datasets:
            ds_id = b["dataset"]["id"]
            stride, offset = 1, 0
            if b["pick"] == "sequential":
                stride, offset = sharers[ds_id], taken[ds_id]
                taken[ds_id] += 1
            bindings.append({
                "key": dataset_key(b["dataset"]), "pick": b["pick"], "onExhausted": b["onExhausted"],
                "stride": stride, "offset": offset,
            })
        plan_flows.append({
            "key": flow_key,
            "name": spec.name,
            "weight": weights[i - 1],
            "datasets": bindings,
            "variables": [{"name": v["name"], "value": v["value"]} for v in spec.variables],
            "reinitSec": spec.reinit_sec,
            "initSteps": [_step(f"{flow_key}i{j}", api, think, file_key) for j, (api, think) in enumerate(spec.init_steps, 1)],
            "steps": [_step(f"{flow_key}s{j}", api, think, file_key) for j, (api, think) in enumerate(spec.steps, 1)],
        })

    plan = {
        "schemaVersion": 1,
        "runId": run_id,
        "test": test,
        "env": env_entry(env),
        "profile": profile,
        "datasets": ds_entries,
        "files": file_entries,
        "flows": plan_flows,
        "slo": slo,
    }
    if debug is not None:
        plan["debug"] = debug
    return plan, inputs


def write_inputs(folder: Path, inputs: Inputs) -> None:
    """数据集写成 UTF-8（不带 BOM）的 JSON 数组，文件写原始字节，路径相对 plan.json 所在目录。"""
    for rel, text in inputs.datasets.items():
        path = folder / rel
        path.parent.mkdir(exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, data in inputs.files.items():
        path = folder / rel
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
