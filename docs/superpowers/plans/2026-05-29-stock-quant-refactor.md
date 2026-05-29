# Stock Quant System — 调度解耦改造 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace embedded nb_cron + APScheduler with Redis Streams consumers, consuming messages published by the standalone `nb-cron-scheduler` service.

**Architecture:** A generic `BaseWorker` class encapsulates Redis Streams Consumer Group lifecycle (XGROUP CREATE, XREADGROUP, XACK). Business-specific workers (`fund_worker.py`, `screener_worker.py`) register handlers for each job type. A unified `run_workers.py` script starts all workers in separate processes.

**Tech Stack:** Python 3.11, redis-py, multiprocessing, existing fund_collector / screener modules

---

## File Structure

```
Modified:
  config/fund_collector.yaml       ← remove scheduler + server sections
  config/screener.yaml             ← remove scheduler section
  requirements.txt                 ← remove nb-cron-nb, apscheduler; add redis
  src/screener/__init__.py         ← remove scheduler exports

Deleted:
  scripts/run_fund_scheduler.py
  scripts/run_screener.py
  src/screener/scheduler.py

Created:
  src/workers/__init__.py
  src/workers/base_worker.py       ← Redis Streams Consumer Group base class
  src/workers/fund_worker.py       ← fund job consumer
  src/workers/screener_worker.py   ← screener job consumer + is_trading_day
  scripts/run_workers.py           ← unified worker entry point
  tests/test_base_worker.py
  tests/test_screener_worker.py
```

---

### Task 1: BaseWorker — Redis Streams Consumer Group

**Files:**
- Create: `e:\workspaces\a_stock_quant_system\src\workers\__init__.py`
- Create: `e:\workspaces\a_stock_quant_system\src\workers\base_worker.py`
- Create: `e:\workspaces\a_stock_quant_system\tests\test_base_worker.py`

- [ ] **Step 1: Write the failing test**

```python
import json
import time
from threading import Thread

import fakeredis
import pytest

from src.workers.base_worker import BaseWorker


class TestBaseWorker:
    @pytest.fixture
    def redis_client(self):
        return fakeredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def worker(self, redis_client):
        return BaseWorker(
            redis_client,
            stream="cron:jobs:test_job",
            group="test_group",
            consumer="test_consumer_1",
        )

    def test_register_and_handle_message(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("test_job", handler)

        # Simulate a message arriving in the stream
        msg_data = {
            "job_id": "test_job:2026-01-01T00:00:00+00:00",
            "job_type": "test_job",
            "triggered_at": "2026-01-01T00:00:00+00:00",
            "timeout": "300",
            "max_retries": "2",
            "payload": json.dumps({"key": "value"}),
        }
        redis_client.xadd("cron:jobs:test_job", msg_data)

        # Process one message manually (not using the blocking loop)
        worker._process_one()

        assert len(handler_called) == 1
        received = handler_called[0]
        assert received["job_type"] == "test_job"
        assert received["timeout"] == "300"
        assert json.loads(received["payload"]) == {"key": "value"}

    def test_process_one_acks_message(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("test_job", handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        # Verify message was ACKed — PEL should be empty
        pending = redis_client.xpending("cron:jobs:test_job", "test_group")
        assert pending["pending"] == 0

    def test_unregistered_job_type_is_skipped(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("other_job", handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        assert len(handler_called) == 0

    def test_handler_exception_leaves_message_in_pending(self, worker, redis_client):
        def failing_handler(message):
            raise RuntimeError("handler error")

        worker.register("test_job", failing_handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        # Message NOT ACKed — stays in PEL
        pending = redis_client.xpending("cron:jobs:test_job", "test_group")
        assert pending["pending"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/test_base_worker.py -v
```
Expected: FAIL (ModuleNotFoundError)

- [ ] **Step 3: Write `src/workers/__init__.py`**

```python
```

- [ ] **Step 4: Write `src/workers/base_worker.py`**

```python
import json
import logging
from typing import Any, Callable

from redis import Redis

log = logging.getLogger(__name__)


class BaseWorker:
    def __init__(self, redis_client: Redis, stream: str, group: str, consumer: str):
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._handlers: dict[str, Callable] = {}
        self._init_group()

    def _init_group(self) -> None:
        try:
            self._redis.xgroup_create(self._stream, self._group, mkstream=True)
        except Exception:
            pass

    def register(self, job_type: str, handler: Callable[[dict[str, str]], None]) -> None:
        self._handlers[job_type] = handler

    def start(self, block_ms: int = 5000) -> None:
        log.info("Worker %s listening on stream %s (group=%s)", self._consumer, self._stream, self._group)
        while True:
            try:
                self._process_one(block_ms)
            except Exception:
                log.exception("Worker loop error, continuing")

    def _process_one(self, block_ms: int | None = None) -> None:
        timeout = block_ms if block_ms is not None else 1000
        messages = self._redis.xreadgroup(
            self._group, self._consumer,
            {self._stream: ">"}, block=timeout, count=1,
        )
        if not messages:
            return

        for stream_name, msgs in messages:
            for msg_id, data in msgs:
                job_type = data.get("job_type", "")
                handler = self._handlers.get(job_type)
                if handler is None:
                    log.warning("No handler for job_type=%s on stream %s, acking anyway", job_type, self._stream)
                    self._redis.xack(self._stream, self._group, msg_id)
                    continue

                try:
                    handler(data)
                except Exception:
                    log.exception("Handler failed for job_type=%s msg=%s, message left in PEL", job_type, msg_id)
                    continue

                self._redis.xack(self._stream, self._group, msg_id)
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/test_base_worker.py -v
```
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add src/workers/__init__.py src/workers/base_worker.py tests/test_base_worker.py && git commit -m "feat: add BaseWorker — Redis Streams Consumer Group wrapper"
```

---

### Task 2: FundWorker

**Files:**
- Create: `e:\workspaces\a_stock_quant_system\src\workers\fund_worker.py`

- [ ] **Step 1: Write `src/workers/fund_worker.py`**

```python
import logging
from pathlib import Path

from redis import Redis

from src.fund_collector import FundStorage, collect_today_nav, refresh_fund_list
from src.utils.config import load_yaml
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def create_fund_worker(redis_client: Redis, db_path: str | None = None) -> BaseWorker:
    if db_path is None:
        cfg = load_yaml(ROOT / "config" / "fund_collector.yaml")
        db_path = str(ROOT / cfg["fund_collector"]["database"])

    storage = FundStorage(Path(db_path))
    storage.init_schema()

    worker = BaseWorker(
        redis_client,
        stream="cron:jobs:fund_incremental",
        group="fund_group",
        consumer="fund_consumer_1",
    )
    worker.register("fund_incremental", _make_handler(collect_today_nav, storage, "fund_incremental"))
    worker.register("fund_list_refresh", _make_handler(refresh_fund_list, storage, "fund_list_refresh"))

    return worker


def _make_handler(func, storage, job_name: str):
    def handler(data: dict[str, str]) -> None:
        log.info("=== %s 开始 ===", job_name)
        try:
            result = func(storage)
            log.info("%s 完成: %s", job_name, result)
        except Exception:
            log.exception("%s 失败", job_name)
            raise
    return handler
```

- [ ] **Step 2: Verify import works**

```bash
cd e:/workspaces/a_stock_quant_system && python -c "from src.workers.fund_worker import create_fund_worker; print('Import OK')"
```
Expected: `Import OK`

- [ ] **Step 3: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add src/workers/fund_worker.py && git commit -m "feat: add FundWorker — fund job consumer via Redis Streams"
```

---

### Task 3: ScreenerWorker

**Files:**
- Create: `e:\workspaces\a_stock_quant_system\src\workers\screener_worker.py`
- Create: `e:\workspaces\a_stock_quant_system\tests\test_screener_worker.py`

- [ ] **Step 1: Write `src/workers/screener_worker.py`**

```python
import logging
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import akshare as ak
import pandas as pd
from redis import Redis

from src.screener.engine import ScreenerEngine
from src.utils.config import load_yaml
from src.utils.logger import get_logger
from src.workers.base_worker import BaseWorker

log = get_logger(__name__)

ROOT = Path(__file__).resolve().parents[2]


def is_trading_day(check_date: Optional[date] = None) -> bool:
    if check_date is None:
        check_date = date.today()

    try:
        trade_df = ak.tool_trade_date_hist_sina()
        trade_dates = set(
            trade_df["trade_date"].dt.date
            if hasattr(trade_df["trade_date"], "dt")
            else pd.to_datetime(trade_df["trade_date"]).dt.date
        )
        return check_date in trade_dates
    except Exception:
        log.warning("交易日历获取失败，假定为交易日")
        return True


def create_screener_worker(redis_client: Redis) -> BaseWorker:
    cfg = load_yaml(ROOT / "config" / "screener.yaml")
    screener_cfg = cfg["screener"]

    engine = ScreenerEngine(screener_cfg, project_root=ROOT)

    worker = BaseWorker(
        redis_client,
        stream="cron:jobs:screener_intraday",
        group="screener_group",
        consumer="screener_consumer_1",
    )
    worker.register("screener_intraday", _make_handler(engine))

    return worker


def _make_handler(engine: ScreenerEngine):
    def handler(data: dict[str, str]) -> None:
        if not is_trading_day():
            log.info("今日非交易日，跳过筛选")
            return

        log.info("=== 盘中选股筛选开始 ===")
        start = datetime.now()
        try:
            engine.run()
        except Exception:
            log.exception("筛选过程异常")
            raise
        elapsed = (datetime.now() - start).total_seconds()
        log.info("=== 筛选结束，耗时 %.1f 秒 ===", elapsed)
    return handler
```

- [ ] **Step 2: Write `tests/test_screener_worker.py`** — test is_trading_day only (engine tested separately)

```python
from datetime import date
from unittest.mock import patch

import pandas as pd
import pytest

from src.workers.screener_worker import is_trading_day


class TestIsTradingDay:
    def test_returns_true_when_date_in_calendar(self):
        mock_df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-29", "2026-05-28"])})
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", return_value=mock_df):
            assert is_trading_day(date(2026, 5, 29)) is True

    def test_returns_false_when_date_not_in_calendar(self):
        mock_df = pd.DataFrame({"trade_date": pd.to_datetime(["2026-05-29", "2026-05-28"])})
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", return_value=mock_df):
            assert is_trading_day(date(2026, 5, 30)) is False

    def test_returns_true_on_api_failure(self):
        with patch("src.workers.screener_worker.ak.tool_trade_date_hist_sina", side_effect=Exception("API down")):
            assert is_trading_day(date(2026, 5, 29)) is True
```

- [ ] **Step 3: Run tests**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/test_base_worker.py tests/test_screener_worker.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 4: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add src/workers/screener_worker.py tests/test_screener_worker.py && git commit -m "feat: add ScreenerWorker — screener job consumer + is_trading_day"
```

---

### Task 4: Unified Worker Entry Point

**Files:**
- Create: `e:\workspaces\a_stock_quant_system\scripts\run_workers.py`

- [ ] **Step 1: Write `scripts/run_workers.py`**

```python
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


def run_fund_worker():
    from redis import Redis
    from src.workers.fund_worker import create_fund_worker
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "fund_worker.log")
    log = get_logger("fund_worker")

    redis_client = Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
    worker = create_fund_worker(redis_client)
    log.info("Fund worker starting")
    worker.start()


def run_screener_worker():
    from redis import Redis
    from src.workers.screener_worker import create_screener_worker
    from src.utils.logger import get_logger, setup_logging

    setup_logging(level="INFO", log_file=ROOT / "logs" / "screener_worker.log")
    log = get_logger("screener_worker")

    redis_client = Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)
    worker = create_screener_worker(redis_client)
    log.info("Screener worker starting")
    worker.start()


WORKERS = {
    "fund": run_fund_worker,
    "screener": run_screener_worker,
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
```

- [ ] **Step 2: Verify import works**

```bash
cd e:/workspaces/a_stock_quant_system && python -c "from scripts.run_workers import main; print('Import OK')" 2>&1 || python -c "import importlib; importlib.import_module('run_workers'); print('Import OK')" 2>&1
```

- [ ] **Step 3: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add scripts/run_workers.py && git commit -m "feat: add unified worker entry point with multiprocessing"
```

---

### Task 5: Cleanup — Remove Old Scheduler Code

**Files:**
- Delete: `scripts/run_fund_scheduler.py`
- Delete: `scripts/run_screener.py`
- Delete: `src/screener/scheduler.py`
- Modify: `src/screener/__init__.py` — remove scheduler exports
- Modify: `config/fund_collector.yaml` — remove scheduler + server sections
- Modify: `config/screener.yaml` — remove scheduler section

- [ ] **Step 1: Remove old scripts and scheduler module**

```bash
cd e:/workspaces/a_stock_quant_system && rm scripts/run_fund_scheduler.py scripts/run_screener.py src/screener/scheduler.py
```

- [ ] **Step 2: Update `src/screener/__init__.py`**

```python
"""盘中选股筛选模块"""
from .engine import ScreenerEngine

__all__ = [
    "ScreenerEngine",
]
```

- [ ] **Step 3: Update `config/fund_collector.yaml`** — remove scheduler and server sections

Write the file:

```yaml
# 基金数据采集器配置
fund_collector:
  database: "data/database/quant.db"

  target_fund_types:
    - "股票型"
    - "混合型"
    - "指数型"

  lookback_years: 2
  request_delay_seconds: 0.5
  progress_every: 20
  max_retries: 3
```

- [ ] **Step 4: Update `config/screener.yaml`** — remove scheduler section

Write the file:

```yaml
# 盘中选股筛选器配置
screener:
  filters:
    market_cap:
      min: 50
      max: 200
    pct_change:
      min: 3
      max: 5
    volume_ratio:
      min: 1.0
    turnover_rate:
      min: 5
      max: 10
    limit_up_history:
      days: 20
      threshold: 9.8
    vwap:
      mode: "above"

  output:
    dir: "output/screener"
    format: "csv"

  data_source:
    primary: "akshare"
    fallback: "jqdata"
```

- [ ] **Step 5: Run existing tests to check for regressions**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/ -v --ignore=tests/JQDataAPI --ignore=tests/mootdxAPI --ignore=tests/akShareAPI
```
Expected: All non-scheduler-dependent tests pass

- [ ] **Step 6: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add -A && git commit -m "refactor: remove embedded schedulers, use Redis Streams consumers"
```

---

### Task 6: Update Dependencies

**Files:**
- Modify: `e:\workspaces\a_stock_quant_system\requirements.txt`

- [ ] **Step 1: Update `requirements.txt`**

Remove `apscheduler`, `nb-cron-nb[fastapi,sqlalchemy]`, `fastapi`, `uvicorn[standard]` and add `redis`:

```
# pip install -r requirements.txt
# pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

jqdatasdk>=1.9.5

# 数据获取层
akshare
tushare
mootdx


# 数据分析与计算层
numpy==1.26.4
pandas==2.2.1
scipy

# 可视化层
matplotlib==3.8.3
mplfinance

# 回测框架
backtrader

# 机器学习层
scikit-learn==1.4.1.post1
xgboost

# 开发工具
jupyterlab
ipywidgets

# 配置管理
python-dotenv
pyyaml

# 测试
pytest>=8.0

# 消息队列
redis>=5.0.0

# 测试工具
fakeredis[lua]>=2.20.0
```

- [ ] **Step 2: Install updated dependencies**

```bash
cd e:/workspaces/a_stock_quant_system && pip install redis fakeredis[lua]
```

- [ ] **Step 3: Run full test suite**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/test_base_worker.py tests/test_screener_worker.py -v
```
Expected: All pass

- [ ] **Step 4: Commit**

```bash
cd e:/workspaces/a_stock_quant_system && git add requirements.txt && git commit -m "chore: replace nb-cron/APScheduler deps with redis-py"
```

---

## Final Verification

- [ ] **Run all tests**

```bash
cd e:/workspaces/a_stock_quant_system && python -m pytest tests/ -v --ignore=tests/JQDataAPI --ignore=tests/mootdxAPI --ignore=tests/akShareAPI
```
Expected: All applicable tests pass, no regressions

- [ ] **Verify import of new modules**

```bash
cd e:/workspaces/a_stock_quant_system && python -c "
from src.workers.base_worker import BaseWorker
from src.workers.fund_worker import create_fund_worker
from src.workers.screener_worker import create_screener_worker, is_trading_day
print('All imports OK')
"
```

- [ ] **Verify manual mode still works** (requires Redis + nb-cron-scheduler running)

```bash
cd e:/workspaces/a_stock_quant_system && python -c "
from src.screener.engine import ScreenerEngine
from src.utils.config import load_yaml
engine = ScreenerEngine(load_yaml('config/screener.yaml')['screener'])
# engine.run()  # uncomment to actually run
print('Manual mode available via engine.run()')
"
```
