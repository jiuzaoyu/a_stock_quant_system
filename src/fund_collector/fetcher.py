"""天天基金 HTTP 接口：基金列表 + 全量历史净值。"""

import json
import re
import time
import urllib.request
from datetime import datetime

TARGET_FUND_TYPE_PREFIXES = ("股票型", "混合型", "指数型")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/117.0.0.0",
    "Referer": "https://fund.eastmoney.com/",
}

FUND_LIST_URL = "http://fund.eastmoney.com/js/fundcode_search.js"
FUND_HISTORY_TPL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"


def fetch_fund_list() -> list[dict]:
    """拉取全量基金列表，过滤出股票型/混合型/指数型。

    Returns:
        [{"code": "019018", "name": "易方达信息产业混合C", "fund_type": "混合型"}, ...]
    """
    req = urllib.request.Request(FUND_LIST_URL, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30)
    text = resp.read().decode("utf-8")

    json_str = text[text.index("[") : text.rindex("]") + 1]
    all_funds = json.loads(json_str)

    result = []
    for item in all_funds:
        code = item[0]
        name = item[2]
        fund_type = item[3]
        if fund_type.startswith(TARGET_FUND_TYPE_PREFIXES):
            result.append({"code": code, "name": name, "fund_type": fund_type})
    return result


def fetch_fund_full_history(code: str) -> list[dict]:
    """拉取单只基金全部历史净值（自成立日起）。

    Args:
        code: 6位基金代码

    Returns:
        [{"code": "019018", "nav_date": "2024-05-28", "unit_nav": 1.2345,
          "accum_nav": 2.3456, "daily_growth": 0.25}, ...]
    """
    url = FUND_HISTORY_TPL.format(code=code)
    req = urllib.request.Request(url, headers=HEADERS)
    resp = urllib.request.urlopen(req, timeout=30)
    text = resp.read().decode("utf-8")

    # 解析 var Data_netWorthTrend = [{...}];
    nav_pattern = r"Data_netWorthTrend\s*=\s*(\[.+?\])"
    nav_match = re.search(nav_pattern, text, re.DOTALL)
    if not nav_match:
        return []

    nav_data = json.loads(nav_match.group(1))

    # 解析 var Data_ACWorthTrend = [[ts, value], ...];  累计净值
    # 格式: [[1735689600000, 1.2345], ...]  (二级数组，非对象数组)
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

        # 计算日增长率 (相对于前一天)
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


def fetch_fund_list_refresh(storage_conn) -> int:
    """刷新基金列表（用于增量采集前更新 fund_info）。

    Returns:
        增/更新的基金数
    """
    funds = fetch_fund_list()
    return storage_conn.executemany(
        """INSERT INTO fund_info (code, name, fund_type)
           VALUES (:code, :name, :fund_type)
           ON CONFLICT(code) DO UPDATE SET
               name = excluded.name,
               fund_type = excluded.fund_type,
               updated_at = datetime('now', 'localtime')""",
        funds,
    )
