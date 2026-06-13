"""
统一 Worker 启动入口 — Redis Streams 消费者。

用法:
    python scripts/run_workers.py                      # 启动所有 worker
    python scripts/run_workers.py --worker fund        # 只启动 fund worker
    python scripts/run_workers.py --worker screener    # 只启动 screener worker
"""

import argparse
import sys
from multiprocessing import Process
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
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
    )


def run_fund_worker():
    from src.workers.fund_worker import create_fund_worker
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "fund_worker.log")
    log = get_logger("fund_worker")

    redis_client = _create_redis_client()
    worker = create_fund_worker(redis_client)
    log.info("Fund worker starting")
    worker.start()


def run_nav_estimation_worker():
    from src.workers.nav_estimation_worker import create_nav_estimation_worker
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "nav_estimation_worker.log")
    log = get_logger("nav_estimation_worker")

    config_path = str(ROOT / "config" / "nav_estimation.yaml")
    redis_client = _create_redis_client()
    worker = create_nav_estimation_worker(redis_client, config_path=config_path)
    log.info("Nav estimation worker starting")
    worker.start()


def run_screener_worker():
    from src.workers.screener_worker import create_screener_worker
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "screener_worker.log")
    log = get_logger("screener_worker")

    redis_client = _create_redis_client()
    worker = create_screener_worker(redis_client)
    log.info("Screener worker starting")
    worker.start()


WORKERS = {
    "fund": run_fund_worker,
    "screener": run_screener_worker,
    "nav": run_nav_estimation_worker,
}


def main():
    parser = argparse.ArgumentParser(description="统一 Worker 启动器")
    parser.add_argument("--worker", "-w", choices=list(WORKERS.keys()),
                        help="只启动指定 worker，默认启动全部")
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
