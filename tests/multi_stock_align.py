"""
多股票数据对齐与 MultiIndex 使用示例

模拟场景：处理多只股票（不同交易日）的行情数据时的对齐策略

用法: python tests/multi_stock_align.py
"""

import pandas as pd
import numpy as np


# ============================================================
#  1. 构造模拟数据 — 模拟不同股票的不同交易日
# ============================================================

def make_mock_data():
    """构造3只股票、日期有交错的行情数据"""
    np.random.seed(42)
    stocks = {
        "000001": pd.date_range("2024-01-02", "2024-01-10"),   # 平安银行(全)
        "600519": pd.date_range("2024-01-03", "2024-01-12"),   # 贵州茅台(错开1天)
        "000858": pd.date_range("2024-01-02", "2024-01-08"),   # 五粮液(少2天)
    }
    df_dict = {}
    for code, dates in stocks.items():
        n = len(dates)
        close = np.cumsum(np.random.randn(n) * 0.02 + 0.001) + 10
        df_dict[code] = pd.DataFrame(
            {
                "open":  close + np.random.randn(n) * 0.01,
                "high":  close + np.abs(np.random.randn(n) * 0.02),
                "low":   close - np.abs(np.random.randn(n) * 0.02),
                "close": close,
                "volume": np.random.randint(10000, 100000, n),
            },
            index=dates,
        )
    return df_dict


df_dict = make_mock_data()

# 各股票交易日数
for code, df in df_dict.items():
    print(f"{code}: {len(df)} 个交易日, 范围 {df.index[0].date()} ~ {df.index[-1].date()}")
print()


# ============================================================
#  2. 时间对齐方案一 — concat 自动对齐（最常用）
# ============================================================

print("=" * 60)
print("  方案一: concat 收盘价 -> 列=股票, 行=日期")
print("=" * 60)
close_panel = pd.concat(
    [df["close"] for df in df_dict.values()],
    axis=1,
    keys=df_dict.keys(),
).sort_index()
print(close_panel)
print()


# ============================================================
#  3. 时间对齐方案二 — 手动对齐所有字段
# ============================================================

print("=" * 60)
print("  方案二: 手动对齐 -> 填充缺失日为 NaN")
print("=" * 60)
all_dates = sorted(set().union(*[df.index for df in df_dict.values()]))
aligned = pd.DataFrame(index=all_dates)
for code, df in df_dict.items():
    aligned[code] = df["close"].reindex(all_dates)
print(aligned)
print()


# ============================================================
#  4. MultiIndex Panel — 同时保留多字段(open/high/low/close/volume)
# ============================================================

print("=" * 60)
print("  方案三: MultiIndex Panel (code, date) 多字段")
print("=" * 60)
frames = []
for code, df in df_dict.items():
    tmp = df[["open", "high", "low", "close", "volume"]].copy()
    tmp["code"] = code
    tmp.index.name = "date"
    frames.append(tmp)

panel = pd.concat(frames)
panel = panel.reset_index().set_index(["code", "date"]).sort_index()
print("索引结构:", panel.index[:5].tolist())
print(f"形状: {panel.shape}")
print(panel.head(8))
print()


# ============================================================
#  5. MultiIndex 切片操作
# ============================================================

print("=" * 60)
print("  切片: xs('000001', level='code') -> 单只股票全部字段")
print("=" * 60)
print(panel.xs("000001", level="code"))
print()

print("=" * 60)
print("  切片: xs('2024-01-05', level='date') -> 某天所有股票")
print("=" * 60)
print(panel.xs("2024-01-05", level="date"))
print()


# ============================================================
#  6. groupby 截面操作
# ============================================================

print("=" * 60)
print("  截面操作: groupby(level='date') 算日涨跌幅")
print("=" * 60)
daily_ret = panel.groupby(level="date")["close"].apply(lambda x: x.pct_change())
print(daily_ret.dropna().head(8))
print()

print("=" * 60)
print("  截面操作: groupby(level='date') 每日涨跌幅排名")
print("=" * 60)
rank = panel.groupby(level="date")["close"].transform(
    lambda x: x.pct_change().rank(ascending=False)
)
print(rank.dropna().head(8))
print()


# ============================================================
#  7. groupby 时序操作 — 滚动窗口
# ============================================================

print("=" * 60)
print("  时序操作: groupby(level='code').rolling(3) 3日波动率")
print("=" * 60)
vol = panel.groupby(level="code")["close"].rolling(3).std().droplevel(0)
panel["vol_3d"] = vol
print(panel[["close", "vol_3d"]].dropna().head(8))
print()


# ============================================================
#  8. 截面 + 时序组合: 每日选涨幅最高的股票
# ============================================================

print("=" * 60)
print("  组合: 每日选涨幅最高的一只股票")
print("=" * 60)
# 先算日收益率
panel["ret"] = panel.groupby(level="code")["close"].pct_change()
# 每天选收益率最高的股票
top_picks = panel.dropna(subset=["ret"]).groupby(level="date")["ret"].idxmax()
# idxmax 返回的是 (code, date) 元组
print(top_picks.head())
