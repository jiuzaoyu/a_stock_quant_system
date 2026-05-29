"""SQLite 基金数据存储：建表、写入、质量检查。"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

FUND_INFO_TABLE = "fund_info"
FUND_NAV_TABLE = "fund_nav"

FUND_INFO_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_INFO_TABLE} (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fund_type TEXT NOT NULL,
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
)
"""

FUND_NAV_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_NAV_TABLE} (
    code TEXT NOT NULL,
    nav_date TEXT NOT NULL,
    unit_nav REAL,
    accum_nav REAL,
    daily_growth REAL,
    PRIMARY KEY (code, nav_date)
)
"""

INDEX_INFO_TYPE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_info_type
ON {FUND_INFO_TABLE}(fund_type)
"""

INDEX_NAV_CODE_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_nav_code_date
ON {FUND_NAV_TABLE}(code, nav_date)
"""

INDEX_NAV_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_nav_date
ON {FUND_NAV_TABLE}(nav_date)
"""


class FundStorage:
    """基金基本信息和净值数据的本地 SQLite 仓库。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def init_schema(self, conn: Optional[sqlite3.Connection] = None) -> None:
        own = conn is None
        conn = conn or self.connect()
        try:
            conn.execute(FUND_INFO_SCHEMA)
            conn.execute(FUND_NAV_SCHEMA)
            conn.execute(INDEX_INFO_TYPE)
            conn.execute(INDEX_NAV_CODE_DATE)
            conn.execute(INDEX_NAV_DATE)
            conn.commit()
        finally:
            if own:
                conn.close()

    def upsert_fund_info(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        sql = f"""
        INSERT INTO {FUND_INFO_TABLE} (code, name, fund_type)
        VALUES (:code, :name, :fund_type)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            fund_type = excluded.fund_type,
            updated_at = datetime('now', 'localtime')
        """
        conn.executemany(sql, records)
        return conn.total_changes

    def append_nav(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        sql = f"""
        INSERT OR IGNORE INTO {FUND_NAV_TABLE}
            (code, nav_date, unit_nav, accum_nav, daily_growth)
        VALUES (:code, :nav_date, :unit_nav, :accum_nav, :daily_growth)
        """
        before = conn.total_changes
        conn.executemany(sql, records)
        return conn.total_changes - before

    def get_last_nav_date(self, conn: sqlite3.Connection, code: str) -> Optional[str]:
        row = conn.execute(
            f"SELECT MAX(nav_date) FROM {FUND_NAV_TABLE} WHERE code = ?", (code,)
        ).fetchone()
        return row[0] if row else None

    def delete_nav_for_code(self, conn: sqlite3.Connection, code: str) -> None:
        conn.execute(f"DELETE FROM {FUND_NAV_TABLE} WHERE code = ?", (code,))

    def get_all_codes(self, conn: Optional[sqlite3.Connection] = None) -> list[str]:
        own = conn is None
        conn = conn or self.connect()
        try:
            rows = conn.execute(f"SELECT code FROM {FUND_INFO_TABLE}").fetchall()
            return [r[0] for r in rows]
        finally:
            if own:
                conn.close()

    def quality_summary(self, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        own = conn is None
        conn = conn or self.connect()
        try:
            funds = conn.execute(
                f"SELECT COUNT(*) FROM {FUND_INFO_TABLE}"
            ).fetchone()[0]
            nav_rows = conn.execute(
                f"SELECT COUNT(*) FROM {FUND_NAV_TABLE}"
            ).fetchone()[0]
            dr = conn.execute(
                f"SELECT MIN(nav_date), MAX(nav_date) FROM {FUND_NAV_TABLE}"
            ).fetchone()
            type_counts = dict(
                conn.execute(
                    f"SELECT fund_type, COUNT(*) FROM {FUND_INFO_TABLE} GROUP BY fund_type"
                ).fetchall()
            )
            return {
                "total_funds": funds,
                "total_nav_rows": nav_rows,
                "nav_date_min": dr[0],
                "nav_date_max": dr[1],
                "type_counts": type_counts,
            }
        finally:
            if own:
                conn.close()
