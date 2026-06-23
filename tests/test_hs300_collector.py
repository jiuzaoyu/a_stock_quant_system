from pathlib import Path

import akshare as ak
import matplotlib.pyplot as plt
import pandas as pd
import yfinance as yf

plt.rcParams["font.sans-serif"] = ["Arial Unicode MS", "SimHei", "STHeiti"]
plt.rcParams["axes.unicode_minus"] = False

OUTPUT_DIR = Path(__file__).resolve().parent / "output"

# yfinance -> akshare 列名映射
_COL_MAP = {
    "日期": "Date",
    "开盘": "Open",
    "收盘": "Close",
    "最高": "High",
    "最低": "Low",
    "成交量": "Volume",
}


def _fetch_via_yfinance(symbol: str, start: str):
    df = yf.download(symbol, start=start, auto_adjust=True, multi_level_index=False, progress=False)
    if df.empty:
        raise RuntimeError("yfinance 返回空数据（可能被限流）")
    return df


def _fetch_via_akshare(symbol: str, start: str):
    code = symbol.replace(".SS", "").replace(".SZ", "")
    start_date = start.replace("-", "")
    df = ak.fund_etf_hist_em(symbol=code, period="daily", start_date=start_date, end_date="20501231", adjust="qfq")
    df = df.rename(columns=_COL_MAP)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.set_index("Date")[["Open", "High", "Low", "Close", "Volume"]]
    return df


def fetch_hs300_etf(symbol: str = "510300.SS", start: str = "2021-01-01"):
    try:
        df = _fetch_via_yfinance(symbol, start)
        print("[数据源] yfinance")
    except Exception:
        print("[数据源] yfinance 失败，回退至 akshare")
        df = _fetch_via_akshare(symbol, start)

    print(df.head(), end="\n\n")
    print(f"数据范围: {df.index[0].date()} 到 {df.index[-1].date()}")
    print(f"数据总行数: {len(df)}")
    return df


def plot_close(df, symbol: str, output_dir: Path = OUTPUT_DIR):
    output_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(12, 5))
    ax.plot(df.index, df["Close"], linewidth=1.5)
    ax.set_title(f"沪深300ETF ({symbol}) 收盘价走势")
    ax.set_xlabel("日期")
    ax.set_ylabel("价格（元）")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    path = output_dir / f"hs300_{symbol}_close.png"
    fig.savefig(path, dpi=150)
    plt.close(fig)
    print(f"图表已保存至: {path}")


if __name__ == "__main__":
    symbol = "510300.SS"
    df = fetch_hs300_etf(symbol)
    plot_close(df, symbol)