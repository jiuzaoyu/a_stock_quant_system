import pandas as pd

from src.data.storage import DailyStorage


def test_schema_and_quality_summary(tmp_path):
    db = tmp_path / "test.db"
    storage = DailyStorage(db)
    storage.init_schema()
    conn = storage.connect()
    df = pd.DataFrame(
        {
            "ts_code": ["000001", "000001"],
            "trade_date": ["2024-01-01", "2024-01-02"],
            "open": [1.0, 1.1],
            "high": [1.2, 1.3],
            "low": [0.9, 1.0],
            "close": [1.1, 1.2],
            "volume": [100, 200],
            "amount": [1000, 2000],
            "pct_change": [0.1, 0.2],
            "turnover": [1.0, 2.0],
        }
    )
    storage.append_daily(conn, df)
    conn.commit()
    conn.close()
    summary = storage.quality_summary()
    assert summary["total_rows"] == 2
    assert summary["stock_count"] == 1
