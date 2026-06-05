"""
SQLite 股票数据存储：建表、写入、质量检查。

数据表一览
==========
stock_info        股票基本信息（全量A股列表快照）
stock_daily       日K线数据（OHLCV）
stock_valuation   估值数据（PE/PB/市值/换手率等，来自腾讯财经）

stock_info 字段说明
-------------------
code         TEXT PK   股票代码，6位数字，如 "688017"
name         TEXT      股票名称，如 "绿的谐波"
market       TEXT      市场: sh(沪) / sz(深) / bj(北)
created_at   TEXT      记录首次入库时间
updated_at   TEXT      记录最近更新时间

stock_daily 字段说明
--------------------
code         TEXT      股票代码
trade_date   TEXT      交易日期 YYYY-MM-DD
open         REAL      开盘价
high         REAL      最高价
low          REAL      最低价
close        REAL      收盘价
volume       REAL      成交量(手)
amount       REAL      成交额(元)
PK: (code, trade_date)

stock_valuation 字段说明
------------------------
code              TEXT    股票代码
trade_date        TEXT    交易日期 YYYY-MM-DD
pe_ttm            REAL    市盈率(TTM)
pe_static         REAL    市盈率(静态)
pb                REAL    市净率
mcap_yi           REAL    总市值(亿元)
float_mcap_yi     REAL    流通市值(亿元)
turnover_pct      REAL    换手率(%)
vol_ratio         REAL    量比
amplitude_pct     REAL    振幅(%)
limit_up          REAL    涨停价
limit_down        REAL    跌停价
change_pct        REAL    涨跌幅(%)
PK: (code, trade_date)
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

STOCK_INFO_TABLE = "stock_info"
STOCK_DAILY_TABLE = "stock_daily"
STOCK_VALUATION_TABLE = "stock_valuation"

STOCK_INFO_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {STOCK_INFO_TABLE} (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT '',
    created_at TEXT DEFAULT (datetime('now', 'localtime')),
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))
)
"""

STOCK_DAILY_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {STOCK_DAILY_TABLE} (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    amount REAL,
    PRIMARY KEY (code, trade_date)
)
"""

STOCK_VALUATION_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {STOCK_VALUATION_TABLE} (
    code TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    pe_ttm REAL,
    pe_static REAL,
    pb REAL,
    mcap_yi REAL,
    float_mcap_yi REAL,
    turnover_pct REAL,
    vol_ratio REAL,
    amplitude_pct REAL,
    limit_up REAL,
    limit_down REAL,
    change_pct REAL,
    PRIMARY KEY (code, trade_date)
)
"""

INDEX_INFO_MARKET = f"""
CREATE INDEX IF NOT EXISTS idx_stock_info_market
ON {STOCK_INFO_TABLE}(market)
"""

INDEX_DAILY_CODE_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_stock_daily_code_date
ON {STOCK_DAILY_TABLE}(code, trade_date)
"""

INDEX_DAILY_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_stock_daily_date
ON {STOCK_DAILY_TABLE}(trade_date)
"""

INDEX_VALUATION_CODE_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_stock_valuation_code_date
ON {STOCK_VALUATION_TABLE}(code, trade_date)
"""

INDEX_VALUATION_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_stock_valuation_date
ON {STOCK_VALUATION_TABLE}(trade_date)
"""


class StockStorage:
    """股票数据本地 SQLite 仓库，管理 stock_info / stock_daily / stock_valuation 三张表。

    用法:
        storage = StockStorage(Path("data/database/stock.db"))
        conn = storage.connect()
        storage.init_schema(conn)
        storage.upsert_stock_info(conn, stock_list)
        storage.append_daily(conn, daily_rows)
        storage.append_valuation(conn, valuation_rows)
        conn.commit()
        conn.close()
    """

    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        return sqlite3.connect(str(self.db_path))

    def init_schema(self, conn: Optional[sqlite3.Connection] = None) -> None:
        own = conn is None
        conn = conn or self.connect()
        try:
            conn.execute(STOCK_INFO_SCHEMA)
            conn.execute(STOCK_DAILY_SCHEMA)
            conn.execute(STOCK_VALUATION_SCHEMA)
            conn.execute(INDEX_INFO_MARKET)
            conn.execute(INDEX_DAILY_CODE_DATE)
            conn.execute(INDEX_DAILY_DATE)
            conn.execute(INDEX_VALUATION_CODE_DATE)
            conn.execute(INDEX_VALUATION_DATE)
            conn.commit()
        finally:
            if own:
                conn.close()

    def upsert_stock_info(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        """批量写入股票基本信息（存在则更新 name/market/updated_at）。"""
        sql = f"""
        INSERT INTO {STOCK_INFO_TABLE} (code, name, market)
        VALUES (:code, :name, :market)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            market = excluded.market,
            updated_at = datetime('now', 'localtime')
        """
        conn.executemany(sql, records)
        return conn.total_changes

    def append_daily(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        """批量追加日K线记录（已存在的主键自动忽略）。"""
        sql = f"""
        INSERT OR IGNORE INTO {STOCK_DAILY_TABLE}
            (code, trade_date, open, high, low, close, volume, amount)
        VALUES (:code, :trade_date, :open, :high, :low, :close, :volume, :amount)
        """
        before = conn.total_changes
        conn.executemany(sql, records)
        return conn.total_changes - before

    def append_valuation(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        """批量追加估值记录（已存在的主键自动忽略）。"""
        sql = f"""
        INSERT OR IGNORE INTO {STOCK_VALUATION_TABLE}
            (code, trade_date, pe_ttm, pe_static, pb, mcap_yi, float_mcap_yi,
             turnover_pct, vol_ratio, amplitude_pct, limit_up, limit_down, change_pct)
        VALUES (:code, :trade_date, :pe_ttm, :pe_static, :pb, :mcap_yi, :float_mcap_yi,
                :turnover_pct, :vol_ratio, :amplitude_pct, :limit_up, :limit_down, :change_pct)
        """
        before = conn.total_changes
        conn.executemany(sql, records)
        return conn.total_changes - before

    def get_all_codes(self, conn: Optional[sqlite3.Connection] = None) -> list[str]:
        own = conn is None
        conn = conn or self.connect()
        try:
            rows = conn.execute(f"SELECT code FROM {STOCK_INFO_TABLE}").fetchall()
            return [r[0] for r in rows]
        finally:
            if own:
                conn.close()

    def get_last_trade_date(
        self, conn: sqlite3.Connection, code: str
    ) -> Optional[str]:
        row = conn.execute(
            f"SELECT MAX(trade_date) FROM {STOCK_DAILY_TABLE} WHERE code = ?", (code,)
        ).fetchone()
        return row[0] if row else None

    def quality_summary(
        self, conn: Optional[sqlite3.Connection] = None
    ) -> Dict[str, Any]:
        own = conn is None
        conn = conn or self.connect()
        try:
            stocks = conn.execute(
                f"SELECT COUNT(*) FROM {STOCK_INFO_TABLE}"
            ).fetchone()[0]
            daily_rows = conn.execute(
                f"SELECT COUNT(*) FROM {STOCK_DAILY_TABLE}"
            ).fetchone()[0]
            dr = conn.execute(
                f"SELECT MIN(trade_date), MAX(trade_date) FROM {STOCK_DAILY_TABLE}"
            ).fetchone()
            val_rows = conn.execute(
                f"SELECT COUNT(*) FROM {STOCK_VALUATION_TABLE}"
            ).fetchone()[0]
            vr = conn.execute(
                f"SELECT MIN(trade_date), MAX(trade_date) FROM {STOCK_VALUATION_TABLE}"
            ).fetchone()
            return {
                "total_stocks": stocks,
                "total_daily_rows": daily_rows,
                "daily_date_min": dr[0],
                "daily_date_max": dr[1],
                "total_valuation_rows": val_rows,
                "valuation_date_min": vr[0],
                "valuation_date_max": vr[1],
            }
        finally:
            if own:
                conn.close()
