"""
基金历史净值全量采集入口（一次性 ETL 任务）。

用法（在项目根目录）:
    python scripts/collect_fund_history.py

采集目标: 股票型 + 混合型 + 指数型基金，近两年净值数据
配置见: config/fund_collector.yaml
"""

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.config import load_yaml
from src.utils.logger import get_logger, setup_logging
from src.fund_collector import FundCollector, FundStorage

logger = get_logger(__name__)


def main():
    cfg = load_yaml(ROOT / "config" / "fund_collector.yaml")
    fund_cfg = cfg["fund_collector"]

    setup_logging(level="INFO", log_file=ROOT / "logs" / "fund_collector.log")

    storage = FundStorage()

    collector = FundCollector(
        storage=storage,
        lookback_years=fund_cfg.get("lookback_years", 2),
        request_delay_seconds=fund_cfg.get("request_delay_seconds", 0.5),
        progress_every=fund_cfg.get("progress_every", 20),
        max_retries=fund_cfg.get("max_retries", 3),
    )

    logger.info("开始全量采集, 回溯: %d年", collector.lookback_years)
    result = asyncio.run(collector.run())

    summary = storage.quality_summary()
    logger.info("库内概况: 基金 %s, 净值记录 %s, 日期 %s ~ %s",
                 summary["total_funds"], f"{summary['total_nav_rows']:,}",
                 summary["nav_date_min"], summary["nav_date_max"])
    logger.info("类型分布: %s", summary["type_counts"])
    logger.info("经理记录: %s, 持仓记录: %s",
                 summary.get("total_manager_rows", "?"),
                 summary.get("total_holding_rows", "?"))

    if result.fail_list:
        logger.info("失败列表(前10): %s", result.fail_list[:10])


if __name__ == "__main__":
    main()
