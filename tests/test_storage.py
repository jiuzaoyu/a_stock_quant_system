import os

import pandas as pd
import pytest

from src.data.storage import DailyStorage


@pytest.fixture
def storage():
    """创建 DailyStorage 实例。需要 DATABASE_URL 环境变量指向测试 PostgreSQL。"""
    if not os.getenv("DATABASE_URL"):
        pytest.skip("需要 DATABASE_URL 环境变量配置测试 PostgreSQL")
    s = DailyStorage()
    s.init_schema()
    yield s
    # 清理测试数据
    conn = s.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM daily WHERE ts_code LIKE 'TEST%'")
        conn.commit()
    finally:
        s.return_conn(conn)


def test_schema_and_quality_summary(storage):
    conn = storage.connect()
    df = pd.DataFrame(
        {
            "ts_code": ["TEST001", "TEST001"],
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
    try:
        storage.append_daily(conn, df)
        conn.commit()
        summary = storage.quality_summary(conn)
        assert summary["total_rows"] >= 2
        assert summary["stock_count"] >= 1
    finally:
        storage.return_conn(conn)
