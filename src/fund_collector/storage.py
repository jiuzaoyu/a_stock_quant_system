"""
SQLite 基金数据存储：建表、写入、迁移、质量检查。

数据表一览
==========
fund_info      基金基本信息（全量基金列表的快照）
fund_nav       基金净值历史（单位净值 + 累计净值 + 日增长率）
fund_manager   基金经理信息（每位经理一条记录，多经理基金对应多条）
fund_holding   基金重仓股持仓（每季度前十大重仓股）

fund_info 字段说明
------------------
code         TEXT PK   基金代码，6 位数字，如 "161725"
name         TEXT      基金名称，如 "招商中证白酒指数(LOF)A"
fund_type    TEXT      基金类型，如 "指数型-股票"、"混合型-偏股"、"股票型"
pinyin       TEXT      拼音缩写，如 "ZSZZBJZS"（天天基金接口 item[1]）
pinyin_full  TEXT      拼音全称，如 "ZHAOSHANGZHONGZHENGBAIJIUZHISHU"（接口 item[4]）
created_at   TEXT      记录首次入库时间（自动生成）
updated_at   TEXT      记录最近更新时间（upsert 时自动刷新）

fund_nav 字段说明
------------------
code         TEXT      基金代码，对应 fund_info.code
nav_date     TEXT      净值日期，格式 YYYY-MM-DD
unit_nav     REAL      单位净值
accum_nav    REAL      累计净值（部分基金可能缺失）
daily_growth REAL      日增长率（百分比，相对于前一交易日）

fund_manager 字段说明
---------------------
code         TEXT      基金代码，对应 fund_info.code
manager_id   TEXT      基金经理ID（天天基金内部ID）
name         TEXT      基金经理姓名
star         INTEGER   星级评分（1-5）
work_time    TEXT      从业年限描述，如 "8年又282天"
fund_size    TEXT      管理规模描述，如 "533.63亿(24只基金)"
power_avr    REAL      综合管理能力评分（五项维度加权均值）
power_json   TEXT      五项评分明细 JSON，如 [87.4, 71.6, 79.2, 83.1, 97.3]
                        依次对应：经验值、收益率、跟踪误差、超额收益、管理规模
profit_json  TEXT      任期收益对比 JSON，如 {"tenure":57.1,"peer_avg":91.2,"hs300":31.0}
updated_at   TEXT      记录最近更新时间（upsert 时自动刷新）
PK: (code, manager_id)

fund_holding 字段说明
---------------------
code           TEXT    基金代码，对应 fund_info.code
report_date    TEXT    报告期截止日 YYYY-MM-DD，如 "2026-03-31"（季度末）
stock_code     TEXT    股票代码，如 "600519"
stock_name     TEXT    股票名称，如 "贵州茅台"
rank           INTEGER 持仓排名（1-10）
nav_pct        REAL    占净值比例(%)，如 18.33
shares_wan     REAL    持股数(万股)
market_cap_wan REAL    持仓市值(万元)
updated_at     TEXT    记录最近更新时间（自动生成）
PK: (code, report_date, stock_code)

索引
====
idx_fund_info_type       按 fund_type 查询
idx_fund_nav_code_date   按 code+nav_date 联合查询（主力索引）
idx_fund_nav_date        按 nav_date 查询（跨基金日期筛选）
idx_fund_manager_code    按 code 查经理
idx_fund_holding_code    按 code 查持仓
idx_fund_holding_date    按 report_date 查持仓（跨基金季度筛选）
"""

import sqlite3
from pathlib import Path
from typing import Any, Dict, Optional

FUND_INFO_TABLE = "fund_info"
FUND_NAV_TABLE = "fund_nav"
FUND_MANAGER_TABLE = "fund_manager"
FUND_HOLDING_TABLE = "fund_holding"

FUND_INFO_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_INFO_TABLE} (
    code TEXT PRIMARY KEY,                                    -- 基金代码 (PK)
    name TEXT NOT NULL,                                       -- 基金名称
    fund_type TEXT NOT NULL,                                  -- 基金类型
    pinyin TEXT NOT NULL DEFAULT '',                          -- 拼音缩写
    pinyin_full TEXT NOT NULL DEFAULT '',                     -- 拼音全称
    created_at TEXT DEFAULT (datetime('now', 'localtime')),   -- 入库时间
    updated_at TEXT DEFAULT (datetime('now', 'localtime'))    -- 最近更新时间
)
"""

FUND_INFO_MIGRATION = f"""
ALTER TABLE {FUND_INFO_TABLE} ADD COLUMN pinyin TEXT NOT NULL DEFAULT ''
"""

FUND_INFO_MIGRATION2 = f"""
ALTER TABLE {FUND_INFO_TABLE} ADD COLUMN pinyin_full TEXT NOT NULL DEFAULT ''
"""

FUND_NAV_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_NAV_TABLE} (
    code TEXT NOT NULL,                -- 基金代码
    nav_date TEXT NOT NULL,            -- 净值日期 YYYY-MM-DD
    unit_nav REAL,                     -- 单位净值
    accum_nav REAL,                    -- 累计净值
    daily_growth REAL,                 -- 日增长率(%)
    PRIMARY KEY (code, nav_date)
)
"""

FUND_MANAGER_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_MANAGER_TABLE} (
    code TEXT NOT NULL,                                       -- 基金代码
    manager_id TEXT NOT NULL,                                 -- 基金经理ID
    name TEXT NOT NULL,                                       -- 基金经理姓名
    star INTEGER,                                             -- 星级 (1-5)
    work_time TEXT,                                           -- 从业年限
    fund_size TEXT,                                           -- 管理规模
    power_avr REAL,                                           -- 综合评分
    power_json TEXT DEFAULT '[]',                              -- 五项评分明细 JSON
    profit_json TEXT DEFAULT '{{}}',                           -- 任期收益对比 JSON
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),   -- 最近更新时间
    PRIMARY KEY (code, manager_id)
)
"""

FUND_HOLDING_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS {FUND_HOLDING_TABLE} (
    code TEXT NOT NULL,                                       -- 基金代码
    report_date TEXT NOT NULL,                                -- 报告期 YYYY-MM-DD
    stock_code TEXT NOT NULL,                                 -- 股票代码
    stock_name TEXT,                                          -- 股票名称
    rank INTEGER,                                             -- 持仓排名 (1-10)
    nav_pct REAL,                                             -- 占净值比例(%)
    shares_wan REAL,                                          -- 持股数(万股)
    market_cap_wan REAL,                                      -- 持仓市值(万元)
    updated_at TEXT DEFAULT (datetime('now', 'localtime')),   -- 最近更新时间
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


class FundStorage:
    """基金数据本地 SQLite 仓库，管理 fund_info / fund_nav / fund_manager / fund_holding 四张表。

    用法:
        storage = FundStorage(Path("data/database/quant.db"))
        conn = storage.connect()
        storage.init_schema(conn)
        storage.upsert_fund_info(conn, fund_list)
        storage.upsert_fund_managers(conn, code, managers)
        storage.upsert_fund_holdings(conn, code, report_date, holdings)
        storage.append_nav(conn, nav_rows)
        conn.commit()
        conn.close()
    """

    def __init__(self, db_path: Path):
        """初始化存储，自动创建数据库文件所在的父目录。

        Args:
            db_path: SQLite 数据库文件路径，如 Path("data/database/quant.db")
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def connect(self) -> sqlite3.Connection:
        """创建新的数据库连接。调用方负责关闭连接。"""
        return sqlite3.connect(str(self.db_path))

    def init_schema(self, conn: Optional[sqlite3.Connection] = None) -> None:
        """初始化数据库表结构并执行迁移。

        幂等操作：表已存在则跳过建表，列已存在则跳过迁移。
        若传入 None 则自动创建临时连接。

        Args:
            conn: 可选的外部连接，若为 None 则内部创建并关闭
        """
        own = conn is None
        conn = conn or self.connect()
        try:
            conn.execute(FUND_INFO_SCHEMA)
            conn.execute(FUND_NAV_SCHEMA)
            conn.execute(FUND_MANAGER_SCHEMA)
            conn.execute(FUND_HOLDING_SCHEMA)
            conn.execute(INDEX_INFO_TYPE)
            conn.execute(INDEX_NAV_CODE_DATE)
            conn.execute(INDEX_NAV_DATE)
            conn.execute(INDEX_MANAGER_CODE)
            conn.execute(INDEX_HOLDING_CODE)
            conn.execute(INDEX_HOLDING_DATE)
            # 迁移旧表：添加 pinyin / pinyin_full 列
            self._migrate(conn)
            conn.commit()
        finally:
            if own:
                conn.close()

    @staticmethod
    def _migrate(conn: sqlite3.Connection) -> None:
        """给旧版 fund_info 表添加新字段（忽略已存在列的错误）。"""
        for sql in (FUND_INFO_MIGRATION, FUND_INFO_MIGRATION2):
            try:
                conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # 字段已存在

    def upsert_fund_info(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        """批量写入基金基本信息（存在则更新）。

        依据 code 主键判断：新基金插入，已有基金更新 name/fund_type/pinyin 及 updated_at。
        records 每条 dict 需包含: code, name, fund_type, pinyin, pinyin_full
        """
        sql = f"""
        INSERT INTO {FUND_INFO_TABLE} (code, name, fund_type, pinyin, pinyin_full)
        VALUES (:code, :name, :fund_type, :pinyin, :pinyin_full)
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            fund_type = excluded.fund_type,
            pinyin = excluded.pinyin,
            pinyin_full = excluded.pinyin_full,
            updated_at = datetime('now', 'localtime')
        """
        conn.executemany(sql, records)
        return conn.total_changes

    def upsert_fund_managers(
        self, conn: sqlite3.Connection, code: str, managers: list[dict]
    ) -> int:
        """写入基金的基金经理信息（先删后插，以最新数据覆盖）。

        managers 每条 dict 需包含: manager_id, name, star, work_time,
        fund_size, power_avr, power_json, profit_json

        Returns:
            写入的记录数
        """
        before = conn.total_changes
        conn.execute(
            f"DELETE FROM {FUND_MANAGER_TABLE} WHERE code = ?", (code,)
        )
        sql = f"""
        INSERT OR REPLACE INTO {FUND_MANAGER_TABLE}
            (code, manager_id, name, star, work_time, fund_size,
             power_avr, power_json, profit_json, updated_at)
        VALUES (:code, :manager_id, :name, :star, :work_time, :fund_size,
                :power_avr, :power_json, :profit_json,
                datetime('now', 'localtime'))
        """
        conn.executemany(
            sql,
            [
                {
                    "code": code,
                    "manager_id": m["manager_id"],
                    "name": m["name"],
                    "star": m.get("star"),
                    "work_time": m.get("work_time"),
                    "fund_size": m.get("fund_size"),
                    "power_avr": m.get("power_avr"),
                    "power_json": m.get("power_json", "[]"),
                    "profit_json": m.get("profit_json", "{}"),
                }
                for m in managers
            ],
        )
        return conn.total_changes - before

    def upsert_fund_holdings(
        self,
        conn: sqlite3.Connection,
        code: str,
        report_date: str,
        holdings: list[dict],
    ) -> int:
        """写入基金某一季度的重仓股持仓（先删后插，以最新数据覆盖）。

        holdings 每条 dict 需包含: stock_code, stock_name, rank,
        nav_pct, shares_wan, market_cap_wan

        Returns:
            写入的记录数
        """
        before = conn.total_changes
        conn.execute(
            f"DELETE FROM {FUND_HOLDING_TABLE} WHERE code = ? AND report_date = ?",
            (code, report_date),
        )
        sql = f"""
        INSERT OR REPLACE INTO {FUND_HOLDING_TABLE}
            (code, report_date, stock_code, stock_name, rank,
             nav_pct, shares_wan, market_cap_wan, updated_at)
        VALUES (:code, :report_date, :stock_code, :stock_name, :rank,
                :nav_pct, :shares_wan, :market_cap_wan,
                datetime('now', 'localtime'))
        """
        conn.executemany(
            sql,
            [
                {
                    "code": code,
                    "report_date": report_date,
                    "stock_code": h["stock_code"],
                    "stock_name": h.get("stock_name"),
                    "rank": h.get("rank"),
                    "nav_pct": h.get("nav_pct"),
                    "shares_wan": h.get("shares_wan"),
                    "market_cap_wan": h.get("market_cap_wan"),
                }
                for h in holdings
            ],
        )
        return conn.total_changes - before

    def append_nav(self, conn: sqlite3.Connection, records: list[dict]) -> int:
        """批量追加净值记录（已存在的主键自动忽略）。

        records 每条 dict 需包含: code, nav_date, unit_nav, accum_nav, daily_growth
        返回实际新写入的行数。
        """
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
            mgr_rows = conn.execute(
                f"SELECT COUNT(*) FROM {FUND_MANAGER_TABLE}"
            ).fetchone()[0]
            hld_rows = conn.execute(
                f"SELECT COUNT(*) FROM {FUND_HOLDING_TABLE}"
            ).fetchone()[0]
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
                conn.close()
