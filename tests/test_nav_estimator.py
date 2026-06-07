"""净值估算引擎单元测试"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.strategy.nav_estimator import NavEstimator, DEFAULT_RULES


# ============================================================================
# generate_suggestion 测试
# ============================================================================


class TestGenerateSuggestion:
    """操作建议生成逻辑测试。"""

    def setup_method(self):
        self.estimator = NavEstimator.__new__(NavEstimator)
        self.estimator._rules = DEFAULT_RULES.copy()

    def test_hold_normal(self):
        """正常情况 — 建议持有。"""
        assert self.estimator.generate_suggestion(5.0, 0.5) == "HOLD"
        assert self.estimator.generate_suggestion(-3.0, -1.0) == "HOLD"

    def test_clear_high_profit_big_drop(self):
        """高盈利 + 大跌 → 清仓止盈。"""
        assert self.estimator.generate_suggestion(35.0, -2.0) == "CLEAR"

    def test_reduce_moderate_profit_drop(self):
        """中等盈利 + 下跌 → 减仓止盈。"""
        assert self.estimator.generate_suggestion(18.0, -2.5) == "REDUCE"

    def test_clear_stop_loss(self):
        """大幅亏损 → 止损清仓。"""
        assert self.estimator.generate_suggestion(-12.0, 1.0) == "CLEAR"
        assert self.estimator.generate_suggestion(-10.5, 0.0) == "CLEAR"

    def test_reduce_stop_loss(self):
        """中度亏损 + 大跌 → 减仓止损。"""
        assert self.estimator.generate_suggestion(-7.0, -3.0) == "REDUCE"

    def test_buy_on_dip(self):
        """亏损中 + 当日大涨 → 加仓摊薄。"""
        assert self.estimator.generate_suggestion(-3.0, 3.0) == "BUY"

    def test_no_clear_at_moderate_profit(self):
        """盈利30%但当日未大跌 → 不清仓。"""
        assert self.estimator.generate_suggestion(32.0, -1.0) == "HOLD"

    def test_no_reduce_at_high_profit_without_drop(self):
        """盈利20%但当日未跌 → 不减仓。"""
        assert self.estimator.generate_suggestion(20.0, 1.0) == "HOLD"

    def test_boundary_clear_profit(self):
        """清仓边界值测试。"""
        # 刚好超过阈值
        assert self.estimator.generate_suggestion(30.1, -1.6) == "CLEAR"
        # 恰好等于阈值 — 不触发
        assert self.estimator.generate_suggestion(30.0, -1.5) == "HOLD"

    def test_boundary_clear_loss(self):
        """止损边界值测试。"""
        assert self.estimator.generate_suggestion(-10.1, 0.0) == "CLEAR"
        assert self.estimator.generate_suggestion(-9.9, 0.0) == "HOLD"


# ============================================================================
# estimate_all 集成测试（Mock）
# ============================================================================


class TestEstimateAll:
    """使用 Mock 测试完整的估算流程。"""

    def setup_method(self):
        self.storage = MagicMock()
        self.estimator = NavEstimator(self.storage)

    def test_empty_holdings(self):
        """无持仓时应返回空列表。"""
        self.storage.get_user_holdings.return_value = []
        conn = MagicMock()
        result = self.estimator.estimate_all(conn)
        assert result == []

    @patch("src.strategy.nav_estimator.fetch_realtime_batch")
    def test_single_fund_estimation(self, mock_fetch):
        """单只基金正常估算。"""
        mock_fetch.return_value = {
            "600519": {"code": "600519", "name": "贵州茅台", "change_pct": 2.5},
            "000858": {"code": "000858", "name": "五粮液", "change_pct": 1.8},
        }

        self.storage.get_user_holdings.return_value = [
            {"id": 1, "fund_code": "161725", "fund_name": "招商中证白酒指数(LOF)A",
             "buy_net_value": 1.2, "shares": 10000.0, "buy_date": "2026-01-15",
             "is_qdii": False, "industry_sector": "白酒", "source": "ali"},
        ]
        self.storage.get_latest_nav.return_value = {
            "code": "161725", "nav_date": "2026-06-06", "unit_nav": 1.35,
            "accum_nav": 1.85, "daily_growth": 1.2,
        }
        self.storage.get_latest_holdings.return_value = [
            {"code": "161725", "report_date": "2026-03-31", "stock_code": "600519",
             "stock_name": "贵州茅台", "rank": 1, "nav_pct": 15.0},
            {"code": "161725", "report_date": "2026-03-31", "stock_code": "000858",
             "stock_name": "五粮液", "rank": 2, "nav_pct": 12.0},
        ]

        conn = MagicMock()
        results = self.estimator.estimate_all(conn)

        assert len(results) == 1
        r = results[0]
        assert r["fund_code"] == "161725"
        assert r["fund_name"] == "招商中证白酒指数(LOF)A"
        assert r["buy_net_value"] == 1.2
        assert r["shares"] == 10000.0
        assert r["cost"] == 12000.0
        # estimated_pct = 0.15*2.5 + 0.12*1.8 = 0.375 + 0.216 = 0.591
        assert r["daily_pnl_pct"] == pytest.approx(0.591, abs=0.01)
        # estimated_nav = 1.35 * (1 + 0.591/100) ≈ 1.35798
        assert r["current_nav"] == pytest.approx(1.3580, abs=0.001)
        # market_value = 10000 * 1.3580 ≈ 13580
        assert r["market_value"] == pytest.approx(13580, abs=1)

        # 验证持久化调用
        self.storage.insert_nav_estimation.assert_called_once()
        self.storage.upsert_user_pnl.assert_called_once()

    @patch("src.strategy.nav_estimator.fetch_qdii_proxy_quotes")
    def test_qdii_fund_estimation(self, mock_fetch):
        """QDII 基金通过代理估算。"""
        mock_fetch.return_value = {
            "nq_future": {"price": 21500.0, "change_pct": -0.8, "name": "纳斯达克100期货"},
        }

        self.storage.get_user_holdings.return_value = [
            {"id": 2, "fund_code": "024239", "fund_name": "华夏全球科技先锋混合(QDII)C",
             "buy_net_value": 2.14, "shares": 45000.0, "buy_date": "2026-03-26",
             "is_qdii": True, "industry_sector": "科技", "source": "ali"},
        ]
        self.storage.get_latest_nav.return_value = {
            "code": "024239", "nav_date": "2026-06-06", "unit_nav": 2.35,
            "accum_nav": 2.35, "daily_growth": 0.5,
        }

        conn = MagicMock()
        results = self.estimator.estimate_all(conn)

        assert len(results) == 1
        r = results[0]
        assert r["fund_code"] == "024239"
        assert r["daily_pnl_pct"] == pytest.approx(-0.8, abs=0.01)
        # current_nav = 2.35 * (1 + (-0.8)/100) = 2.3312
        # total_pnl_pct = (2.3312 - 2.14) / 2.14 * 100 ≈ 8.93
        assert r["total_pnl_pct"] == pytest.approx(8.93, abs=0.1)


# ============================================================================
# _estimate_qdii 测试
# ============================================================================


class TestQdiiEstimation:
    """QDII 代理估算专项测试。"""

    def setup_method(self):
        self.storage = MagicMock()
        self.storage.get_latest_nav.return_value = {"unit_nav": 1.5}
        self.estimator = NavEstimator(self.storage)

    @patch("src.strategy.nav_estimator.fetch_qdii_proxy_quotes")
    def test_with_proxy(self, mock_fetch):
        mock_fetch.return_value = {
            "nq_future": {"price": 21500.0, "change_pct": -0.8, "name": "纳斯达克100期货"},
        }
        result = self.estimator._estimate_qdii("024239", 1.5, {"fund_code": "024239"})
        assert result["estimated_pct"] == -0.8
        assert result["is_qdii"] is True
        assert "_proxy" in result["stock_detail"]

    @patch("src.strategy.nav_estimator.fetch_qdii_proxy_quotes")
    def test_without_proxy(self, mock_fetch):
        mock_fetch.return_value = {}
        result = self.estimator._estimate_qdii("999999", 1.5, {"fund_code": "999999"})
        assert result["estimated_pct"] == 0.0
        assert result["is_qdii"] is True


# ============================================================================
# estimate_single 测试（无重仓股）
# ============================================================================


class TestEstimateSingleEdgeCases:
    """单基金估算边界情况。"""

    def setup_method(self):
        self.storage = MagicMock()
        self.storage.get_latest_nav.return_value = {"unit_nav": 1.5}
        self.estimator = NavEstimator(self.storage)

    def test_no_holdings_data(self):
        """基金无重仓股数据时返回空结果。"""
        self.storage.get_latest_holdings.return_value = []
        conn = MagicMock()
        result = self.estimator.estimate_single(
            conn, {"fund_code": "000001", "is_qdii": False})
        assert result["estimated_pct"] == 0.0
        assert result["coverage_pct"] == 0.0
