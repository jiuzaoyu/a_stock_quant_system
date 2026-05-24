import pandas as pd
import pytest

from src.data import DataProcessor


def test_clean_ohlcv_dedup_and_sort():
    df = pd.DataFrame(
        {
            "date": ["2024-01-02", "2024-01-01", "2024-01-02"],
            "open": [10, 9, 10],
            "high": [11, 10, 11],
            "low": [9, 8, 9],
            "close": [10.5, 9.5, 10.5],
            "volume": [100, 200, 100],
        }
    )
    out = DataProcessor.clean_ohlcv(df)
    assert len(out) == 2
    assert out["date"].is_monotonic_increasing


def test_clean_ohlcv_missing_columns():
    with pytest.raises(ValueError, match="缺少字段"):
        DataProcessor.clean_ohlcv(pd.DataFrame({"date": ["2024-01-01"], "close": [1]}))
