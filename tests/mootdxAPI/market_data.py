"""
A股稳定行情数据 API — 基于 mootdx(TCP) + 腾讯财经(HTTP)

数据源优先级（均免费、无 API Key、不封IP）:
  1. mootdx      — K线 + 五档盘口 + 逐笔成交 + 财务快照 + F10 (TCP 7709)
  2. 腾讯财经     — PE/PB/市值/换手率/涨跌停价/指数/ETF (HTTP)

用法:
  python tests/mootdxAPI/market_data.py           # 跑全部demo
  python tests/mootdxAPI/market_data.py --kline    # 只看K线
  python tests/mootdxAPI/market_data.py --quote    # 只看实时行情
"""

import argparse
import urllib.request
from datetime import date as _date

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
    """归一化为纯6位数字代码: SH688017 / 688017.SH / SZ000001 → 688017 / 000001"""
    raw = raw.upper()
    for s in [".SH", ".SZ", ".BJ"]:
        raw = raw.replace(s, "")
    for s in ["SH", "SZ", "BJ"]:
        if raw.startswith(s) and len(raw) == 8:
            raw = raw[2:]
    return raw


# ============================================================================
# 1. mootdx — K线 + 五档盘口 + 逐笔成交 + 财务快照 + F10 (TCP)
#    依赖: pip install mootdx
# ============================================================================


def mootdx_client():
    """获取 mootdx 标准行情客户端"""
    from mootdx.quotes import Quotes

    return Quotes.factory(market="std")


def get_kline(code: str, category: int = 4, offset: int = 10) -> pd.DataFrame:
    """
    K线数据 (最常用接口) — 返回 DataFrame
    code     : 6位股票代码, 如 "688017"
    category : 4=日线, 5=周线, 6=月线,
               7=1分钟, 8=5分钟, 9=15分钟, 10=30分钟, 11=60分钟
    offset   : 返回最近N根K线
    返回列   : open, close, high, low, volume, amount, datetime
    """
    client = mootdx_client()
    return client.bars(symbol=normalize_code(code), category=category, offset=offset)


def get_realtime_quotes(codes: list[str]) -> pd.DataFrame:
    """
    实时报价 — 返回 DataFrame, 含五档盘口
    返回列: market, code, active1, price, last_close, open, high, low,
           servertime, vol, amount, s_vol, bid1~5, ask1~5, bid_vol1~5, ask_vol1~5
    """
    client = mootdx_client()
    return client.quotes(symbol=[normalize_code(c) for c in codes])


def get_transactions(code: str, date: str = None) -> pd.DataFrame:
    """
    逐笔成交 (非交易时间返回空)
    date: "YYYYMMDD", None=今天
    返回列: time, price, vol, num, buyorsell (0买/1卖/2中性)
    """
    client = mootdx_client()
    if date is None:
        date = _date.today().strftime("%Y%m%d")
    return client.transaction(symbol=normalize_code(code), date=date)


def get_finance(code: str) -> pd.Series:
    """
    财务快照 — 37字段季报数据, 返回 Series
    含: liutongguben(流通股本), zongguben(总股本), 每股收益, 每股净资产,
        净资产收益率, 净利润, 主营收入, 每股公积金, 每股未分配利润 等
    """
    client = mootdx_client()
    return client.finance(symbol=normalize_code(code)).iloc[0]


def get_f10(code: str, category: str = "最新提示") -> str:
    """
    公司F10文本资料
    category: "最新提示" / "公司概况" / "财务分析" /
              "股东研究" / "股本结构" / "资本运作" /
              "业内点评" / "行业分析" / "公司大事"
    """
    client = mootdx_client()
    return client.F10(symbol=normalize_code(code), name=category)


# ============================================================================
# 2. 腾讯财经 API — PE/PB/市值/换手率/涨跌停/指数/ETF (HTTP)
#    mootdx 不提供上述字段，腾讯补齐
# ============================================================================


def tencent_quote(codes: list[str]) -> dict[str, dict]:
    """
    批量拉取腾讯财经实时行情 (HTTP GET, GBK编码, 不封IP)
    codes: 个股["688017","300476"] / 指数["000001","000300","399006"] / ETF["510050","510300"]
    返回: {code: {name, price, pe_ttm, pb, mcap_yi, ...}}
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
        result[code] = {
            "name": vals[1],
            "price": float(vals[3]) if vals[3] else 0,
            "last_close": float(vals[4]) if vals[4] else 0,
            "open": float(vals[5]) if vals[5] else 0,
            "change_amt": float(vals[31]) if vals[31] else 0,
            "change_pct": float(vals[32]) if vals[32] else 0,
            "high": float(vals[33]) if vals[33] else 0,
            "low": float(vals[34]) if vals[34] else 0,
            "amount_wan": float(vals[37]) if vals[37] else 0,
            "turnover_pct": float(vals[38]) if vals[38] else 0,
            "pe_ttm": float(vals[39]) if vals[39] else 0,
            "amplitude_pct": float(vals[43]) if vals[43] else 0,
            "mcap_yi": float(vals[44]) if vals[44] else 0,
            "float_mcap_yi": float(vals[45]) if vals[45] else 0,
            "pb": float(vals[46]) if vals[46] else 0,
            "limit_up": float(vals[47]) if vals[47] else 0,
            "limit_down": float(vals[48]) if vals[48] else 0,
            "vol_ratio": float(vals[49]) if vals[49] else 0,
            "pe_static": float(vals[52]) if vals[52] else 0,
        }
    return result


# ============================================================================
# 3. 便捷函数 — 一键获取完整行情
# ============================================================================


def quick_view(code: str) -> dict:
    """
    一键查看个股完整行情 — 同时拉 mootdx 实时盘口 + 腾讯估值数据
    """
    code = normalize_code(code)

    # mootdx 实时报价 (DataFrame)
    from mootdx.quotes import Quotes

    client = Quotes.factory(market="std")
    qt_df = client.quotes(symbol=[code])

    # 腾讯估值数据 (dict)
    tx = tencent_quote([code]).get(code, {})

    result = {
        "code": code,
        "name": tx.get("name", ""),
        "price": tx.get("price", 0),
        "open": tx.get("open", 0),
        "high": tx.get("high", 0),
        "low": tx.get("low", 0),
        "last_close": tx.get("last_close", 0),
        "change_pct": tx.get("change_pct", 0),
        "amount_wan": tx.get("amount_wan", 0),
        "turnover_pct": tx.get("turnover_pct", 0),
        "vol_ratio": tx.get("vol_ratio", 0),
        "pe_ttm": tx.get("pe_ttm", 0),
        "pb": tx.get("pb", 0),
        "mcap_yi": tx.get("mcap_yi", 0),
        "float_mcap_yi": tx.get("float_mcap_yi", 0),
        "limit_up": tx.get("limit_up", 0),
        "limit_down": tx.get("limit_down", 0),
    }

    if not qt_df.empty:
        row = qt_df.iloc[0]
        result["bid1"] = row.get("bid1", 0) if "bid1" in row.index else 0
        result["ask1"] = row.get("ask1", 0) if "ask1" in row.index else 0
    else:
        result["bid1"] = 0
        result["ask1"] = 0

    return result


# ============================================================================
# 4. Demo 演示
# ============================================================================

DEMO_CODE = "000001"  # 平安银行


def demo_kline():
    """K线数据"""
    print("=" * 60)
    print("【1】K线数据 (mootdx) — get_kline()")
    print("=" * 60)

    # 日线
    df = get_kline(DEMO_CODE, category=4, offset=5)
    print("\n--- 日线 (最近5根) ---")
    print(df[["datetime", "open", "high", "low", "close", "volume"]].to_string(index=False) if "datetime" in df.columns else df.head().to_string())

    # 周线
    df_w = get_kline(DEMO_CODE, category=5, offset=5)
    print("\n--- 周线 (最近5根) ---")
    print(df_w[["datetime", "open", "high", "low", "close"]].to_string(index=False) if "datetime" in df_w.columns else df_w.head().to_string())

    # 15分钟线
    df_m = get_kline(DEMO_CODE, category=9, offset=5)
    print("\n--- 15分钟线 (最近5根) ---")
    print(df_m[["datetime", "open", "high", "low", "close"]].to_string(index=False) if "datetime" in df_m.columns else df_m.head().to_string())


def demo_realtime():
    """实时报价 + 五档盘口"""
    print("=" * 60)
    print("【2】实时报价 + 五档盘口 (mootdx) — get_realtime_quotes()")
    print("=" * 60)

    df = get_realtime_quotes(["000001", "600519"])
    if df.empty:
        print("  无数据 (非交易时间?)")
        return

    show_cols = ["code", "price", "open", "high", "low", "vol", "amount", "bid1", "ask1"]
    available = [c for c in show_cols if c in df.columns]
    print()
    print(df[available].to_string(index=False))

    # 盘口详情
    for _, row in df.iterrows():
        bids = [str(row.get(f"bid{i}", "")) for i in range(1, 6)]
        asks = [str(row.get(f"ask{i}", "")) for i in range(1, 6)]
        print(f"\n  {row.get('code','')} 买五档: {' / '.join(bids)}")
        print(f"  {row.get('code','')} 卖五档: {' / '.join(asks)}")


def demo_tencent_quote():
    """腾讯财经 — 估值数据"""
    print("\n" + "=" * 60)
    print("【3】腾讯财经实时估值 (PE/PB/市值/涨跌停价) — tencent_quote()")
    print("=" * 60)

    print("\n--- 个股 ---")
    quotes = tencent_quote(["000001", "600519", "300476"])
    for code, q in quotes.items():
        print(f"  {q['name']}({code}): price={q['price']} "
              f"PE(TTM)={q['pe_ttm']} PB={q['pb']} "
              f"总市值={q['mcap_yi']}亿 换手={q['turnover_pct']}% "
              f"涨停={q['limit_up']} 跌停={q['limit_down']}")

    print("\n--- 指数 ---")
    idx = tencent_quote(["000001", "000300", "399006"])
    for code, q in idx.items():
        print(f"  {q['name']}({code}): {q['price']} 涨跌={q['change_pct']}% 成交={q['amount_wan']}万")

    print("\n--- ETF ---")
    etf = tencent_quote(["510050", "510300"])
    for code, q in etf.items():
        print(f"  {q['name']}({code}): {q['price']} 涨跌={q['change_pct']}%")


def demo_finance():
    """财务快照"""
    print("\n" + "=" * 60)
    print("【4】财务快照 (mootdx finance) — get_finance()")
    print("=" * 60)

    fin = get_finance(DEMO_CODE)
    if not isinstance(fin, pd.Series):
        print("  无数据")
        return

    # pinyin key → Chinese label mapping (37 fields)
    key_map = {
        "meigujingzichan": "每股净资产",
        "jinglirun": "净利润",
        "zhuyingshouru": "主营收入",
        "liutongguben": "流通股本",
        "zongguben": "总股本",
        "zibengongjijin": "资本公积金",
        "weifenpeilirun": "未分配利润",
        "jingzichan": "净资产",
        "yingyelirun": "营业利润",
        "touzishouyu": "投资收益",
        "gudongrenshu": "股东人数",
        "ipo_date": "上市日期",
        "updated_date": "财报更新日",
    }
    # 大型金额字段 (单位: 元 → 亿)
    big_amount_keys = {"jinglirun", "zhuyingshouru", "yingyelirun",
                        "touzishouyu", "jingzichan", "liutongguben",
                        "zongguben", "zibengongjijin", "weifenpeilirun"}
    for py_key, cn_label in key_map.items():
        val = fin.get(py_key, "N/A")
        if py_key in big_amount_keys and isinstance(val, (int, float)):
            val = f"{val / 1e8:.2f}亿"
        print(f"  {cn_label}: {val}")


def demo_quick_view():
    """一键综合行情"""
    print("\n" + "=" * 60)
    print("【5】一键综合行情 (mootdx + 腾讯财经) — quick_view()")
    print("=" * 60)

    for code in ["000001", "600519"]:
        q = quick_view(code)
        print(f"\n  {q['name']}({q['code']})")
        print(f"    现价={q['price']}  涨跌幅={q['change_pct']}%")
        print(f"    PE(TTM)={q['pe_ttm']}  PB={q['pb']}  总市值={q['mcap_yi']}亿")
        print(f"    换手率={q['turnover_pct']}%  量比={q['vol_ratio']}")
        print(f"    买一={q['bid1']}  卖一={q['ask1']}")
        print(f"    涨停价={q['limit_up']}  跌停价={q['limit_down']}")


ALL_DEMOS = {
    "kline": demo_kline,
    "realtime": demo_realtime,
    "tencent": demo_tencent_quote,
    "finance": demo_finance,
    "quick": demo_quick_view,
}


def main():
    parser = argparse.ArgumentParser(description="A股稳定行情数据API演示")
    parser.add_argument("--kline", action="store_true", help="只看K线")
    parser.add_argument("--realtime", "--quote", dest="realtime", action="store_true", help="只看实时盘口")
    parser.add_argument("--tencent", "--tx", dest="tencent", action="store_true", help="只看腾讯估值")
    parser.add_argument("--finance", "--fin", dest="finance", action="store_true", help="只看财务快照")
    parser.add_argument("--quick", "-q", dest="quick", action="store_true", help="只看综合行情")
    parser.add_argument("--all", "-a", action="store_true", help="跑全部(默认)")
    args = parser.parse_args()

    any_selected = any([args.kline, args.realtime, args.tencent, args.finance, args.quick])
    run_all = not any_selected or args.all

    if run_all:
        print(">>> A股稳定行情数据 API 演示 (全部)\n")
        for name in ["kline", "realtime", "tencent", "finance", "quick"]:
            try:
                ALL_DEMOS[name]()
            except Exception as e:
                print(f"\n  [!] {name} 执行失败: {e}")
    else:
        if args.kline:
            demo_kline()
        if args.realtime:
            demo_realtime()
        if args.tencent:
            demo_tencent_quote()
        if args.finance:
            demo_finance()
        if args.quick:
            demo_quick_view()


if __name__ == "__main__":
    main()
