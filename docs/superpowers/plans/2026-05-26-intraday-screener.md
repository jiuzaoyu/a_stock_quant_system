# 盘中实时选股筛选器 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在交易日 14:30 自动筛选符合量价条件的 A 股，输出 CSV

**Architecture:** 新增 `src/screener/` 模块，复用现有 `DataFetcher` 拉数据。filters.py 提供纯函数筛选条件，engine.py 编排全流程，scheduler.py 封装 APScheduler + 交易日判断。参数由 `config/screener.yaml` 驱动。

**Tech Stack:** Python 3.11, AKShare, APScheduler, pandas, pytest

**New files:**
- `config/screener.yaml` — 筛选阈值 + 调度配置
- `src/screener/__init__.py` — 公开 API 导出
- `src/screener/filters.py` — 每个筛选条件一个纯函数
- `src/screener/engine.py` — `ScreenerEngine` 编排全流程
- `src/screener/scheduler.py` — APScheduler 封装 + 交易日判断
- `scripts/run_screener.py` — 启动入口（`--manual` 手动单次）
- `tests/test_screener.py` — 单元测试 + 集成测试

---

### Task 1: 创建配置文件 `config/screener.yaml`

**Files:**
- Create: `config/screener.yaml`

- [ ] **Step 1: 写入配置文件**

```yaml
# 盘中选股筛选器配置
screener:
  scheduler:
    trigger_time: "14:30"
    timezone: "Asia/Shanghai"
    max_instances: 1
    misfire_grace_time: 300

  filters:
    market_cap:
      min: 50    # 亿
      max: 200
    pct_change:
      min: 3     # %
      max: 5
    volume_ratio:
      min: 1.0
    turnover_rate:
      min: 5
      max: 10
    limit_up_history:
      days: 20           # 近N个交易日
      threshold: 9.8     # 涨停阈值 %
    vwap:
      mode: "above"      # 股价全天在分时均线上方

  output:
    dir: "output/screener"
    format: "csv"

  data_source:
    primary: "akshare"
    fallback: "jqdata"
```

- [ ] **Step 2: 验证 YAML 格式正确**

```bash
python -c "import yaml; yaml.safe_load(open('config/screener.yaml')); print('OK')"
```

---

### Task 2: 创建筛选函数模块 `src/screener/filters.py`

**Files:**
- Create: `src/screener/filters.py`

- [ ] **Step 1: 写筛选函数模块**

```python
"""筛选条件纯函数 — 每个函数输入 DataFrame，返回过滤后的 DataFrame 或 bool"""

from typing import List

import pandas as pd


def filter_by_market_cap(df: pd.DataFrame, min_cap: float, max_cap: float) -> pd.DataFrame:
    """筛选市值在 [min_cap, max_cap] 亿之间的股票。

    df 需包含 '总市值' 列（AKShare stock_zh_a_spot_em 输出，单位：元）
    """
    cap_yuan_min = min_cap * 1e8
    cap_yuan_max = max_cap * 1e8
    return df[(df["总市值"] >= cap_yuan_min) & (df["总市值"] <= cap_yuan_max)]


def filter_by_pct_change(df: pd.DataFrame, min_pct: float, max_pct: float) -> pd.DataFrame:
    """筛选涨跌幅在 [min_pct, max_pct] 之间的股票。

    df 需包含 '涨跌幅' 列（百分比数值，如 3.5 表示 3.5%）
    """
    return df[(df["涨跌幅"] >= min_pct) & (df["涨跌幅"] <= max_pct)]


def filter_by_volume_ratio(df: pd.DataFrame, min_ratio: float) -> pd.DataFrame:
    """筛选量比 >= min_ratio 的股票。

    df 需包含 '量比' 列
    """
    return df[df["量比"] >= min_ratio]


def filter_by_turnover_rate(df: pd.DataFrame, min_rate: float, max_rate: float) -> pd.DataFrame:
    """筛选换手率在 [min_rate, max_rate] 之间的股票。

    df 需包含 '换手率' 列（百分比数值，如 7.5 表示 7.5%）
    """
    return df[(df["换手率"] >= min_rate) & (df["换手率"] <= max_rate)]


def has_limit_up_in_history(
    daily_df: pd.DataFrame, days: int = 20, threshold: float = 9.8
) -> bool:
    """检查近 N 个交易日内是否出现过涨停（涨幅 >= threshold）。

    daily_df 需包含 '涨跌幅' 列（AKShare stock_zh_a_hist 输出），
    按日期升序排列，取最近 N 行。
    """
    recent = daily_df.tail(days)
    return (recent["涨跌幅"] >= threshold).any()


def check_vwap_above(minute_df: pd.DataFrame) -> bool:
    """检查全天所有分钟K线的 low 是否都在分时均线(VWAP)上方。

    minute_df 需包含 '最低', '成交量', '成交额' 列，
    VWAP = 累计成交额 / 累计成交量。
    返回 True 表示所有 K 线的 low >= VWAP。
    """
    if minute_df.empty:
        return False

    cum_turnover = minute_df["成交额"].cumsum()
    cum_volume = minute_df["成交量"].cumsum()

    mask = cum_volume > 0
    vwap = pd.Series(0.0, index=minute_df.index)
    vwap[mask] = cum_turnover[mask] / cum_volume[mask]

    return (minute_df["最低"] >= vwap).all()


def get_stock_codes(df: pd.DataFrame) -> List[str]:
    """从 spot DataFrame 提取股票代码列表。"""
    return df["代码"].tolist()
```

---

### Task 3: 创建筛选引擎 `src/screener/engine.py`

**Files:**
- Create: `src/screener/engine.py`

- [ ] **Step 1: 写筛选引擎**

```python
"""筛选引擎 — 编排：拉数据 → 预筛选 → 精细筛选 → 输出 CSV"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import akshare as ak
import pandas as pd

from .filters import (
    check_vwap_above,
    filter_by_market_cap,
    filter_by_pct_change,
    filter_by_turnover_rate,
    filter_by_volume_ratio,
    get_stock_codes,
    has_limit_up_in_history,
)

log = logging.getLogger(__name__)


class ScreenerEngine:
    """盘中选股筛选引擎。

    不依赖调度器，可独立调用 run() 进行手动筛选。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.filters_cfg = self.config.get("filters", {})
        self.output_cfg = self.config.get("output", {})

    def run(self) -> pd.DataFrame:
        """执行筛选全流程，返回命中股票 DataFrame。"""
        log.info("开始盘中选股筛选…")

        # 1. 拉全市场实时快照
        df = self._fetch_market_snapshot()
        log.info("全市场快照: %d 只股票", len(df))

        # 2. 预筛选（DataFrame 级，快）
        df = self._prefilter(df)
        log.info("预筛选后: %d 只", len(df))

        if df.empty:
            log.info("预筛选无命中，结束")
            return df

        # 3. 涨停历史过滤（需逐只拉日线）
        df = self._filter_limit_up_history(df)
        log.info("涨停历史过滤后: %d 只", len(df))

        if df.empty:
            log.info("涨停历史过滤无命中，结束")
            return df

        # 4. 分时均线过滤（需逐只拉分钟线，放最后）
        df = self._filter_vwap(df)
        log.info("分时均线过滤后: %d 只", len(df))

        # 5. 输出 CSV
        self._save_to_csv(df)

        log.info("筛选完成，最终命中: %d 只", len(df))
        return df

    def _fetch_market_snapshot(self) -> pd.DataFrame:
        """拉取全市场实时行情快照。"""
        return ak.stock_zh_a_spot_em()

    def _prefilter(self, df: pd.DataFrame) -> pd.DataFrame:
        """执行快速预筛选（市值、涨幅、量比、换手率）。"""
        mc = self.filters_cfg.get("market_cap", {})
        pc = self.filters_cfg.get("pct_change", {})
        vr = self.filters_cfg.get("volume_ratio", {})
        tr = self.filters_cfg.get("turnover_rate", {})

        df = filter_by_market_cap(df, mc.get("min", 50), mc.get("max", 200))
        df = filter_by_pct_change(df, pc.get("min", 3), pc.get("max", 5))
        df = filter_by_volume_ratio(df, vr.get("min", 1.0))
        df = filter_by_turnover_rate(df, tr.get("min", 5), tr.get("max", 10))
        return df

    def _filter_limit_up_history(self, df: pd.DataFrame) -> pd.DataFrame:
        """对候选股逐只检查近20日是否有涨停。"""
        lu_cfg = self.filters_cfg.get("limit_up_history", {})
        days = lu_cfg.get("days", 20)
        threshold = lu_cfg.get("threshold", 9.8)

        end_date = datetime.now().strftime("%Y%m%d")
        start_date = _shift_date_for_trading_days(days + 5)

        results = []
        for code in get_stock_codes(df):
            try:
                daily = ak.stock_zh_a_hist(
                    symbol=code,
                    period="daily",
                    start_date=start_date,
                    end_date=end_date,
                    adjust="qfq",
                )
                if has_limit_up_in_history(daily, days=days, threshold=threshold):
                    results.append(code)
            except Exception:
                log.debug("拉取 %s 日线失败，跳过", code)

        return df[df["代码"].isin(results)]

    def _filter_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """对候选股逐只检查分时均线位置。"""
        results = []
        for code in get_stock_codes(df):
            try:
                minute_df = ak.stock_zh_a_hist_min_em(symbol=code)
                if check_vwap_above(minute_df):
                    results.append(code)
            except Exception:
                log.debug("拉取 %s 分钟线失败，跳过", code)

        return df[df["代码"].isin(results)]

    def _save_to_csv(self, df: pd.DataFrame) -> None:
        """输出筛选结果到 CSV（含时分防覆盖）。"""
        output_dir = Path(self.output_cfg.get("dir", "output/screener"))
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = output_dir / f"{timestamp}.csv"

        if df.empty:
            log.info("无命中股票，不生成 CSV")
            return

        df.to_csv(path, index=False, encoding="utf-8-sig")
        log.info("结果已保存: %s", path)


def _shift_date_for_trading_days(offset_days: int) -> str:
    """粗略估算起始日期：往前推 offset_days 个自然日。"""
    from datetime import timedelta

    return (datetime.now() - timedelta(days=offset_days)).strftime("%Y%m%d")
```

---

### Task 4: 创建调度器 `src/screener/scheduler.py`

**Files:**
- Create: `src/screener/scheduler.py`

- [ ] **Step 1: 写调度器模块**

```python
"""APScheduler 封装 + 交易日判断"""

import logging
from datetime import date, datetime
from typing import Any, Dict, Optional

import akshare as ak
import pandas as pd
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

log = logging.getLogger(__name__)


def is_trading_day(check_date: Optional[date] = None) -> bool:
    """判断 check_date 是否为 A 股交易日。

    使用 AKShare 交易日历接口。
    """
    if check_date is None:
        check_date = date.today()

    try:
        trade_df = ak.tool_trade_date_hist_sina()
        trade_dates = set(
            trade_df["trade_date"].dt.date
            if hasattr(trade_df["trade_date"], "dt")
            else pd.to_datetime(trade_df["trade_date"]).dt.date
        )
        return check_date in trade_dates
    except Exception:
        log.warning("交易日历获取失败，假定为交易日")
        return True


def create_scheduler(engine: Any, trigger_time: str = "14:30", timezone: str = "Asia/Shanghai") -> BackgroundScheduler:
    """创建并配置后台调度器。

    Args:
        engine: ScreenerEngine 实例
        trigger_time: 触发时间，格式 "HH:MM"
        timezone: 时区
    """
    scheduler = BackgroundScheduler(timezone=timezone)
    hour, minute = map(int, trigger_time.split(":"))

    scheduler.add_job(
        _screener_job,
        CronTrigger(hour=hour, minute=minute, timezone=timezone),
        args=[engine],
        id="intraday_screener",
        name="盘中选股筛选",
        max_instances=1,
        misfire_grace_time=300,
    )

    log.info("调度器已配置: 交易日 %s 触发", trigger_time)
    return scheduler


def _screener_job(engine: Any) -> None:
    """调度器回调：判断交易日 → 执行筛选。"""
    if not is_trading_day():
        log.info("今日非交易日，跳过筛选")
        return

    log.info("=== 盘中选股筛选开始 ===")
    start = datetime.now()
    try:
        engine.run()
    except Exception:
        log.exception("筛选过程异常")
    elapsed = (datetime.now() - start).total_seconds()
    log.info("=== 筛选结束，耗时 %.1f 秒 ===", elapsed)


def run_scheduler(config: Dict[str, Any], engine: Any) -> BackgroundScheduler:
    """便捷函数：根据配置启动调度器。"""
    sc = config.get("scheduler", {})
    scheduler = create_scheduler(
        engine,
        trigger_time=sc.get("trigger_time", "14:30"),
        timezone=sc.get("timezone", "Asia/Shanghai"),
    )
    scheduler.start()
    log.info("调度器已启动，等待触发… (Ctrl+C 退出)")
    return scheduler
```

---

### Task 5: 创建模块导出 `src/screener/__init__.py`

**Files:**
- Create: `src/screener/__init__.py`

- [ ] **Step 1: 写 __init__.py**

```python
"""盘中选股筛选模块 — 交易日 14:30 自动筛选 + 手动触发"""

from .engine import ScreenerEngine
from .scheduler import is_trading_day, run_scheduler

__all__ = [
    "ScreenerEngine",
    "is_trading_day",
    "run_scheduler",
]
```

---

### Task 6: 创建启动脚本 `scripts/run_screener.py`

**Files:**
- Create: `scripts/run_screener.py`

- [ ] **Step 1: 写启动脚本**

```python
"""盘中选股筛选器启动入口

用法:
    python scripts/run_screener.py           # 启动调度器（交易日 14:30 触发）
    python scripts/run_screener.py --manual   # 手动单次执行
"""

import argparse
import sys
import time
from pathlib import Path

# 确保项目根目录在 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.screener import ScreenerEngine, run_scheduler
from src.utils.config import load_config
from src.utils.logger import get_logger, setup_logging


def main():
    parser = argparse.ArgumentParser(description="盘中选股筛选器")
    parser.add_argument(
        "--manual", "-m",
        action="store_true",
        help="手动单次执行（不启动调度器）",
    )
    args = parser.parse_args()

    cfg = load_config()
    screener_cfg = cfg.get("screener", {})

    setup_logging(level="INFO", log_file=ROOT / "logs" / "screener.log")
    log = get_logger(__name__)

    engine = ScreenerEngine(config=screener_cfg)

    if args.manual:
        log.info("手动单次执行…")
        df = engine.run()
        print(f"\n命中 {len(df)} 只股票:")
        if not df.empty:
            cols = ["代码", "名称", "涨跌幅", "量比", "换手率", "总市值"]
            available = [c for c in cols if c in df.columns]
            print(df[available].to_string(index=False))
    else:
        log.info("启动调度器模式…")
        scheduler = run_scheduler(screener_cfg, engine)
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            log.info("收到退出信号")
            scheduler.shutdown()


if __name__ == "__main__":
    main()
```

---

### Task 7: 创建测试文件 `tests/test_screener.py`

**Files:**
- Create: `tests/test_screener.py`

- [ ] **Step 1: 写单元测试（筛选函数 + 交易日判断）**

```python
"""盘中筛选器测试"""

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.screener import ScreenerEngine, is_trading_day
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
    turns = [v * 10.1 for v in vols]
    df = _make_minute_df(low_values=lows, volume_values=vols, turnover_values=turns)
    assert check_vwap_above(df)


def test_check_vwap_above_one_below():
    """有一根 K 线 low 跌破 VWAP"""
    lows = [10.05] * 240
    lows[100] = 9.5  # 中间某根跌破
    vols = [10000] * 240
    turns = [v * 10.1 for v in vols]
    df = _make_minute_df(low_values=lows, volume_values=vols, turnover_values=turns)
    assert not check_vwap_above(df)


def test_check_vwap_above_empty():
    df = pd.DataFrame()
    assert not check_vwap_above(df)


def test_get_stock_codes():
    df = _make_spot_df()
    codes = get_stock_codes(df)
    assert codes == ["000001", "000002", "600519", "300750", "688001"]


# ── 交易日判断测试 ──


def test_is_trading_day_mocked():
    """用 mock 验证交易日判断逻辑"""
    mock_df = pd.DataFrame({
        "trade_date": pd.to_datetime(["2026-05-25", "2026-05-26", "2026-05-27"])
    })
    with patch("akshare.tool_trade_date_hist_sina", return_value=mock_df):
        assert is_trading_day(date(2026, 5, 26))
        assert not is_trading_day(date(2026, 5, 24))


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
        minute_df = _make_minute_df()

        with patch.object(ScreenerEngine, "_fetch_market_snapshot", return_value=spot_df):
            with patch("src.screener.engine.ak.stock_zh_a_hist", return_value=daily_df):
                with patch("src.screener.engine.ak.stock_zh_a_hist_min_em", return_value=minute_df):
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
```

- [ ] **Step 2: 运行测试确认全部通过**

```bash
pytest tests/test_screener.py -v
```

预期：全部 PASS（网络请求被 mock，无需联网）

---

### Task 8: 验证 `--manual` 模式可运行

**Files:**
- (无新建文件，验证已有代码)

- [ ] **Step 1: 用 mock 数据跑 `--manual` 模式确认脚本不报错**

```bash
python -c "
import sys; sys.path.insert(0, '.')
from unittest.mock import patch, MagicMock
from src.screener import ScreenerEngine

# Mock akshare import inside engine
with patch('src.screener.engine.ak') as mock_ak:
    mock_ak.stock_zh_a_spot_em.return_value = __import__('pandas').DataFrame()
    mock_ak.stock_zh_a_hist.return_value = __import__('pandas').DataFrame()
    mock_ak.stock_zh_a_hist_min_em.return_value = __import__('pandas').DataFrame()
    engine = ScreenerEngine(config={})
    result = engine.run()
    print('Manual run OK, result:', len(result), 'stocks')
"
```

预期：输出 "Manual run OK, result: 0 stocks"

---

### Task 9: 跑完整测试套件确认无回归

**Files:**
- (验证所有现有测试仍然通过)

- [ ] **Step 1: 运行全量测试**

```bash
pytest tests/ -v
```

预期：所有已有测试 + 新测试全部 PASS
