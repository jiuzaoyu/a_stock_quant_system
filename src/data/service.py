"""数据服务层：统一对外提供行情与因子数据，隔离具体数据源实现。"""

from pathlib import Path
from typing import Optional

import pandas as pd

from .fetcher import DataFetcher
from .processor import DataProcessor


class DataService:
    """
    数据服务（工厂层）。

    策略与回测只依赖本类，不直接调用 AkShare / Tushare 等接口。
    更换数据源时仅修改 fetcher 实现。
    """

    def __init__(
        self,
        cache_dir: Optional[Path] = None,
        fetcher: Optional[DataFetcher] = None,
        processor: Optional[DataProcessor] = None,
    ):
        self.fetcher = fetcher or DataFetcher(cache_dir=cache_dir)
        self.processor = processor or DataProcessor()

    def get_daily_ohlcv(
        self,
        symbol: str,
        start: str,
        end: str,
        source: str = "akshare",
        save_processed: bool = False,
        processed_dir: Optional[Path] = None,
    ) -> pd.DataFrame:
        raw = self.fetcher.fetch_daily(symbol, start, end, source=source)
        clean = self.processor.clean_ohlcv(raw)

        if save_processed and processed_dir:
            processed_dir = Path(processed_dir)
            processed_dir.mkdir(parents=True, exist_ok=True)
            path = processed_dir / f"{symbol}_{start}_{end}.csv"
            clean.to_csv(path, index=False)

        return clean
