"""盘中筛选器测试"""

from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.screener import ScreenerEngine
from src.screener.filters import (
    check_vwap_above,
    filter_by_market_cap,
    filter_by_pct_change,
    filter_by_turnover_rate,
    filter_by_volume_ratio,
    get_stock_codes,
    has_limit_up_in_history,
)


# ── 构造测试 DataFrame ──

def _make_spot_df() -> pd.DataFrame:
    """模拟 stock_zh_a_spot_em 输出。"""
    return pd.DataFrame({
        "代码": ["000001", "000002", "600519", "300750", "688001"],
        "名称": ["平安银行", "万科A", "贵州茅台", "宁德时代", "华兴源创"],
        "最新价": [12.0, 15.0, 1800.0, 200.0, 30.0],
        "涨跌幅": [2.0, 4.0, 3.5, 6.0, 1.5],
        "量比": [1.5, 0.8, 2.0, 1.2, 0.6],
        "换手率": [3.0, 7.0, 5.5, 12.0, 2.0],
        "总市值": [
            1800e8,   # 1800亿 → 超出50-200亿
            120e8,    # 120亿  → 符合
            22000e8,  # 2.2万亿 → 超出
            9000e8,   # 9000亿 → 超出
            60e8,     # 60亿   → 符合
        ],
        "成交额": [1e8, 2e8, 5e9, 3e9, 0.5e8],
        "成交量": [800000, 1300000, 2800000, 1500000, 1600000],
    })


def _make_daily_df(pct_changes=None):
    """模拟 stock_zh_a_hist 输出（30 天数据）。"""
    if pct_changes is None:
        pct_changes = [1.0] * 30
    dates = pd.date_range(end="2026-05-26", periods=30)
    return pd.DataFrame({
        "日期": dates,
        "开盘": [10.0] * 30,
        "收盘": [10.1] * 30,
        "最高": [10.2] * 30,
        "最低": [9.9] * 30,
        "成交量": [1e6] * 30,
        "成交额": [1e7] * 30,
        "涨跌幅": pct_changes,
    })


def _make_minute_df(low_values=None, volume_values=None, turnover_values=None):
    """模拟 stock_zh_a_hist_min_em 输出（240 分钟数据）。"""
    n = len(low_values) if low_values else 240
    times = pd.date_range("2026-05-26 09:30", periods=n, freq="1min")
    lows = low_values if low_values else [10.0] * n
    vols = volume_values if volume_values else [10000] * n
    turns = turnover_values if turnover_values else [v * 10.05 for v in vols]
    return pd.DataFrame({
        "时间": times,
        "开盘": [10.1] * n,
        "收盘": [10.1] * n,
        "最高": [10.2] * n,
        "最低": lows,
        "成交量": vols,
        "成交额": turns,
    })


# ── 纯函数测试 ──


def test_filter_by_market_cap_in_range():
    df = _make_spot_df()
    result = filter_by_market_cap(df, min_cap=50, max_cap=200)
    codes = result["代码"].tolist()
    assert "000002" in codes    # 120亿
    assert "688001" in codes    # 60亿
    assert "600519" not in codes  # 2.2万亿
    assert "000001" not in codes  # 1800亿


def test_filter_by_pct_change():
    df = _make_spot_df()
    result = filter_by_pct_change(df, min_pct=3, max_pct=5)
    codes = result["代码"].tolist()
    assert "000002" in codes   # 4.0
    assert "600519" in codes   # 3.5
    assert "300750" not in codes  # 6.0
    assert "000001" not in codes  # 2.0


def test_filter_by_volume_ratio():
    df = _make_spot_df()
    result = filter_by_volume_ratio(df, min_ratio=1.0)
    codes = result["代码"].tolist()
    assert "000001" in codes   # 1.5
    assert "000002" not in codes  # 0.8


def test_filter_by_turnover_rate():
    df = _make_spot_df()
    result = filter_by_turnover_rate(df, min_rate=5, max_rate=10)
    codes = result["代码"].tolist()
    assert "000002" in codes   # 7.0
    assert "600519" in codes   # 5.5
    assert "000001" not in codes  # 3.0


def test_has_limit_up_in_history_true():
    pct = [1.0] * 28 + [10.0, 2.0]  # 倒数第2天涨停
    df = _make_daily_df(pct_changes=pct)
    assert has_limit_up_in_history(df, days=20, threshold=9.8)


def test_has_limit_up_in_history_false():
    pct = [1.0] * 30
    df = _make_daily_df(pct_changes=pct)
    assert not has_limit_up_in_history(df, days=20, threshold=9.8)


def test_has_limit_up_outside_window():
    """涨停发生在20天窗口之外"""
    pct = [10.0] + [1.0] * 29  # 第1天（30天前）涨停
    df = _make_daily_df(pct_changes=pct)
    assert not has_limit_up_in_history(df, days=20, threshold=9.8)


def test_check_vwap_above_all_above():
    """所有 K 线 low 都在 VWAP 上方"""
    lows = [10.05] * 240
    vols = [10000] * 240
    turns = [v * 10.04 for v in vols]
    df = _make_minute_df(low_values=lows, volume_values=vols, turnover_values=turns)
    assert check_vwap_above(df)


def test_check_vwap_above_one_below():
    """有一根 K 线 low 跌破 VWAP"""
    lows = [10.05] * 240
    lows[100] = 9.5  # 中间某根跌破
    vols = [10000] * 240
    turns = [v * 10.04 for v in vols]
    df = _make_minute_df(low_values=lows, volume_values=vols, turnover_values=turns)
    assert not check_vwap_above(df)


def test_check_vwap_above_empty():
    df = pd.DataFrame()
    assert not check_vwap_above(df)


def test_get_stock_codes():
    df = _make_spot_df()
    codes = get_stock_codes(df)
    assert codes == ["000001", "000002", "600519", "300750", "688001"]


# ── 引擎集成测试 ──


class TestScreenerEngine:
    """ScreenerEngine 集成测试（mock AKShare API）"""

    def test_run_empty_after_prefilter(self):
        """预筛选后无命中，直接返回空 DataFrame"""
        with patch.object(
            ScreenerEngine, "_fetch_market_snapshot", return_value=_make_spot_df()
        ):
            cfg = {
                "filters": {
                    "market_cap": {"min": 50, "max": 200},
                    "pct_change": {"min": 3, "max": 5},
                    "volume_ratio": {"min": 1.0},
                    "turnover_rate": {"min": 5, "max": 10},
                },
                "output": {"dir": "output/screener"},
            }
            engine = ScreenerEngine(config=cfg)
            result = engine.run()
            assert isinstance(result, pd.DataFrame)

    def test_run_full_pipeline(self):
        """全流程 mock 测试"""
        spot_df = pd.DataFrame({
            "代码": ["000002"],
            "名称": ["万科A"],
            "涨跌幅": [4.0],
            "量比": [1.5],
            "换手率": [7.0],
            "总市值": [120e8],
            "最新价": [15.0],
        })

        daily_df = _make_daily_df([1.0] * 28 + [10.0, 2.0])
        # VWAP = 100000/10000 = 10.0 = low, so check_vwap_above passes
        minute_df = _make_minute_df(
            low_values=[10.0] * 240,
            volume_values=[10000] * 240,
            turnover_values=[100000] * 240,
        )

        with patch.object(ScreenerEngine, "_fetch_market_snapshot", return_value=spot_df):
            with patch.object(ScreenerEngine, "_fetch_daily", return_value=daily_df):
                with patch.object(ScreenerEngine, "_fetch_minute", return_value=minute_df):
                    cfg = {
                        "filters": {
                            "market_cap": {"min": 50, "max": 200},
                            "pct_change": {"min": 3, "max": 5},
                            "volume_ratio": {"min": 1.0},
                            "turnover_rate": {"min": 5, "max": 10},
                            "limit_up_history": {"days": 20, "threshold": 9.8},
                            "vwap": {"mode": "above"},
                        },
                        "output": {"dir": "output/screener"},
                    }
                    engine = ScreenerEngine(config=cfg)
                    result = engine.run()
                    assert len(result) == 1
                    assert result.iloc[0]["代码"] == "000002"
