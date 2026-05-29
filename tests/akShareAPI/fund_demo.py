"""
基金信息获取示例（019018 易方达信息产业混合C）

用法: python tests/akShareAPI/fund_demo.py [基金代码]
"""

import json
import sys
import urllib.request

import akshare as ak


def basic_info(symbol):
    """基金基本信息：名称、规模、经理、投资策略等"""
    df = ak.fund_individual_basic_info_xq(symbol=symbol)
    print(f"\n{'='*60}")
    print(f"  {symbol} 基本信息")
    print(f"{'='*60}")
    for _, row in df.iterrows():
        print(f"  {row['item']}：{row['value']}")


def nav_trend(symbol):
    """单位净值走势"""
    df = ak.fund_open_fund_info_em(symbol=symbol, indicator="单位净值走势")
    print(f"\n--- 单位净值走势（最近10条）---")
    print(df.tail(10))


def cum_return(symbol):
    """累计收益率走势"""
    df = ak.fund_open_fund_info_em(symbol=symbol, indicator="累计收益率走势")
    print(f"\n--- 累计收益率（最近5条）---")
    print(df.tail(5))


def peer_rank(symbol):
    """同类排名走势"""
    df = ak.fund_open_fund_info_em(symbol=symbol, indicator="同类排名走势")
    print(f"\n--- 同类排名（最近5条）---")
    print(df.tail(5))


def peer_top_near_three_month(symbol, top_n=10):
    """近三月同类排名TOP — 直连天天基金排行榜(免费/无鉴权)"""
    # 1. 获取基金类型代码
    info_df = ak.fund_individual_basic_info_xq(symbol=symbol)
    info = {row["item"]: row["value"] for _, row in info_df.iterrows()}
    fund_name = info.get("基金全称", symbol)
    fund_type = info.get("基金类型", "")

    # 基金类型 → 天天基金 type code
    type_map = {
        "股票型": "gp", "混合型": "hh", "债券型": "zq",
        "指数型": "zs", "QDII": "qdii", "货币型": "hb",
    }
    ft_code = type_map.get(fund_type, "hh")

    # 2. 拉排行榜
    url = (
        f"https://fund.eastmoney.com/data/rankhandler.aspx"
        f"?op=ph&dt=kf&ft={ft_code}"
        f"&sc=3nf&st=desc&pi=1&pn={top_n}"
    )
    req = urllib.request.Request(url)
    req.add_header("User-Agent", "Mozilla/5.0")
    req.add_header("Referer", "https://fund.eastmoney.com/")
    resp = urllib.request.urlopen(req, timeout=10)
    text = resp.read().decode("utf-8")
    # 返回格式: var rankData = {ErrCode:0, datas:[...], ...}
    # ErrCode:-999 = 无访问权限(缺少Referer)
    if "[" not in text and "]" not in text:
        print(f"  API返回异常: {text[:200]}")
        return
    json_str = text[text.index("[") : text.rindex("]") + 1]
    datas = json.loads(json_str)

    print(f"\n{'=' * 60}")
    print(f"  {fund_name} ({symbol}) — {fund_type} 近三月排名 TOP{top_n}")
    print(f"{'=' * 60}")
    print(f"  {'排名':<4} {'代码':<8} {'基金名称':<30} {'近三月':>8}")
    print(f"  {'-' * 50}")
    for i, item in enumerate(datas[:top_n], 1):
        fields = item.split(",")
        code = fields[0]
        name = fields[1]
        ret_3m = fields[9]  # 近三月收益率(索引9)
        print(f"  {i:<4} {code:<8} {name:<30} {ret_3m:>8}%")


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "019018"
    basic_info(symbol)
    nav_trend(symbol)
    cum_return(symbol)
    peer_rank(symbol)
    peer_top_near_three_month(symbol)


if __name__ == "__main__":
    main()
