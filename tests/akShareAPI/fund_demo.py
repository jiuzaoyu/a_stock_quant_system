"""
基金信息获取示例（019018 易方达信息产业混合C）

用法: python tests/akShareAPI/fund_demo.py [基金代码]
"""

import sys
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


def main():
    symbol = sys.argv[1] if len(sys.argv) > 1 else "019018"
    basic_info(symbol)
    nav_trend(symbol)
    cum_return(symbol)
    peer_rank(symbol)


if __name__ == "__main__":
    main()
