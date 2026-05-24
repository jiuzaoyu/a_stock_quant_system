"""生产入口：配置 → 数据服务 → 策略信号 → 回测引擎（各层解耦）。"""

from pathlib import Path

from src.backtest import BacktestEngine
from src.data import DataService
from src.strategy import CTA
from src.utils.config import load_config
from src.utils.logger import get_logger, setup_logging

ROOT = Path(__file__).resolve().parent


def main() -> None:
    cfg = load_config()
    setup_logging(
        level=cfg["base"]["logging"]["level"],
        log_file=ROOT / cfg["base"]["logging"]["file"],
    )
    log = get_logger(__name__)

    paths = cfg["base"]["paths"]
    strat_cfg = cfg["strategy"]["cta"]
    bt_cfg = cfg["strategy"]["backtest"]

    # 1. 数据服务层（策略不直接接触 AkShare 等接口）
    data_service = DataService(cache_dir=ROOT / paths["data_cache"])
    log.info("拉取行情数据…")
    ohlcv = data_service.get_daily_ohlcv(
        symbol="000001",
        start="2023-01-01",
        end="2024-12-31",
        save_processed=True,
        processed_dir=ROOT / paths["data_processed"],
    )

    # 2. 策略层：只生成信号
    strategy = CTA(
        fast_period=strat_cfg["fast_period"],
        slow_period=strat_cfg["slow_period"],
    )
    signals = strategy.generate_signals(ohlcv)
    log.info("信号已生成，最后一日 signal=%s", signals["signal"].iloc[-1])

    # 3. 回测层：只负责模拟执行与绩效
    engine = BacktestEngine(
        initial_cash=bt_cfg["initial_cash"],
        commission=bt_cfg["commission"],
    )
    result = engine.run(ohlcv, signals)
    log.info("回测结果: %s", result)


if __name__ == "__main__":
    main()
