"""股票数据采集 Worker。

以多线程监听 Redis Stream:
  - cron:jobs:stock_queue_1 → 单只股票数据采集（日K线 + 估值）
"""

from datetime import date
from typing import Optional
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import akshare as ak
import pandas as pd
from redis import Redis

from src.collector.stock import StockStorage, fetch_kline, fetch_tencent_batch, fetch_tencent_valuation, fetch_stock_list

from src.utils.config import load_yaml
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker, start_workers

log = get_logger(__name__)


def create_stock_workers(redis_client: Redis) -> list[BaseWorker]:
    """创建股票数据采集 Worker 实例。"""
    storage = StockStorage()
    storage.init_schema()

    # 加载配置
    root = Path(__file__).resolve().parents[2]
    stock_cfg = load_yaml(root / "config" / "stock_collector.yaml").get("stock_collector", {})
    concurrency = stock_cfg.get("concurrency", 5)
    delay = stock_cfg.get("request_delay_seconds", 0.3)
    max_retries = stock_cfg.get("max_retries", 3)
    daily_lookback = stock_cfg.get("daily_lookback_days", 7)
    history_lookback = stock_cfg.get("history_lookback_days", 500)

    data_worker = BaseWorker(
        redis_client,
        stream="cron:jobs:stock_queue_1",
        group="stock_queue_group",
        consumer="stock_queue_consumer_1",
    )

    # 原有：单股采集
    data_worker.register(
        "stock_collect_single",
        _make_single_stock_handler(storage),
    )

    # 股票列表同步
    data_worker.register(
        "stock_list_sync",
        _make_stock_list_sync_handler(storage),
    )

    # 历史数据补齐
    data_worker.register(
        "stock_history_collect",
        _make_batch_collect_handler(
            storage, concurrency, history_lookback, delay, max_retries,
            job_name="stock_history_collect",
        ),
    )

    # 每日增量采集
    data_worker.register(
        "stock_daily_collect",
        _make_batch_collect_handler(
            storage, concurrency, daily_lookback, delay, max_retries,
            job_name="stock_daily_collect", check_trading_day=True,
        ),
    )

    return [data_worker]


# ==========================================================================
# Handler factories
# ==========================================================================


def _make_single_stock_handler(storage: StockStorage):
    def handler(data: dict[str, str]) -> None:
        code = (data.get("code") or "").strip()
        if not code:
            log.warning("stock_collect_single: 缺少股票代码参数 (code)")
            return

        log.info("=== stock_collect_single 开始: %s ===", code)
        try:
            # 采集日K线（最近250根）
            kline_rows = fetch_kline(code, category=4, offset=250)

            # 采集估值数据
            val_data = fetch_tencent_valuation([code])
            val_records = [
                {
                    "code": c,
                    "trade_date": info.get("trade_date", ""),
                    "pe_ttm": info.get("pe_ttm", 0),
                    "pe_static": info.get("pe_static", 0),
                    "pb": info.get("pb", 0),
                    "mcap_yi": info.get("mcap_yi", 0),
                    "float_mcap_yi": info.get("float_mcap_yi", 0),
                    "turnover_pct": info.get("turnover_pct", 0),
                    "vol_ratio": info.get("vol_ratio", 0),
                    "amplitude_pct": info.get("amplitude_pct", 0),
                    "limit_up": info.get("limit_up", 0),
                    "limit_down": info.get("limit_down", 0),
                    "change_pct": info.get("change_pct", 0),
                }
                for c, info in val_data.items()
            ]

            conn = storage.connect()
            try:
                daily_ins = storage.append_daily(conn, kline_rows)
                val_ins = storage.append_valuation(conn, val_records)
                conn.commit()
                log.info(
                    "stock_collect_single 完成: %s, K线 %d 条, 估值 %d 条",
                    code, daily_ins, val_ins,
                )
            finally:
                storage.return_conn(conn)
        except Exception:
            log.exception("stock_collect_single 失败: %s", code)
            raise

    return handler


def _make_stock_list_sync_handler(storage: StockStorage):
    def handler(data: dict[str, str]) -> None:
        log.info("=== stock_list_sync 开始 ===")
        try:
            stocks = fetch_stock_list(source="mootdx")
            conn = storage.connect()
            try:
                count = storage.sync_stock_list(conn, stocks)
                conn.commit()
                log.info("stock_list_sync 完成: %d 行变更", count)
            finally:
                storage.return_conn(conn)
        except Exception:
            log.exception("stock_list_sync 失败")
            raise

    return handler


def _make_batch_collect_handler(
    storage: StockStorage,
    concurrency: int,
    lookback_days: int,
    delay: float,
    max_retries: int,
    job_name: str,
    check_trading_day: bool = False,
):
    def handler(data: dict[str, str]) -> None:
        if check_trading_day and not is_trading_day():
            log.info("%s: 非交易日，跳过", job_name)
            return

        log.info("=== %s 开始 (lookback=%d 天) ===", job_name, lookback_days)
        codes = storage.get_active_codes()
        if not codes:
            log.info("%s: 无活跃股票，跳过", job_name)
            return

        log.info("%s: 活跃股票 %d 只, 并发数 %d", job_name, len(codes), concurrency)

        t0 = time.time()
        success = 0
        fail = 0
        daily_total = 0

        def collect_one(code: str):
            for attempt in range(max_retries):
                try:
                    kline_rows = fetch_kline(code, category=4, offset=lookback_days)
                    return (code, kline_rows, None)
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 2))
                    else:
                        return (code, [], str(e))
            return (code, [], "max_retries")

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(collect_one, code): code for code in codes}
            for future in as_completed(futures):
                code, kline_rows, error = future.result()
                if error:
                    fail += 1
                    log.warning("%s: %s K线采集失败: %s", job_name, code, error)
                    continue

                conn = storage.connect()
                try:
                    if kline_rows:
                        daily_total += storage.append_daily(conn, kline_rows)
                    conn.commit()
                finally:
                    storage.return_conn(conn)
                success += 1

                if delay > 0:
                    time.sleep(delay)

        val_total = 0
        val_records = fetch_tencent_batch(codes, batch_size=80)
        if val_records:
            conn = storage.connect()
            try:
                val_total = storage.append_valuation(conn, val_records)
                conn.commit()
            finally:
                storage.return_conn(conn)

        elapsed = time.time() - t0
        log.info(
            "%s 完成: 成功 %d, 失败 %d, K线 %d 条, 估值 %d 条, 耗时 %.1fs",
            job_name, success, fail, daily_total, val_total, elapsed,
        )

    return handler


# ==========================================================================
# 工具函数
# ==========================================================================


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
