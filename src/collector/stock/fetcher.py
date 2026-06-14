"""
股票数据获取：mootdx (K线) + 腾讯财经 (估值) + AkShare (股票列表)。

数据源优先级（均免费、无 API Key、不封IP）:
  1. AkShare     — A股全量股票列表 (HTTP)
  2. mootdx      — K线数据 (TCP 7709)
  3. 腾讯财经     — PE/PB/市值/换手率/涨跌停价 (HTTP)
"""

import urllib.request
from datetime import date as _date
from typing import Optional

import pandas as pd

# ============================================================================
# 0. 工具函数
# ============================================================================


def get_prefix(code: str) -> str:
    """6位代码 → 市场前缀: sh(沪) / sz(深) / bj(北)"""
    if code.startswith(("6", "9")):
        return "sh"
    elif code.startswith("8"):
        return "bj"
    else:
        return "sz"


def normalize_code(raw: str) -> str:
    """归一化为纯6位数字代码。"""
    raw = raw.upper()
    for s in [".SH", ".SZ", ".BJ"]:
        raw = raw.replace(s, "")
    for s in ["SH", "SZ", "BJ"]:
        if raw.startswith(s) and len(raw) == 8:
            raw = raw[2:]
    return raw


# ============================================================================
# 1. AkShare — A股全量股票列表
# ============================================================================


# A股代码前缀过滤规则
_SH_STOCK_PREFIXES = ("600", "601", "603", "605", "688", "689")
_SZ_STOCK_PREFIXES = ("000", "001", "002", "003", "300", "301")
_BJ_STOCK_PREFIXES = ("8",)


def _is_a_stock(code: str) -> bool:
    """判断是否为A股（过滤掉指数、债券、ETF等）。"""
    return (
        code.startswith(_SH_STOCK_PREFIXES)
        or code.startswith(_SZ_STOCK_PREFIXES)
        or code.startswith(_BJ_STOCK_PREFIXES)
    )


def fetch_stock_list(source: str = "mootdx") -> list[dict]:
    """拉取A股全量股票列表（代码+名称）。

    Args:
        source: "mootdx" (TCP, 可靠) / "akshare" (HTTP, 更快但可能被墙)

    Returns:
        [{"code": "688017", "name": "绿的谐波", "market": "sh"}, ...]
    """
    if source == "akshare":
        return _fetch_stock_list_akshare()
    return _fetch_stock_list_mootdx()


def _fetch_stock_list_mootdx() -> list[dict]:
    """通过 mootdx TCP 获取股票列表，按市场分别过滤A股。

    注意: 同一代码可能同时出现在沪深两市:
      - 000001 在沪市(market=1)是"上证指数"，在深市(market=0)是"平安银行"
      - 必须按市场分别过滤，避免将指数当股票入库
    """
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    records = []
    seen = set()

    # 沪市: 只取 6xx 开头
    market_filters = {
        1: _SH_STOCK_PREFIXES,   # 沪: 600/601/603/605/688/689
        0: _SZ_STOCK_PREFIXES,   # 深: 000/001/002/003/300/301
    }

    for market_id in (1, 0):
        try:
            df = client.stocks(market=market_id)
        except Exception:
            continue
        prefixes = market_filters[market_id]
        for _, row in df.iterrows():
            code = str(int(row["code"])).zfill(6)
            if not code.startswith(prefixes):
                continue
            if code in seen:
                continue
            seen.add(code)
            name = str(row.get("name", ""))
            records.append({
                "code": code,
                "name": name,
                "market": get_prefix(code),
            })

    return records


def _fetch_stock_list_akshare() -> list[dict]:
    """通过 AkShare HTTP 获取股票列表（更快，但需网络畅通）。"""
    import akshare as ak

    df = ak.stock_info_a_code_name()
    records = []
    for _, row in df.iterrows():
        code = normalize_code(str(row["code"]))
        records.append({
            "code": code,
            "name": str(row["name"]),
            "market": get_prefix(code),
        })
    return records


# ============================================================================
# 2. mootdx — K线数据
# ============================================================================


def _mootdx_client():
    """获取 mootdx 标准行情客户端。"""
    from mootdx.quotes import Quotes

    return Quotes.factory(market="std")


def fetch_kline(
    code: str, category: int = 4, offset: int = 10
) -> list[dict]:
    """获取单只股票K线数据。

    Args:
        code: 6位股票代码
        category: 4=日线, 5=周线, 6=月线, 7=1分钟, 8=5分钟, 9=15分钟, 10=30分钟, 11=60分钟
        offset: 返回最近N根K线

    Returns:
        [{"code": "688017", "trade_date": "2026-06-04", "open": 1.0, ...}, ...]
    """
    client = _mootdx_client()
    df = client.bars(symbol=normalize_code(code), category=category, offset=offset)

    if df.empty:
        return []

    records = []
    for _, row in df.iterrows():
        dt = row.get("datetime")
        if dt is not None:
            trade_date = pd.Timestamp(dt).strftime("%Y-%m-%d")
        else:
            continue

        records.append({
            "code": normalize_code(code),
            "trade_date": trade_date,
            "open": _safe_float(row.get("open")),
            "high": _safe_float(row.get("high")),
            "low": _safe_float(row.get("low")),
            "close": _safe_float(row.get("close")),
            "volume": _safe_float(row.get("volume")),
            "amount": _safe_float(row.get("amount")),
        })
    return records


# ============================================================================
# 3. 腾讯财经 — PE/PB/市值/换手率/涨跌停价 (HTTP)
# ============================================================================


def fetch_tencent_valuation(codes: list[str]) -> dict[str, dict]:
    """批量拉取腾讯财经估值数据。

    Args:
        codes: 股票代码列表，支持个股/指数/ETF

    Returns:
        {code: {pe_ttm, pb, mcap_yi, trade_date, ...}, ...}
    """
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
        key = line.split("=")[0].split("_")[-1]
        vals = line.split('"')[1].split("~")
        if len(vals) < 53:
            continue
        code = key[2:]
        trade_date = _date.today().strftime("%Y-%m-%d")

        result[code] = {
            "code": code,
            "name": vals[1],
            "trade_date": trade_date,
            "price": _safe_float(vals[3]),
            "last_close": _safe_float(vals[4]),
            "open": _safe_float(vals[5]),
            "change_pct": _safe_float(vals[32]),
            "high": _safe_float(vals[33]),
            "low": _safe_float(vals[34]),
            "amount_wan": _safe_float(vals[37]),
            "turnover_pct": _safe_float(vals[38]),
            "pe_ttm": _safe_float(vals[39]),
            "amplitude_pct": _safe_float(vals[43]),
            "mcap_yi": _safe_float(vals[44]),
            "float_mcap_yi": _safe_float(vals[45]),
            "pb": _safe_float(vals[46]),
            "limit_up": _safe_float(vals[47]),
            "limit_down": _safe_float(vals[48]),
            "vol_ratio": _safe_float(vals[49]),
            "pe_static": _safe_float(vals[52]),
        }
    return result


def fetch_tencent_batch(
    codes: list[str], batch_size: int = 80
) -> list[dict]:
    """批量拉取腾讯财经估值数据，自动分批。

    Returns:
        估值记录列表，每条包含 code, trade_date, pe_ttm, pb, ...
    """
    all_records = []
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        data = fetch_tencent_valuation(batch)
        for code, info in data.items():
            all_records.append({
                "code": code,
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
            })
    return all_records


# ============================================================================
# 内部辅助
# ============================================================================


def _safe_float(val) -> Optional[float]:
    """安全转换为 float，空值返回 None。"""
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None
