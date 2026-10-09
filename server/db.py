"""SQLite：连接、建表、版本迁移、通用小工具。

FastAPI 的同步接口跑在线程池里，后台还有等待 k6 退出的线程，所以不共享连接：
每次操作新建一个连接，用完即关。配合 WAL 模式和 busy timeout，读写互不阻塞。
JSON 类字段存 TEXT，数值类字段用 NUMERIC（整数存整数，小数存小数）。

表结构版本记在 `PRAGMA user_version`：
  1  最初的六张表
  2  environments 增加 type、三个安全上限可为空；新增 executors；runs 增加 env_type、executor_id、executor_name
  3  新增 folders（接口文件夹，可嵌套）；apis 增加 folder_id
  4  environments 增加 variables（环境变量的初始值）
全新的库直接建成最新结构；旧库在启动时逐级迁移，迁移前先备份，整个迁移在一个事务里。
"""

import json
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

log = logging.getLogger("uvicorn.error")

SCHEMA_VERSION = 4

LOCAL_EXECUTOR_NAME = "本机执行机"


def _environments_ddl(table: str = "environments") -> str:
    # 迁移时要用另一个表名重建，所以表名是参数
    return f"""
CREATE TABLE IF NOT EXISTS {table} (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    type             TEXT NOT NULL DEFAULT 'test',
    base_url         TEXT NOT NULL,
    headers          TEXT NOT NULL DEFAULT '{{}}',
    variables        TEXT NOT NULL DEFAULT '{{}}',
    max_vus          NUMERIC,
    max_rate         NUMERIC,
    max_duration_sec NUMERIC,
    note             TEXT NOT NULL DEFAULT '',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
)"""


_EXECUTORS_DDL = """
CREATE TABLE IF NOT EXISTS executors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    kind       TEXT NOT NULL DEFAULT 'local',
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

_FOLDERS_DDL = """
CREATE TABLE IF NOT EXISTS folders (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    parent_id  INTEGER,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)"""

# 最新结构。全部是 IF NOT EXISTS，每次启动执行一遍
_SCHEMA = [
    _environments_ddl(),
    _EXECUTORS_DDL,
    _FOLDERS_DDL,
    """
CREATE TABLE IF NOT EXISTS apis (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    folder_id            INTEGER,
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
)""",
    """
CREATE TABLE IF NOT EXISTS flows (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    steps      TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS profiles (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    type       TEXT NOT NULL,
    model      TEXT NOT NULL,
    config     TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS tests (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    note       TEXT NOT NULL DEFAULT '',
    flows      TEXT NOT NULL DEFAULT '[]',
    slo        TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
)""",
    """
CREATE TABLE IF NOT EXISTS runs (
    run_id         TEXT PRIMARY KEY,
    test_id        INTEGER,
    test_name      TEXT NOT NULL DEFAULT '',
    profile_id     INTEGER,
    profile_name   TEXT NOT NULL DEFAULT '',
    env_id         INTEGER,
    env_name       TEXT NOT NULL DEFAULT '',
    env_type       TEXT,
    executor_id    INTEGER,
    executor_name  TEXT NOT NULL DEFAULT '',
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
)""",
    "CREATE INDEX IF NOT EXISTS idx_runs_started ON runs (started_at DESC)",
    "CREATE INDEX IF NOT EXISTS idx_runs_test ON runs (test_id, started_at DESC)",
]

DEFINITION_TABLES = ("environments", "folders", "apis", "flows", "profiles", "tests")


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


# ---------- 建表与迁移 ----------

def _has_table(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def guess_env_type(base_url: Any) -> str:
    """旧数据没有被测环境类型：地址里带 baidu.com 的算生产，其余按测试环境处理。"""
    return "prod" if isinstance(base_url, str) and "baidu.com" in base_url.lower() else "test"


def _ensure_local_executor(conn: sqlite3.Connection) -> int:
    """保证有一条本机执行机，返回它的 id。"""
    row = conn.execute("SELECT id FROM executors WHERE kind = 'local' ORDER BY id LIMIT 1").fetchone()
    if row:
        return int(row[0])
    now = now_iso()
    cur = conn.execute(
        "INSERT INTO executors (name, kind, note, created_at, updated_at) VALUES (?, 'local', '', ?, ?)",
        (LOCAL_EXECUTOR_NAME, now, now),
    )
    return int(cur.lastrowid)


def _backup(conn: sqlite3.Connection, version: int) -> None:
    """迁移前把整个库备份到 app.db.v<旧版本>.bak（已有同名备份时不覆盖，保留最早的那份）。"""
    target = config.DB_PATH.with_name(f"{config.DB_PATH.name}.v{version}.bak")
    if target.exists():
        return
    dst = sqlite3.connect(target)
    try:
        conn.backup(dst)
    finally:
        dst.close()
    log.info("数据库迁移前已备份：%s", target)


def _migrate_v1_to_v2(conn: sqlite3.Connection) -> None:
    """版本 1 → 2。conn 处于手动事务模式，调用方负责 BEGIN / COMMIT。"""
    # 1) environments：加 type，三个上限去掉 NOT NULL。SQLite 不能直接改列约束，只能重建表再拷数据
    seq = conn.execute("SELECT seq FROM sqlite_sequence WHERE name = 'environments'").fetchone()
    conn.execute("DROP TABLE IF EXISTS environments_v2")
    conn.execute(_environments_ddl("environments_v2"))
    conn.execute(
        "INSERT INTO environments_v2 (id, name, type, base_url, headers, max_vus, max_rate, max_duration_sec, "
        "note, created_at, updated_at) "
        "SELECT id, name, CASE WHEN lower(base_url) LIKE '%baidu.com%' THEN 'prod' ELSE 'test' END, base_url, "
        "headers, max_vus, max_rate, max_duration_sec, note, created_at, updated_at FROM environments"
    )
    conn.execute("DROP TABLE environments")
    conn.execute("ALTER TABLE environments_v2 RENAME TO environments")
    # 保住自增计数：重建后的计数是现存的最大 id，如果最大的那条曾被删掉，id 会被复用，
    # 历史运行里的 envId 就会指向另一个环境
    if seq is not None:
        conn.execute("DELETE FROM sqlite_sequence WHERE name = 'environments'")
        conn.execute("INSERT INTO sqlite_sequence (name, seq) VALUES ('environments', ?)", (seq[0],))

    # 2) executors：新表 + 本机执行机
    conn.execute(_EXECUTORS_DDL)
    executor_id = _ensure_local_executor(conn)
    executor_name = conn.execute("SELECT name FROM executors WHERE id = ?", (executor_id,)).fetchone()[0]

    # 3) runs：加三列，并给旧记录补值
    existing = _columns(conn, "runs")
    if "env_type" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN env_type TEXT")
    if "executor_id" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN executor_id INTEGER")
    if "executor_name" not in existing:
        conn.execute("ALTER TABLE runs ADD COLUMN executor_name TEXT NOT NULL DEFAULT ''")
    for run_id, snapshot in conn.execute("SELECT run_id, snapshot FROM runs").fetchall():
        env_type = None
        try:
            env = (json.loads(snapshot) or {}).get("env") or {}
            # 快照里有类型就用；没有就按地址推断；连地址都没有就留空
            env_type = env.get("type") or (guess_env_type(env["baseUrl"]) if env.get("baseUrl") else None)
        except (TypeError, ValueError, AttributeError):
            pass
        conn.execute(
            "UPDATE runs SET env_type = ?, executor_id = ?, executor_name = ? WHERE run_id = ?",
            (env_type, executor_id, executor_name, run_id),
        )


def _migrate_v2_to_v3(conn: sqlite3.Connection) -> None:
    """版本 2 → 3：接口文件夹。加一张表、一列，旧接口的 folder_id 为空（在根目录）。"""
    conn.execute(_FOLDERS_DDL)
    if "folder_id" not in _columns(conn, "apis"):
        conn.execute("ALTER TABLE apis ADD COLUMN folder_id INTEGER")


def _migrate_v3_to_v4(conn: sqlite3.Connection) -> None:
    """版本 3 → 4：被测环境的环境变量。旧环境的变量为空对象。"""
    if "variables" not in _columns(conn, "environments"):
        conn.execute("ALTER TABLE environments ADD COLUMN variables TEXT NOT NULL DEFAULT '{}'")


def init() -> bool:
    """建表或迁移（幂等）。返回 True 表示这是一个全新的库，需要写入种子数据。"""
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    config.RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    # isolation_level=None：不让 sqlite3 模块自动开事务，由这里显式 BEGIN / COMMIT。
    # SQLite 的建表、改表语句可以放在事务里，迁移中途出错能整体回滚
    conn = sqlite3.connect(config.DB_PATH, timeout=30, isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # 写进库文件，之后的连接自动生效
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        existed = _has_table(conn, "environments")
        if version > SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库 {config.DB_PATH} 的结构版本是 {version}，比这份代码支持的 {SCHEMA_VERSION} 新，请升级代码"
            )

        # 按结构判断而不只看版本号：版本号为 0 但表已存在（上次建库后没来得及写版本号）也能处理
        if existed and "type" not in _columns(conn, "environments"):
            _backup(conn, 1)
            conn.execute("BEGIN IMMEDIATE")
            try:
                _migrate_v1_to_v2(conn)
                conn.execute("PRAGMA user_version = 2")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                log.error("数据库迁移失败，已回滚，库文件没有被改动：%s", config.DB_PATH)
                raise
            log.info("数据库已从版本 1 迁移到版本 2：%s", config.DB_PATH)
        if existed and "folder_id" not in _columns(conn, "apis"):
            _backup(conn, 2)
            conn.execute("BEGIN IMMEDIATE")
            try:
                _migrate_v2_to_v3(conn)
                conn.execute("PRAGMA user_version = 3")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                log.error("数据库迁移失败，已回滚，库文件没有被改动：%s", config.DB_PATH)
                raise
            log.info("数据库已从版本 2 迁移到版本 3：%s", config.DB_PATH)
        if existed and "variables" not in _columns(conn, "environments"):
            _backup(conn, 3)
            conn.execute("BEGIN IMMEDIATE")
            try:
                _migrate_v3_to_v4(conn)
                conn.execute("PRAGMA user_version = 4")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                log.error("数据库迁移失败，已回滚，库文件没有被改动：%s", config.DB_PATH)
                raise
            log.info("数据库已从版本 3 迁移到版本 4：%s", config.DB_PATH)
        # 以后的迁移接在这里：if 结构还是版本 4：备份 → BEGIN → _migrate_v4_to_v5 → user_version = 5 → COMMIT

        conn.execute("BEGIN IMMEDIATE")
        try:
            for statement in _SCHEMA:
                conn.execute(statement)
            _ensure_local_executor(conn)
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

        return (not existed) or (
            version == 0
            and all(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == 0 for t in DEFINITION_TABLES)
        )
    finally:
        conn.close()


def mark_initialized() -> None:
    with connect() as conn:
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


# ---------- 小工具 ----------

def now_iso() -> str:
    """ISO 8601 UTC，毫秒精度，例如 2026-09-30T10:15:00.000Z。"""
    return iso(datetime.now(timezone.utc))


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def loads(text: str | None) -> Any:
    return None if text is None else json.loads(text)
