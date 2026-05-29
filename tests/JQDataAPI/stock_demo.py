"""
JQData 股票行情 API 示例

用法: python tests/JQDataAPI/stock_demo.py
依赖: pip install jqdatasdk
凭据: 在 config/.env 中设置 JQDATA_USER / JQDATA_PASSWORD
"""

import os
import sys
from pathlib import Path

# 确保项目根目录在 sys.path，以便加载 .env
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / "config" / ".env")


def main():
    from jqdatasdk import auth, get_all_securities, get_price

    # 1. 认证
    user = os.getenv("JQDATA_USER")
    pwd = os.getenv("JQDATA_PASSWORD")
    if not user or not pwd:
        print("缺少 JQDATA_USER / JQDATA_PASSWORD，请在 config/.env 中配置")
        return
    auth(user, pwd)
    print("JQData 认证成功\n")

    today = "2026-02-20"  # JQData 数据权限范围内

    # 2. 获取全量股票列表
    sec = get_all_securities(types=["stock"], date=today)
    print(f"=== 全量股票: {len(sec)} 只 ===")
    print(sec.head(10))
    print()

    # 3. 单只股票日线 (get_price 返回 Panel)
    jq_code = "000001.XSHE"
    panel = get_price(
        jq_code,
        count=5,
        end_date=today,
        frequency="daily",
        fields=["open", "close", "high", "low", "volume", "money"],
        fq="pre",
    )
    print(f"=== {jq_code} 日线 (get_price 返回类型: {type(panel).__name__}) ===")
    # panel 是 dict-like，键为 field 名，值为 DataFrame (index=date, columns=[security])
    for field in ["close", "volume"]:
        print(f"--- {field} ---")
        print(panel[field])
    print()

    # 4. 单只股票分钟线
    panel = get_price(
        jq_code,
        count=5,
        end_date=today,
        frequency="minute",
        fields=["open", "close", "high", "low", "volume", "money"],
        fq="pre",
    )
    print(f"=== {jq_code} 分钟线 (最近5根) ===")
    print(panel["close"])
    print()

    # 5. 批量拉取多只股票 (返回 Panel, columns 为股票代码)
    codes = ["000001.XSHE", "000002.XSHE", "600519.XSHG"]
    panel = get_price(
        codes,
        count=3,
        end_date=today,
        frequency="daily",
        fields=["close", "volume"],
        fq="pre",
    )
    print(f"=== 批量日线: {len(codes)} 只 ===")
    print(panel["close"])


if __name__ == "__main__":
    main()
