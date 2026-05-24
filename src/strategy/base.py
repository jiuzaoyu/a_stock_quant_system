"""策略基类 — 统一接口契约"""

from abc import ABC, abstractmethod
from typing import Any, Dict

import pandas as pd


class BaseStrategy(ABC):
    """
    所有策略必须实现的接口。

    职责边界：
    - 策略：根据输入数据生成 signal，不拉取数据、不下单、不计算账户收益
    - 回测引擎：根据 signal 模拟成交并统计绩效
    - 数据服务：提供标准化 DataFrame
    """

    def __init__(self, params: Dict[str, Any] | None = None):
        self.params = params or {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        根据行情或因子数据生成交易信号。

        Args:
            data: 标准化行情（OHLCV）或截面因子表，由调用方通过 DataService 准备

        Returns:
            含 signal 列的 DataFrame（1 做多, -1 平仓/做空, 0 观望），与输入索引对齐
        """
