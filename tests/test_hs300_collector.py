from pathlib import Path

import akshare as ak
import pandas as pd
import pytest
import sqlite3
import time

from src.data.hs300_collector import HS300DailyCollector

# 项目根目录 a_stock_quant_system（tests 的上一级）
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "database" / "hs300_daily.db"


def test_constituent_code_extraction_from_wrong_first_column():
    """第一列是日期时，应能从「品种代码」列提取 6 位代码。"""
    df = pd.DataFrame(
        {
            "日期": ["2026-05-19"] * 3,
            "品种代码": ["000001", "600000", "300750"],
        }
    )
    col = "品种代码"
    codes = (
        df[col]
        .astype(str)
        .str.strip()
        .str.extract(r"(\d{6})", expand=False)
        .dropna()
        .unique()
        .tolist()
    )
    assert codes == ["000001", "600000", "300750"]


def test_fetch_one_rejects_date_like_code():
    c = HS300DailyCollector(db_path=DB_PATH)
    with pytest.raises(ValueError, match="非法股票代码"):
        c.fetch_one("2026-05-19")


def test_batch_collect_and_insert():
    # Step 1: 获取沪深300成分股列表
    hs300 = ak.index_stock_cons_csindex(symbol="000300")
    print(hs300.head().to_string())
    print(hs300.columns.tolist())
    stock_list = hs300['成分券代码'].tolist()
    print(f"共{len(stock_list)}只成分股")

    # Step 2: 创建 SQLite 数据库（与 scripts/collect_hs300_daily.py 相同位置）
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily (
        ts_code TEXT, trade_date TEXT, open REAL, high REAL,
        low REAL, close REAL, volume REAL, amount REAL,
        pct_change REAL, turnover REAL,
        PRIMARY KEY (ts_code, trade_date)
    )
    """)
    conn.commit()

    # Step 3: 逐只采集并入库
    success_count = 0
    fail_list = []

    for i, code in enumerate(stock_list):
        try:
            df = ak.stock_zh_a_hist(
                symbol=code, period="daily",
                start_date="20190101", end_date="20241231",
                adjust="qfq"
            )
            print(2222222222222)
            # 列名标准化
            df.columns = ['date','open','close','high','low',
                        'volume','amount','amplitude','pct_change',
                        'change','turnover']
            df.insert(0, 'code', code)

            # 写入数据库
            df.to_sql("daily", conn,
                    if_exists="append", index=False)
            success_count += 1

            if (i + 1) % 50 == 0:
                print(f"进度: {i+1}/{len(stock_list)}")
            time.sleep(0.5)  # 控制请求频率

        except Exception as e:
            fail_list.append((code, str(e)))
            print(f"失败: {code}, 原因: {e}")

    print(f"完成! 成功{success_count}, 失败{len(fail_list)}")
    print(f"数据库: {DB_PATH}")
    print(1/0)
