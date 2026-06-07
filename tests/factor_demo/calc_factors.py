"""
量化因子计算演示

从 PostgreSQL 读取 stock_daily + stock_valuation 数据，
计算价值/动量/波动率/流动性/技术等因子，展示最新截面。

用法:
    python tests/factor_demo/calc_factors.py          # 默认200只股票
    python tests/factor_demo/calc_factors.py --all    # 全量股票
    python tests/factor_demo/calc_factors.py -n 50    # 50只股票
"""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.utils.database import get_connection, return_connection


def load_stock_daily(sample_codes: list[str] | None = None) -> pd.DataFrame:
    """加载 stock_daily 数据，可选限定股票列表。"""
    conn = get_connection()
    try:
        if sample_codes:
            # 用 IN 子句分批查询
            placeholders = ",".join(["%s"] * len(sample_codes))
            sql = f"""
            SELECT code, trade_date, open, high, low, close, volume, amount
            FROM stock_daily
            WHERE code IN ({placeholders})
            ORDER BY code, trade_date
            """
            with conn.cursor() as cur:
                cur.execute(sql, sample_codes)
                rows = cur.fetchall()
        else:
            sql = """
            SELECT code, trade_date, open, high, low, close, volume, amount
            FROM stock_daily
            ORDER BY code, trade_date
            """
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        df = pd.DataFrame(
            rows,
            columns=["code", "trade_date", "open", "high", "low", "close", "volume", "amount"],
        )
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    finally:
        return_connection(conn)


def load_stock_valuation(codes: list[str] | None = None) -> pd.DataFrame:
    """加载 stock_valuation 数据。"""
    conn = get_connection()
    try:
        if codes:
            placeholders = ",".join(["%s"] * len(codes))
            sql = f"""
            SELECT code, trade_date, pe_ttm, pe_static, pb, turnover_pct,
                   mcap_yi, float_mcap_yi, change_pct
            FROM stock_valuation
            WHERE code IN ({placeholders})
            ORDER BY code, trade_date
            """
            with conn.cursor() as cur:
                cur.execute(sql, codes)
                rows = cur.fetchall()
        else:
            sql = """
            SELECT code, trade_date, pe_ttm, pe_static, pb, turnover_pct,
                   mcap_yi, float_mcap_yi, change_pct
            FROM stock_valuation
            ORDER BY code, trade_date
            """
            with conn.cursor() as cur:
                cur.execute(sql)
                rows = cur.fetchall()

        df = pd.DataFrame(
            rows,
            columns=[
                "code", "trade_date", "pe_ttm", "pe_static", "pb",
                "turnover_pct", "mcap_yi", "float_mcap_yi", "change_pct",
            ],
        )
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        return df
    finally:
        return_connection(conn)


def calc_factors(group: pd.DataFrame) -> pd.DataFrame:
    """计算单只股票的所有因子值。"""
    g = group.sort_values("trade_date").copy()

    # === 日收益率 ===
    g["ret"] = g["close"].pct_change()

    # === 价值因子 ===
    g["pe_ttm_inv"] = 1.0 / g["pe_ttm"].replace(0, np.nan)
    g["pb_inv"] = 1.0 / g["pb"].replace(0, np.nan)

    # === 动量因子 ===
    g["momentum_20d"] = g["close"].pct_change(20)
    g["momentum_60d"] = g["close"].pct_change(60)

    # === 波动率因子 ===
    g["volatility_20d"] = g["ret"].rolling(20).std() * np.sqrt(252)

    # === 流动性因子 ===
    g["amihud"] = (np.abs(g["ret"]) / (g["amount"] + 1e-8)).rolling(20).mean()
    g["turnover"] = g["turnover_pct"]

    # === 技术因子 ===
    g["avg_amount_20d"] = g["amount"].rolling(20).mean()
    g["price_volume_corr"] = g["close"].rolling(20).corr(g["volume"])

    # === 市值因子 ===
    g["log_mcap"] = np.log(g["mcap_yi"].replace(0, np.nan))

    return g


FACTOR_COLS = [
    "pe_ttm_inv", "pb_inv", "momentum_20d", "momentum_60d",
    "volatility_20d", "turnover", "amihud",
    "avg_amount_20d", "price_volume_corr", "log_mcap",
]

FACTOR_LABELS = {
    "pe_ttm_inv": "PE倒数(价值)",
    "pb_inv": "PB倒数(价值)",
    "momentum_20d": "20日动量",
    "momentum_60d": "60日动量",
    "volatility_20d": "年化波动率",
    "turnover": "换手率(%)",
    "amihud": "Amihud非流动性",
    "avg_amount_20d": "20日均成交额",
    "price_volume_corr": "量价相关性",
    "log_mcap": "对数市值",
}


def main():
    parser = argparse.ArgumentParser(description="量化因子计算演示")
    parser.add_argument("-n", "--sample", type=int, default=200,
                        help="采样股票数 (默认: 200)")
    parser.add_argument("--all", action="store_true",
                        help="全量股票（数据量大，耗时较长）")
    parser.add_argument("--min-rows", type=int, default=60,
                        help="最少K线记录数 (默认: 60)")
    args = parser.parse_args()

    # 1. 获取股票列表
    print("获取股票列表...")
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            if args.all:
                cur.execute("SELECT DISTINCT code FROM stock_daily")
            else:
                cur.execute(
                    "SELECT code FROM (SELECT DISTINCT code FROM stock_daily) t "
                    "ORDER BY RANDOM() LIMIT %s", (args.sample,)
                )
            codes = [r[0] for r in cur.fetchall()]
    finally:
        return_connection(conn)
    print(f"选中 {len(codes)} 只股票")

    # 2. 加载数据
    print("加载 stock_daily 数据...")
    daily = load_stock_daily(codes)

    print("加载 stock_valuation 数据...")
    val = load_stock_valuation(codes)

    # 3. 合并 daily + valuation（左连接，保留所有K线）
    print("合并数据...")
    df = daily.merge(val, on=["code", "trade_date"], how="left")
    print(f"合并完成: {df['code'].nunique()} 只股票, {len(df)} 条记录")

    # 过滤数据点过少的股票
    counts = df.groupby("code").size()
    valid = counts[counts >= args.min_rows].index
    df = df[df["code"].isin(valid)]
    print(f"过滤后 (>= {args.min_rows}条): {df['code'].nunique()} 只股票, {len(df)} 条记录")

    # 4. 计算因子（手动分组，避免 groupby.apply 丢弃 code 列）
    print("计算因子...")
    parts = []
    total = df["code"].nunique()
    for i, (_, group) in enumerate(df.groupby("code", sort=False)):
        parts.append(calc_factors(group))
        if (i + 1) % 500 == 0:
            print(f"  {i + 1}/{total} 只...")
    df = pd.concat(parts, ignore_index=True)
    print(f"因子计算完成")

    # 5. 最新截面
    latest_date = df["trade_date"].max()
    latest = (
        df[df["trade_date"] == latest_date][["code"] + FACTOR_COLS]
    )

    print(f"\n{'='*60}")
    print(f"最新截面因子 ({latest_date.strftime('%Y-%m-%d')})")
    print(f"{'='*60}")
    print(f"有效股票数: {len(latest)}")

    # 描述统计
    print(f"\n--- 因子描述统计 ---")
    desc = latest[FACTOR_COLS].describe().round(4)
    desc.index = ["count", "mean", "std", "min", "25%", "50%", "75%", "max"]
    # 重命名列
    desc.columns = [f"{FACTOR_LABELS.get(c, c)}" for c in FACTOR_COLS]
    print(desc.to_string())

    # 前15只
    print(f"\n--- 前15只股票因子值 ---")
    display = latest.head(15).copy()
    display.columns = ["code"] + [FACTOR_LABELS.get(c, c) for c in FACTOR_COLS]
    print(display.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
