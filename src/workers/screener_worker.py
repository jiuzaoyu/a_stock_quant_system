import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd
from redis import Redis

from src.screener.engine import ScreenerEngine
from src.utils.config import load_yaml
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def is_trading_day(check_date: Optional[date] = None) -> bool:
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


def create_screener_worker(redis_client: Redis) -> BaseWorker:
    cfg = load_yaml(ROOT / "config" / "screener.yaml")
    screener_cfg = cfg["screener"]

    engine = ScreenerEngine(screener_cfg, project_root=ROOT)

    worker = BaseWorker(
        redis_client,
        stream="cron:jobs:screener_intraday",
        group="screener_group",
        consumer="screener_consumer_1",
    )
    worker.register("screener_intraday", _make_handler(engine))

    return worker


def _make_handler(engine: ScreenerEngine):
    def handler(data: dict[str, str]) -> None:
        if not is_trading_day():
            log.info("今日非交易日，跳过筛选")
            return

        log.info("=== 盘中选股筛选开始 ===")
        start = datetime.now()
        try:
            engine.run()
        except Exception:
            log.exception("筛选过程异常")
            raise
        elapsed = (datetime.now() - start).total_seconds()
        log.info("=== 筛选结束，耗时 %.1f 秒 ===", elapsed)
    return handler
