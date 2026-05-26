"""
A股日线行情获取示例

用法: python tests/akShareAPI/stock_demo.py
"""

import akshare as ak


def main():
    # adjust: qfq=前复权, hfq=后复权, ""=不复权
    # period: daily / weekly / monthly
    df = ak.stock_zh_a_hist(
        symbol="000001",          # 平安银行
        period="daily",
        start_date="20200101",
        end_date="20241231",
        adjust="qfq",
    )
    print(f"平安银行(000001)日线 形状: {df.shape}")
    print(df.head())


if __name__ == "__main__":
    main()
