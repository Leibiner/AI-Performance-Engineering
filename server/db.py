"""SQLite：连接、建表、通用小工具。

FastAPI 的同步接口跑在线程池里，后台还有等待 k6 退出的线程，所以不共享连接：
每次操作新建一个连接，用完即关。配合 WAL 模式和 busy timeout，读写互不阻塞。
JSON 类字段存 TEXT，数值类字段用 NUMERIC（整数存整数，小数存小数）。
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS environments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    base_url         TEXT NOT NULL,
    headers          TEXT NOT NULL DEFAULT '{}',
    max_vus          NUMERIC NOT NULL,
    max_rate         NUMERIC NOT NULL,
    max_duration_sec NUMERIC NOT NULL,
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS apis (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    name                 TEXT NOT NULL,
    method               TEXT NOT NULL,
    path                 TEXT NOT NULL,
    headers              TEXT NOT NULL DEFAULT '{}',
    body                 TEXT,
    expect_status        INTEGER NOT NULL DEFAULT 200,
    expect_body_contains TEXT,
    extracts             TEXT NOT NULL DEFAULT '[]',
    note                 TEXT NOT NULL DEFAULT '',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS flows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    steps      TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS profiles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,
    model      TEXT NOT NULL,
    config     TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    flows      TEXT NOT NULL DEFAULT '[]',
    slo        TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    test_id        INTEGER,
    test_name      TEXT NOT NULL DEFAULT '',
    profile_id     INTEGER,
    profile_name   TEXT NOT NULL DEFAULT '',
    env_id         INTEGER,
    env_name       TEXT NOT NULL DEFAULT '',
    status         TEXT NOT NULL,
    verdict        TEXT,
    started_at     TEXT NOT NULL,
    ended_at       TEXT,
    exit_code      INTEGER,
    note           TEXT NOT NULL DEFAULT '',
    archived       INTEGER NOT NULL DEFAULT 0,
    stop_requested INTEGER NOT NULL DEFAULT 0,
    pid            INTEGER,
    summary        TEXT,
    snapshot       TEXT,
    record         TEXT
);
CREATE INDEX IF NOT EXISTS idx_runs_started ON runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_runs_test ON runs (test_id, started_at DESC);
"""

DEFINITION_TABLES = ("environments", "apis", "flows", "profiles", "tests")


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """新建一个连接；正常退出时提交，抛异常时回滚，最后一定关闭。"""
    conn = sqlite3.connect(config.DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> bool:
    """建表（幂等）。返回 True 表示这是一个全新的库，需要写入种子数据。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with connect() as conn:
        conn.execute("PRAGMA journal_mode=WAL")  # 写进库文件，之后的连接自动生效
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        conn.executescript(_SCHEMA)
        # 以后要改表结构：在这里按 version 逐级执行 ALTER，再把 user_version 调高
        fresh = version == 0 and all(
            conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in DEFINITION_TABLES
        )
    return fresh


def mark_initialized() -> None:
    with connect() as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def now_iso() -> str:
    """ISO 8601 UTC，毫秒精度，例如 2026-09-30T10:15:00.000Z。"""
    return iso(datetime.now(timezone.utc))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)
