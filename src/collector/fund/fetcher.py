"""天天基金 HTTP 接口：基金列表 + 历史净值 + 基金经理 + 重仓股持仓。"""

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

import aiohttp
from psycopg2.extras import execute_values

from config.collector.fund_cfg import (
    FUND_HISTORY_TPL,
    FUND_HOLDINGS_URL,
    FUND_LIST_URL,
    HEADERS_F10,
    HEADERS_FUND,
    REQUEST_TIMEOUT,
    TARGET_FUND_TYPE_PREFIXES,
)
from ...utils.database import sanitize
from ...utils.logger import get_logger

CST = timezone(timedelta(hours=8))

logger = get_logger(__name__)


async def fetch_fund_list(session: Optional[aiohttp.ClientSession] = None) -> list[dict]:
    """拉取全量基金列表，过滤出股票型/混合型/指数型。

    API 返回每条记录共 5 个字段: [code, pinyin_abbr, name, fund_type, pinyin_full]

    Returns:
        [{"code": "019018", "name": "易方达信息产业混合C", "fund_type": "混合型",
          "pinyin": "YFDXXCYHHC", "pinyin_full": "YIFANGDAXINXICHANYEHUNHEC"}, ...]
    """
    text = await _get_text(session, FUND_LIST_URL, HEADERS_FUND)

    json_str = text[text.index("[") : text.rindex("]") + 1]
    all_funds = json.loads(json_str)

    result = []
    for item in all_funds:
        code = item[0]
        name = item[2]
        fund_type = item[3]
        if fund_type.startswith(TARGET_FUND_TYPE_PREFIXES):
            result.append({
                "code": code,
                "name": name,
                "fund_type": fund_type,
                "pinyin": item[1],
                "pinyin_full": item[4],
            })
    return result


async def fetch_fund_full_history(
    code: str, session: Optional[aiohttp.ClientSession] = None
) -> list[dict]:
    """拉取单只基金全部历史净值（自成立日起）。

    Args:
        code: 6位基金代码

    Returns:
        [{"code": "019018", "nav_date": "2024-05-28", "unit_nav": 1.2345,
          "accum_nav": 2.3456, "daily_growth": 0.25}, ...]
    """
    url = FUND_HISTORY_TPL.format(code=code)
    text = await _get_text(session, url, HEADERS_FUND)

    nav_pattern = r"Data_netWorthTrend\s*=\s*(\[.*?\])\s*;"
    nav_match = re.search(nav_pattern, text, re.DOTALL)
    if not nav_match:
        logger.warning("%s: Data_netWorthTrend not found", code)
        return []

    try:
        nav_data = json.loads(nav_match.group(1))
    except json.JSONDecodeError as e:
        logger.warning("%s: Data_netWorthTrend JSON parse failed: %s", code, e)
        return []

    ac_pattern = r"Data_ACWorthTrend\s*=\s*(\[\[.*?\]\])\s*;"
    ac_match = re.search(ac_pattern, text, re.DOTALL)
    ac_map = {}
    if ac_match:
        try:
            ac_data = json.loads(ac_match.group(1))
        except json.JSONDecodeError as e:
            logger.warning("%s: Data_ACWorthTrend JSON parse failed: %s", code, e)
            ac_data = []
        for entry in ac_data:
            if isinstance(entry, list) and len(entry) >= 2:
                ts = entry[0]
                val = entry[1]
                if ts is not None and val is not None:
                    date_str = _ts_to_date(ts)
                    if isinstance(val, list):
                        val = val[0] if val else None
                    if val is not None:
                        ac_map[date_str] = val

    rows = []
    for i, item in enumerate(nav_data):
        ts = item.get("x")
        unit_nav = item.get("y")
        if ts is None or unit_nav is None:
            continue
        date_str = _ts_to_date(ts)
        accum_nav = item.get("equityReturn") or ac_map.get(date_str)

        daily_growth = 0.0
        if i > 0:
            prev_nav = nav_data[i - 1].get("y", 0)
            if prev_nav and prev_nav > 0:
                daily_growth = round((unit_nav - prev_nav) / prev_nav * 100, 4)

        rows.append({
            "code": code,
            "nav_date": date_str,
            "unit_nav": unit_nav,
            "accum_nav": accum_nav,
            "daily_growth": daily_growth,
        })
    return rows


def _ts_to_date(ts: int) -> str:
    """Unix 毫秒时间戳 → YYYY-MM-DD（北京时间）"""
    return datetime.fromtimestamp(ts / 1000, tz=CST).strftime("%Y-%m-%d")


async def fetch_fund_manager(
    code: str, session: Optional[aiohttp.ClientSession] = None
) -> list[dict]:
    """拉取单只基金的基金经理信息。

    数据来源: pingzhongdata/{code}.js 中的 Data_currentFundManager 变量。

    Returns:
        [{"manager_id": "30379533", "name": "侯昊", "star": 5,
          "work_time": "8年又282天", "fund_size": "533.63亿(24只基金)",
          "power_avr": 83.64, "power_json": "[87.4, 71.6, ...]",
          "profit_json": "{...}"}, ...]
    """
    url = FUND_HISTORY_TPL.format(code=code)
    text = await _get_text(session, url, HEADERS_FUND)

    mgr_pattern = r"Data_currentFundManager\s*=\s*(.+?);\s*/\*"
    mgr_match = re.search(mgr_pattern, text)
    if not mgr_match:
        return []

    try:
        managers = json.loads(mgr_match.group(1))
    except json.JSONDecodeError as e:
        logger.warning("%s: Data_currentFundManager JSON parse failed: %s", code, e)
        return []
    result = []
    for m in managers:
        power = m.get("power", {}) or {}
        profit = m.get("profit", {}) or {}

        profit_json = "{}"
        series = profit.get("series", [])
        if series and series[0].get("data"):
            profit_json = json.dumps({
                "tenure": series[0]["data"][0].get("y"),
                "peer_avg": series[0]["data"][1].get("y") if len(series[0]["data"]) > 1 else None,
                "hs300": series[0]["data"][2].get("y") if len(series[0]["data"]) > 2 else None,
            }, ensure_ascii=False)

        result.append({
            "manager_id": m.get("id", ""),
            "name": m.get("name", ""),
            "star": _safe_int(m.get("star")),
            "work_time": m.get("workTime"),
            "fund_size": m.get("fundSize"),
            "power_avr": _safe_float(power.get("avr")),
            "power_json": json.dumps(power.get("data", []), ensure_ascii=False),
            "profit_json": profit_json,
        })
    return result


async def fetch_fund_holdings(
    code: str, session: Optional[aiohttp.ClientSession] = None
) -> tuple[str, list[dict]]:
    """拉取单只基金最新季度的前十大重仓股。

    数据来源: fundf10.eastmoney.com FundArchivesDatas.aspx (HTML table)。

    Returns:
        (report_date, holdings)
        report_date  报告期截止日 "2026-03-31"
        holdings     [{"stock_code": "600519", "stock_name": "贵州茅台",
                       "rank": 1, "nav_pct": 18.33,
                       "shares_wan": 508.34, "market_cap_wan": 737086.62}, ...]
    """
    url = FUND_HOLDINGS_URL.format(code=code)
    text = await _get_text(session, url, HEADERS_F10)

    report_date = ""
    date_m = re.search(r"截止至：<font[^>]*>(\d{4}-\d{2}-\d{2})</font>", text)
    if date_m:
        report_date = date_m.group(1)

    row_pattern = (
        r"<tr><td>(\d+)</td>"
        r"<td>.*?>(.*?)</a></td>"
        r"<td[^>]*>.*?>(.*?)</a></td>"
        r".*?<td[^>]*>([^<]+)</td>"
        r".*?<td[^>]*>([^<]+)</td>"
        r".*?<td[^>]*>([^<]+)</td>"
    )
    rows = re.findall(row_pattern, text)

    holdings = []
    for row in rows:
        rank, stock_code, stock_name, nav_pct_str, shares_str, mcap_str = row
        try:
            nav_pct = float(nav_pct_str.replace("%", "").strip())
        except ValueError:
            nav_pct = None
        try:
            shares_wan = float(shares_str.replace(",", "").strip())
        except ValueError:
            shares_wan = None
        try:
            market_cap_wan = float(mcap_str.replace(",", "").strip())
        except ValueError:
            market_cap_wan = None

        holdings.append({
            "stock_code": stock_code.strip(),
            "stock_name": stock_name.strip(),
            "rank": int(rank),
            "nav_pct": nav_pct,
            "shares_wan": shares_wan,
            "market_cap_wan": market_cap_wan,
        })

    return report_date, holdings


async def fetch_fund_list_refresh(storage_conn) -> int:
    """从天天基金拉取全量列表，增量同步到 fund_info 表。

    行为：
      - 新基金 → INSERT 入库（is_deleted = FALSE）
      - 已有基金 → UPDATE name / fund_type / pinyin，同时 is_deleted = FALSE（已下架又上架的基金恢复）
      - 不在本次列表中的基金 → is_deleted 标记为 TRUE（软删除，历史数据不丢）

    Returns:
        本次增/更新的基金数（纯新增 + 有变更的）
    """

    funds = await fetch_fund_list()
    sql = """
        INSERT INTO fund_info (code, name, fund_type, pinyin, pinyin_full)
        VALUES %s
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            fund_type = excluded.fund_type,
            pinyin = excluded.pinyin,
            pinyin_full = excluded.pinyin_full,
            is_deleted = FALSE,
            updated_at = NOW()
    """

    tuples = [
        (sanitize(f["code"]), sanitize(f["name"]), sanitize(f["fund_type"]),
         sanitize(f.get("pinyin", "")), sanitize(f.get("pinyin_full", "")))
        for f in funds
    ]
    tuples = list({t[0]: t for t in tuples}.values())
    active_codes = [t[0] for t in tuples]
    with storage_conn.cursor() as cur:
        execute_values(cur, sql, tuples, page_size=1000)
        upserted = cur.rowcount
        cur.execute(
            "UPDATE fund_info SET is_deleted = TRUE, updated_at = NOW() "
            "WHERE is_deleted = FALSE AND code != ALL(%s)",
            (active_codes,),
        )
        deleted = cur.rowcount
        logger.info("基金列表同步: upsert %d 条, 标记删除 %d 条", upserted, deleted)
        return upserted


# ------------------------------------------------------------------ 内部辅助

def _safe_float(value):
    """将值转为 float，无法转换（如'暂无数据'）时返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _safe_int(value):
    """将值转为 int，无法转换时返回 None。"""
    if value is None:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


async def _get_text(
    session: Optional[aiohttp.ClientSession],
    url: str,
    headers: dict[str, str],
) -> str:
    """发起 GET 请求并返回响应文本。session 为 None 时自动创建临时 session。"""
    timeout = aiohttp.ClientTimeout(total=REQUEST_TIMEOUT)
    if session:
        async with session.get(url, headers=headers, timeout=timeout) as resp:
            return await resp.text(encoding="utf-8")
    async with aiohttp.ClientSession(headers=headers) as s:
        async with s.get(url, timeout=timeout) as resp:
            return await resp.text(encoding="utf-8")
