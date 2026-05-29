"""基金数据批量采集与增量更新。"""

import random
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .fetcher import fetch_fund_list, fetch_fund_full_history, fetch_fund_list_refresh
from .storage import FundStorage
from ..utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FundCollectResult:
    total_funds: int = 0
    success_count: int = 0
    nav_rows_inserted: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class FundCollector:
    """批量采集基金历史净值并写入 SQLite。

    用法:
        storage = FundStorage(Path("data/database/quant.db"))
        collector = FundCollector(storage, lookback_years=2)
        result = collector.run()
    """

    storage: FundStorage
    lookback_years: int = 2
    request_delay_seconds: float = 0.5
    progress_every: int = 20
    max_retries: int = 3

    def run(self) -> FundCollectResult:
        result = FundCollectResult()
        t0 = time.time()

        # 1. 拉基金列表
        logger.info("正在获取基金列表...")
        funds = fetch_fund_list()
        result.total_funds = len(funds)
        logger.info("符合条件的基金: %d 只 (股票型/混合型/指数型)", len(funds))

        # 2. 写入 fund_info
        conn = self.storage.connect()
        try:
            self.storage.init_schema(conn)
            self.storage.upsert_fund_info(conn, funds)
            conn.commit()
        finally:
            conn.close()

        # 3. 截止日期 = today
        cutoff = date.today() - timedelta(days=self.lookback_years * 365)

        for i, fund in enumerate(funds):
            code = fund["code"]
            try:
                rows = self._fetch_with_retry(code)
                # 过滤只保留 lookback_years 内的数据
                rows = [r for r in rows if r["nav_date"] >= str(cutoff)]
                if not rows:
                    continue

                conn = self.storage.connect()
                try:
                    inserted = self.storage.append_nav(conn, rows)
                    conn.commit()
                    result.nav_rows_inserted += inserted
                finally:
                    conn.close()

                result.success_count += 1

                if self.progress_every and (i + 1) % self.progress_every == 0:
                    logger.info("进度: %d/%d (已写入 %d 条净值)", i + 1, result.total_funds, result.nav_rows_inserted)
            except Exception as e:
                result.fail_list.append((code, str(e)))
                logger.warning("采集失败 %s %s: %s", code, fund["name"], e)

            time.sleep(self._jitter_delay())

        result.elapsed_seconds = round(time.time() - t0, 1)
        logger.info(
            "采集完成: 成功 %d/%d, 写入 %d 条净值, 失败 %d, 耗时 %.1fs",
            result.success_count, result.total_funds,
            result.nav_rows_inserted, len(result.fail_list), result.elapsed_seconds,
        )
        return result

    def _fetch_with_retry(self, code: str) -> list[dict]:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                return fetch_fund_full_history(code)
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    wait = self.request_delay_seconds * (attempt + 2)
                    logger.debug("%s 第 %d 次失败, %.1fs 后重试: %s", code, attempt + 1, wait, e)
                    time.sleep(wait)
        raise last_err  # type: ignore[misc]


def collect_today_nav(storage: FundStorage, target_date: Optional[str] = None) -> int:
    """增量采集：只拉当日净值（供 nb_cron 调度）。

    Args:
        storage: FundStorage 实例
        target_date: 目标日期 YYYY-MM-DD，None=今天

    Returns:
        本次写入的净值记录数
    """
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    logger.info("增量采集开始: %s", target_date)

    # 1. 刷新基金列表（可能有新基金）
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        fetch_fund_list_refresh(conn)
        conn.commit()
        codes = storage.get_all_codes(conn)
    finally:
        conn.close()

    logger.info("待采集基金: %d 只", len(codes))

    total_inserted = 0
    for i, code in enumerate(codes):
        try:
            rows = fetch_fund_full_history(code)
            # 只保留目标日期
            today_rows = [r for r in rows if r["nav_date"] == target_date]
            if not today_rows:
                continue

            conn = storage.connect()
            try:
                inserted = storage.append_nav(conn, today_rows)
                conn.commit()
                total_inserted += inserted
            finally:
                conn.close()

            time.sleep(0.3)  # 增量模式请求间隔更短

        except Exception as e:
            logger.warning("增量采集失败 %s: %s", code, e)

        if (i + 1) % 200 == 0:
            logger.info("增量进度: %d/%d (已写入 %d 条)", i + 1, len(codes), total_inserted)

    logger.info("增量采集完成: 写入 %d 条净值记录", total_inserted)
    return total_inserted


def refresh_fund_list(storage: FundStorage) -> int:
    """刷新基金列表（供 nb_cron 周调度）。"""
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        count = fetch_fund_list_refresh(conn)
        conn.commit()
        logger.info("基金列表刷新完成: %d 只基金", count)
        return count
    finally:
        conn.close()
