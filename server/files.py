"""文件（契约 §3.7）：接口 multipart 请求体里引用的文件。

内容存库（BLOB），运行和调试时复制进运行目录交给 k6（plan.py）。上传走 JSON + Base64，不用 multipart。
"""

import base64
import binascii
import hashlib
import mimetypes
import os
import re
import unicodedata
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Body
from fastapi.responses import Response

from . import db, references
from .errors import not_found
from .validators import Checker, is_int

MAX_BYTES = 10 * 1024 * 1024
NAME_MAX = 200
DEFAULT_CONTENT_TYPE = "application/octet-stream"

_META = "id, name, content_type, size, sha256, note, created_at, updated_at"
_CONTENT_TYPE_RE = re.compile(r"[\w.+-]+/[\w.+-]+(?:[ \t]*;[ -~]*)?", re.ASCII)  # 不能用 \s：会放过 \r \n，注入分段头
_ASCII_NAME_RE = re.compile(r"[A-Za-z0-9._ ()+-]+")


# ---------- 小工具（数据集也用） ----------

def fmt_size(n: int | float) -> str:
    """按 1024 进制给出人能读的大小，例如 12.3 MiB。"""
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024 or unit == "GiB":
            return f"{f'{n:.1f}'.removesuffix('.0')} {unit}"
        n /= 1024
    return ""


def decode_base64(value: Any, label: str, limit: int = MAX_BYTES) -> tuple[bytes | None, str | None]:
    """严格解码 Base64（允许夹带换行等空白）。返回 (内容, 问题)，有问题时内容为 None。"""
    if not isinstance(value, str):
        return None, f"{label} 必须是字符串（文件内容的 Base64）"
    compact = re.sub(r"\s+", "", value)
    # 先按长度估算，明显超限时不必真的解码
    if len(compact) // 4 * 3 - 2 > limit:
        return None, f"{label} 解码后超过 {fmt_size(limit)} 的上限"
    try:
        data = base64.b64decode(compact, validate=True)
    except (binascii.Error, ValueError):
        return None, f"{label} 不是合法的 Base64"
    if len(data) > limit:
        return None, f"{label} 解码后为 {fmt_size(len(data))}（{len(data)} 字节），超过 {fmt_size(limit)} 的上限"
    return data, None


def attachment(filename: str, fallback: str) -> str:
    """附件下载的 Content-Disposition：filename* 按 RFC 5987 带 UTF-8 文件名，filename 给只含 ASCII 的后备名。"""
    plain = filename if _ASCII_NAME_RE.fullmatch(filename) else fallback
    return f"attachment; filename=\"{plain}\"; filename*=UTF-8''{quote(filename, safe='')}"


# ---------- 读写 ----------

def _usage(conn) -> dict[int, list[dict]]:
    """文件 id → 引用了它的对象（标准格式，契约 §3.8）。"""
    return references.used_by(conn, "file")


def _to_obj(row, used: dict[int, list[dict]]) -> dict:
    return {
        "id": row["id"], "name": row["name"], "contentType": row["content_type"], "size": row["size"],
        "sha256": row["sha256"], "note": row["note"], "usedBy": used.get(row["id"], []),
        "createdAt": row["created_at"], "updatedAt": row["updated_at"],
    }


def _get(conn, item_id: int) -> dict:
    row = conn.execute(f"SELECT {_META} FROM files WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise not_found(f"文件 #{item_id} 不存在")
    return _to_obj(row, _usage(conn))


def _validate(payload: Any, *, creating: bool) -> dict:
    c = Checker(payload)
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip():
        c.err("name（文件名）必填，且不能为空")
        name = ""
    else:
        name = name.strip()
        if len(name) > NAME_MAX:
            c.err(f"name（文件名）不能超过 {NAME_MAX} 个字符")
        if "/" in name or "\\" in name:
            c.err("name（文件名）不能包含 / 和 \\")
        if any(unicodedata.category(ch) == "Cc" for ch in name):
            c.err("name（文件名）不能包含控制字符")

    content_type = payload.get("contentType")
    if content_type is None or (isinstance(content_type, str) and not content_type.strip()):
        content_type = mimetypes.guess_type(name)[0] or DEFAULT_CONTENT_TYPE
    elif not isinstance(content_type, str):
        c.err("contentType 必须是字符串；省略时按文件名的扩展名推断")
    else:
        content_type = content_type.strip()
        # 它会原样进响应头和 multipart 的 Content-Type，只接受 ASCII 的 type/subtype[; 参数]
        if len(content_type) > NAME_MAX or not _CONTENT_TYPE_RE.fullmatch(content_type):
            c.err("contentType 不是合法的媒体类型，例如 image/png、application/pdf")

    note = c.note()
    content = None
    raw = payload.get("contentBase64")
    if raw is None:
        if creating:
            c.err("contentBase64（文件内容的 Base64）必填；0 字节的文件传空字符串")
    else:
        content, problem = decode_base64(raw, "contentBase64")
        if problem:
            c.err(problem)
    c.done()
    return {"name": name, "contentType": content_type, "note": note, "content": content}


def load_many(conn, ids) -> dict[int, dict]:
    """运行和调试用：元数据和内容在一条语句里取出，保证 sha256、size 和写进运行目录的内容是同一版。"""
    out: dict[int, dict] = {}
    for file_id in ids:
        if file_id in out or not is_int(file_id):
            continue
        row = conn.execute(
            "SELECT id, name, content_type, size, sha256, data FROM files WHERE id = ?", (file_id,)
        ).fetchone()
        if row is not None:
            out[file_id] = {
                "id": row["id"], "name": row["name"], "contentType": row["content_type"],
                "size": row["size"], "sha256": row["sha256"], "data": bytes(row["data"]),
            }
    return out


def load_for_steps(conn, apis: list[dict]) -> tuple[dict[int, dict], list[str]]:
    """步骤里 multipart 请求体引用的文件（只有 multipart 会发送文件）。返回 (取到的文件, 不存在的逐条原因)。"""
    wanted: list[tuple[dict, Any]] = []
    for api in apis:
        if api.get("bodyType") != "multipart":
            continue
        for item in api.get("form") or []:
            if item.get("type") == "file":
                wanted.append((api, item.get("fileId")))
    loaded = load_many(conn, [file_id for _, file_id in wanted])
    problems: list[str] = []
    lookup = references.Lookup(conn)
    for api in apis:
        if api.get("bodyType") != "multipart":
            continue
        for problem in references.broken_messages(lookup, "api", api, api["name"]):
            if problem not in problems:
                problems.append(problem)
    return loaded, problems


# ---------- 路由 ----------

router = APIRouter(prefix="/api/files", tags=["文件"])


@router.get("", summary="文件列表（只有元数据）")
def list_files():
    with db.connect() as conn:
        used = _usage(conn)
        return [_to_obj(row, used) for row in conn.execute(f"SELECT {_META} FROM files ORDER BY id").fetchall()]


@router.post("", status_code=201, summary="上传文件")
def create_file(payload: Any = Body(...)):
    data = _validate(payload, creating=True)
    content = data["content"]
    now = db.now_iso()
    with db.connect() as conn:
        cur = conn.execute(
            "INSERT INTO files (name, content_type, size, sha256, data, note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (data["name"], data["contentType"], len(content), hashlib.sha256(content).hexdigest(),
             content, data["note"], now, now),
        )
        return _get(conn, int(cur.lastrowid))


@router.get("/{item_id}", summary="文件元数据")
def get_file(item_id: int):
    with db.connect() as conn:
        return _get(conn, item_id)


@router.get("/{item_id}/content", summary="文件内容")
def get_file_content(item_id: int, download: str | None = None):
    with db.connect() as conn:
        row = conn.execute("SELECT id, name, content_type, data FROM files WHERE id = ?", (item_id,)).fetchone()
    if row is None:
        raise not_found(f"文件 #{item_id} 不存在")
    headers = {
        "Content-Type": row["content_type"],
        "Cache-Control": "no-store",
        # 用户上传的 HTML / SVG 直接在本站打开时不能执行脚本
        "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "sandbox",
    }
    if download and download.strip().lower() in ("1", "true"):
        ext = os.path.splitext(row["name"])[1]
        fallback = f"file-{row['id']}{ext if _ASCII_NAME_RE.fullmatch(ext or 'x') else ''}"
        headers["Content-Disposition"] = attachment(row["name"], fallback)
    return Response(content=bytes(row["data"]), headers=headers)


@router.put("/{item_id}", summary="修改文件名、类型、备注或替换内容")
def replace_file(item_id: int, payload: Any = Body(...)):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM files WHERE id = ?", (item_id,)).fetchone() is None:
            raise not_found(f"文件 #{item_id} 不存在")
    data = _validate(payload, creating=False)
    content = data["content"]
    with db.connect() as conn:
        if content is None:
            cur = conn.execute(
                "UPDATE files SET name = ?, content_type = ?, note = ?, updated_at = ? WHERE id = ?",
                (data["name"], data["contentType"], data["note"], db.now_iso(), item_id),
            )
        else:
            cur = conn.execute(
                "UPDATE files SET name = ?, content_type = ?, note = ?, size = ?, sha256 = ?, data = ?, updated_at = ? "
                "WHERE id = ?",
                (data["name"], data["contentType"], data["note"], len(content),
                 hashlib.sha256(content).hexdigest(), content, db.now_iso(), item_id),
            )
        if cur.rowcount == 0:
            raise not_found(f"文件 #{item_id} 不存在")
        return _get(conn, item_id)


@router.delete("/{item_id}", summary="删除文件")
def delete_file(item_id: int):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM files WHERE id = ?", (item_id,)).fetchone() is None:
            raise not_found(f"文件 #{item_id} 不存在")
        # 被接口引用也可以删：那些文件项变成失效引用，接口在修好之前不能以 form-data 发送（契约 §3.7）
        conn.execute("DELETE FROM files WHERE id = ?", (item_id,))
    return {"ok": True}

