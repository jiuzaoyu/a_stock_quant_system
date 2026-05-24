import pandas as pd

from src.strategy import CTA


def test_cta_generate_signals():
    df = pd.DataFrame(
        {
            "date": pd.date_range("2024-01-01", periods=60),
            "close": range(60),
            "open": range(60),
            "high": range(60),
            "low": range(60),
            "volume": [1000] * 60,
        }
    )
    strategy = CTA(fast_period=5, slow_period=20)
    out = strategy.generate_signals(df)
    assert "signal" in out.columns
    assert out["signal"].isin([-1, 0, 1]).all()
