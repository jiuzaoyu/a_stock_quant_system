"""
基金盘中净值估算引擎。

核心逻辑:
  estimated_pct = Σ(weight_i × stock_change_pct_i)
  estimated_nav = last_nav × (1 + estimated_pct / 100)

QDII 基金通过关联指数期货/ETF 间接估算。
"""

import logging
from datetime import date as _date, datetime
from typing import Optional

from ..data.realtime_quote import fetch_realtime_batch, fetch_qdii_proxy_quotes
from ..fund_collector.storage import FundStorage

log = logging.getLogger(__name__)

# QDII 基金 → 代理指标映射（用于无法获取海外持仓实时行情时）
QDII_PROXY_MAP = {
    "024239": "nq_future",    # 华夏全球科技先锋 → 纳斯达克期货
}

# 默认操作建议阈值
DEFAULT_RULES = {
    "reduce_profit": 15.0,      # 累计盈利超过此值，触发减仓止盈判断
    "clear_profit": 30.0,       # 累计盈利超过此值，触发清仓止盈判断
    "clear_loss": -10.0,        # 累计亏损超过此值，触发止损清仓
    "reduce_loss": -5.0,        # 累计亏损超过此值，触发减仓止损判断
    "daily_drop_reduce": -2.0,  # 当日跌幅超过此值，触发减仓
    "daily_drop_clear": -1.5,   # 当日跌幅超过此值（高盈利时），触发清仓
    "daily_rise_buy": 2.0,      # 当日涨幅超过此值（亏损中），触发加仓
}


def _load_rules(config_path: Optional[str] = None) -> dict:
    """加载操作建议阈值，优先从配置文件读取，否则用默认值。"""
    if config_path:
        try:
            import yaml
            with open(config_path, encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            return cfg.get("rules", DEFAULT_RULES)
        except Exception:
            log.warning("加载阈值配置失败，使用默认值")
    return DEFAULT_RULES


class NavEstimator:
    """基金净值估算器。

    用法:
        storage = FundStorage()
        storage.init_schema()
        estimator = NavEstimator(storage)

        conn = storage.connect()
        try:
            results = estimator.estimate_all(conn)
            for r in results:
                print(r["fund_code"], r["estimated_pct"], r["suggestion"])
        finally:
            storage.return_conn(conn)
    """

    def __init__(self, storage: FundStorage, config_path: Optional[str] = None):
        self._storage = storage
        self._rules = _load_rules(config_path)

    def estimate_single(self, conn, holding: dict) -> dict:
        """估算单只基金当前净值和涨跌幅。

        Args:
            conn: 数据库连接
            holding: user_holding 行 {"fund_code", "buy_net_value", "shares", "is_qdii", ...}

        Returns:
            {"fund_code", "trade_date", "estimate_time", "last_nav", "estimated_nav",
             "estimated_pct", "coverage_pct", "stock_detail", "is_qdii"}
        """
        fund_code = holding["fund_code"]
        is_qdii = holding.get("is_qdii", False)

        latest_nav = self._storage.get_latest_nav(conn, fund_code)
        last_nav = latest_nav["unit_nav"] if latest_nav else None

        if is_qdii:
            return self._estimate_qdii(fund_code, last_nav, holding)

        holdings = self._storage.get_latest_holdings(conn, fund_code)

        if not holdings:
            log.warning("%s 无重仓股数据，跳过估算", fund_code)
            return self._empty_result(fund_code, last_nav)

        stock_codes = [h["stock_code"] for h in holdings]
        quotes = fetch_realtime_batch(stock_codes)

        total_weight = 0.0
        weighted_change = 0.0
        stock_detail = {}

        for h in holdings:
            sc = h["stock_code"]
            weight = (h["nav_pct"] or 0) / 100.0
            quote = quotes.get(sc)
            change = quote["change_pct"] if quote and quote["change_pct"] is not None else 0.0

            weighted_change += weight * change
            total_weight += weight
            stock_detail[sc] = {
                "name": h.get("stock_name", ""),
                "weight_pct": round(h["nav_pct"] or 0, 2),
                "change_pct": change,
            }

        coverage_pct = round(total_weight * 100, 2)
        estimated_pct = weighted_change  # 加权涨跌幅(%)

        estimated_nav = None
        if last_nav is not None:
            estimated_nav = round(last_nav * (1 + estimated_pct / 100.0), 6)

        return {
            "fund_code": fund_code,
            "trade_date": _date.today().isoformat(),
            "estimate_time": datetime.now(),
            "last_nav": last_nav,
            "estimated_nav": estimated_nav,
            "estimated_pct": round(estimated_pct, 4),
            "coverage_pct": coverage_pct,
            "stock_detail": stock_detail,
            "is_qdii": False,
        }

    def _estimate_qdii(self, fund_code: str, last_nav, holding: dict) -> dict:
        """QDII 基金通过期货/指数代理估算。"""
        proxy_quotes = fetch_qdii_proxy_quotes()
        proxy_key = QDII_PROXY_MAP.get(fund_code)

        if proxy_key and proxy_key in proxy_quotes:
            proxy = proxy_quotes[proxy_key]
            estimated_pct = proxy["change_pct"] or 0.0
            stock_detail = {
                "_proxy": {
                    "name": proxy.get("name", proxy_key),
                    "change_pct": estimated_pct,
                    "note": "QDII代理估算，非实际持仓涨跌",
                }
            }
            coverage_pct = 0.0
        else:
            estimated_pct = 0.0
            stock_detail = {"_note": "QDII基金，无可用代理，使用上日净值"}
            coverage_pct = 0.0

        estimated_nav = None
        if last_nav is not None:
            estimated_nav = round(last_nav * (1 + estimated_pct / 100.0), 6)

        return {
            "fund_code": fund_code,
            "trade_date": _date.today().isoformat(),
            "estimate_time": datetime.now(),
            "last_nav": last_nav,
            "estimated_nav": estimated_nav,
            "estimated_pct": round(estimated_pct, 4),
            "coverage_pct": coverage_pct,
            "stock_detail": stock_detail,
            "is_qdii": True,
        }

    def _empty_result(self, fund_code: str, last_nav) -> dict:
        return {
            "fund_code": fund_code,
            "trade_date": _date.today().isoformat(),
            "estimate_time": datetime.now(),
            "last_nav": last_nav,
            "estimated_nav": last_nav,
            "estimated_pct": 0.0,
            "coverage_pct": 0.0,
            "stock_detail": {},
            "is_qdii": False,
        }

    def estimate_all(self, conn) -> list[dict]:
        """遍历用户全部持仓，逐一估算净值并生成操作建议。

        Returns:
            [{fund_code, buy_net_value, shares, last_nav, estimated_nav,
              estimated_pct, coverage_pct, cost, market_value,
              total_pnl, total_pnl_pct, suggestion, ...}, ...]
        """
        holdings = self._storage.get_user_holdings(conn)
        if not holdings:
            log.info("无持仓数据")
            return []

        trade_date = _date.today().isoformat()
        estimation_records = []
        pnl_records = []

        for h in holdings:
            est = self.estimate_single(conn, h)
            estimation_records.append(est)

            buy_nav = h["buy_net_value"]
            shares = h["shares"]
            current_nav = est["estimated_nav"] or est["last_nav"] or buy_nav
            cost = round(buy_nav * shares, 2)
            market_value = round(current_nav * shares, 2)
            total_pnl = round(market_value - cost, 2)
            total_pnl_pct = round((current_nav - buy_nav) / buy_nav * 100, 4)
            daily_pnl = round(market_value - (est["last_nav"] or buy_nav) * shares, 2)
            daily_pnl_pct = est["estimated_pct"]

            suggestion = self.generate_suggestion(total_pnl_pct, daily_pnl_pct)

            pnl_records.append({
                "trade_date": trade_date,
                "fund_code": h["fund_code"],
                "fund_name": h.get("fund_name", ""),
                "buy_net_value": buy_nav,
                "current_nav": current_nav,
                "shares": shares,
                "cost": cost,
                "market_value": market_value,
                "total_pnl": total_pnl,
                "total_pnl_pct": total_pnl_pct,
                "daily_pnl": daily_pnl,
                "daily_pnl_pct": daily_pnl_pct,
                "suggestion": suggestion,
            })

        # 持久化
        if estimation_records:
            self._storage.insert_nav_estimation(conn, estimation_records)
        if pnl_records:
            self._storage.upsert_user_pnl(conn, pnl_records)

        return pnl_records

    def generate_suggestion(self, total_pnl_pct: float, daily_pct: float) -> str:
        """根据累计盈亏和当日涨跌生成操作建议。

        Args:
            total_pnl_pct: 累计盈亏百分比
            daily_pct: 当日估算涨跌幅百分比

        Returns:
            "HOLD" | "BUY" | "REDUCE" | "CLEAR"
        """
        r = self._rules

        if total_pnl_pct > r["clear_profit"] and daily_pct < r["daily_drop_clear"]:
            return "CLEAR"
        if total_pnl_pct > r["reduce_profit"] and daily_pct < r["daily_drop_reduce"]:
            return "REDUCE"
        if total_pnl_pct < r["clear_loss"]:
            return "CLEAR"
        if total_pnl_pct < r["reduce_loss"] and daily_pct < r["daily_drop_reduce"]:
            return "REDUCE"
        if daily_pct > r["daily_rise_buy"] and total_pnl_pct < 0:
            return "BUY"
        return "HOLD"
