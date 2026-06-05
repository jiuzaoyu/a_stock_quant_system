"""PostgreSQL 连接池管理（基于 psycopg2 ThreadedConnectionPool）。"""

import os
from contextlib import contextmanager
from typing import Optional

import psycopg2
from psycopg2 import pool
from dotenv import load_dotenv

from .secrets import get_env


def sanitize(value):
    """清洗字符串中的 NUL 等 PostgreSQL 不接受的特殊字符。"""
    if isinstance(value, str):
        return value.replace("\x00", "").replace("\r", "").replace("\\", "\\\\")
    return value

_pool: Optional[pool.ThreadedConnectionPool] = None


def _ensure_env_loaded() -> None:
    """确保 config/.env 已加载到环境变量（幂等）。"""
    env_path = os.environ.get("DOTENV_LOADED")
    if not env_path:
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        load_dotenv(root / "config" / ".env", override=False)
        os.environ["DOTENV_LOADED"] = "1"


def get_pool() -> pool.ThreadedConnectionPool:
    """懒加载初始化线程安全连接池。"""
    global _pool
    if _pool is None:
        _ensure_env_loaded()
        dsn = get_env("DATABASE_URL")
        if not dsn:
            raise RuntimeError("缺少 DATABASE_URL 环境变量，请在 config/.env 中配置")
        _pool = pool.ThreadedConnectionPool(
            minconn=2,
            maxconn=10,
            dsn=dsn,
        )
    return _pool


def get_connection():
    """从连接池获取一个 psycopg2 连接。调用方用完后必须调用 return_connection() 归还。"""
    return get_pool().getconn()


def return_connection(conn) -> None:
    """将连接归还到连接池。"""
    if _pool is not None:
        _pool.putconn(conn)


@contextmanager
def db_context():
    """上下文管理器：自动从连接池获取/归还连接。

    用法:
        with db_context() as conn:
            with conn.cursor() as cur:
                cur.execute(...)
    """
    conn = get_connection()
    try:
        yield conn
    finally:
        return_connection(conn)
