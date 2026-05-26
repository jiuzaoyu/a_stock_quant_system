"""
第一个量化脚本：获取沪深300成分股数据并绘制K线图
作者：AI量化交易实战读者
运行环境：quant虚拟环境（Python 3.11 + AKShare + mplfinance）
"""

import akshare as ak
import mplfinance as mpf
import pandas as pd
from datetime import datetime, timedelta

def get_hs300_stocks():
    """获取沪深300成分股列表"""
    print("📊 正在获取沪深300成分股列表...")
    df = ak.index_stock_cons_weight_csindex(symbol="000300")
    print(f"✅ 共获取 {len(df)} 只成分股")
    return df

def get_stock_data(code, days=120):
    """
    获取单只股票的日K线数据
    参数:
        code: 股票代码，如 "000001"
        days: 获取最近多少个交易日的数据
    返回:
        DataFrame，包含OHLCV数据
    """
    end_date = datetime.now().strftime("%Y%m%d")
    start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")

    # 使用AKShare获取个股日K数据
    df = ak.stock_zh_a_hist(
        symbol=code,
        period="daily",
        start_date=start_date,
        end_date=end_date,
        adjust="qfq"  # 前复权
    )

    # 重命名列以适配mplfinance格式
    df = df.rename(columns={
        "日期": "Date",
        "开盘": "Open",
        "最高": "High",
        "最低": "Low",
        "收盘": "Close",
        "成交量": "Volume"
    })

    # 转换日期为datetime并设为索引
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")

    # 只保留最近N个交易日
    df = df.tail(days)

    return df[["Open", "High", "Low", "Close", "Volume"]]

def plot_candlestick(df, title="K线图"):
    """绘制专业K线图"""
    # 设置K线图样式
    mc = mpf.make_marketcolors(
        up='red',       # 中国A股：红涨
        down='green',   # 中国A股：绿跌
        edge='i',
        wick='i',
        volume='in',
    )
    style = mpf.make_mpf_style(
        marketcolors=mc,
        figcolor='#F0EBE5',
        gridstyle='--',
        gridaxis='both'
    )

    # 绘制K线图（含成交量）
    fig, axes = mpf.plot(
        df,
        type='candle',
        style=style,
        title=title,
        volume=True,
        figsize=(14, 8),
        returnfig=True
    )

    # 保存图片
    fig.savefig("output/first_candlestick.png", dpi=150, bbox_inches='tight')
    print(f"📈 K线图已保存到 output/first_candlestick.png")

def main():
    """主函数"""
    print("=" * 50)
    print("🚀 第一个量化脚本启动！")
    print("=" * 50)

    # 1. 获取沪深300成分股
    hs300 = get_hs300_stocks()

    # 2. 选取一只代表性股票（如贵州茅台 600519）
    # 你可以修改这个代码来查看不同的股票
    stock_code = "600519"
    stock_name = "贵州茅台"

    print(f"\n📊 正在获取 {stock_name}({stock_code}) 的行情数据...")
    df = get_stock_data(stock_code, days=120)
    print(f"✅ 获取到 {len(df)} 个交易日数据")
    print(f"   日期范围: {df.index[0].date()} ~ {df.index[-1].date()}")
    print(f"   最新收盘价: {df['Close'].iloc[-1]:.2f}")

    # 3. 绘制K线图
    plot_candlestick(df, title=f"{stock_name}({stock_code}) 日K线图")

    print("\n✅ 恭喜！你的第一个量化脚本运行成功！")
    print("📁 项目结构已就绪，接下来可以开始数据探索。")

if __name__ == "__main__":
    main()