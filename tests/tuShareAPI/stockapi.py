"""
TuShare A股数据获取示例

用法: python tests/tuShareAPI/stockapi.py

注意: tushare pro 接口需要积分权限（https://tushare.pro 注册获取Token后
      需在"个人主页-接口权限"中查看各接口所需积分）。
      stock_basic/daily/income 等接口需要相应积分才能调用。
"""

import os
import sys
import tushare as ts
from dotenv import load_dotenv

# 加载 config/.env 中的 TUSHARE_TOKEN
env_path = os.path.join(os.path.dirname(__file__), "..", "..", "config", ".env")
load_dotenv(env_path)

token = os.getenv("TUSHARE_TOKEN")
if not token:
    print("错误: 未找到 TUSHARE_TOKEN，请检查 config/.env")
    sys.exit(1)

ts.set_token(token)
pro = ts.pro_api()


def try_fetch(label, fn, *args, **kwargs):
    """封装 try/except，统一输出成功或失败信息"""
    try:
        result = fn(*args, **kwargs)
        print(f"=== {label} ===")
        print(result, "\n")
        return result
    except Exception as e:
        print(f"[无权限] {label}: {e}\n")
        return None


def main():
    # 1. 股票基本信息
    try_fetch(
        "平安银行(000001.SZ) 基本信息",
        pro.stock_basic,
        ts_code="000001.SZ",
        fields="ts_code,name,industry,list_date",
    )

    # 2. 日线行情
    try_fetch(
        "平安银行(000001.SZ) 日线行情",
        pro.daily,
        ts_code="000001.SZ",
        start_date="20200101",
        end_date="20241231",
    )

    # 3. 利润表
    income = try_fetch(
        "平安银行(000001.SZ) 利润表",
        pro.income,
        ts_code="000001.SZ",
        start_date="20230101",
        end_date="20241231",
    )
    if income is not None:
        print(income[["ts_code", "ann_date", "total_revenue", "n_income"]].head())


if __name__ == "__main__":
    main()
