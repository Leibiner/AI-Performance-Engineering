"""数据集（契约 §3.6）：只读的表格数据，第一行是表头，列名就是变量名；绑定在业务流程上。

CSV 只在这里解析（k6 没有非 experimental 的 CSV 模块，引擎里也解不了 GBK），存成规范的行：
rows 是 JSON 数组，每行一个字符串数组。运行和调试时由 plan.py 把用到的行写进运行目录交给 k6。
"""

import csv
import hashlib
import io
import json
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import Response

from . import db
from .errors import bad_request, not_found
from .files import attachment, decode_base64, fmt_size
from .validators import VAR_NAME_RULE, Checker, is_int, is_var_name

MAX_BYTES = 10 * 1024 * 1024
MAX_ROWS = 100_000
MAX_COLUMNS = 100
PREVIEW_ROWS = 100
BAD_ROWS_LISTED = 5
DELIMITERS = (",", "\t", ";")

# 默认单个字段最多 128 KiB；总量已经限制在 10 MiB 以内，单个字段不再另设上限
csv.field_size_limit(MAX_BYTES)

_META = "id, name, note, columns, row_count, sha256, source, created_at, updated_at"


# ---------- 解析 ----------

def _decode(raw: bytes) -> tuple[str | None, str | None]:
    """返回 (文本, source.encoding)。先去掉 UTF-8 BOM 按 UTF-8 严格解码，失败再按 GB18030（Excel 中文版另存的是 GBK）。"""
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        return (raw[3:] if bom else raw).decode("utf-8"), "utf-8-sig" if bom else "utf-8"
    except UnicodeDecodeError:
        pass
    try:
        return raw.decode("gb18030"), "gb18030"
    except UnicodeDecodeError:
        return None, None


def _detect_delimiter(text: str) -> str:
    """在第一个非空行里数 , \\t ; 的个数，取最多的；都没有或打平时用逗号。"""
    for line in io.StringIO(text, newline=""):
        if line.strip():
            counts = {d: line.count(d) for d in DELIMITERS}
            best = max(counts.values())
            winners = [d for d, n in counts.items() if n == best]
            return winners[0] if best > 0 and len(winners) == 1 else ","
    return ","


def _blank(record: list[str]) -> bool:
    """空行：csv 读出 []；只有空白的行读出一个全是空白的字段。"""
    return not record or (len(record) == 1 and not record[0].strip())


def parse_text(text: str) -> tuple[list[str], list[list[str]], str, list[str]]:
    """解析解码后的 CSV 文本。返回 (columns, rows, delimiter, problems)，problems 不为空时前两项无意义。"""
    delimiter = _detect_delimiter(text)
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, strict=True)
    header: list[str] | None = None
    rows: list[list[str]] = []
    bad: list[tuple[int, int]] = []  # (物理行号, 字段数)
    bad_total = 0
    problems: list[str] = []
    consumed = 0  # 已读过的物理行数；一条记录可能跨行（引号里的换行），行号取它开始的那一行
    try:
        for record in reader:
            line = consumed + 1
            consumed = reader.line_num
            if header is None:
                if not _blank(record):
                    header = [name.strip() for name in record]
                continue
            # 只有一列时，全是空白的一行就是这一行的值（原样保存），不当空行
            if not record or (len(header) > 1 and _blank(record)):
                continue
            if len(record) != len(header):
                bad_total += 1
                if len(bad) < BAD_ROWS_LISTED:
                    bad.append((line, len(record)))
                continue
            rows.append(record)
            if len(rows) > MAX_ROWS:
                problems.append(f"数据行超过 {MAX_ROWS} 行的上限")
                break
    except csv.Error as exc:
        problems.append(f"第 {reader.line_num} 行附近 CSV 格式不正确（{exc}）：检查引号是否成对，字段里的引号要写成两个 \"\"")
        return [], [], delimiter, problems

    if header is None:
        problems.append("没有内容：第一个非空行应该是表头（列名）")
        return [], [], delimiter, problems
    if len(header) > MAX_COLUMNS:
        # 误传了一个单行的大文件时表头可能有上百万列，逐列报问题会把响应和页面撑爆
        problems.append(f"表头有 {len(header)} 列，超过 {MAX_COLUMNS} 列的上限")
        return [], [], delimiter, problems
    seen: dict[str, int] = {}
    header_problems: list[str] = []
    for index, name in enumerate(header, 1):
        if not name:
            header_problems.append(f"表头第 {index} 列的列名为空")
        elif not is_var_name(name):
            header_problems.append(f"表头第 {index} 列的列名“{name}”不能用作变量名：{VAR_NAME_RULE}")
        elif name in seen:
            header_problems.append(f"表头第 {index} 列的列名 {name} 和第 {seen[name]} 列重复")
        else:
            seen[name] = index
    problems.extend(header_problems[:BAD_ROWS_LISTED])
    if len(header_problems) > BAD_ROWS_LISTED:
        problems.append(f"表头共有 {len(header_problems)} 列有问题，只列出前 {BAD_ROWS_LISTED} 列")
    for line, count in bad:
        problems.append(f"第 {line} 行有 {count} 个字段，和表头的 {len(header)} 列不一致")
    if bad_total > len(bad):
        problems.append(f"共有 {bad_total} 行字段数和表头不一致，只列出前 {BAD_ROWS_LISTED} 行")
    if not rows and not bad_total:
        problems.append("没有数据行：表头之后至少要有 1 行数据")
    return header, rows, delimiter, problems


def digest(columns: list[str], rows: list[list[str]]) -> str:
    """sha256：{"columns", "rows"} 按 UTF-8、紧凑 JSON 序列化后的摘要（契约 §3.6）。"""
    text = json.dumps({"columns": columns, "rows": rows}, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def parse_payload(payload: dict, problems: list[str], *, required: bool) -> dict | None:
    """取出请求体里的数据（csv，或 contentBase64 + fileName）并解析。

    两个都没给且 required 为 False 时返回 None（数据不变）；有问题时追加到 problems 并返回 None。
    """
    has_csv = payload.get("csv") is not None
    has_b64 = payload.get("contentBase64") is not None
    if has_csv and has_b64:
        problems.append("csv（CSV 文本）和 contentBase64（文件内容）只能给一个")
        return None
    if not has_csv and not has_b64:
        if required:
            problems.append("csv（CSV 文本）和 contentBase64（文件内容的 Base64）必须给一个")
        return None

    if has_csv:
        text = payload["csv"]
        if not isinstance(text, str):
            problems.append("csv 必须是字符串")
            return None
        text = text.removeprefix("﻿")
        source: dict[str, Any] = {"fileName": None, "encoding": "utf-8"}
    else:
        file_name = payload.get("fileName")
        if file_name is not None and not isinstance(file_name, str):
            problems.append("fileName 必须是字符串")
            return None
        raw, problem = decode_base64(payload["contentBase64"], "contentBase64", MAX_BYTES)
        if problem:
            problems.append(problem)
            return None
        text, encoding = _decode(raw)
        if text is None:
            problems.append("无法识别文件的编码：既不是 UTF-8，也不是 GB18030 / GBK")
            return None
        text = text.removeprefix("﻿")
        source = {"fileName": (file_name or "").strip() or None, "encoding": encoding}

    try:
        size = len(text.encode("utf-8"))
    except UnicodeEncodeError:
        problems.append("csv 里有无法编码为 UTF-8 的字符（不成对的代理项）")
        return None
    if size > MAX_BYTES:
        problems.append(f"数据按 UTF-8 计为 {fmt_size(size)}（{size} 字节），超过 {fmt_size(MAX_BYTES)} 的上限")
        return None

    columns, rows, delimiter, parse_problems = parse_text(text)
    source["delimiter"] = delimiter
    if parse_problems:
        problems.extend(parse_problems)
        return None
    return {"columns": columns, "rows": rows, "source": source, "sha256": digest(columns, rows)}


# ---------- 读写 ----------

def _usage(conn) -> dict[int, list[dict]]:
    """数据集 id → 绑定了它的业务流程。"""
    used: dict[int, list[dict]] = {}
    for row in conn.execute("SELECT id, name, datasets FROM flows ORDER BY id"):
        for binding in db.loads(row["datasets"]) or []:
            ds_id = binding.get("datasetId") if isinstance(binding, dict) else None
            if is_int(ds_id):
                used.setdefault(ds_id, []).append({"flowId": row["id"], "flowName": row["name"]})
    return used


def _to_obj(row, used: dict[int, list[dict]]) -> dict:
    return {
        "id": row["id"], "name": row["name"], "note": row["note"],
        "columns": json.loads(row["columns"]), "rowCount": row["row_count"], "sha256": row["sha256"],
        "source": json.loads(row["source"]), "usedBy": used.get(row["id"], []),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _detail(conn, item_id: int) -> dict:
    row = conn.execute(f"SELECT {_META}, rows FROM datasets WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise not_found(f"数据集 #{item_id} 不存在")
    obj = _to_obj(row, _usage(conn))
    obj["previewRows"] = json.loads(row["rows"])[:PREVIEW_ROWS]
    return obj


def _data_columns(parsed: dict) -> tuple:
    return (
        db.dumps(parsed["columns"]),
        json.dumps(parsed["rows"], ensure_ascii=False, separators=(",", ":")),
        len(parsed["rows"]),
        parsed["sha256"],
        db.dumps(parsed["source"]),
    )


def load_many(conn, ids, cache: dict[int, dict] | None = None) -> dict[int, dict]:
    """运行和调试用：元数据和全部行在一条语句里取出，保证 sha256 和写进运行目录的行是同一版。

    rowsJson 是库里存的紧凑 JSON 文本，正式运行原样写进运行目录。cache 让同一个数据集在一次组装里只取一次。
    """
    cache = {} if cache is None else cache
    out: dict[int, dict] = {}
    for ds_id in ids:
        if not is_int(ds_id):
            continue
        if ds_id not in cache:
            row = conn.execute(
                "SELECT id, name, columns, row_count, sha256, rows FROM datasets WHERE id = ?", (ds_id,)
            ).fetchone()
            if row is None:
                continue
            cache[ds_id] = {
                "id": row["id"], "name": row["name"], "columns": json.loads(row["columns"]),
                "rowCount": row["row_count"], "sha256": row["sha256"], "rowsJson": row["rows"],
            }
        out[ds_id] = cache[ds_id]
    return out


def binding_problems(flow_name: str, bindings: list[dict], variables: list[dict]) -> list[str]:
    """预检第 9 条里和负载无关的部分。数据集在绑定之后可以整体替换数据，所以保存流程时校验过的这里还要再查一遍。"""
    problems: list[str] = []
    owners: dict[str, str] = {}
    for binding in bindings:
        ds = binding["dataset"]
        if ds["rowCount"] < 1:
            problems.append(f"业务流程“{flow_name}”绑定的数据集“{ds['name']}”没有数据行")
        for column in ds["columns"]:
            if column in owners:
                problems.append(
                    f"业务流程“{flow_name}”绑定的数据集“{owners[column]}”和“{ds['name']}”都有列 {column}，"
                    "同一流程绑定的数据集列名不能重复"
                )
            else:
                owners[column] = ds["name"]
    for var in variables:
        if var["name"] in owners:
            problems.append(f"业务流程“{flow_name}”的流程变量 {var['name']} 和数据集“{owners[var['name']]}”的列重名")
    return problems


# ---------- 路由 ----------

router = APIRouter(prefix="/api/datasets", tags=["数据集"])


@router.get("", summary="数据集列表（不含行数据）")
def list_datasets():
    with db.connect() as conn:
        used = _usage(conn)
        return [_to_obj(row, used) for row in conn.execute(f"SELECT {_META} FROM datasets ORDER BY id").fetchall()]


@router.post("/preview", summary="只解析不保存")
def preview_dataset(payload: Any = Body(...)):
    if not isinstance(payload, dict):
        raise bad_request("请求体必须是 JSON 对象")
    problems: list[str] = []
    parsed = parse_payload(payload, problems, required=True)
    if parsed is None:
        raise bad_request("数据解析失败", problems)
    return {
        "columns": parsed["columns"], "rowCount": len(parsed["rows"]),
        "previewRows": parsed["rows"][:PREVIEW_ROWS], "source": parsed["source"],
    }


@router.post("", status_code=201, summary="新建数据集")
def create_dataset(payload: Any = Body(...)):
    c = Checker(payload)
    name, note = c.name(), c.note()
    parsed = parse_payload(payload, c.errors, required=True)
    c.done()
    assert parsed is not None
    now = db.now_iso()
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO datasets (name, note, columns, rows, row_count, sha256, source, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (name, note, *_data_columns(parsed), now, now),
        )
        return _detail(conn, int(cur.lastrowid))


@router.get("/{item_id}", summary="数据集详情（含前 100 行）")
def get_dataset(item_id: int):
    with db.connect() as conn:
        return _detail(conn, item_id)


@router.put("/{item_id}", summary="改名称、备注，或整体替换数据")
def replace_dataset(item_id: int, payload: Any = Body(...)):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM datasets WHERE id = ?", (item_id,)).fetchone() is None:
            raise not_found(f"数据集 #{item_id} 不存在")
    c = Checker(payload)
    name, note = c.name(), c.note()
    parsed = parse_payload(payload, c.errors, required=False)
    c.done()
    with db.connect() as conn:
        if parsed is None:
            cur = conn.execute(
                "UPDATE datasets SET name = ?, note = ?, updated_at = ? WHERE id = ?",
                (name, note, db.now_iso(), item_id),
            )
        else:
            cur = conn.execute(
                "UPDATE datasets SET name = ?, note = ?, columns = ?, rows = ?, row_count = ?, sha256 = ?, source = ?, "
                "updated_at = ? WHERE id = ?",
                (name, note, *_data_columns(parsed), db.now_iso(), item_id),
            )
        if cur.rowcount == 0:
            raise not_found(f"数据集 #{item_id} 不存在")
        return _detail(conn, item_id)


@router.delete("/{item_id}", summary="删除数据集")
def delete_dataset(item_id: int):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM datasets WHERE id = ?", (item_id,)).fetchone() is None:
            raise not_found(f"数据集 #{item_id} 不存在")
        # 被流程绑定也可以删：那些绑定变成失效绑定，流程在修好之前不能试跑和运行（契约 §3.6）
        conn.execute("DELETE FROM datasets WHERE id = ?", (item_id,))
    return {"ok": True}


@router.get("/{item_id}/csv", summary="导出 CSV（UTF-8 带 BOM）")
def export_csv(item_id: int, download: str | None = None):
    with db.connect() as conn:
        row = conn.execute("SELECT id, name, columns, rows FROM datasets WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise not_found(f"数据集 #{item_id} 不存在")
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(json.loads(row["columns"]))
    writer.writerows(json.loads(row["rows"]))
    headers = {"Cache-Control": "no-store"}
    if download and download.strip().lower() in ("1", "true"):
        headers["Content-Disposition"] = attachment(f"{row['name']}.csv", f"dataset-{row['id']}.csv")
    # BOM 让 Excel 按 UTF-8 打开
    content = ("﻿" + buf.getvalue()).encode("utf-8")
    return Response(content=content, media_type="text/csv; charset=utf-8", headers=headers)
