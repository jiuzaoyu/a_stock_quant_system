"""回测引擎：只负责模拟执行、计算收益，不实现策略逻辑。"""

from typing import Any, Dict, Optional, Union

import backtrader as bt
import pandas as pd

from ..strategy.base import BaseStrategy


class PandasData(bt.feeds.PandasData):
    params = (
        ("datetime", "date"),
        ("open", "open"),
        ("high", "high"),
        ("low", "low"),
        ("close", "close"),
        ("volume", "volume"),
        ("openinterest", -1),
    )


class SignalStrategy(bt.Strategy):
    """根据预计算信号列执行买卖，不包含 alpha 逻辑。"""

    params = dict(signals=None)

    def next(self):
        if self.params.signals is None:
            return
        idx = len(self) - 1
        if idx >= len(self.params.signals):
            return
        sig = int(self.params.signals.iloc[idx]["signal"])
        if sig > 0 and not self.position:
            self.buy()
        elif sig < 0 and self.position:
            self.close()


class BacktestEngine:
    """回测引擎：接收行情 + 信号，输出绩效统计。"""

    def __init__(self, initial_cash: float = 1_000_000, commission: float = 0.0003):
        self.initial_cash = initial_cash
        self.commission = commission

    def run(
        self,
        price_data: pd.DataFrame,
        signals: pd.DataFrame,
        plot: bool = False,
    ) -> Dict[str, Any]:
        """
        使用已生成的信号进行回测。

        Args:
            price_data: OHLCV 行情
            signals: 含 signal 列，与 price_data 行对齐
        """
        if "signal" not in signals.columns:
            raise ValueError("signals 必须包含 signal 列")

        cerebro = bt.Cerebro()
        cerebro.broker.setcash(self.initial_cash)
        cerebro.broker.setcommission(commission=self.commission)

        cerebro.adddata(PandasData(dataname=price_data))
        cerebro.addstrategy(
            SignalStrategy,
            signals=signals.reset_index(drop=True),
        )

        start_value = cerebro.broker.getvalue()
        cerebro.run()
        end_value = cerebro.broker.getvalue()

        result = {
            "start_value": start_value,
            "end_value": end_value,
            "return_pct": (end_value - start_value) / start_value,
        }
        if plot:
            cerebro.plot()
        return result

    def run_with_strategy(
        self,
        price_data: pd.DataFrame,
        strategy: BaseStrategy,
        plot: bool = False,
    ) -> Dict[str, Any]:
        """便捷方法：先调用策略生成信号，再回测（编排层使用，非策略职责）。"""
        signals = strategy.generate_signals(price_data)
        return self.run(price_data, signals, plot=plot)
