"""
将用户初始持仓数据写入 fund_user_holding 表。

用法:
    python scripts/import_user_holdings.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fund_collector.storage import FundStorage
from src.utils.logger import get_logger

log = get_logger(__name__)

INITIAL_HOLDINGS = [
    {
        "fund_code": "008327",
        "fund_name": "东财通信C",
        "buy_net_value": 4.7146,
        "shares": 12726.42,
        "buy_date": "2026-05-29",
        "holding_days": 9,
        "industry_sector": "指数",
        "source": "天天基金",
        "is_qdii": False,
    },
    {
        "fund_code": "024239",
        "fund_name": "华夏全球科技先锋混合(QDII)C",
        "buy_net_value": 2.142285,
        "shares": 44974.01,
        "buy_date": "2026-03-26",
        "holding_days": 0,
        "industry_sector": "科技",
        "source": "ali",
        "is_qdii": True,
    },
]


def main():
    storage = FundStorage()
    storage.init_schema()
    conn = storage.connect()
    try:
        count = storage.upsert_user_holding(conn, INITIAL_HOLDINGS)
        conn.commit()
        log.info("已写入 %d 条持仓记录", count)

        holdings = storage.get_user_holdings(conn)
        for h in holdings:
            log.info(
                "  %s %s 买入净值=%.4f 份额=%.2f QDII=%s",
                h["fund_code"], h["fund_name"],
                h["buy_net_value"], h["shares"], h["is_qdii"],
            )
    finally:
        storage.return_conn(conn)


if __name__ == "__main__":
    main()
