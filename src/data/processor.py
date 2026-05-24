"""数据清洗与处理"""

import pandas as pd


class DataProcessor:
    """行情与因子数据的通用清洗流程。"""

    @staticmethod
    def clean_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
        """标准化 OHLCV 字段并去重、排序。"""
        required = {"date", "open", "high", "low", "close", "volume"}
        missing = required - set(df.columns)
        if missing:
            raise ValueError(f"缺少字段: {missing}")

        out = df.copy()
        out["date"] = pd.to_datetime(out["date"])
        out = out.sort_values("date").drop_duplicates(subset=["date"])
        out = out.dropna(subset=["close"])
        return out.reset_index(drop=True)

    @staticmethod
    def add_returns(df: pd.DataFrame, price_col: str = "close") -> pd.DataFrame:
        out = df.copy()
        out["return"] = out[price_col].pct_change()
        return out
