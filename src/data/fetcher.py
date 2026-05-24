"""数据获取"""

from pathlib import Path
from typing import Optional

import pandas as pd


class DataFetcher:
    """从 AkShare / Tushare / 聚宽等源拉取行情与基础数据。"""

    def __init__(self, cache_dir: Optional[Path] = None):
        self.cache_dir = Path(cache_dir) if cache_dir else Path("data/cache")
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch_daily(
        self,
        symbol: str,
        start: str,
        end: str,
        source: str = "akshare",
    ) -> pd.DataFrame:
        """
        获取日线数据。

        Returns:
            DataFrame，列建议包含 date, open, high, low, close, volume
        """
        if source == "akshare":
            return self._fetch_akshare_daily(symbol, start, end)
        if source == "tushare":
            return self._fetch_tushare_daily(symbol, start, end)
        if source == "jqdata":
            return self._fetch_jqdata_daily(symbol, start, end)
        raise ValueError(f"不支持的数据源: {source}")

    def _fetch_akshare_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        import akshare as ak

        code = symbol.replace(".SH", "").replace(".SZ", "")
        df = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
            adjust="qfq",
        )
        df = df.rename(
            columns={
                "日期": "date",
                "开盘": "open",
                "收盘": "close",
                "最高": "high",
                "最低": "low",
                "成交量": "volume",
            }
        )
        df["date"] = pd.to_datetime(df["date"])
        return df

    def _fetch_tushare_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """Token 从环境变量 TUSHARE_TOKEN 读取，禁止在代码中硬编码。"""
        import tushare as ts

        from ..utils.secrets import require_env

        ts.set_token(require_env("TUSHARE_TOKEN"))
        pro = ts.pro_api()
        ts_code = symbol if "." in symbol else f"{symbol}.SZ"
        df = pro.daily(ts_code=ts_code, start_date=start.replace("-", ""), end_date=end.replace("-", ""))
        df = df.rename(columns={"trade_date": "date", "vol": "volume"})
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date")

    def _fetch_jqdata_daily(self, symbol: str, start: str, end: str) -> pd.DataFrame:
        """账号密码从 JQDATA_USER / JQDATA_PASSWORD 读取。"""
        from jqdatasdk import auth, get_price

        from ..utils.secrets import require_env

        auth(require_env("JQDATA_USER"), require_env("JQDATA_PASSWORD"))
        code = symbol if "." in symbol else f"{symbol}.XSHG"
        df = get_price(code, start_date=start, end_date=end, frequency="daily", fields=["open", "close", "high", "low", "volume"])
        df = df.reset_index().rename(columns={"index": "date"})
        return df
