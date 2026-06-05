import pandas as pd
import pytest

from src.data.hs300_collector import HS300DailyCollector


def test_constituent_code_extraction_from_wrong_first_column():
    """第一列是日期时，应能从「品种代码」列提取 6 位代码。"""
    df = pd.DataFrame(
        {
            "日期": ["2026-05-19"] * 3,
            "品种代码": ["000001", "600000", "300750"],
        }
    )
    col = "品种代码"
    codes = (
        df[col]
        .astype(str)
        .str.strip()
        .str.extract(r"(\d{6})", expand=False)
        .dropna()
        .unique()
        .tolist()
    )
    assert codes == ["000001", "600000", "300750"]


def test_fetch_one_rejects_date_like_code():
    c = HS300DailyCollector()
    with pytest.raises(ValueError, match="非法股票代码"):
        c.fetch_one("2026-05-19")
