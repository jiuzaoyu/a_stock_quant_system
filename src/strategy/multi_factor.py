"""多因子选股策略（骨架）

输入为截面因子表，不拉取行情；数据由 DataService 准备。
"""

import pandas as pd

from .base import BaseStrategy


class MultiFactorStrategy(BaseStrategy):
    def __init__(self, top_n: int = 30, **kwargs):
        super().__init__(kwargs)
        self.top_n = top_n

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        data 需为截面因子表：index=股票代码，columns=因子名。
        返回含 score、signal 的排名结果。
        """
        if data.empty:
            raise ValueError("因子数据为空")

        df = data.copy()
        df["score"] = df.rank(pct=True).mean(axis=1)
        df["signal"] = 0
        top = df.nlargest(self.top_n, "score").index
        df.loc[top, "signal"] = 1
        return df
