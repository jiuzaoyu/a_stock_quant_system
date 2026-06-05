"""天天基金 HTTP 接口：基金列表 + 历史净值 + 基金经理 + 重仓股持仓。"""

import json
import re
from datetime import datetime
from typing import Optional

import aiohttp

TARGET_FUND_TYPE_PREFIXES = ("股票型", "混合型", "指数型")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
    "Referer": "https://fund.eastmoney.com/",
}

FUND_LIST_URL = "http://fund.eastmoney.com/js/fundcode_search.js"
FUND_HISTORY_TPL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
FUND_HOLDINGS_URL = (
    "https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    "?type=jjcc&code={code}&topline=10&year=&month=&rt=0.1"
)

HEADERS_F10 = {
    **HEADERS,
    "Referer": "https://fundf10.eastmoney.com/",
}


async def fetch_fund_list(session: Optional[aiohttp.ClientSession] = None) -> list[dict]:
    """拉取全量基金列表，过滤出股票型/混合型/指数型。

    API 返回每条记录共 5 个字段: [code, pinyin_abbr, name, fund_type, pinyin_full]

    Returns:
        [{"code": "019018", "name": "易方达信息产业混合C", "fund_type": "混合型",
          "pinyin": "YFDXXCYHHC", "pinyin_full": "YIFANGDAXINXICHANYEHUNHEC"}, ...]
    """
    text = await _get_text(session, FUND_LIST_URL, HEADERS)

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
    text = await _get_text(session, url, HEADERS)

    nav_pattern = r"Data_netWorthTrend\s*=\s*(\[.+?\])"
    nav_match = re.search(nav_pattern, text, re.DOTALL)
    if not nav_match:
        return []

    nav_data = json.loads(nav_match.group(1))

    ac_pattern = r"Data_ACWorthTrend\s*=\s*(\[\[.+?\]\])"
    ac_match = re.search(ac_pattern, text, re.DOTALL)
    ac_map = {}
    if ac_match:
        ac_data = json.loads(ac_match.group(1))
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
    """Unix 毫秒时间戳 → YYYY-MM-DD"""
    return datetime.fromtimestamp(ts / 1000).strftime("%Y-%m-%d")


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
    text = await _get_text(session, url, HEADERS)

    mgr_pattern = r"Data_currentFundManager\s*=\s*(.+?);\s*/\*"
    mgr_match = re.search(mgr_pattern, text)
    if not mgr_match:
        return []

    managers = json.loads(mgr_match.group(1))
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
    """刷新基金列表（用于增量采集前更新 fund_info）。

    Returns:
        增/更新的基金数
    """
    from psycopg2.extras import execute_values

    funds = await fetch_fund_list()
    sql = """
        INSERT INTO fund_info (code, name, fund_type, pinyin, pinyin_full)
        VALUES %s
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            fund_type = excluded.fund_type,
            pinyin = excluded.pinyin,
            pinyin_full = excluded.pinyin_full,
            updated_at = NOW()
    """
    from ..utils.database import sanitize

    tuples = [
        (sanitize(f["code"]), sanitize(f["name"]), sanitize(f["fund_type"]),
         sanitize(f.get("pinyin", "")), sanitize(f.get("pinyin_full", "")))
        for f in funds
    ]
    tuples = list({t[0]: t for t in tuples}.values())
    with storage_conn.cursor() as cur:
        execute_values(cur, sql, tuples, page_size=1000)
        return cur.rowcount


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
    if session is not None:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            return await resp.text(encoding="utf-8")
    else:
        async with aiohttp.ClientSession(headers=headers) as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=30)) as resp:
                return await resp.text(encoding="utf-8")
