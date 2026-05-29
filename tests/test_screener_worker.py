from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from src.workers.screener_worker import is_trading_day


class TestIsTradingDay:
    def test_returns_true_when_date_in_calendar(self):
        mock_df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-29", "2026-05-28"])})
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", return_value=mock_df):
            assert is_trading_day(date(2026, 5, 29)) is True

    def test_returns_false_when_date_not_in_calendar(self):
        mock_df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-29", "2026-05-28"])})
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", return_value=mock_df):
            assert is_trading_day(date(2026, 5, 30)) is False

    def test_returns_true_on_api_failure(self):
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", side_effect=Exception("API down")):
            assert is_trading_day(date(2026, 5, 29)) is True
