"""PostgreSQL 行情存储：建表、索引、质量检查。"""

from typing import Any, Dict, Optional

import pandas as pd

from ..utils.database import get_connection, return_connection

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

# ---- 字段注释 ----
DAILY_COMMENTS = [
    (f"TABLE {DAILY_TABLE}", "沪深300日线行情数据"),
    (f"{DAILY_TABLE}.ts_code", "股票代码，如 000001"),
    (f"{DAILY_TABLE}.trade_date", "交易日期 YYYY-MM-DD"),
    (f"{DAILY_TABLE}.open", "开盘价"),
    (f"{DAILY_TABLE}.high", "最高价"),
    (f"{DAILY_TABLE}.low", "最低价"),
    (f"{DAILY_TABLE}.close", "收盘价"),
    (f"{DAILY_TABLE}.volume", "成交量（手）"),
    (f"{DAILY_TABLE}.amount", "成交额（元）"),
    (f"{DAILY_TABLE}.pct_change", "涨跌幅（%）"),
    (f"{DAILY_TABLE}.turnover", "换手率（%）"),
]


class DailyStorage:
    """沪深300等批量日线数据的 PostgreSQL 仓库。"""

    def __init__(self):
        pass

    def connect(self):
        """从连接池获取一个连接。调用方负责归还。"""
        return get_connection()

    def init_schema(self, conn=None) -> None:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(SCHEMA_SQL)
                cur.execute(INDEX_SQL)
                for obj, desc in DAILY_COMMENTS:
                    prefix = "" if obj.startswith("TABLE ") else "COLUMN "
                    cur.execute(f"COMMENT ON {prefix}{obj} IS %s", (desc,))
            conn.commit()
        finally:
            if own:
                return_connection(conn)

    def delete_symbol(self, conn, ts_code: str) -> None:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {DAILY_TABLE} WHERE ts_code = %s", (ts_code,))

    def append_daily(self, conn, df: pd.DataFrame) -> None:
        df.to_sql(DAILY_TABLE, conn, if_exists="append", index=False)

    def quality_summary(self, conn=None) -> Dict[str, Any]:
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
                return_connection(conn)
