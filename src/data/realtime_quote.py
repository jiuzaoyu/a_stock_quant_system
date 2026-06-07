"""
股票实时行情获取 — 腾讯财经 HTTP 接口。

用于盘中净值估算，获取重仓股的实时涨跌幅和价格。
"""

import urllib.request
from datetime import date as _date
from typing import Optional

from ..stock_collector.fetcher import get_prefix, normalize_code


def _safe_float(val) -> Optional[float]:
    try:
        return float(val) if val not in ("", "-", None) else None
    except (ValueError, TypeError):
        return None


def fetch_realtime_quotes(codes: list[str]) -> dict[str, dict]:
    """批量获取股票实时行情（价格 + 涨跌幅）。

    接口: qt.gtimg.cn，免费无认证，单次最多约 80 只。

    Args:
        codes: 股票代码列表

    Returns:
        {code: {name, price, last_close, change_pct, open, high, low, turnover_pct}, ...}
        获取失败的 code 不在返回结果中。
    """
    if not codes:
        return {}

    prefixed = []
    for c in codes:
        c = normalize_code(c)
        prefixed.append(f"{get_prefix(c)}{c}")

    url = "https://qt.gtimg.cn/q=" + ",".join(prefixed)
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = normalize_code(line.split("=")[0].split("_")[-1])

        result[code] = {
            "code": code,
            "name": vals[1],
            "price": _safe_float(vals[3]),
            "last_close": _safe_float(vals[4]),
            "open": _safe_float(vals[5]),
            "high": _safe_float(vals[33]),
            "low": _safe_float(vals[34]),
            "change_pct": _safe_float(vals[32]),
            "turnover_pct": _safe_float(vals[38]),
        }
    return result


def fetch_realtime_batch(codes: list[str], batch_size: int = 80) -> dict[str, dict]:
    """分批次获取股票实时行情。

    Returns:
        合并后的 {code: quote_dict} 字典。
    """
    all_quotes = {}
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        all_quotes.update(fetch_realtime_quotes(batch))
    return all_quotes


def fetch_qdii_proxy_quotes() -> dict[str, dict]:
    """获取 QDII 代理行情（恒生指数、纳斯达克 100 期货等）。

    用于 QDII 基金的间接估算。

    Returns:
        {proxy_name: {price, change_pct}, ...}
    """
    symbols = {
        "hs_index": "100.HSI",           # 恒生指数
        "hs_tech": "124.HSTECH",         # 恒生科技指数
        "nq_future": "112.NQmain",       # 纳斯达克 100 期货 (芝商所迷你)
    }

    url = "https://qt.gtimg.cn/q=" + ",".join(symbols.values())
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    resp = urllib.request.urlopen(req, timeout=10)
    data = resp.read().decode("gbk")

    result = {}
    code_to_name = {v: k for k, v in symbols.items()}
    for line in data.strip().split(";"):
        if not line.strip() or "=" not in line or '"' not in line:
            continue
        key = line.split("=")[0].split("_")[-1] if "_" in line.split("=")[0] else ""
        if not key:
            continue
        vals = line.split('"')[1].split("~")
        if len(vals) < 33:
            continue
        name = code_to_name.get(key, key)
        result[name] = {
            "price": _safe_float(vals[3]),
            "change_pct": _safe_float(vals[32]),
            "name": vals[1],
        }
    return result
