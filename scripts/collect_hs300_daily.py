"""
沪深300日线批量采集入口（一次性/定期 ETL 任务）。

用法（在项目根目录）:
    python scripts/collect_hs300_daily.py

逻辑实现在 src/data/hs300_collector.py，配置见 config/base.yaml → data.hs300_collector
数据库默认: data/database/quant.db（paths.database）
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.hs300_collector import HS300DailyCollector
from src.data.storage import DailyStorage
from src.utils.config import load_config
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


def main() -> None:
    cfg = load_config()
    setup_logging(
        level=cfg["base"]["logging"]["level"],
        log_file=ROOT / cfg["base"]["logging"]["file"],
    )
    paths = cfg["base"]["paths"]
    col_cfg = cfg["base"]["data"]["hs300_collector"]

    db_path = ROOT / paths["database"]
    collector = HS300DailyCollector(
        db_path=db_path,
        start_date=col_cfg["start_date"],
        end_date=col_cfg["end_date"],
        adjust=col_cfg["adjust"],
        request_delay_seconds=col_cfg["request_delay_seconds"],
        progress_every=col_cfg["progress_every"],
        index_symbol=col_cfg["index_symbol"],
        hist_source=col_cfg.get("hist_source", "auto"),
        max_retries=col_cfg.get("max_retries", 3),
    )

    logger.info("开始采集，数据库: %s", db_path)
    result = collector.run()

    storage = DailyStorage(db_path)
    summary = storage.quality_summary()
    logger.info(
        "完成: 成功 %d, 失败 %d",
        result.success_count,
        len(result.fail_list),
    )
    logger.info(
        "库内概况: 记录 %s, 股票 %s, 日期 %s ~ %s",
        f"{summary['total_rows']:,}",
        summary["stock_count"],
        summary["date_min"],
        summary["date_max"],
    )
    if result.fail_list:
        logger.info("失败列表(前10): %s", result.fail_list[:10])


if __name__ == "__main__":
    main()
