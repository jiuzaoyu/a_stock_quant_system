"""股票数据批量采集与增量更新。

mootdx 和腾讯财经均为同步 API，使用 ThreadPoolExecutor 并发。"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

from .fetcher import (
    fetch_kline,
    fetch_stock_list,
    fetch_tencent_batch,
)
from .storage import StockStorage
from ..utils.logger import get_logger

logger = get_logger(__name__)

DEFAULT_CONCURRENCY = 5
TENCENT_BATCH_SIZE = 80


@dataclass
class StockCollectResult:
    total_stocks: int = 0
    success_count: int = 0
    daily_rows_inserted: int = 0
    valuation_rows_inserted: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class StockCollector:
    """批量采集A股日K线 + 估值数据并写入 PostgreSQL。

    用法:
        storage = StockStorage()
        collector = StockCollector(storage, lookback_years=2)
        collector.run()
    """

    storage: StockStorage
    lookback_years: int = 2
    kline_category: int = 4
    request_delay_seconds: float = 0.3
    progress_every: int = 50
    max_retries: int = 3
    concurrency: int = DEFAULT_CONCURRENCY

    def run(self) -> StockCollectResult:
        result = StockCollectResult()
        t0 = time.time()

        # 1. 拉股票列表
        logger.info("正在获取A股股票列表...")
        stocks = fetch_stock_list()
        result.total_stocks = len(stocks)
        logger.info("A股股票总数: %d 只", len(stocks))

        # 2. 写入 stock_info
        conn = self.storage.connect()
        try:
            self.storage.init_schema(conn)
            self.storage.upsert_stock_info(conn, stocks)
            conn.commit()
        finally:
            self.storage.return_conn(conn)

        codes = [s["code"] for s in stocks]
        cutoff = date.today() - timedelta(days=self.lookback_years * 365)

        # 3. 并发采集K线 (ThreadPoolExecutor)
        logger.info("开始并发采集日K线 (并发=%d)...", self.concurrency)
        completed = 0

        def collect_one(code: str):
            nonlocal completed
            for attempt in range(self.max_retries):
                try:
                    offset = self.lookback_years * 250  # ~250 trading days/year
                    kline_rows = fetch_kline(code, category=self.kline_category, offset=offset)
                    kline_rows = [r for r in kline_rows if r["trade_date"] >= str(cutoff)]

                    conn2 = self.storage.connect()
                    try:
                        daily_ins = 0
                        if kline_rows:
                            daily_ins = self.storage.append_daily(conn2, kline_rows)
                        conn2.commit()
                    finally:
                        self.storage.return_conn(conn2)
                    return (code, daily_ins, None)
                except Exception as e:
                    if attempt < self.max_retries - 1:
                        time.sleep(self.request_delay_seconds * (attempt + 2))
                    else:
                        return (code, 0, str(e))

            return (code, 0, "max_retries_exceeded")

        with ThreadPoolExecutor(max_workers=self.concurrency) as executor:
            futures = {executor.submit(collect_one, code): code for code in codes}
            for future in as_completed(futures):
                code, daily_ins, error = future.result()
                if error:
                    result.fail_list.append((code, error))
                else:
                    result.success_count += 1
                    result.daily_rows_inserted += daily_ins

                completed += 1
                if self.progress_every and completed % self.progress_every == 0:
                    logger.info("K线进度: %d/%d", completed, result.total_stocks)

                # 请求间隔
                if self.request_delay_seconds > 0:
                    time.sleep(self.request_delay_seconds)

        # 4. 批量采集估值数据 (腾讯财经)
        logger.info("开始采集估值数据 (腾讯财经)...")
        val_records = fetch_tencent_batch(codes, batch_size=TENCENT_BATCH_SIZE)

        conn = self.storage.connect()
        try:
            if val_records:
                result.valuation_rows_inserted = self.storage.append_valuation(conn, val_records)
            conn.commit()
        finally:
            self.storage.return_conn(conn)

        result.elapsed_seconds = round(time.time() - t0, 1)
        logger.info(
            "采集完成: 成功 %d/%d, K线 %d 条, 估值 %d 条, 失败 %d, 耗时 %.1fs",
            result.success_count, result.total_stocks,
            result.daily_rows_inserted, result.valuation_rows_inserted,
            len(result.fail_list), result.elapsed_seconds,
        )
        return result


def collect_today_daily(
    storage: StockStorage, target_date: Optional[str] = None
) -> int:
    """增量采集：只拉当日K线。

    Args:
        storage: StockStorage 实例
        target_date: 目标日期 YYYY-MM-DD，None=今天

    Returns:
        本次写入的K线记录数
    """
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    logger.info("增量采集开始: %s", target_date)

    conn = storage.connect()
    try:
        storage.init_schema(conn)
        # 刷新股票列表
        stocks = fetch_stock_list()
        storage.upsert_stock_info(conn, stocks)
        conn.commit()
        codes = storage.get_all_codes(conn)
    finally:
        storage.return_conn(conn)

    logger.info("待采集股票: %d 只", len(codes))
    total_inserted = 0

    with ThreadPoolExecutor(max_workers=DEFAULT_CONCURRENCY) as executor:
        futures = {
            executor.submit(fetch_kline, code, 4, 3): code for code in codes
        }
        for future in as_completed(futures):
            try:
                rows = future.result()
                today_rows = [r for r in rows if r["trade_date"] == target_date]
                if today_rows:
                    conn2 = storage.connect()
                    try:
                        total_inserted += storage.append_daily(conn2, today_rows)
                        conn2.commit()
                    finally:
                        storage.return_conn(conn2)
            except Exception as e:
                logger.warning("增量采集失败 %s: %s", futures[future], e)

    # 增量估值
    logger.info("增量估值采集...")
    val_records = fetch_tencent_batch(codes, batch_size=TENCENT_BATCH_SIZE)
    val_today = [r for r in val_records if r["trade_date"] == target_date]
    if val_today:
        conn = storage.connect()
        try:
            storage.append_valuation(conn, val_today)
            conn.commit()
        finally:
            storage.return_conn(conn)

    logger.info("增量采集完成: 写入 %d 条K线记录, %d 条估值记录",
                total_inserted, len(val_today))
    return total_inserted


def refresh_stock_list(storage: StockStorage) -> int:
    """刷新股票列表。"""
    stocks = fetch_stock_list()
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        count = storage.upsert_stock_info(conn, stocks)
        conn.commit()
        logger.info("股票列表刷新完成: %d 只", len(stocks))
        return count
    finally:
        storage.return_conn(conn)
