"""筛选引擎 — 编排：拉数据 → 预筛选 → 精细筛选 → 输出 CSV

数据源优先级：JQData > AKShare
"""

import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .filters import (
    check_vwap_above,
    filter_by_market_cap,
    filter_by_pct_change,
    filter_by_turnover_rate,
    filter_by_volume_ratio,
    get_stock_codes,
    has_limit_up_in_history,
)

log = logging.getLogger(__name__)


def is_trading_day(d: Any) -> bool:
    """判断给定日期是否为 A 股交易日。

    使用新浪财经数据源，拉取日期所在月份的交易日历。
    """
    from datetime import date as date_type

    import akshare as ak

    if isinstance(d, datetime):
        d = d.date()
    if not isinstance(d, date_type):
        d = date_type(d.year, d.month, d.day)

    try:
        trade_df = ak.tool_trade_date_hist_sina()
        trade_dates = pd.to_datetime(trade_df["trade_date"]).dt.date.tolist()
        return d in trade_dates
    except Exception:
        log.warning("交易日历查询失败，假定为交易日")
        return True

# AKShare 股票代码不含后缀，JQData 代码带 .XSHG / .XSHE
_SH_SUFFIX = ".XSHG"
_SZ_SUFFIX = ".XSHE"


def _bare_to_jq(code: str) -> str:
    """将纯数字代码转为 JQData 格式。6/9 开头 → XSHG，其余 → XSHE。"""
    if "." in code:
        return code
    if code.startswith(("6", "9")):
        return f"{code}{_SH_SUFFIX}"
    return f"{code}{_SZ_SUFFIX}"


def _jq_to_bare(code: str) -> str:
    """将 JQData 格式转为纯数字代码。"""
    return code.split(".")[0]


class ScreenerEngine:
    """盘中选股筛选引擎。

    不依赖调度器，可独立调用 run() 进行手动筛选。
    数据源：优先 JQData，失败回退 AKShare。
    """

    _RETRY_TIMES = 3
    _RETRY_DELAY = 5  # 秒
    _JQ_CHUNK_SIZE = 800  # JQData 单次查询股票数上限

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self.config = config or {}
        self.filters_cfg = self.config.get("filters", {})
        self.output_cfg = self.config.get("output", {})
        data_cfg = self.config.get("data_source", {})
        self._jq_available = False
        self._try_init_jqdata()

    # ── 数据源初始化 ──

    def _try_init_jqdata(self) -> None:
        """尝试初始化 JQData 认证。"""
        try:
            from jqdatasdk import auth

            user = os.getenv("JQDATA_USER")
            pwd = os.getenv("JQDATA_PASSWORD")
            if not user or not pwd:
                log.warning("JQData 未配置凭据，将使用 AKShare")
                return
            auth(user, pwd)
            self._jq_available = True
            log.info("JQData 认证成功")
        except ImportError:
            log.warning("jqdatasdk 未安装，将使用 AKShare")
        except Exception as e:
            log.warning("JQData 认证失败: %s，将使用 AKShare", e)

    # ── 核心流程 ──

    def run(self) -> pd.DataFrame:
        """执行筛选全流程，返回命中股票 DataFrame。"""
        log.info("开始盘中选股筛选…")

        # 1. 拉全市场实时快照
        df = self._fetch_market_snapshot()
        log.info("全市场快照: %d 只股票", len(df))

        # 2. 预筛选（DataFrame 级，快）
        df = self._prefilter(df)
        log.info("预筛选后: %d 只", len(df))

        if df.empty:
            log.info("预筛选无命中，结束")
            return df

        # 3. 涨停历史过滤（需逐只拉日线）
        df = self._filter_limit_up_history(df)
        log.info("涨停历史过滤后: %d 只", len(df))

        if df.empty:
            log.info("涨停历史过滤无命中，结束")
            return df

        # 4. 分时均线过滤（需逐只拉分钟线，放最后）
        df = self._filter_vwap(df)
        log.info("分时均线过滤后: %d 只", len(df))

        # 5. 输出 CSV
        self._save_to_csv(df)

        log.info("筛选完成，最终命中: %d 只", len(df))
        return df

    # ── 全市场快照 ──

    def _fetch_market_snapshot(self) -> pd.DataFrame:
        """拉取全市场实时行情快照（JQData 优先，AKShare 兜底）。"""
        if self._jq_available:
            try:
                return self._call_with_retry(
                    self._fetch_spot_jqdata, "JQData 全市场快照"
                )
            except Exception as e:
                log.warning("JQData 快照失败: %s，回退 AKShare", e)
        return self._call_with_retry(
            self._fetch_spot_akshare, "AKShare 全市场快照"
        )

    def _fetch_spot_akshare(self) -> pd.DataFrame:
        import akshare as ak
        return ak.stock_zh_a_spot_em()

    def _fetch_spot_jqdata(self) -> pd.DataFrame:
        """用 JQData 组装全市场快照 DataFrame。

        所需列：代码, 名称, 最新价, 涨跌幅, 量比, 换手率, 总市值, 成交额, 成交量
        """
        from jqdatasdk import get_all_securities, get_extras, get_price

        today_str = datetime.now().strftime("%Y-%m-%d")

        # 1. 全量股票代码 + 名称
        sec_df = get_all_securities(types=["stock"], date=today_str)
        all_jq_codes = sec_df.index.tolist()
        names = sec_df["display_name"]
        log.info("JQData: 获取到 %d 只股票", len(all_jq_codes))

        # 2. 分块拉取行情（get_price 单次限制约 800 只）
        chunks = [
            all_jq_codes[i : i + self._JQ_CHUNK_SIZE]
            for i in range(0, len(all_jq_codes), self._JQ_CHUNK_SIZE)
        ]

        price_frames = []
        for chunk in chunks:
            panel = get_price(
                chunk,
                count=6,
                end_date=today_str,
                frequency="daily",
                fields=["close", "volume", "money"],
                skip_paused=False,
                fq="pre",
            )
            price_frames.append(panel)

        # get_price 返回 Panel（dict-like），合并各块
        close_all, volume_all, money_all = [], [], []
        for panel in price_frames:
            close_df = panel["close"]
            volume_df = panel["volume"]
            money_df = panel["money"]
            close_all.append(close_df)
            volume_all.append(volume_df)
            money_all.append(money_df)

        close_prices = pd.concat(close_all, axis=1)
        volumes = pd.concat(volume_all, axis=1)
        moneys = pd.concat(money_all, axis=1)

        # 3. 计算涨跌幅：(最新收盘 - 前日收盘) / 前日收盘 * 100
        latest_close = close_prices.iloc[-1]
        prev_close = close_prices.iloc[-2]
        pct_change = ((latest_close - prev_close) / prev_close * 100).fillna(0)

        # 4. 量比 = 当日成交量 / 近5日均量
        avg_vol_5d = volumes.iloc[-6:-1].mean()
        latest_vol = volumes.iloc[-1]
        vol_ratio = (latest_vol / avg_vol_5d).fillna(1.0)

        # 5. 换手率：成交量(手)*100 / 流通股本(股) * 100
        try:
            float_share = get_extras(
                "float_share", all_jq_codes, end_date=today_str
            ).iloc[-1]
            turnover = ((latest_vol * 100) / float_share * 100).fillna(0)
        except Exception:
            log.debug("JQData: 无法获取流通股本，换手率置 0")
            turnover = pd.Series(0.0, index=latest_close.index)

        # 6. 总市值（分块拉取）
        cap_parts = []
        for chunk in chunks:
            caps = get_extras("market_cap", chunk, end_date=today_str).iloc[-1]
            cap_parts.append(caps)
        total_cap = pd.concat(cap_parts)

        # 7. 组装 DataFrame
        bare_codes = [_jq_to_bare(c) for c in latest_close.index]
        raw = pd.DataFrame(
            {
                "代码": bare_codes,
                "名称": names.reindex(latest_close.index).values,
                "最新价": latest_close.values,
                "涨跌幅": pct_change.values,
                "量比": vol_ratio.values,
                "换手率": turnover.values,
                "总市值": total_cap.reindex(latest_close.index).values,
                "成交量": latest_vol.values,
                "成交额": moneys.iloc[-1].values,
            }
        )
        return raw

    # ── 预筛选 ──

    def _prefilter(self, df: pd.DataFrame) -> pd.DataFrame:
        """执行快速预筛选（市值、涨幅、量比、换手率）。"""
        mc = self.filters_cfg.get("market_cap", {})
        pc = self.filters_cfg.get("pct_change", {})
        vr = self.filters_cfg.get("volume_ratio", {})
        tr = self.filters_cfg.get("turnover_rate", {})

        df = filter_by_market_cap(df, mc.get("min", 50), mc.get("max", 200))
        df = filter_by_pct_change(df, pc.get("min", 3), pc.get("max", 5))
        df = filter_by_volume_ratio(df, vr.get("min", 1.0))
        df = filter_by_turnover_rate(df, tr.get("min", 5), tr.get("max", 10))
        return df

    # ── 涨停历史过滤 ──

    def _filter_limit_up_history(self, df: pd.DataFrame) -> pd.DataFrame:
        """对候选股逐只检查近20日是否有涨停（JQData 优先）。"""
        lu_cfg = self.filters_cfg.get("limit_up_history", {})
        days = lu_cfg.get("days", 20)
        threshold = lu_cfg.get("threshold", 9.8)

        end_date = datetime.now().strftime("%Y-%m-%d")

        results = []
        for code in get_stock_codes(df):
            try:
                daily = self._fetch_daily(code, days + 10, end_date)
                if daily is not None and has_limit_up_in_history(
                    daily, days=days, threshold=threshold
                ):
                    results.append(code)
            except Exception:
                log.debug("拉取 %s 日线失败，跳过", code)

        return df[df["代码"].isin(results)]

    def _fetch_daily(self, code: str, count: int, end_date: str) -> Optional[pd.DataFrame]:
        """拉取个股日线（JQData 优先，AKShare 兜底）。"""
        if self._jq_available:
            try:
                return self._fetch_daily_jqdata(code, count, end_date)
            except Exception:
                pass
        return self._fetch_daily_akshare(code, count)

    def _fetch_daily_jqdata(self, code: str, count: int, end_date: str) -> pd.DataFrame:
        from jqdatasdk import get_price

        jq_code = _bare_to_jq(code)
        panel = get_price(
            jq_code,
            count=count,
            end_date=end_date,
            frequency="daily",
            fields=["open", "close", "high", "low", "volume", "money"],
            fq="pre",
        )
        df = pd.DataFrame(
            {
                "日期": panel["close"].index,
                "开盘": panel["open"].values.flatten(),
                "收盘": panel["close"].values.flatten(),
                "最高": panel["high"].values.flatten(),
                "最低": panel["low"].values.flatten(),
                "成交量": panel["volume"].values.flatten(),
                "成交额": panel["money"].values.flatten(),
            }
        )
        df["涨跌幅"] = df["收盘"].pct_change() * 100
        return df

    def _fetch_daily_akshare(self, code: str, count: int) -> Optional[pd.DataFrame]:
        import akshare as ak

        end = datetime.now().strftime("%Y%m%d")
        start = (datetime.now() - timedelta(days=count + 10)).strftime("%Y%m%d")
        raw = ak.stock_zh_a_hist(
            symbol=code,
            period="daily",
            start_date=start,
            end_date=end,
            adjust="qfq",
        )
        return raw.rename(
            columns={
                "日期": "日期",
                "开盘": "开盘",
                "收盘": "收盘",
                "最高": "最高",
                "最低": "最低",
                "成交量": "成交量",
                "成交额": "成交额",
                "涨跌幅": "涨跌幅",
            }
        )

    # ── 分时均线过滤 ──

    def _filter_vwap(self, df: pd.DataFrame) -> pd.DataFrame:
        """对候选股逐只检查分时均线位置（JQData 优先）。"""
        results = []
        for code in get_stock_codes(df):
            try:
                minute_df = self._fetch_minute(code)
                if minute_df is not None and check_vwap_above(minute_df):
                    results.append(code)
            except Exception:
                log.debug("拉取 %s 分钟线失败，跳过", code)

        return df[df["代码"].isin(results)]

    def _fetch_minute(self, code: str) -> Optional[pd.DataFrame]:
        """拉取个股分钟K线（JQData 优先，AKShare 兜底）。"""
        if self._jq_available:
            try:
                return self._fetch_minute_jqdata(code)
            except Exception:
                pass
        return self._fetch_minute_akshare(code)

    def _fetch_minute_jqdata(self, code: str) -> pd.DataFrame:
        from jqdatasdk import get_price

        jq_code = _bare_to_jq(code)
        today = datetime.now().strftime("%Y-%m-%d")
        panel = get_price(
            jq_code,
            count=240,
            end_date=today,
            frequency="minute",
            fields=["open", "close", "high", "low", "volume", "money"],
            fq="pre",
        )
        df = pd.DataFrame(
            {
                "时间": panel["close"].index,
                "开盘": panel["open"].values.flatten(),
                "收盘": panel["close"].values.flatten(),
                "最高": panel["high"].values.flatten(),
                "最低": panel["low"].values.flatten(),
                "成交量": panel["volume"].values.flatten(),
                "成交额": panel["money"].values.flatten(),
            }
        )
        return df

    def _fetch_minute_akshare(self, code: str) -> Optional[pd.DataFrame]:
        import akshare as ak

        raw = ak.stock_zh_a_hist_min_em(symbol=code)
        return raw.rename(
            columns={
                "时间": "时间",
                "开盘": "开盘",
                "收盘": "收盘",
                "最高": "最高",
                "最低": "最低",
                "成交量": "成交量",
                "成交额": "成交额",
            }
        )

    # ── 输出 ──

    def _save_to_csv(self, df: pd.DataFrame) -> None:
        """输出筛选结果到 CSV（含时分防覆盖）。"""
        output_dir = Path(self.output_cfg.get("dir", "output/screener"))
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        path = output_dir / f"{timestamp}.csv"

        if df.empty:
            log.info("无命中股票，不生成 CSV")
            return

        df.to_csv(path, index=False, encoding="utf-8-sig")
        log.info("结果已保存: %s", path)

    # ── 工具 ──

    @staticmethod
    def _call_with_retry(fn: Callable[[], Any], name: str) -> Any:
        """调用函数，失败自动重试。"""
        last_err = None
        for attempt in range(1, ScreenerEngine._RETRY_TIMES + 1):
            try:
                return fn()
            except Exception as e:
                last_err = e
                if attempt < ScreenerEngine._RETRY_TIMES:
                    log.warning(
                        "%s 第 %d 次失败，%d 秒后重试",
                        name, attempt, ScreenerEngine._RETRY_DELAY,
                    )
                    time.sleep(ScreenerEngine._RETRY_DELAY)
        raise RuntimeError(
            f"{name} 重试 {ScreenerEngine._RETRY_TIMES} 次均失败"
        ) from last_err
