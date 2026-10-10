"""定义之间的引用（契约 §3.8）。

所有引用关系只在 RELATIONS 里登记一次：谁（引用方）的哪个字段引用了谁（被引用方）、引用的位置怎么称呼。
反向引用（usedBy）、失效引用（brokenRefs）、删除影响（GET /api/references/:kind/:id）、
预检里"已被删除"的提示都由它生成，各资源不再各写各的。

每个对象可以单独删除，被引用不挡删除、也不级联；引用它的地方保留原 id，成为失效引用。
"""

from dataclasses import dataclass
from typing import Any, Callable

from fastapi import APIRouter

from . import db
from .errors import not_found

# 种类 → (中文名, 表名)
KINDS: dict[str, tuple[str, str]] = {
    "api": ("接口", "apis"),
    "flow": ("业务流程", "flows"),
    "test": ("测试", "tests"),
    "dataset": ("数据集", "datasets"),
    "file": ("文件", "files"),
}


@dataclass(frozen=True)
class Relation:
    owner: str  # 引用方的种类
    target: str  # 被引用方的种类
    field: str  # 引用方对象里的字段（camelCase）
    column: str  # 引用方表里的列（JSON）
    refs: Callable[[Any], list[tuple[Any, str]]]  # 字段的值 → [(被引用的 id, 位置)]


def _items(value: Any) -> list[tuple[int, dict]]:
    return [(i, item) for i, item in enumerate(value or [], 1) if isinstance(item, dict)]


RELATIONS: tuple[Relation, ...] = (
    Relation("flow", "api", "initSteps", "init_steps",
             lambda v: [(s.get("apiId"), f"初始化第 {i} 步") for i, s in _items(v)]),
    Relation("flow", "api", "steps", "steps",
             lambda v: [(s.get("apiId"), f"第 {i} 步") for i, s in _items(v)]),
    Relation("flow", "dataset", "datasets", "datasets",
             lambda v: [(b.get("datasetId"), f"数据集绑定第 {i} 项") for i, b in _items(v)]),
    Relation("test", "flow", "flows", "flows",
             lambda v: [(f.get("flowId"), f"第 {i} 个流程") for i, f in _items(v)]),
    Relation("api", "file", "form", "form",
             lambda v: [(f.get("fileId"), f"表单第 {i} 项") for i, f in _items(v)
                        if f.get("type") == "file" and f.get("fileId") is not None]),
)


def label(kind: str) -> str:
    return KINDS[kind][0]


def missing_message(owner: str, owner_name: str, where: str, target: str, target_id: Any) -> str:
    """失效引用的标准提示：在哪、引用了谁、怎么修。预检、试跑、发送共用。"""
    t = label(target)
    return f"{label(owner)}“{owner_name}”{where}引用的{t} #{target_id} 已被删除（失效引用）：换一个{t}，或移除这一项"


class Lookup:
    """一次请求里按需查出各种类现存的 id，避免每个对象查一次库。"""

    def __init__(self, conn):
        self.conn = conn
        self._ids: dict[str, set[int]] = {}

    def exists(self, kind: str, item_id: Any) -> bool:
        if kind not in self._ids:
            self._ids[kind] = {row[0] for row in self.conn.execute(f"SELECT id FROM {KINDS[kind][1]}")}
        return item_id in self._ids[kind]


def _grouped(pairs: list[tuple[str, Any, str]]) -> list[dict]:
    """[(种类, id, 位置)] → 按 (种类, id) 合并位置，保持出现顺序。"""
    out: dict[tuple[str, Any], list[str]] = {}
    for kind, item_id, where in pairs:
        out.setdefault((kind, item_id), []).append(where)
    return [{"kind": kind, "id": item_id, "where": wheres} for (kind, item_id), wheres in out.items()]


def broken_in(lookup: Lookup, owner: str, obj: dict) -> list[dict]:
    """一个引用方对象（camelCase 字段）里指向已删除对象的引用：[{kind, id, where: [位置]}]。"""
    pairs = [
        (rel.target, target_id, where)
        for rel in RELATIONS if rel.owner == owner
        for target_id, where in rel.refs(obj.get(rel.field))
        if not lookup.exists(rel.target, target_id)
    ]
    return _grouped(pairs)


def broken_messages(lookup: Lookup, owner: str, obj: dict, owner_name: str) -> list[str]:
    return [
        missing_message(owner, owner_name, where, ref["kind"], ref["id"])
        for ref in broken_in(lookup, owner, obj)
        for where in ref["where"]
    ]


def used_by(conn, target: str) -> dict[Any, list[dict]]:
    """被引用方的 id → 引用了它的对象 [{kind, id, name, where: [位置]}]，按引用方种类和 id 排序。"""
    out: dict[Any, list[dict]] = {}
    owners = sorted({rel.owner for rel in RELATIONS if rel.target == target}, key=list(KINDS).index)
    for owner in owners:
        rels = [rel for rel in RELATIONS if rel.owner == owner and rel.target == target]
        columns = ", ".join(rel.column for rel in rels)
        for row in conn.execute(f"SELECT id, name, {columns} FROM {KINDS[owner][1]} ORDER BY id"):
            wheres: dict[Any, list[str]] = {}
            for rel in rels:
                for target_id, where in rel.refs(db.loads(row[rel.column])):
                    wheres.setdefault(target_id, []).append(where)
            for target_id, places in wheres.items():
                out.setdefault(target_id, []).append({"kind": owner, "id": row["id"], "name": row["name"], "where": places})
    return out


def impact(conn, kind: str, item_id: int) -> dict:
    """删除一个对象会让哪些引用失效：直接引用它的对象，以及间接依赖这些对象的（例如接口 → 流程 → 测试）。"""
    row = conn.execute(f"SELECT name FROM {KINDS[kind][1]} WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise not_found(f"{label(kind)} #{item_id} 不存在")
    cache: dict[str, dict[Any, list[dict]]] = {}

    def users(k: str, i: Any, depth: int) -> list[dict]:
        if depth > len(KINDS):  # 引用关系是有向无环的，这只是兜底
            return []
        if k not in cache:
            cache[k] = used_by(conn, k)
        return [{**u, "usedBy": users(u["kind"], u["id"], depth + 1)} for u in cache[k].get(i, [])]

    return {"kind": kind, "id": item_id, "name": row["name"], "usedBy": users(kind, item_id, 1)}


router = APIRouter(prefix="/api/references", tags=["引用"])


@router.get("/{kind}/{item_id}", summary="删除影响：哪些对象引用了它（含间接的）")
def get_impact(kind: str, item_id: int):
    if kind not in KINDS:
        raise not_found(f"不认识的种类 {kind}，可以是 " + "、".join(KINDS))
    with db.connect() as conn:
        return impact(conn, kind, item_id)
