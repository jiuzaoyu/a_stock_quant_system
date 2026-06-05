"""
A股日K线 + 估值数据全量采集入口（一次性 ETL 任务）。

用法（在项目根目录）:
    python scripts/collect_stock_history.py

采集目标: 全量A股，近两年日K线 + 估值数据
配置见: config/stock_collector.yaml
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.config import load_yaml
from src.utils.logger import get_logger, setup_logging
from src.stock_collector import StockCollector, StockStorage

logger = get_logger(__name__)


def main():
    cfg = load_yaml(ROOT / "config" / "stock_collector.yaml")
    stock_cfg = cfg["stock_collector"]

    setup_logging(level="INFO", log_file=ROOT / "logs" / "stock_collector.log")

    storage = StockStorage()

    collector = StockCollector(
        storage=storage,
        lookback_years=stock_cfg.get("lookback_years", 2),
        kline_category=stock_cfg.get("kline_category", 4),
        request_delay_seconds=stock_cfg.get("request_delay_seconds", 0.3),
        progress_every=stock_cfg.get("progress_every", 50),
        max_retries=stock_cfg.get("max_retries", 3),
        concurrency=stock_cfg.get("concurrency", 5),
    )

    logger.info("开始全量采集, 回溯: %d年", collector.lookback_years)
    result = collector.run()

    summary = storage.quality_summary()
    logger.info("库内概况: 股票 %s, K线记录 %s, 日期 %s ~ %s",
                 summary["total_stocks"], f"{summary['total_daily_rows']:,}",
                 summary["daily_date_min"], summary["daily_date_max"])
    logger.info("估值记录: %s, 日期 %s ~ %s",
                 f"{summary.get('total_valuation_rows', '?'):,}",
                 summary.get("valuation_date_min", "?"),
                 summary.get("valuation_date_max", "?"))

    if result.fail_list:
        logger.info("失败列表(前10): %s", result.fail_list[:10])


if __name__ == "__main__":
    main()
