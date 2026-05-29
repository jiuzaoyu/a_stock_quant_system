"""筛选条件纯函数 — 每个函数输入 DataFrame，返回过滤后的 DataFrame 或 bool"""

from typing import List

import pandas as pd


def filter_by_market_cap(df: pd.DataFrame, min_cap: float, max_cap: float) -> pd.DataFrame:
    """筛选市值在 [min_cap, max_cap] 亿之间的股票。

    df 需包含 '总市值' 列（AKShare stock_zh_a_spot_em 输出，单位：元）
    """
    cap_yuan_min = min_cap * 1e8
    cap_yuan_max = max_cap * 1e8
    return df[(df["总市值"] >= cap_yuan_min) & (df["总市值"] <= cap_yuan_max)]


def filter_by_pct_change(df: pd.DataFrame, min_pct: float, max_pct: float) -> pd.DataFrame:
    """筛选涨跌幅在 [min_pct, max_pct] 之间的股票。

    df 需包含 '涨跌幅' 列（百分比数值，如 3.5 表示 3.5%）
    """
    return df[(df["涨跌幅"] >= min_pct) & (df["涨跌幅"] <= max_pct)]


def filter_by_volume_ratio(df: pd.DataFrame, min_ratio: float) -> pd.DataFrame:
    """筛选量比 >= min_ratio 的股票。

    df 需包含 '量比' 列
    """
    return df[df["量比"] >= min_ratio]


def filter_by_turnover_rate(df: pd.DataFrame, min_rate: float, max_rate: float) -> pd.DataFrame:
    """筛选换手率在 [min_rate, max_rate] 之间的股票。

    df 需包含 '换手率' 列（百分比数值，如 7.5 表示 7.5%）
    """
    return df[(df["换手率"] >= min_rate) & (df["换手率"] <= max_rate)]


def has_limit_up_in_history(
    daily_df: pd.DataFrame, days: int = 20, threshold: float = 9.8
) -> bool:
    """检查近 N 个交易日内是否出现过涨停（涨幅 >= threshold）。

    daily_df 需包含 '涨跌幅' 列（AKShare stock_zh_a_hist 输出），
    按日期升序排列，取最近 N 行。
    """
    recent = daily_df.tail(days)
    return (recent["涨跌幅"] >= threshold).any()


def check_vwap_above(minute_df: pd.DataFrame) -> bool:
    """检查全天所有分钟K线的 low 是否都在分时均线(VWAP)上方。

    minute_df 需包含 '最低', '成交量', '成交额' 列，
    VWAP = 累计成交额 / 累计成交量。
    返回 True 表示所有 K 线的 low >= VWAP。
    """
    if minute_df.empty:
        return False

    cum_turnover = minute_df["成交额"].cumsum()
    cum_volume = minute_df["成交量"].cumsum()

    mask = cum_volume > 0
    vwap = pd.Series(0.0, index=minute_df.index)
    vwap[mask] = cum_turnover[mask] / cum_volume[mask]

    return (minute_df["最低"] >= vwap).all()


def get_stock_codes(df: pd.DataFrame) -> List[str]:
    """从 spot DataFrame 提取股票代码列表。"""
    return df["代码"].tolist()
