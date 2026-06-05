"""
PostgreSQL 基金数据存储：建表、写入、迁移、质量检查。

数据表一览
==========
fund_info      基金基本信息（全量基金列表的快照）
fund_nav       基金净值历史（单位净值 + 累计净值 + 日增长率）
fund_manager   基金经理信息（每位经理一条记录，多经理基金对应多条）
fund_holding   基金重仓股持仓（每季度前十大重仓股）
"""

from typing import Any, Dict, Optional

from psycopg2.extras import execute_values

from ..utils.database import get_connection, return_connection, sanitize

FUND_INFO_TABLE = "fund_info"
FUND_NAV_TABLE = "fund_nav"
FUND_MANAGER_TABLE = "fund_manager"
FUND_HOLDING_TABLE = "fund_holding"

FUND_INFO_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_INFO_TABLE} (
    code TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    fund_type TEXT NOT NULL,
    pinyin TEXT NOT NULL DEFAULT '',
    pinyin_full TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

FUND_INFO_MIGRATION1 = f"""
ALTER TABLE {FUND_INFO_TABLE} ADD COLUMN IF NOT EXISTS pinyin TEXT NOT NULL DEFAULT ''
"""

FUND_INFO_MIGRATION2 = f"""
ALTER TABLE {FUND_INFO_TABLE} ADD COLUMN IF NOT EXISTS pinyin_full TEXT NOT NULL DEFAULT ''
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

FUND_MANAGER_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_MANAGER_TABLE} (
    code TEXT NOT NULL,
    manager_id TEXT NOT NULL,
    name TEXT NOT NULL,
    star INTEGER,
    work_time TEXT,
    fund_size TEXT,
    power_avr REAL,
    power_json TEXT DEFAULT '[]',
    profit_json TEXT DEFAULT '{{}}',
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (code, manager_id)
)
"""

FUND_HOLDING_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_HOLDING_TABLE} (
    code TEXT NOT NULL,
    report_date TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    stock_name TEXT,
    rank INTEGER,
    nav_pct REAL,
    shares_wan REAL,
    market_cap_wan REAL,
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (code, report_date, stock_code)
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

INDEX_MANAGER_CODE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_manager_code
ON {FUND_MANAGER_TABLE}(code)
"""

INDEX_HOLDING_CODE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_holding_code
ON {FUND_HOLDING_TABLE}(code)
"""

INDEX_HOLDING_DATE = f"""
CREATE INDEX IF NOT EXISTS idx_fund_holding_date
ON {FUND_HOLDING_TABLE}(report_date)
"""

# ---- 字段注释 ----
FUND_COMMENTS = [
    # fund_info
    (f"TABLE {FUND_INFO_TABLE}", "基金基本信息（全量基金列表快照）"),
    (f"{FUND_INFO_TABLE}.code", "基金代码，6位数字，如 161725"),
    (f"{FUND_INFO_TABLE}.name", "基金名称，如 招商中证白酒指数(LOF)A"),
    (f"{FUND_INFO_TABLE}.fund_type", "基金类型，如 指数型-股票、混合型-偏股、股票型"),
    (f"{FUND_INFO_TABLE}.pinyin", "拼音缩写，如 ZSZZBJZS"),
    (f"{FUND_INFO_TABLE}.pinyin_full", "拼音全称，如 ZHAOSHANGZHONGZHENGBAIJIUZHISHU"),
    (f"{FUND_INFO_TABLE}.created_at", "记录首次入库时间"),
    (f"{FUND_INFO_TABLE}.updated_at", "记录最近更新时间"),
    # fund_nav
    (f"TABLE {FUND_NAV_TABLE}", "基金净值历史"),
    (f"{FUND_NAV_TABLE}.code", "基金代码"),
    (f"{FUND_NAV_TABLE}.nav_date", "净值日期 YYYY-MM-DD"),
    (f"{FUND_NAV_TABLE}.unit_nav", "单位净值"),
    (f"{FUND_NAV_TABLE}.accum_nav", "累计净值"),
    (f"{FUND_NAV_TABLE}.daily_growth", "日增长率（%）"),
    # fund_manager
    (f"TABLE {FUND_MANAGER_TABLE}", "基金经理信息"),
    (f"{FUND_MANAGER_TABLE}.code", "基金代码"),
    (f"{FUND_MANAGER_TABLE}.manager_id", "基金经理ID（天天基金内部ID）"),
    (f"{FUND_MANAGER_TABLE}.name", "基金经理姓名"),
    (f"{FUND_MANAGER_TABLE}.star", "星级评分 1-5"),
    (f"{FUND_MANAGER_TABLE}.work_time", "从业年限描述，如 8年又282天"),
    (f"{FUND_MANAGER_TABLE}.fund_size", "管理规模描述，如 533.63亿(24只基金)"),
    (f"{FUND_MANAGER_TABLE}.power_avr", "综合管理能力评分（五项加权均值）"),
    (f"{FUND_MANAGER_TABLE}.power_json", "五项评分明细 JSON [经验值,收益率,跟踪误差,超额收益,管理规模]"),
    (f"{FUND_MANAGER_TABLE}.profit_json", "任期收益对比 JSON {tenure,peer_avg,hs300}"),
    (f"{FUND_MANAGER_TABLE}.updated_at", "记录最近更新时间"),
    # fund_holding
    (f"TABLE {FUND_HOLDING_TABLE}", "基金重仓股持仓（季度前十大）"),
    (f"{FUND_HOLDING_TABLE}.code", "基金代码"),
    (f"{FUND_HOLDING_TABLE}.report_date", "报告期截止日 YYYY-MM-DD（季度末）"),
    (f"{FUND_HOLDING_TABLE}.stock_code", "股票代码，如 600519"),
    (f"{FUND_HOLDING_TABLE}.stock_name", "股票名称，如 贵州茅台"),
    (f"{FUND_HOLDING_TABLE}.rank", "持仓排名 1-10"),
    (f"{FUND_HOLDING_TABLE}.nav_pct", "占净值比例（%）"),
    (f"{FUND_HOLDING_TABLE}.shares_wan", "持股数（万股）"),
    (f"{FUND_HOLDING_TABLE}.market_cap_wan", "持仓市值（万元）"),
    (f"{FUND_HOLDING_TABLE}.updated_at", "记录最近更新时间"),
]


class FundStorage:
    """基金数据 PostgreSQL 仓库，管理 fund_info / fund_nav / fund_manager / fund_holding 四张表。

    用法:
        storage = FundStorage()
        conn = storage.connect()
        storage.init_schema(conn)
        storage.upsert_fund_info(conn, fund_list)
        storage.upsert_fund_managers(conn, code, managers)
        storage.upsert_fund_holdings(conn, code, report_date, holdings)
        storage.append_nav(conn, nav_rows)
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
                cur.execute(FUND_INFO_SCHEMA)
                cur.execute(FUND_NAV_SCHEMA)
                cur.execute(FUND_MANAGER_SCHEMA)
                cur.execute(FUND_HOLDING_SCHEMA)
                cur.execute(INDEX_INFO_TYPE)
                cur.execute(INDEX_NAV_CODE_DATE)
                cur.execute(INDEX_NAV_DATE)
                cur.execute(INDEX_MANAGER_CODE)
                cur.execute(INDEX_HOLDING_CODE)
                cur.execute(INDEX_HOLDING_DATE)
                cur.execute(FUND_INFO_MIGRATION1)
                cur.execute(FUND_INFO_MIGRATION2)
                for obj, desc in FUND_COMMENTS:
                    prefix = "" if obj.startswith("TABLE ") else "COLUMN "
                    cur.execute(f"COMMENT ON {prefix}{obj} IS %s", (desc,))
            conn.commit()
        finally:
            if own:
                return_connection(conn)

    def upsert_fund_info(self, conn, records: list[dict]) -> int:
        """批量写入基金基本信息（存在则更新）。"""
        sql = f"""
        INSERT INTO {FUND_INFO_TABLE} (code, name, fund_type, pinyin, pinyin_full)
        VALUES %s
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            fund_type = excluded.fund_type,
            pinyin = excluded.pinyin,
            pinyin_full = excluded.pinyin_full,
            updated_at = NOW()
        """
        tuples = [
            (sanitize(r["code"]), sanitize(r["name"]), sanitize(r["fund_type"]),
             sanitize(r.get("pinyin", "")), sanitize(r.get("pinyin_full", "")))
            for r in records
        ]
        # 按主键 code 去重
        tuples = list({t[0]: t for t in tuples}.values())
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount

    def upsert_fund_managers(self, conn, code: str, managers: list[dict]) -> int:
        """写入基金的基金经理信息（先删后插，以最新数据覆盖）。"""
        if not managers:
            return 0
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {FUND_MANAGER_TABLE} WHERE code = %s", (code,)
            )
        sql = f"""
        INSERT INTO {FUND_MANAGER_TABLE}
            (code, manager_id, name, star, work_time, fund_size,
             power_avr, power_json, profit_json)
        VALUES %s
        ON CONFLICT (code, manager_id) DO UPDATE SET
            name = excluded.name,
            star = excluded.star,
            work_time = excluded.work_time,
            fund_size = excluded.fund_size,
            power_avr = excluded.power_avr,
            power_json = excluded.power_json,
            profit_json = excluded.profit_json,
            updated_at = NOW()
        """
        tuples = [
            (sanitize(code), sanitize(m["manager_id"]), sanitize(m["name"]), m.get("star"),
             sanitize(m.get("work_time")), sanitize(m.get("fund_size")), m.get("power_avr"),
             sanitize(m.get("power_json", "[]")), sanitize(m.get("profit_json", "{}")))
            for m in managers
        ]
        # 按主键 (code, manager_id) 去重
        tuples = list({(t[0], t[1]): t for t in tuples}.values())
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples)
            return cur.rowcount

    def upsert_fund_holdings(
        self, conn, code: str, report_date: str, holdings: list[dict]
    ) -> int:
        """写入基金某一季度的重仓股持仓（先删后插，以最新数据覆盖）。"""
        if not holdings:
            return 0
        with conn.cursor() as cur:
            cur.execute(
                f"DELETE FROM {FUND_HOLDING_TABLE} WHERE code = %s AND report_date = %s",
                (code, report_date),
            )
        sql = f"""
        INSERT INTO {FUND_HOLDING_TABLE}
            (code, report_date, stock_code, stock_name, rank,
             nav_pct, shares_wan, market_cap_wan)
        VALUES %s
        ON CONFLICT (code, report_date, stock_code) DO UPDATE SET
            stock_name = excluded.stock_name,
            rank = excluded.rank,
            nav_pct = excluded.nav_pct,
            shares_wan = excluded.shares_wan,
            market_cap_wan = excluded.market_cap_wan,
            updated_at = NOW()
        """
        tuples = [
            (sanitize(code), sanitize(report_date), sanitize(h["stock_code"]),
             sanitize(h.get("stock_name")), h.get("rank"), h.get("nav_pct"),
             h.get("shares_wan"), h.get("market_cap_wan"))
            for h in holdings
        ]
        # 按主键 (code, report_date, stock_code) 去重
        tuples = list({(t[0], t[1], t[2]): t for t in tuples}.values())
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples)
            return cur.rowcount

    def append_nav(self, conn, records: list[dict]) -> int:
        """批量追加净值记录（已存在的主键自动忽略）。"""
        if not records:
            return 0
        sql = f"""
        INSERT INTO {FUND_NAV_TABLE}
            (code, nav_date, unit_nav, accum_nav, daily_growth)
        VALUES %s
        ON CONFLICT (code, nav_date) DO NOTHING
        """
        tuples = [
            (sanitize(r["code"]), sanitize(r["nav_date"]), r.get("unit_nav"),
             r.get("accum_nav"), r.get("daily_growth"))
            for r in records
        ]
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount

    def get_last_nav_date(self, conn, code: str) -> Optional[str]:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT MAX(nav_date) FROM {FUND_NAV_TABLE} WHERE code = %s", (code,)
            )
            row = cur.fetchone()
            return row[0] if row else None

    def delete_nav_for_code(self, conn, code: str) -> None:
        with conn.cursor() as cur:
            cur.execute(f"DELETE FROM {FUND_NAV_TABLE} WHERE code = %s", (code,))

    def get_all_codes(self, conn=None) -> list[str]:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT code FROM {FUND_INFO_TABLE}")
                return [r[0] for r in cur.fetchall()]
        finally:
            if own:
                return_connection(conn)

    def quality_summary(self, conn=None) -> Dict[str, Any]:
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {FUND_INFO_TABLE}")
                funds = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {FUND_NAV_TABLE}")
                nav_rows = cur.fetchone()[0]
                cur.execute(f"SELECT MIN(nav_date), MAX(nav_date) FROM {FUND_NAV_TABLE}")
                dr = cur.fetchone()
                cur.execute(
                    f"SELECT fund_type, COUNT(*) FROM {FUND_INFO_TABLE} GROUP BY fund_type"
                )
                type_counts = dict(cur.fetchall())
                cur.execute(f"SELECT COUNT(*) FROM {FUND_MANAGER_TABLE}")
                mgr_rows = cur.fetchone()[0]
                cur.execute(f"SELECT COUNT(*) FROM {FUND_HOLDING_TABLE}")
                hld_rows = cur.fetchone()[0]
            return {
                "total_funds": funds,
                "total_nav_rows": nav_rows,
                "nav_date_min": dr[0],
                "nav_date_max": dr[1],
                "type_counts": type_counts,
                "total_manager_rows": mgr_rows,
                "total_holding_rows": hld_rows,
            }
        finally:
            if own:
                return_connection(conn)
