"""CTA 趋势策略（双均线示例）

仅根据行情生成 signal，不访问外部数据源。
"""

import pandas as pd

from .base import BaseStrategy


class CTAStrategy(BaseStrategy):
    def __init__(self, fast_period: int = 10, slow_period: int = 30, **kwargs):
        super().__init__(kwargs)
        self.fast_period = fast_period
        self.slow_period = slow_period

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        df = data.copy()
        df["ma_fast"] = df["close"].rolling(self.fast_period).mean()
        df["ma_slow"] = df["close"].rolling(self.slow_period).mean()
        df["signal"] = 0
        df.loc[df["ma_fast"] > df["ma_slow"], "signal"] = 1
        df.loc[df["ma_fast"] < df["ma_slow"], "signal"] = -1
        return df
