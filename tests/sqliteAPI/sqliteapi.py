"""SQLite 常用操作封装 —— 连接、建表、增删改查、事务。

函数                         用途
──────────────────────────────────────────────────────────────
connect()         上下文管理器，获取连接，自动提交/回滚/关闭
get_cursor()      上下文管理器，获取游标，自动管理事务
create_table()    建表，传入 {列名: 类型约束} 字典
insert()          插入单行，返回 rowid
insert_many()     批量插入，返回插入行数
query()           查询，返回 list[dict]
query_one()       查询单行，返回 dict | None
execute()         执行写操作 (UPDATE/DELETE/DDL)，返回影响行数
execute_script()  执行多条 SQL 语句
list_tables()     列出所有表名
table_info()      获取表结构 (PRAGMA table_info)
count_rows()      统计行数，可选 where 条件
transaction()     事务中批量执行多条 SQL
"""

import sqlite3
from contextlib import contextmanager
from typing import Any


@contextmanager
def connect(db_path: str):
    """获取数据库连接（上下文管理器，自动关闭）。"""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_cursor(db_path: str):
    """获取游标（上下文管理器，自动提交/回滚/关闭连接）。"""
    with connect(db_path) as conn:
        cursor = conn.cursor()
        try:
            yield cursor
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def create_table(db_path: str, table_name: str, columns: dict[str, str], *, if_not_exists: bool = True) -> None:
    """建表。

    Args:
        db_path: 数据库文件路径
        table_name: 表名
        columns: {列名: 类型约束}，如 {'id': 'INTEGER PRIMARY KEY AUTOINCREMENT', 'name': 'TEXT NOT NULL'}
        if_not_exists: 是否加 IF NOT EXISTS
    """
    col_defs = ", ".join(f"{col} {dtype}" for col, dtype in columns.items())
    exists_clause = "IF NOT EXISTS" if if_not_exists else ""
    sql = f"CREATE TABLE {exists_clause} {table_name} ({col_defs})"
    with get_cursor(db_path) as cur:
        cur.execute(sql)


def insert(db_path: str, table_name: str, data: dict[str, Any]) -> int:
    """插入一行，返回 rowid。"""
    columns = ", ".join(data.keys())
    placeholders = ", ".join("?" for _ in data)
    sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
    with get_cursor(db_path) as cur:
        cur.execute(sql, tuple(data.values()))
        return cur.lastrowid


def insert_many(db_path: str, table_name: str, rows: list[dict[str, Any]]) -> int:
    """批量插入，返回插入行数。"""
    if not rows:
        return 0
    columns = ", ".join(rows[0].keys())
    placeholders = ", ".join("?" for _ in rows[0])
    sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
    values = [tuple(r.values()) for r in rows]
    with get_cursor(db_path) as cur:
        cur.executemany(sql, values)
        return cur.rowcount


def query(db_path: str, sql: str, params: tuple | None = None) -> list[dict[str, Any]]:
    """执行查询，返回字典列表。"""
    with get_cursor(db_path) as cur:
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        return [dict(row) for row in rows]


def query_one(db_path: str, sql: str, params: tuple | None = None) -> dict[str, Any] | None:
    """执行查询，返回单行字典，无结果返回 None。"""
    with get_cursor(db_path) as cur:
        cur.execute(sql, params or ())
        row = cur.fetchone()
        return dict(row) if row else None


def execute(db_path: str, sql: str, params: tuple | None = None) -> int:
    """执行写操作（UPDATE/DELETE/DDL），返回影响行数。"""
    with get_cursor(db_path) as cur:
        cur.execute(sql, params or ())
        return cur.rowcount


def execute_script(db_path: str, sql: str) -> None:
    """执行多条 SQL 语句（executescript）。"""
    with connect(db_path) as conn:
        conn.executescript(sql)


def list_tables(db_path: str) -> list[str]:
    """列出数据库中所有表名。"""
    rows = query(db_path, "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return [r["name"] for r in rows]


def table_info(db_path: str, table_name: str) -> list[dict[str, Any]]:
    """获取表结构信息（PRAGMA table_info）。"""
    return query(db_path, f"PRAGMA table_info({table_name})")


def count_rows(db_path: str, table_name: str, *, where: str | None = None) -> int:
    """统计表行数，可选 where 条件。"""
    sql = f"SELECT COUNT(*) AS cnt FROM {table_name}"
    if where:
        sql += f" WHERE {where}"
    row = query_one(db_path, sql)
    return row["cnt"] if row else 0


def transaction(db_path: str, statements: list[tuple[str, tuple | None]]) -> None:
    """在一个事务中执行多条 SQL。

    Args:
        db_path: 数据库路径
        statements: [(sql, params), ...] 列表
    """
    with connect(db_path) as conn:
        cur = conn.cursor()
        try:
            for sql, params in statements:
                cur.execute(sql, params or ())
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
