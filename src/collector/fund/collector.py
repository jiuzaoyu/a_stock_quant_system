"""基金数据批量采集与增量更新。"""

import asyncio
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

import aiohttp

from config.collector.fund_cfg import (
    CONCURRENCY,
    HEADERS_FUND,
    LOOKBACK_YEARS,
    MAX_RETRIES,
    PROGRESS_EVERY,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT,
)
from .fetcher import (
    fetch_fund_list,
    fetch_fund_full_history,
    fetch_fund_list_refresh,
    fetch_fund_manager,
    fetch_fund_holdings,
    fetch_fund_pingzhong,
    PingzhongData,
)
from .storage import FundStorage
from ...utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class FundCollectResult:
    total_funds: int = 0
    success_count: int = 0
    nav_rows_inserted: int = 0
    manager_rows_inserted: int = 0
    holding_rows_inserted: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class ManagerCollectResult:
    total_funds: int = 0
    success_count: int = 0
    updated_count: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class HoldingsCollectResult:
    total_funds: int = 0
    success_count: int = 0
    updated_count: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)
    elapsed_seconds: float = 0.0


@dataclass
class FundCollector:
    """批量采集基金历史净值并写入 PostgreSQL。

    用法:
        storage = FundStorage()
        collector = FundCollector(storage, lookback_years=2)
        result = asyncio.run(collector.run())
    """

    storage: FundStorage                          # 数据库读写入口
    lookback_years: int = LOOKBACK_YEARS          # 历史净值回溯年数
    request_delay_seconds: float = REQUEST_DELAY_SECONDS  # 请求间隔（防反爬）
    progress_every: int = PROGRESS_EVERY          # 每采集 N 只基金输出一次进度日志
    max_retries: int = MAX_RETRIES                # 单只基金采集失败最大重试次数
    concurrency: int = CONCURRENCY                # 并发采集数

    async def run(self) -> FundCollectResult:
        result = FundCollectResult()
        t0 = time.time()

        # 1. 拉基金列表
        logger.info("正在获取基金列表...")
        async with _new_session() as session:
            funds = await fetch_fund_list(session)
        result.total_funds = len(funds)
        logger.info("符合条件的基金: %d 只 (股票型/混合型/指数型)", len(funds))

        # 2. 写入 fund_info
        conn = self.storage.connect()
        try:
            self.storage.init_schema(conn)
            self.storage.upsert_fund_info(conn, funds)
            conn.commit()
        finally:
            self.storage.return_conn(conn)

        # 3. 并发采集净值
        cutoff = date.today() - timedelta(days=self.lookback_years * 365)
        sem = asyncio.Semaphore(self.concurrency)
        completed = 0

        async def collect_one(fund: dict, session):
            nonlocal completed
            async with sem:
                code = fund["code"]
                try:
                    ping = await self._fetch_pingzhong_with_retry(code, session)
                    nav_rows = [r for r in ping.nav_history if r["nav_date"] >= str(cutoff)]
                    managers = ping.managers
                    report_date, holdings = await fetch_fund_holdings(code, session)

                    nav_ins = mgr_ins = hld_ins = 0
                    conn2 = self.storage.connect()
                    try:
                        if nav_rows:
                            nav_ins = self.storage.append_nav(conn2, nav_rows)
                        if managers:
                            mgr_ins = self.storage.upsert_fund_managers(conn2, code, managers)
                        if holdings:
                            hld_ins = self.storage.upsert_fund_holdings(conn2, code, report_date, holdings)
                        conn2.commit()
                    finally:
                        self.storage.return_conn(conn2)
                    return (nav_ins, mgr_ins, hld_ins)
                except Exception as e:
                    result.fail_list.append((code, str(e)))
                    logger.warning("采集失败 %s %s: %s", code, fund["name"], e)
                    return (0, 0, 0)
                finally:
                    completed += 1
                    if self.progress_every and completed % self.progress_every == 0:
                        logger.info("进度: %d/%d", completed, result.total_funds)

        async with _new_session() as session:
            tasks = [collect_one(f, session) for f in funds]
            all_results = await asyncio.gather(*tasks)

        result.nav_rows_inserted = sum(r[0] for r in all_results)
        result.manager_rows_inserted = sum(r[1] for r in all_results)
        result.holding_rows_inserted = sum(r[2] for r in all_results)
        result.success_count = result.total_funds - len(result.fail_list)
        result.elapsed_seconds = round(time.time() - t0, 1)
        logger.info(
            "采集完成: 成功 %d/%d, 净值 %d 条, 经理 %d 条, 持仓 %d 条, 失败 %d, 耗时 %.1fs",
            result.success_count, result.total_funds,
            result.nav_rows_inserted, result.manager_rows_inserted,
            result.holding_rows_inserted, len(result.fail_list), result.elapsed_seconds,
        )
        return result

    async def _fetch_pingzhong_with_retry(
        self, code: str, session
    ) -> PingzhongData:
        last_err = None
        for attempt in range(self.max_retries):
            try:
                return await fetch_fund_pingzhong(code, session)
            except Exception as e:
                last_err = e
                if attempt < self.max_retries - 1:
                    wait = self.request_delay_seconds * (attempt + 2)
                    logger.debug("%s 第 %d 次失败, %.1fs 后重试: %s", code, attempt + 1, wait, e)
                    await asyncio.sleep(wait)
        raise last_err  # type: ignore[misc]


async def collect_fund_history_nav(storage: FundStorage) -> FundCollectResult:
    """全量历史净值采集（先清空再重采，仅净值）。

    用法:
        result = asyncio.run(collect_fund_history_nav(storage))
    """
    result = FundCollectResult()
    t0 = time.time()

    # 1. 从 DB 取基金列表 + 清空全部净值
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        codes = storage.get_all_codes(conn)
        deleted = storage.delete_all_nav(conn)
        logger.info("已清空 %d 条历史净值记录", deleted)
        conn.commit()
    finally:
        storage.return_conn(conn)

    result.total_funds = len(codes)
    logger.info("待采集基金: %d 只", len(codes))

    # 2. 并发采集净值
    cutoff = date.today() - timedelta(days=LOOKBACK_YEARS * 365)
    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0

    async def collect_one(code: str, session):
        nonlocal completed
        async with sem:
            try:
                rows = await fetch_fund_full_history(code, session)
                rows = [r for r in rows if r["nav_date"] >= str(cutoff)]
                if not rows:
                    return 0

                conn2 = storage.connect()
                try:
                    inserted = storage.append_nav(conn2, rows)
                    conn2.commit()
                    return inserted
                finally:
                    storage.return_conn(conn2)
            except Exception as e:
                result.fail_list.append((code, str(e)))
                logger.warning("净值采集失败 %s: %s", code, e)
                return 0
            finally:
                completed += 1
                if completed % PROGRESS_EVERY == 0:
                    logger.info("净值采集进度: %d/%d", completed, result.total_funds)

    async with _new_session() as session:
        all_results = await asyncio.gather(*[collect_one(c, session) for c in codes])

    result.nav_rows_inserted = sum(all_results)
    result.success_count = result.total_funds - len(result.fail_list)
    result.elapsed_seconds = round(time.time() - t0, 1)
    logger.info(
        "全量净值采集完成: 成功 %d/%d, 写入 %d 条, 失败 %d, 耗时 %.1fs",
        result.success_count, result.total_funds,
        result.nav_rows_inserted, len(result.fail_list), result.elapsed_seconds,
    )
    return result


async def collect_recent_nav(
    storage: FundStorage, target_date: Optional[str] = None, lookback_days: int = 7
) -> int:
    """增量采集：拉取近N日净值，已有记录自动跳过。

    用于每日定时采集 + 故障恢复。若系统中断几天，重跑即可补回缺失数据。

    Args:
        storage: FundStorage 实例
        target_date: 目标日期 YYYY-MM-DD，None=今天
        lookback_days: 往前推的天数，默认 7 天（覆盖约 5 个交易日）

    Returns:
        本次写入的净值记录数
    """
    if target_date is None:
        target_date = date.today().strftime("%Y-%m-%d")

    from_date = (date.fromisoformat(target_date) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
    logger.info("增量采集: %s ~ %s (回溯 %d 天)", from_date, target_date, lookback_days)

    # 1. 刷新基金列表
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        await fetch_fund_list_refresh(conn)
        conn.commit()
        codes = storage.get_all_codes(conn)
    finally:
        storage.return_conn(conn)

    logger.info("待采集基金: %d 只", len(codes))

    sem = asyncio.Semaphore(CONCURRENCY)

    async def collect_one(code: str, session):
        async with sem:
            try:
                rows = await fetch_fund_full_history(code, session)
                match_rows = [r for r in rows if from_date <= r["nav_date"] <= target_date]
                if not match_rows:
                    return 0

                conn2 = storage.connect()
                try:
                    inserted = storage.append_nav(conn2, match_rows)
                    conn2.commit()
                    return inserted
                finally:
                    storage.return_conn(conn2)
            except Exception as e:
                logger.warning("增量采集失败 %s: %s", code, e)
                return 0

    async with _new_session() as session:
        results = await asyncio.gather(*[collect_one(c, session) for c in codes])

    total_inserted = sum(results)
    logger.info("增量采集完成: 写入 %d 条净值记录", total_inserted)
    return total_inserted


async def refresh_fund_list(storage: FundStorage) -> int:
    """刷新基金列表。"""
    conn = storage.connect()
    try:
        storage.init_schema(conn)
        count = await fetch_fund_list_refresh(conn)
        conn.commit()
        logger.info("基金列表刷新完成: %d 只基金", count)
        return count
    finally:
        storage.return_conn(conn)


async def collect_manager_data(
    storage: FundStorage, codes: Optional[List[str]] = None
) -> ManagerCollectResult:
    """独立采集基金经理信息

    可用于基金经理变动后的增量更新。
    """
    result = ManagerCollectResult()
    t0 = time.time()

    conn = storage.connect()
    try:
        storage.init_schema(conn)
        if codes is None:
            codes = storage.get_all_codes(conn)
    finally:
        storage.return_conn(conn)

    result.total_funds = len(codes)
    logger.info("基金经理采集开始: %d 只基金", len(codes))

    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0

    async def collect_one(code: str, session):
        nonlocal completed
        async with sem:
            try:
                managers = await fetch_fund_manager(code, session)
                if not managers:
                    return 0
                conn2 = storage.connect()
                try:
                    inserted = storage.upsert_fund_managers(conn2, code, managers)
                    conn2.commit()
                    return inserted
                finally:
                    storage.return_conn(conn2)
            except Exception as e:
                result.fail_list.append((code, str(e)))
                logger.warning("基金经理采集失败 %s: %s", code, e)
                return 0
            finally:
                completed += 1
                if completed % PROGRESS_EVERY == 0:
                    logger.info("经理采集进度: %d/%d", completed, result.total_funds)

    async with _new_session() as session:
        all_results = await asyncio.gather(*[collect_one(c, session) for c in codes])

    result.success_count = result.total_funds - len(result.fail_list)
    result.updated_count = sum(all_results)
    result.elapsed_seconds = round(time.time() - t0, 1)
    logger.info(
        "基金经理采集完成: 成功 %d/%d, 更新 %d 条, 失败 %d, 耗时 %.1fs",
        result.success_count, result.total_funds,
        result.updated_count, len(result.fail_list), result.elapsed_seconds,
    )
    return result


async def collect_holdings_data(
    storage: FundStorage, codes: Optional[List[str]] = None
) -> HoldingsCollectResult:
    """独立采集基金重仓股持仓

    增量逻辑：先获取 report_date 检查 DB 是否已有该季度数据，已存在则跳过。
    """
    result = HoldingsCollectResult()
    t0 = time.time()

    conn = storage.connect()
    try:
        storage.init_schema(conn)
        if codes is None:
            codes = storage.get_all_codes(conn)
    finally:
        storage.return_conn(conn)

    result.total_funds = len(codes)
    logger.info("重仓股采集开始: %d 只基金", len(codes))

    sem = asyncio.Semaphore(CONCURRENCY)
    completed = 0
    skipped = 0

    async def collect_one(code: str, session):
        nonlocal completed, skipped
        async with sem:
            try:
                report_date, holdings = await fetch_fund_holdings(code, session)
                if not holdings or not report_date:
                    return (0, 0)

                conn2 = storage.connect()
                try:
                    if storage.has_holdings_for_report(conn2, code, report_date):
                        skipped += 1
                        return (0, 0)
                    inserted = storage.upsert_fund_holdings(
                        conn2, code, report_date, holdings
                    )
                    conn2.commit()
                    return (inserted, 1)
                finally:
                    storage.return_conn(conn2)
            except Exception as e:
                result.fail_list.append((code, str(e)))
                logger.warning("重仓股采集失败 %s: %s", code, e)
                return (0, 0)
            finally:
                completed += 1
                if completed % PROGRESS_EVERY == 0:
                    logger.info("持仓采集进度: %d/%d", completed, result.total_funds)

    async with _new_session() as session:
        all_results = await asyncio.gather(*[collect_one(c, session) for c in codes])

    result.success_count = result.total_funds - len(result.fail_list)
    result.updated_count = sum(r[1] for r in all_results)
    result.elapsed_seconds = round(time.time() - t0, 1)
    logger.info(
        "重仓股采集完成: 成功 %d/%d, 有新季度数据 %d 只, 跳过 %d 只, 失败 %d, 耗时 %.1fs",
        result.success_count, result.total_funds,
        result.updated_count, skipped, len(result.fail_list), result.elapsed_seconds,
    )
    return result


def _new_session():
    """为每轮采集创建一个共享的 ClientSession，复用 TCP 连接。"""
    return aiohttp.ClientSession(
        headers=HEADERS_FUND,
        timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT),
    )
