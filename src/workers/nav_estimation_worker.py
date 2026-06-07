"""
Nav Estimation Worker — 监听 Redis Stream，执行盘中净值估算。

监听流: cron:jobs:nav_estimation
Job 类型: nav_estimation
"""

import logging
from datetime import date as _date
from pathlib import Path

from redis import Redis

from src.fund_collector import FundStorage
from src.strategy.nav_estimator import NavEstimator
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker

log = get_logger(__name__)

SUGGESTION_LABELS = {
    "CLEAR": "清仓",
    "REDUCE": "减仓",
    "BUY": "加仓",
    "HOLD": "持有观望",
}


def _is_trading_day() -> bool:
    """简单判断是否为交易日（周末不交易）。"""
    return _date.today().weekday() < 5


def create_nav_estimation_worker(
    redis_client: Redis,
    config_path: str | None = None,
) -> BaseWorker:
    """创建净值估算 Worker。"""
    storage = FundStorage()
    storage.init_schema()

    estimator = NavEstimator(storage, config_path=config_path)

    worker = BaseWorker(
        redis_client,
        stream="cron:jobs:nav_estimation",
        group="nav_estimation_group",
        consumer="nav_estimation_consumer_1",
    )
    worker.register(
        "nav_estimation",
        _make_handler(storage, estimator),
    )
    return worker


def _make_handler(storage: FundStorage, estimator: NavEstimator):
    def handler(data: dict[str, str]) -> None:
        log.info("=== 盘中净值估算开始 ===")

        if not _is_trading_day():
            log.info("今日非交易日，跳过估算")
            return

        conn = storage.connect()
        try:
            results = estimator.estimate_all(conn)
            conn.commit()

            log.info("净值估算完成，共 %d 只基金", len(results))
            _print_summary(results)
        except Exception:
            log.exception("净值估算失败")
            conn.rollback()
            raise
        finally:
            storage.return_conn(conn)

    return handler


def _print_summary(results: list[dict]) -> None:
    """输出估算结果摘要（日志 + 终端）。"""
    lines = []
    lines.append("=" * 78)
    lines.append(f"  盘中净值估算 — {_date.today().isoformat()} 14:30")
    lines.append("=" * 78)
    lines.append(f"  {'基金代码':<8} {'基金名称':<26} {'估算净值':>8} {'涨跌%':>7} {'累计盈亏%':>8} {'建议':<8}")
    lines.append("-" * 78)

    for r in results:
        suggestion_cn = SUGGESTION_LABELS.get(r["suggestion"], r["suggestion"])
        fund_code = r.get("fund_code", "")
        current_nav = r.get("current_nav")
        nav_str = f"{current_nav:>.4f}" if current_nav else "N/A"
        fund_name = r.get("fund_name", "")
        lines.append(
            f"  {fund_code:<8} "
            f"{_truncate(fund_name, 26):<26} "
            f"{nav_str:>8} "
            f"{r.get('daily_pnl_pct', 0):>+7.2f} "
            f"{r.get('total_pnl_pct', 0):>+8.2f} "
            f"{suggestion_cn:<8}"
        )

    lines.append("-" * 78)
    total_pnl = sum(r.get("total_pnl", 0) or 0 for r in results)
    daily = sum(r.get("daily_pnl", 0) or 0 for r in results)
    lines.append(f"  当日估算盈亏: {daily:+.2f}    累计盈亏: {total_pnl:+.2f}")
    lines.append("=" * 78)

    summary = "\n".join(lines)
    log.info("估算结果:\n%s", summary)
    print(summary)


def _truncate(s: str, width: int) -> str:
    """截断中英文混排字符串到指定显示宽度。"""
    w = 0
    result = []
    for ch in s:
        w += 2 if '一' <= ch <= '鿿' or '　' <= ch <= '〿' else 1
        if w > width:
            break
        result.append(ch)
    return "".join(result)
