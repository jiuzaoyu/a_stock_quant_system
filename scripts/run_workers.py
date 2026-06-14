"""
统一 Worker 启动入口 — Redis Streams 消费者。

用法:
    python scripts/run_workers.py                    # 启动所有 worker
    python scripts/run_workers.py --worker fund      # 只启动基金相关 worker
    python scripts/run_workers.py --worker stock     # 只启动股票相关 worker
"""

import argparse
import sys
from multiprocessing import Process
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

load_dotenv(ROOT / "config" / ".env")


def _create_redis_client():
    from redis import Redis
    from src.utils.secrets import get_env

    return Redis(
        host=get_env("REDIS_HOST", "127.0.0.1"),
        port=int(get_env("REDIS_PORT", "6379")),
        db=int(get_env("REDIS_DB", "0")),
        password=get_env("REDIS_PASSWORD"),
        decode_responses=True,
        socket_timeout=15,  # 必须大于 XREADGROUP 的 block_ms（5s），否则阻塞等待时 socket 会先超时
    )


def run_fund_worker():
    from src.workers.fund_worker import create_fund_workers
    from src.workers.base_worker import start_workers
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "fund_worker.log")
    log = get_logger("fund_worker")

    redis_client = _create_redis_client()
    config_path = str(ROOT / "config" / "nav_estimation.yaml")
    workers = create_fund_workers(redis_client, config_path=config_path)
    log.info("Fund workers starting (%d threads)", len(workers))
    start_workers(workers)


def run_stock_worker():
    from src.workers.stock_worker import create_stock_workers
    from src.workers.base_worker import start_workers
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "stock_worker.log")
    log = get_logger("stock_worker")

    redis_client = _create_redis_client()
    workers = create_stock_workers(redis_client)
    log.info("Stock workers starting (%d threads)", len(workers))
    start_workers(workers)


WORKERS = {
    "fund": run_fund_worker,
    "stock": run_stock_worker,
}


def main():
    parser = argparse.ArgumentParser(description="统一 Worker 启动器")
    parser.add_argument(
        "--worker", "-w", choices=list(WORKERS.keys()),
        help="只启动指定 worker，默认启动全部",
    )
    args = parser.parse_args()

    if args.worker:
        WORKERS[args.worker]()
    else:
        processes = []
        for name, target in WORKERS.items():
            p = Process(target=target, name=name)
            p.start()
            processes.append(p)
            print(f"Started {name} worker (pid={p.pid})")

        for p in processes:
            p.join()


if __name__ == "__main__":
    main()
