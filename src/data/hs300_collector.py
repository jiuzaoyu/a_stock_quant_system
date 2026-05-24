"""沪深300成分股日线批量采集并入库。"""

import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

import akshare as ak
import pandas as pd

from ..utils.logger import get_logger
from .storage import DailyStorage

logger = get_logger(__name__)

# AkShare stock_zh_a_hist 列名映射 → 数据库字段
_AK_HIST_RENAME = {
    "日期": "trade_date",
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
    "涨跌幅": "pct_change",
    "换手率": "turnover",
}


@dataclass
class CollectResult:
    success_count: int = 0
    fail_list: List[Tuple[str, str]] = field(default_factory=list)


class HS300DailyCollector:
    """
    获取沪深300成分股列表，逐只拉取日线并写入 SQLite。

    职责：数据采集与入库（不属于策略/回测层）。
    """

    def __init__(
        self,
        db_path: Path,
        start_date: str = "20190101",
        end_date: str = "20241231",
        adjust: str = "qfq",
        request_delay_seconds: float = 0.5,
        progress_every: int = 50,
        index_symbol: str = "000300",
        hist_source: str = "auto",
        max_retries: int = 3,
    ):
        self.storage = DailyStorage(db_path)
        self.start_date = start_date
        self.end_date = end_date
        self.adjust = adjust
        self.request_delay_seconds = request_delay_seconds
        self.progress_every = progress_every
        self.index_symbol = index_symbol
        self.hist_source = hist_source
        self.max_retries = max_retries

    def fetch_constituents(self) -> List[str]:
        """获取指数成分股代码列表（6 位数字，如 000001）。"""
        hs300 = ak.index_stock_cons_csindex(symbol=self.index_symbol)
        logger.info("成分股表列名: %s", list(hs300.columns))

        preferred_cols = ["品种代码", "成分券代码", "股票代码", "证券代码", "代码"]
        col = next((c for c in preferred_cols if c in hs300.columns), None)

        if col is None:
            for c in hs300.columns:
                sample = hs300[c].astype(str).str.strip().head(30)
                if sample.str.fullmatch(r"\d{6}").mean() >= 0.8:
                    col = c
                    break

        if col is None:
            raise ValueError(
                f"无法识别成分股代码列，请检查 AkShare 返回结构: {list(hs300.columns)}"
            )

        codes = (
            hs300[col]
            .astype(str)
            .str.strip()
            .str.extract(r"(\d{6})", expand=False)
            .dropna()
            .unique()
            .tolist()
        )
        if len(codes) < 200:
            raise ValueError(
                f"成分股数量异常({len(codes)})，可能仍取错列(当前列={col})，样例={codes[:5]}"
            )
        logger.info("成分股数量: %d (%s)，代码列=%s", len(codes), self.index_symbol, col)
        return codes

    @staticmethod
    def _normalize_hist(df: pd.DataFrame, ts_code: str) -> pd.DataFrame:
        """将 AkShare 返回列转为 daily 表结构。"""
        out = df.rename(columns=_AK_HIST_RENAME)
        if "trade_date" not in out.columns and "date" in out.columns:
            out = out.rename(columns={"date": "trade_date"})
        out["trade_date"] = pd.to_datetime(out["trade_date"]).dt.strftime("%Y-%m-%d")
        out.insert(0, "ts_code", ts_code)
        keep = [
            "ts_code",
            "trade_date",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "amount",
            "pct_change",
            "turnover",
        ]
        return out[[c for c in keep if c in out.columns]]

    @staticmethod
    def _to_tx_symbol(code: str) -> str:
        """腾讯行情接口代码前缀：6 开头上交所 sh，其余 sz。"""
        return f"sh{code}" if code.startswith("6") else f"sz{code}"

    def _fetch_em(self, code: str) -> pd.DataFrame:
        return ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=self.start_date,
            end_date=self.end_date,
            adjust=self.adjust,
        )

    def _fetch_tx(self, code: str) -> pd.DataFrame:
        tx_rename = {
            "date": "trade_date",
            "open": "open",
            "close": "close",
            "high": "high",
            "low": "low",
            "amount": "amount",
        }
        df = ak.stock_zh_a_hist_tx(
            symbol=self._to_tx_symbol(code),
            start_date=self.start_date,
            end_date=self.end_date,
            adjust=self.adjust,
        )
        return df.rename(columns=tx_rename)

    def _fetch_with_source(self, code: str, source: str) -> pd.DataFrame:
        if source == "em":
            raw = self._fetch_em(code)
        elif source == "tx":
            raw = self._fetch_tx(code)
        else:
            raise ValueError(f"未知数据源: {source}")
        return self._normalize_hist(raw, code)

    def fetch_one(self, code: str, max_retries: Optional[int] = None) -> pd.DataFrame:
        if not re.fullmatch(r"\d{6}", code):
            raise ValueError(f"非法股票代码: {code}（应为 6 位数字）")

        retries = max_retries if max_retries is not None else self.max_retries
        sources: List[str]
        if self.hist_source == "auto":
            sources = ["em", "tx"]
        else:
            sources = [self.hist_source]

        last_err: Optional[Exception] = None
        for source in sources:
            for attempt in range(retries):
                try:
                    return self._fetch_with_source(code, source)
                except Exception as e:
                    last_err = e
                    wait = self.request_delay_seconds * (attempt + 2)
                    logger.warning(
                        "请求失败 %s [%s] 第 %d/%d 次: %s，%.1f 秒后重试",
                        code,
                        source,
                        attempt + 1,
                        retries,
                        e,
                        wait,
                    )
                    time.sleep(wait)
            if self.hist_source == "auto" and source == "em":
                logger.info("%s 东财接口失败，尝试腾讯接口…", code)

        raise last_err  # type: ignore[misc]

    def run(self, stock_list: Optional[List[str]] = None) -> CollectResult:
        """
        执行全量采集：建表 → 逐只入库 → 建索引 → 返回统计。
        """
        stock_list = stock_list or self.fetch_constituents()
        result = CollectResult()
        conn = self.storage.connect()
        print(1111111111111)
        try:
            self.storage.init_schema(conn)
            for i, code in enumerate(stock_list):
                try:
                    print(code)
                    df = self.fetch_one(code)
                    print(222222222222)
                    self.storage.delete_symbol(conn, code)
                    self.storage.append_daily(conn, df)
                    conn.commit()
                    result.success_count += 1
                    if self.progress_every and (i + 1) % self.progress_every == 0:
                        logger.info("进度: %d/%d", i + 1, len(stock_list))
                except Exception as e:
                    result.fail_list.append((code, str(e)))
                    logger.warning("采集失败 %s: %s", code, e)
                time.sleep(self.request_delay_seconds)
            self.storage.init_schema(conn)
        finally:
            conn.close()
        return result
