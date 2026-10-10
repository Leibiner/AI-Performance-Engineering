"""定义类资源（环境、文件夹、接口、业务流程、施压配置、测试）的统一增删改查（契约 §3.1）。

数据集和文件的写入方式不同（上传、解析），在 datasets.py、files.py。
"""

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter, Body

from . import db, references, validators
from .errors import conflict, not_found


@dataclass(frozen=True)
class Field:
    name: str  # JSON 里的字段名（camelCase）
    column: str  # 表里的列名
    json: bool = False  # 是否以 JSON 文本存储


@dataclass(frozen=True)
class Resource:
    name: str  # 路径和表名
    label: str  # 中文名，用在提示里
    fields: tuple[Field, ...]
    validate: Callable[[Any, sqlite3.Connection], dict]
    decorate: Callable[[list[dict], sqlite3.Connection], None] | None = None  # GET 时附加只读字段
    guard_delete: Callable[[int, sqlite3.Connection], None] | None = None  # 被引用时抛 409


# ---------- 读写 ----------

def _to_obj(res: Resource, row: sqlite3.Row) -> dict:
    obj: dict[str, Any] = {"id": row["id"]}
    for f in res.fields:
        value = row[f.column]
        obj[f.name] = db.loads(value) if f.json else value
    obj["createdAt"] = row["created_at"]
    obj["updatedAt"] = row["updated_at"]
    return obj


def _encode(res: Resource, data: dict) -> list:
    return [db.dumps(data[f.name]) if f.json else data[f.name] for f in res.fields]


def list_objs(conn: sqlite3.Connection, res: Resource) -> list[dict]:
    rows = conn.execute(f"SELECT * FROM {res.name} ORDER BY id").fetchall()
    return [_to_obj(res, r) for r in rows]


def get_obj(conn: sqlite3.Connection, res: Resource, item_id: Any) -> dict | None:
    """按 id 取一条（不带只读的展示字段）；不存在返回 None。"""
    if not validators.is_int(item_id):
        return None
    row = conn.execute(f"SELECT * FROM {res.name} WHERE id = ?", (item_id,)).fetchone()
    return _to_obj(res, row) if row else None


def insert(conn: sqlite3.Connection, res: Resource, data: dict) -> int:
    now = db.now_iso()
    columns = [f.column for f in res.fields] + ["created_at", "updated_at"]
    marks = ", ".join("?" for _ in columns)
    cur = conn.execute(
        f"INSERT INTO {res.name} ({', '.join(columns)}) VALUES ({marks})",
        _encode(res, data) + [now, now],
    )
    return int(cur.lastrowid)


def _update(conn: sqlite3.Connection, res: Resource, item_id: int, data: dict) -> None:
    sets = ", ".join(f"{f.column} = ?" for f in res.fields)
    conn.execute(
        f"UPDATE {res.name} SET {sets}, updated_at = ? WHERE id = ?",
        _encode(res, data) + [db.now_iso(), item_id],
    )


def _require(conn: sqlite3.Connection, res: Resource, item_id: int) -> dict:
    obj = get_obj(conn, res, item_id)
    if obj is None:
        raise not_found(f"{res.label} #{item_id} 不存在")
    return obj


def _decorated(conn: sqlite3.Connection, res: Resource, objs: list[dict]) -> list[dict]:
    if res.decorate:
        res.decorate(objs, conn)
    return objs


# ---------- 各资源特有的逻辑 ----------

def _decorate_flows(flows: list[dict], conn: sqlite3.Connection) -> None:
    apis = {r["id"]: r for r in conn.execute("SELECT id, name, method, path FROM apis")}
    datasets = {r["id"]: r for r in conn.execute("SELECT id, name, columns, row_count FROM datasets")}
    for flow in flows:
        for step in flow["initSteps"] + flow["steps"]:
            api = apis.get(step["apiId"])
            step["apiName"] = api["name"] if api else None
            step["method"] = api["method"] if api else None
            step["path"] = api["path"] if api else None
        for binding in flow["datasets"]:
            ds = datasets.get(binding["datasetId"])
            binding["datasetName"] = ds["name"] if ds else None
            binding["columns"] = db.loads(ds["columns"]) if ds else None
            binding["rowCount"] = ds["row_count"] if ds else None
    _attach_references(conn, "flow", flows)


def _decorate_apis(apis: list[dict], conn: sqlite3.Connection) -> None:
    _attach_references(conn, "api", apis)


def _attach_references(conn: sqlite3.Connection, kind: str, objs: list[dict]) -> None:
    """标准的引用字段（契约 §3.8）：usedBy 谁引用了它；brokenRefs 它引用的对象里哪些已被删除。"""
    used = references.used_by(conn, kind)
    lookup = references.Lookup(conn)
    owner = any(rel.owner == kind for rel in references.RELATIONS)
    for obj in objs:
        obj["usedBy"] = used.get(obj["id"], [])
        if owner:
            obj["brokenRefs"] = references.broken_in(lookup, kind, obj)


def _decorate_tests(tests: list[dict], conn: sqlite3.Connection) -> None:
    _attach_references(conn, "test", tests)
    names = {r["id"]: r["name"] for r in conn.execute("SELECT id, name FROM flows")}
    for test in tests:
        for item in test["flows"]:
            item["flowName"] = names.get(item["flowId"])
        row = conn.execute(
            "SELECT run_id, verdict, started_at FROM runs WHERE test_id = ? "
            "ORDER BY started_at DESC, run_id DESC LIMIT 1",
            (test["id"],),
        ).fetchone()
        test["lastRun"] = (
            {"runId": row["run_id"], "verdict": row["verdict"], "startedAt": row["started_at"]} if row else None
        )


def _guard_folder_delete(folder_id: int, conn: sqlite3.Connection) -> None:
    """非空的文件夹不能删：先把里面的子文件夹和接口移走或删掉。"""
    used = [f"子文件夹“{r['name']}”（#{r['id']}）" for r in conn.execute("SELECT id, name FROM folders WHERE parent_id = ?", (folder_id,))]
    used += [f"接口“{r['name']}”（#{r['id']}）" for r in conn.execute("SELECT id, name FROM apis WHERE folder_id = ?", (folder_id,))]
    if used:
        raise conflict("该文件夹不是空的，不能删除。请先把里面的内容移走或删除", used)


ENVIRONMENTS = Resource(
    name="environments",
    label="被测环境",
    fields=(
        Field("name", "name"),
        Field("type", "type"),
        Field("baseUrl", "base_url"),
        Field("headers", "headers", json=True),
        Field("variables", "variables", json=True),
        Field("maxVus", "max_vus"),
        Field("maxRate", "max_rate"),
        Field("maxDurationSec", "max_duration_sec"),
        Field("note", "note"),
    ),
    validate=validators.validate_environment,
)

FOLDERS = Resource(
    name="folders",
    label="文件夹",
    fields=(Field("name", "name"), Field("parentId", "parent_id"), Field("note", "note")),
    validate=validators.validate_folder,
    guard_delete=_guard_folder_delete,
)

APIS = Resource(
    name="apis",
    label="接口",
    fields=(
        Field("folderId", "folder_id"),
        Field("name", "name"),
        Field("method", "method"),
        Field("path", "path"),
        Field("headers", "headers", json=True),
        Field("bodyType", "body_type"),
        Field("body", "body"),
        Field("form", "form", json=True),
        Field("expectStatus", "expect_status"),
        Field("expectBodyContains", "expect_body_contains"),
        Field("extracts", "extracts", json=True),
        Field("note", "note"),
    ),
    validate=validators.validate_api,
    decorate=_decorate_apis,
)

FLOWS = Resource(
    name="flows",
    label="业务流程",
    fields=(
        Field("name", "name"),
        Field("note", "note"),
        Field("datasets", "datasets", json=True),
        Field("variables", "variables", json=True),
        Field("initSteps", "init_steps", json=True),
        Field("reinitSec", "reinit_sec"),
        Field("steps", "steps", json=True),
    ),
    validate=validators.validate_flow,
    decorate=_decorate_flows,
)

PROFILES = Resource(
    name="profiles",
    label="施压配置",
    fields=(
        Field("name", "name"),
        Field("type", "type"),
        Field("model", "model"),
        Field("config", "config", json=True),
        Field("note", "note"),
    ),
    validate=validators.validate_profile,
)

TESTS = Resource(
    name="tests",
    label="测试",
    fields=(
        Field("name", "name"),
        Field("note", "note"),
        Field("flows", "flows", json=True),
        Field("slo", "slo", json=True),
    ),
    validate=validators.validate_test,
    decorate=_decorate_tests,
)

RESOURCES = (ENVIRONMENTS, FOLDERS, APIS, FLOWS, PROFILES, TESTS)


# ---------- 路由 ----------

def _build_router(res: Resource) -> APIRouter:
    router = APIRouter(prefix=f"/api/{res.name}", tags=[res.label])

    @router.get("", summary=f"{res.label}列表")
    def list_items():
        with db.connect() as conn:
            return _decorated(conn, res, list_objs(conn, res))

    @router.post("", status_code=201, summary=f"新建{res.label}")
    def create_item(payload: Any = Body(...)):
        with db.connect() as conn:
            data = res.validate(payload, conn)
            item_id = insert(conn, res, data)
            return _decorated(conn, res, [_require(conn, res, item_id)])[0]

    @router.get("/{item_id}", summary=f"{res.label}详情")
    def get_item(item_id: int):
        with db.connect() as conn:
            return _decorated(conn, res, [_require(conn, res, item_id)])[0]

    @router.put("/{item_id}", summary=f"整体替换{res.label}")
    def replace_item(item_id: int, payload: Any = Body(...)):
        # 让校验器知道正在改的是哪一条（文件夹要据此防止把自己放到自己下面）；多余字段校验器本来就忽略
        if isinstance(payload, dict):
            payload = {**payload, "id": item_id}
        with db.connect() as conn:
            _require(conn, res, item_id)
            data = res.validate(payload, conn)
            _update(conn, res, item_id, data)
            return _decorated(conn, res, [_require(conn, res, item_id)])[0]

    @router.delete("/{item_id}", summary=f"删除{res.label}")
    def delete_item(item_id: int):
        with db.connect() as conn:
            _require(conn, res, item_id)
            if res.guard_delete:
                res.guard_delete(item_id, conn)
            conn.execute(f"DELETE FROM {res.name} WHERE id = ?", (item_id,))
        return {"ok": True}

    return router


routers = [_build_router(res) for res in RESOURCES]
