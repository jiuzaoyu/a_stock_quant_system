"""
基金重仓股持仓采集入口（独立脚本）。

用法（在项目根目录）:
    python scripts/collect_fund_holdings.py                  # 采集所有活跃基金
    python scripts/collect_fund_holdings.py --codes 019018,161725  # 指定基金

增量采集：先检查 DB 是否已有该季度数据，已存在则自动跳过。
"""

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.collector.fund import FundStorage, HoldingsCollectResult, collect_holdings_data
from src.utils.logger import get_logger, setup_logging

logger = get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(description="基金重仓股持仓采集")
    parser.add_argument("--codes", help="逗号分隔的基金代码，默认采集全部活跃基金")
    args = parser.parse_args()

    setup_logging(level="INFO", log_file=ROOT / "logs" / "fund_holdings.log")

    storage = FundStorage()
    codes = args.codes.split(",") if args.codes else None

    logger.info("开始重仓股采集%s", f": {codes}" if codes else "（全部活跃基金）")
    result: HoldingsCollectResult = asyncio.run(collect_holdings_data(storage, codes=codes))

    logger.info(
        "完成: 成功 %d/%d, 有新季度数据 %d 只, 失败 %d, 耗时 %.1fs",
        result.success_count, result.total_funds,
        result.updated_count, len(result.fail_list), result.elapsed_seconds,
    )

    if result.fail_list:
        logger.info("失败列表(前20): %s", result.fail_list[:20])


if __name__ == "__main__":
    main()
