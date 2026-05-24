import pandas as pd

from src.backtest import BacktestEngine
from src.strategy import CTA


def _sample_ohlcv(n: int = 80) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=n),
            "open": range(n),
            "high": range(n),
            "low": range(n),
            "close": [10 + i * 0.1 for i in range(n)],
            "volume": [1000] * n,
        }
    )


def test_engine_run_with_precomputed_signals():
    ohlcv = _sample_ohlcv()
    signals = CTA(fast_period=5, slow_period=20).generate_signals(ohlcv)
    result = BacktestEngine(initial_cash=100000).run(ohlcv, signals)
    assert "return_pct" in result
    assert result["end_value"] > 0
