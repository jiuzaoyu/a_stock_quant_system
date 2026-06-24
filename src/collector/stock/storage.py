"""
PostgreSQL 股票数据存储：建表、写入、质量检查。

数据表一览
==========
stock_info        股票基本信息（全量A股列表快照）
stock_daily       日K线数据（OHLCV）
stock_valuation   估值数据（PE/PB/市值/换手率等，来自腾讯财经）
"""

from typing import Any, Dict, Optional

from psycopg2.extras import execute_values

from ...utils.database import get_connection, return_connection, sanitize

STOCK_INFO_TABLE = "stock_info"
STOCK_DAILY_TABLE = "stock_daily"
STOCK_VALUATION_TABLE = "stock_valuation"

STOCK_INFO_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {STOCK_INFO_TABLE} (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
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

# ---- 字段注释 ----
STOCK_COMMENTS = [
    # stock_info
    (f"TABLE {STOCK_INFO_TABLE}", "A股股票基本信息（全量列表快照）"),
    (f"{STOCK_INFO_TABLE}.code", "股票代码，6位数字，如 688017"),
    (f"{STOCK_INFO_TABLE}.name", "股票名称，如 绿的谐波"),
    (f"{STOCK_INFO_TABLE}.market", "市场: sh(沪) / sz(深) / bj(北)"),
    (f"{STOCK_INFO_TABLE}.created_at", "记录首次入库时间"),
    (f"{STOCK_INFO_TABLE}.updated_at", "记录最近更新时间"),
    (f"{STOCK_INFO_TABLE}.active", "采集开关：TRUE=参与定时采集，FALSE=跳过。默认FALSE需手动开启"),
    # stock_daily
    (f"TABLE {STOCK_DAILY_TABLE}", "A股日K线数据（OHLCV）"),
    (f"{STOCK_DAILY_TABLE}.code", "股票代码"),
    (f"{STOCK_DAILY_TABLE}.trade_date", "交易日期 YYYY-MM-DD"),
    (f"{STOCK_DAILY_TABLE}.open", "开盘价"),
    (f"{STOCK_DAILY_TABLE}.high", "最高价"),
    (f"{STOCK_DAILY_TABLE}.low", "最低价"),
    (f"{STOCK_DAILY_TABLE}.close", "收盘价"),
    (f"{STOCK_DAILY_TABLE}.volume", "成交量（手）"),
    (f"{STOCK_DAILY_TABLE}.amount", "成交额（元）"),
    # stock_valuation
    (f"TABLE {STOCK_VALUATION_TABLE}", "A股估值数据（来源：腾讯财经）"),
    (f"{STOCK_VALUATION_TABLE}.code", "股票代码"),
    (f"{STOCK_VALUATION_TABLE}.trade_date", "交易日期 YYYY-MM-DD"),
    (f"{STOCK_VALUATION_TABLE}.pe_ttm", "市盈率 TTM"),
    (f"{STOCK_VALUATION_TABLE}.pe_static", "市盈率 静态"),
    (f"{STOCK_VALUATION_TABLE}.pb", "市净率"),
    (f"{STOCK_VALUATION_TABLE}.mcap_yi", "总市值（亿元）"),
    (f"{STOCK_VALUATION_TABLE}.float_mcap_yi", "流通市值（亿元）"),
    (f"{STOCK_VALUATION_TABLE}.turnover_pct", "换手率（%）"),
    (f"{STOCK_VALUATION_TABLE}.vol_ratio", "量比"),
    (f"{STOCK_VALUATION_TABLE}.amplitude_pct", "振幅（%）"),
    (f"{STOCK_VALUATION_TABLE}.limit_up", "涨停价"),
    (f"{STOCK_VALUATION_TABLE}.limit_down", "跌停价"),
    (f"{STOCK_VALUATION_TABLE}.change_pct", "涨跌幅（%）"),
]


class StockStorage:
    """股票数据 PostgreSQL 仓库，管理 stock_info / stock_daily / stock_valuation 三张表。

    用法:
        storage = StockStorage()
        conn = storage.connect()
        storage.init_schema(conn)
        storage.upsert_stock_info(conn, stock_list)
        storage.append_daily(conn, daily_rows)
        storage.append_valuation(conn, valuation_rows)
        conn.commit()
        storage.return_conn(conn)
    """

    def __init__(self):
        pass

    def connect(self):
        return get_connection()

    def return_conn(self, conn) -> None:
        return_connection(conn)

    def init_schema(self, conn=None) -> None:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(STOCK_INFO_SCHEMA)
                cur.execute(STOCK_DAILY_SCHEMA)
                cur.execute(STOCK_VALUATION_SCHEMA)
                cur.execute(INDEX_INFO_MARKET)
                cur.execute(INDEX_DAILY_CODE_DATE)
                cur.execute(INDEX_DAILY_DATE)
                cur.execute(INDEX_VALUATION_CODE_DATE)
                cur.execute(INDEX_VALUATION_DATE)
                # 迁移：添加 active 列 (v2)
                cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stock_info' AND column_name = 'active'
                    ) THEN
                        ALTER TABLE stock_info ADD COLUMN active BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END $$;
                """)
                for obj, desc in STOCK_COMMENTS:
                    prefix = "" if obj.startswith("TABLE ") else "COLUMN "
                    cur.execute(f"COMMENT ON {prefix}{obj} IS %s", (desc,))
            conn.commit()
        finally:
            if own:
                return_connection(conn)

    def upsert_stock_info(self, conn, records: list[dict]) -> int:
        """批量写入股票基本信息（存在则更新）。"""
        sql = f"""
        INSERT INTO {STOCK_INFO_TABLE} (code, name, market)
        VALUES %s
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            market = excluded.market,
            updated_at = NOW()
        """
        tuples = [(sanitize(r["code"]), sanitize(r["name"]), sanitize(r.get("market", ""))) for r in records]
        tuples = list({t[0]: t for t in tuples}.values())
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount

    def append_daily(self, conn, records: list[dict]) -> int:
        """批量追加日K线记录（已存在的主键自动忽略）。"""
        if not records:
            return 0
        sql = f"""
        INSERT INTO {STOCK_DAILY_TABLE}
            (code, trade_date, open, high, low, close, volume, amount)
        VALUES %s
        ON CONFLICT (code, trade_date) DO NOTHING
        """
        tuples = [
            (sanitize(r["code"]), sanitize(r["trade_date"]), r.get("open"), r.get("high"),
             r.get("low"), r.get("close"), r.get("volume"), r.get("amount"))
            for r in records
        ]
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount

    def append_valuation(self, conn, records: list[dict]) -> int:
        """批量追加估值记录（已存在的主键自动忽略）。"""
        if not records:
            return 0
        sql = f"""
        INSERT INTO {STOCK_VALUATION_TABLE}
            (code, trade_date, pe_ttm, pe_static, pb, mcap_yi, float_mcap_yi,
             turnover_pct, vol_ratio, amplitude_pct, limit_up, limit_down, change_pct)
        VALUES %s
        ON CONFLICT (code, trade_date) DO NOTHING
        """
        tuples = [
            (sanitize(r["code"]), sanitize(r["trade_date"]), r.get("pe_ttm"), r.get("pe_static"),
             r.get("pb"), r.get("mcap_yi"), r.get("float_mcap_yi"),
             r.get("turnover_pct"), r.get("vol_ratio"), r.get("amplitude_pct"),
             r.get("limit_up"), r.get("limit_down"), r.get("change_pct"))
            for r in records
        ]
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount

    def get_all_codes(self, conn=None) -> list[str]:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT code FROM {STOCK_INFO_TABLE}")
                return [r[0] for r in cur.fetchall()]
        finally:
            if own:
                return_connection(conn)

    def get_last_trade_date(self, conn, code: str) -> Optional[str]:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MAX(trade_date) FROM {STOCK_DAILY_TABLE} WHERE code = %s", (code,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def quality_summary(self, conn=None) -> Dict[str, Any]:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {STOCK_INFO_TABLE}")
                stocks = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {STOCK_DAILY_TABLE}")
                daily_rows = cur.fetchone()[0]
                cur.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM {STOCK_DAILY_TABLE}")
                dr = cur.fetchone()
                cur.execute(f"SELECT COUNT(*) FROM {STOCK_VALUATION_TABLE}")
                val_rows = cur.fetchone()[0]
                cur.execute(f"SELECT MIN(trade_date), MAX(trade_date) FROM {STOCK_VALUATION_TABLE}")
                vr = cur.fetchone()
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
                return_connection(conn)
