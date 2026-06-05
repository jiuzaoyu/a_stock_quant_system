import asyncio
import logging
from pathlib import Path

from redis import Redis

from src.fund_collector import FundStorage, collect_today_nav, refresh_fund_list
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker

log = get_logger(__name__)


def create_fund_worker(redis_client: Redis, db_path: str | None = None) -> BaseWorker:
    storage = FundStorage()
    storage.init_schema()

    worker = BaseWorker(
        redis_client,
        stream="cron:jobs:fund_incremental",
        group="fund_group",
        consumer="fund_consumer_1",
    )
    worker.register("fund_incremental", _make_handler(collect_today_nav, storage, "fund_incremental"))
    worker.register("fund_list_refresh", _make_handler(refresh_fund_list, storage, "fund_list_refresh"))

    return worker


def _make_handler(async_func, storage, job_name: str):
    def handler(data: dict[str, str]) -> None:
        log.info("=== %s 开始 ===", job_name)
        try:
            result = asyncio.run(async_func(storage))
            log.info("%s 完成: %s", job_name, result)
        except Exception:
            log.exception("%s 失败", job_name)
            raise
    return handler
