"""SQLite 行情存储：建表、索引、质量检查。"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import pandas as pd

DAILY_TABLE = "daily"

SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS {DAILY_TABLE} (
    ts_code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    pct_change REAL,
    turnover REAL,
    PRIMARY KEY (ts_code, trade_date)
)
"""

INDEX_SQL = f"""
CREATE INDEX IF NOT EXISTS idx_tscode_date
ON {DAILY_TABLE}(ts_code, trade_date)
"""


class DailyStorage:
    """沪深300等批量日线数据的本地 SQLite 仓库。"""

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def init_schema(self, conn: Optional[sqlite3.Connection] = None) -> None:
        own = conn is None
        conn = conn or self.connect()
        try:
            conn.execute(SCHEMA_SQL)
            conn.execute(INDEX_SQL)
            conn.commit()
        finally:
            if own:
                conn.close()

    def delete_symbol(self, conn: sqlite3.Connection, ts_code: str) -> None:
        conn.execute(f"DELETE FROM {DAILY_TABLE} WHERE ts_code = ?", (ts_code,))

    def append_daily(self, conn: sqlite3.Connection, df: pd.DataFrame) -> None:
        df.to_sql(DAILY_TABLE, conn, if_exists="append", index=False)

    def quality_summary(self, conn: Optional[sqlite3.Connection] = None) -> Dict[str, Any]:
        own = conn is None
        conn = conn or self.connect()
        try:
            total = pd.read_sql(f"SELECT COUNT(*) AS cnt FROM {DAILY_TABLE}", conn).iloc[0, 0]
            stocks = pd.read_sql(
                f"SELECT COUNT(DISTINCT ts_code) AS cnt FROM {DAILY_TABLE}", conn
            ).iloc[0, 0]
            dr = pd.read_sql(
                f"SELECT MIN(trade_date) AS dmin, MAX(trade_date) AS dmax FROM {DAILY_TABLE}",
                conn,
            ).iloc[0]
            return {
                "total_rows": int(total),
                "stock_count": int(stocks),
                "date_min": dr["dmin"],
                "date_max": dr["dmax"],
            }
        finally:
            if own:
                conn.close()
