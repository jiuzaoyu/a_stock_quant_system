"""
JQData 扩展数据 API 示例 (市值、流通股本等)

用法: python tests/JQDataAPI/extras_demo.py
依赖: pip install jqdatasdk
凭据: 在 config/.env 中设置 JQDATA_USER / JQDATA_PASSWORD
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")


def main():
    from jqdatasdk import auth, get_extras, get_price

    user = os.getenv("JQDATA_USER")
    pwd = os.getenv("JQDATA_PASSWORD")
    if not user or not pwd:
        print("缺少 JQDATA_USER / JQDATA_PASSWORD，请在 config/.env 中配置")
        return
    auth(user, pwd)
    print("JQData 认证成功\n")

    today = "2026-02-20"  # JQData 数据权限范围内
    codes = ["000001.XSHE", "000002.XSHE", "600519.XSHG", "300750.XSHE"]

    # 1. 总市值
    print("=== 总市值 (market_cap) ===")
    cap = get_extras("market_cap", codes, end_date=today)
    print(cap)
    print()

    # 2. 流通股本
    print("=== 流通股本 (float_share) ===")
    fs = get_extras("float_share", codes, end_date=today)
    print(fs)
    print()

    # 3. 换手率计算示例：成交量(手)*100 / 流通股本(股) * 100%
    print("=== 换手率计算示例 ===")
    panel = get_price(
        codes,
        count=1,
        end_date=today,
        frequency="daily",
        fields=["volume"],
        fq="pre",
    )
    latest_vol = panel["volume"].iloc[-1]
    float_share = fs.iloc[-1]

    for c in codes:
        vol = latest_vol.get(c, 0)
        fs_val = float_share.get(c, 1)
        turnover = vol * 100 / fs_val * 100
        print(f"  {c}: 成交量={vol:.0f}手, 流通股本={fs_val:.0f}股, 换手率={turnover:.2f}%")


if __name__ == "__main__":
    main()
