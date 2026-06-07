"""
手动触发盘中净值估算。

用法:
    python scripts/run_nav_estimation.py           # 估算 + 终端输出
    python scripts/run_nav_estimation.py --json    # 估算 + JSON 输出
    python scripts/run_nav_estimation.py --csv     # 估算 + 保存 CSV
"""

import argparse
import csv
import json
import sys
from datetime import date as _date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.fund_collector.storage import FundStorage
from src.strategy.nav_estimator import NavEstimator
from src.utils.logger import get_logger

log = get_logger(__name__)

SUGGESTION_LABELS = {
    "CLEAR": "清仓",
    "REDUCE": "减仓",
    "BUY": "加仓",
    "HOLD": "持有观望",
}


def main():
    parser = argparse.ArgumentParser(description="盘中基金净值估算")
    parser.add_argument("--json", action="store_true", help="JSON 格式输出")
    parser.add_argument("--csv", action="store_true", help="保存结果到 CSV 文件")
    args = parser.parse_args()

    config_path = str(ROOT / "config" / "nav_estimation.yaml")
    storage = FundStorage()
    storage.init_schema()

    estimator = NavEstimator(storage, config_path=config_path)

    conn = storage.connect()
    try:
        results = estimator.estimate_all(conn)
        conn.commit()
    except Exception:
        log.exception("估算失败")
        conn.rollback()
        raise
    finally:
        storage.return_conn(conn)

    if not results:
        print("无持仓数据或无重仓股数据，无法估算。")
        return

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    else:
        _print_table(results)

    if args.csv:
        _save_csv(results)


def _print_table(results: list[dict]) -> None:
    """终端表格输出。"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print()
    print("=" * 90)
    print(f"  盘中基金净值估算 — {now_str}")
    print("=" * 90)
    print(f"  {'代码':<8} {'基金名称':<28} {'估算净值':>8} {'成本':>10} {'市值':>10} {'累计盈亏%':>9} {'当日%':>7} {'建议':<8}")
    print("-" * 90)

    for r in results:
        suggestion = SUGGESTION_LABELS.get(r.get("suggestion", ""), r.get("suggestion", ""))
        fund_code = r.get("fund_code", "")
        fund_name = r.get("fund_name", fund_code)
        current_nav = r.get("current_nav")
        nav_str = f"{current_nav:.4f}" if current_nav else "N/A"
        cost = r.get("cost", 0)
        market_value = r.get("market_value", 0)
        total_pnl_pct = r.get("total_pnl_pct", 0) or 0
        daily_pnl_pct = r.get("daily_pnl_pct", 0) or 0

        print(
            f"  {fund_code:<8} "
            f"{fund_name[:28]:<28} "
            f"{nav_str:>8} "
            f"{cost:>10.2f} "
            f"{market_value:>10.2f} "
            f"{total_pnl_pct:>+8.2f}% "
            f"{daily_pnl_pct:>+6.2f}% "
            f"{suggestion:<8}"
        )

    print("-" * 90)
    total_cost = sum(r.get("cost", 0) or 0 for r in results)
    total_mv = sum(r.get("market_value", 0) or 0 for r in results)
    total_pnl = sum(r.get("total_pnl", 0) or 0 for r in results)
    daily = sum(r.get("daily_pnl", 0) or 0 for r in results)
    print(f"  总成本: {total_cost:,.2f}    总市值: {total_mv:,.2f}   当日盈亏: {daily:+,.2f}   累计盈亏: {total_pnl:+,.2f}")
    print("=" * 90)
    print()


def _save_csv(results: list[dict]) -> None:
    """保存结果到 CSV 文件。"""
    output_dir = ROOT / "output" / "nav_estimation"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = output_dir / f"nav_estimation_{_date.today().isoformat()}.csv"

    fieldnames = [
        "fund_code", "fund_name", "buy_net_value", "current_nav",
        "shares", "cost", "market_value", "total_pnl", "total_pnl_pct",
        "daily_pnl", "daily_pnl_pct", "suggestion",
    ]
    with open(filename, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(results)

    log.info("估算结果已保存到 %s", filename)


if __name__ == "__main__":
    main()
