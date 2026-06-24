# 股票定时采集系统 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现三个定时任务（股票列表同步、历史数据补齐、每日增量采集），通过外部 cron 向 Redis Stream 发消息触发

**Architecture:** 在现有 `stock_worker.py` 上扩展 3 个 handler，复用 `fetch_kline` / `fetch_tencent_batch` / `StockStorage`，在 `stock_info` 表新增 `active` 字段控制采集范围

**Tech Stack:** Python, mootdx (TCP K线), 腾讯财经 (HTTP 估值), Redis Streams, PostgreSQL (psycopg2), ThreadPoolExecutor

**Spec:** `docs/superpowers/specs/2026-06-24-stock-scheduled-collection-design.md`

---

## File Structure

| 文件 | 角色 |
|------|------|
| `src/collector/stock/storage.py` | 新增 `sync_stock_list()` (sync without touching active), `get_active_codes()`, schema migration |
| `src/workers/stock_worker.py` | 新增 3 个 handler 工厂 + 注册到 Worker + 读取配置 |
| `config/stock_collector.yaml` | 新增 `daily_lookback_days`、`history_lookback_days` |
| `tests/test_stock_storage.py` | 新增 storage 方法测试 |

`src/collector/stock/fetcher.py` 无需修改——`fetch_stock_list()` 已默认 mootdx 数据源。

---

### Task 1: Schema migration — 添加 `active` 列

**Files:**
- Modify: `src/collector/stock/storage.py`

- [ ] **Step 1: 在 `init_schema` 中添加 migration 逻辑**

在 `STOCK_INFO_SCHEMA` 的 `CREATE TABLE IF NOT EXISTS` 后面（现有 DDL 不变），`init_schema` 方法中 `conn.commit()` 之前插入 migration 代码。

修改 `init_schema` 方法，在 `with conn.cursor() as cur:` 块内、`INDEX_DATE` 执行之后添加：

```python
                # 迁移：添加 active 列 (v2)
                cur.execute("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM information_schema.columns
                        WHERE table_name = 'stock_info' AND column_name = 'active'
                    ) THEN
                        ALTER TABLE stock_info ADD COLUMN active BOOLEAN NOT NULL DEFAULT FALSE;
                    END IF;
                END $$;
                """)
```

这段代码加在 `cur.execute(INDEX_VALUATION_DATE)` 之后、`for obj, desc in STOCK_COMMENTS:` 之前。

- [ ] **Step 2: 验证 migration SQL 语法**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from src.collector.stock import StockStorage
s = StockStorage()
conn = s.connect()
s.init_schema(conn)
cur = conn.cursor()
cur.execute(\"SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns WHERE table_name='stock_info' AND column_name='active'\")
print(cur.fetchone())
conn.close()
"
```

Expected: 打印 `active` 列信息，包含 `BOOLEAN`, `NO`, `false`

- [ ] **Step 3: Commit**

```bash
git add src/collector/stock/storage.py
git commit -m "feat(stock): add active column migration to stock_info schema"
```

---

### Task 2: Storage 新增方法 — `sync_stock_list()` + `get_active_codes()`

**Files:**
- Modify: `src/collector/stock/storage.py`

- [ ] **Step 1: 在 `StockStorage` 类中添加 `sync_stock_list` 方法**

在 `upsert_stock_info` 方法之后插入（约第 184 行之后）：

```python
    def sync_stock_list(self, conn, records: list[dict]) -> int:
        """批量同步股票列表：新股票 INSERT (active=FALSE)，已有股票 UPDATE name/market（不修改 active）。"""
        sql = f"""
        INSERT INTO {STOCK_INFO_TABLE} (code, name, market)
        VALUES %s
        ON CONFLICT(code) DO UPDATE SET
            name = excluded.name,
            market = excluded.market,
            updated_at = NOW()
        """
        tuples = [(sanitize(r["code"]), sanitize(r["name"]), sanitize(r.get("market", ""))) for r in records]
        tuples = list({t[0]: t for t in tuples}.values())
        with conn.cursor() as cur:
            execute_values(cur, sql, tuples, page_size=1000)
            return cur.rowcount
```

注意：此方法不显式设置 `active` 值，INSERT 时依赖列默认值 `FALSE`，UPDATE 时不碰 `active`，保证用户手动设置不被覆盖。

- [ ] **Step 2: 在 `StockStorage` 类中添加 `get_active_codes` 方法**

在 `get_all_codes` 方法之后插入（约第 236 行之后）：

```python
    def get_active_codes(self, conn=None) -> list[str]:
        """获取 active=TRUE 的股票代码列表。"""
        own = conn is None
        conn = conn or self.connect()
        try:
            with conn.cursor() as cur:
                cur.execute(f"SELECT code FROM {STOCK_INFO_TABLE} WHERE active = TRUE ORDER BY code")
                return [r[0] for r in cur.fetchall()]
        finally:
            if own:
                return_connection(conn)
```

- [ ] **Step 3: 更新 `__init__.py` 导出**

`src/collector/stock/__init__.py` 无需修改——`StockStorage` 已导出，新方法是类方法自动可用。

- [ ] **Step 4: Commit**

```bash
git add src/collector/stock/storage.py
git commit -m "feat(stock): add sync_stock_list and get_active_codes methods"
```

---

### Task 3: Storage 方法单元测试

**Files:**
- Create: `tests/test_stock_storage.py`

- [ ] **Step 1: 编写测试**

```python
import psycopg2
import pytest

from src.collector.stock import StockStorage


@pytest.fixture
def storage():
    return StockStorage()


@pytest.fixture
def conn(storage):
    c = storage.connect()
    storage.init_schema(c)
    yield c
    c.rollback()
    storage.return_conn(c)


class TestSyncStockList:
    def test_insert_new_stocks_with_active_false(self, storage, conn):
        records = [
            {"code": "999999", "name": "测试股A", "market": "sh"},
            {"code": "888888", "name": "测试股B", "market": "sz"},
        ]
        storage.sync_stock_list(conn, records)
        conn.commit()

        cur = conn.cursor()
        cur.execute("SELECT code, name, market, active FROM stock_info WHERE code IN ('999999','888888') ORDER BY code")
        rows = cur.fetchall()
        assert len(rows) == 2
        assert rows[0] == ("888888", "测试股B", "sz", False)
        assert rows[1] == ("999999", "测试股A", "sh", False)

    def test_update_existing_does_not_change_active(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('777777','旧名称','sh',TRUE) "
                    "ON CONFLICT(code) DO UPDATE SET active=TRUE")
        conn.commit()

        records = [{"code": "777777", "name": "新名称", "market": "sh"}]
        storage.sync_stock_list(conn, records)
        conn.commit()

        cur.execute("SELECT code, name, market, active FROM stock_info WHERE code='777777'")
        row = cur.fetchone()
        assert row == ("777777", "新名称", "sh", True)


class TestGetActiveCodes:
    def test_returns_only_active_codes(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('666666','活跃股','sh',TRUE)")
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('555555','非活跃股','sz',FALSE)")
        conn.commit()

        codes = storage.get_active_codes(conn)
        assert codes == ["666666"]

    def test_returns_empty_when_no_active(self, storage, conn):
        cur = conn.cursor()
        cur.execute("INSERT INTO stock_info (code, name, market, active) VALUES ('444444','全非活跃','sh',FALSE)")
        conn.commit()

        codes = storage.get_active_codes(conn)
        assert codes == []
```

- [ ] **Step 2: 运行测试**

```bash
cd /e/workspaces/a_stock_quant_system && python -m pytest tests/test_stock_storage.py -v
```

Expected: 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/test_stock_storage.py
git commit -m "test(stock): add tests for sync_stock_list and get_active_codes"
```

---

### Task 4: 配置新增 lookback 字段

**Files:**
- Modify: `config/stock_collector.yaml`

- [ ] **Step 1: 在 `stock_collector` 节点末尾追加两个字段**

```yaml
  # 增量采集回溯天数（交易日）
  daily_lookback_days: 7

  # 历史补齐回溯天数
  history_lookback_days: 500
```

- [ ] **Step 2: Commit**

```bash
git add config/stock_collector.yaml
git commit -m "feat(config): add daily_lookback_days and history_lookback_days to stock collector config"
```

---

### Task 5: Worker 新增批量采集 handler 工厂

**Files:**
- Modify: `src/workers/stock_worker.py`

- [ ] **Step 1: 新增 import**

在现有 `import` 区域追加 `time` 和 `concurrent.futures`：

```python
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
```

同时在现有 import 中补充 `fetch_tencent_batch`：

```python
from src.collector.stock import StockStorage, fetch_kline, fetch_tencent_batch, fetch_tencent_valuation, fetch_stock_list
```

以及追加配置加载：

```python
from src.utils.config import load_yaml
```

- [ ] **Step 2: 新增 `_make_stock_list_sync_handler` 工厂函数**

在 `_make_single_stock_handler` 函数之后插入（约第 94 行之后）：

```python
def _make_stock_list_sync_handler(storage: StockStorage):
    def handler(data: dict[str, str]) -> None:
        log.info("=== stock_list_sync 开始 ===")
        try:
            stocks = fetch_stock_list(source="mootdx")
            conn = storage.connect()
            try:
                count = storage.sync_stock_list(conn, stocks)
                conn.commit()
                log.info("stock_list_sync 完成: %d 只股票", len(stocks))
            finally:
                storage.return_conn(conn)
        except Exception:
            log.exception("stock_list_sync 失败")
            raise

    return handler
```

- [ ] **Step 3: 新增 `_make_batch_collect_handler` 工厂函数**

在 `_make_stock_list_sync_handler` 之后插入：

```python
def _make_batch_collect_handler(
    storage: StockStorage,
    concurrency: int,
    lookback_days: int,
    delay: float,
    max_retries: int,
    job_name: str,
    check_trading_day: bool = False,
):
    def handler(data: dict[str, str]) -> None:
        if check_trading_day and not is_trading_day():
            log.info("%s: 非交易日，跳过", job_name)
            return

        log.info("=== %s 开始 (lookback=%d 天) ===", job_name, lookback_days)
        codes = storage.get_active_codes()
        if not codes:
            log.info("%s: 无活跃股票，跳过", job_name)
            return

        log.info("%s: 活跃股票 %d 只, 并发数 %d", job_name, len(codes), concurrency)

        t0 = time.time()
        success = 0
        fail = 0
        daily_total = 0

        def collect_one(code: str):
            for attempt in range(max_retries):
                try:
                    kline_rows = fetch_kline(code, category=4, offset=lookback_days)
                    return (code, kline_rows, None)
                except Exception as e:
                    if attempt < max_retries - 1:
                        time.sleep(delay * (attempt + 2))
                    else:
                        return (code, [], str(e))
            return (code, [], "max_retries")

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(collect_one, code): code for code in codes}
            for future in as_completed(futures):
                code, kline_rows, error = future.result()
                if error:
                    fail += 1
                    log.warning("%s: %s K线采集失败: %s", job_name, code, error)
                    continue

                conn = storage.connect()
                try:
                    if kline_rows:
                        daily_total += storage.append_daily(conn, kline_rows)
                    conn.commit()
                finally:
                    storage.return_conn(conn)
                success += 1

                if delay > 0:
                    time.sleep(delay)

        # 批量估值为减少 HTTP 请求数，统一按批次拉取
        val_total = 0
        val_records = fetch_tencent_batch(codes, batch_size=80)
        if val_records:
            conn = storage.connect()
            try:
                val_total = storage.append_valuation(conn, val_records)
                conn.commit()
            finally:
                storage.return_conn(conn)

        elapsed = time.time() - t0
        log.info(
            "%s 完成: 成功 %d, 失败 %d, K线 %d 条, 估值 %d 条, 耗时 %.1fs",
            job_name, success, fail, daily_total, val_total, elapsed,
        )

    return handler
```

- [ ] **Step 4: Commit**

```bash
git add src/workers/stock_worker.py
git commit -m "feat(stock): add batch collect and list sync handler factories"
```

---

### Task 6: Worker 注册 — `create_stock_workers` 改造

**Files:**
- Modify: `src/workers/stock_worker.py`

- [ ] **Step 1: 修改 `create_stock_workers` 函数**

用以下代码替换现有 `create_stock_workers` 函数（第 22-38 行）：

```python
def create_stock_workers(redis_client: Redis) -> list[BaseWorker]:
    """创建股票数据采集 Worker 实例。"""
    storage = StockStorage()
    storage.init_schema()

    # 加载配置
    root = Path(__file__).resolve().parents[2]
    stock_cfg = load_yaml(root / "config" / "stock_collector.yaml").get("stock_collector", {})
    concurrency = stock_cfg.get("concurrency", 5)
    delay = stock_cfg.get("request_delay_seconds", 0.3)
    max_retries = stock_cfg.get("max_retries", 3)
    daily_lookback = stock_cfg.get("daily_lookback_days", 7)
    history_lookback = stock_cfg.get("history_lookback_days", 500)

    data_worker = BaseWorker(
        redis_client,
        stream="cron:jobs:stock_queue_1",
        group="stock_queue_group",
        consumer="stock_queue_consumer_1",
    )

    # 原有：单股采集
    data_worker.register(
        "stock_collect_single",
        _make_single_stock_handler(storage),
    )

    # 股票列表同步
    data_worker.register(
        "stock_list_sync",
        _make_stock_list_sync_handler(storage),
    )

    # 历史数据补齐
    data_worker.register(
        "stock_history_collect",
        _make_batch_collect_handler(
            storage, concurrency, history_lookback, delay, max_retries,
            job_name="stock_history_collect",
        ),
    )

    # 每日增量采集
    data_worker.register(
        "stock_daily_collect",
        _make_batch_collect_handler(
            storage, concurrency, daily_lookback, delay, max_retries,
            job_name="stock_daily_collect", check_trading_day=True,
        ),
    )

    return [data_worker]
```

- [ ] **Step 2: 检查无法访问的 import**

移除不再需要的 `from typing import Optional` 中的 `Optional`（如果只用于 `is_trading_day`，保留它）。确认 `pd` (pandas) 仍被 `is_trading_day` 使用。

- [ ] **Step 3: Commit**

```bash
git add src/workers/stock_worker.py
git commit -m "feat(stock): register list_sync, history_collect, daily_collect handlers"
```

---

### Task 7: 集成验证

**Files:**
- 无新建文件

- [ ] **Step 1: 启动 Redis（如未运行）**

```bash
docker ps --filter name=nc_redis --format "{{.Names}}"
```

如果 Redis 容器未运行：
```bash
cd /e/workspaces/a_stock_quant_system/docker && docker compose up -d nc_redis
```

- [ ] **Step 2: 验证 Worker 正常启动并注册 handler**

```bash
cd /e/workspaces/a_stock_quant_system && timeout 5 python -c "
from redis import Redis
from src.workers.stock_worker import create_stock_workers
import os
r = Redis(host=os.getenv('REDIS_HOST','localhost'), port=int(os.getenv('REDIS_PORT',36379)), decode_responses=True)
workers = create_stock_workers(r)
for w in workers:
    print('Registered handlers:', list(w._handlers.keys()))
" 2>&1 || true
```

Expected: 打印 `Registered handlers: ['stock_collect_single', 'stock_list_sync', 'stock_history_collect', 'stock_daily_collect']`

- [ ] **Step 3: 手动推送 `stock_list_sync` 验证**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from redis import Redis
import os, json
r = Redis(host=os.getenv('REDIS_HOST','localhost'), port=int(os.getenv('REDIS_PORT',36379)), decode_responses=True)
msg = {
    'job_id': 'manual_test:stock_list_sync',
    'job_type': 'stock_list_sync',
    'triggered_at': '2026-06-24T00:00:00',
    'timeout': '600',
    'max_retries': '2',
    'payload': '{}',
}
r.xadd('cron:jobs:stock_queue_1', msg)
print('Message pushed:', r.xlen('cron:jobs:stock_queue_1'), 'messages pending')
"
```

- [ ] **Step 4: 运行 Worker 消费消息**

```bash
cd /e/workspaces/a_stock_quant_system && timeout 30 python scripts/run_workers.py --worker stock 2>&1 || true
```

Expected: 日志输出 `stock_list_sync 开始` → `stock_list_sync 完成`

- [ ] **Step 5: 验证数据库 stock_info 表有数据且 active=FALSE**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from src.collector.stock import StockStorage
s = StockStorage()
conn = s.connect()
cur = conn.cursor()
cur.execute('SELECT COUNT(*), COUNT(*) FILTER (WHERE active = TRUE) FROM stock_info')
total, active = cur.fetchone()
print(f'Total stocks: {total}, Active: {active}')
cur.execute('SELECT code, name, active FROM stock_info LIMIT 5')
for row in cur.fetchall():
    print(row)
s.return_conn(conn)
"
```

Expected: `Total stocks` > 0, `Active: 0`

- [ ] **Step 6: 手动激活一只股票测试采集**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from src.collector.stock import StockStorage
s = StockStorage()
conn = s.connect()
cur = conn.cursor()
cur.execute(\"UPDATE stock_info SET active = TRUE WHERE code = '688017'\")
conn.commit()
print('Activated 688017')
s.return_conn(conn)
"
```

- [ ] **Step 7: 推送 `stock_daily_collect` 验证增量采集**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from redis import Redis
import os
r = Redis(host=os.getenv('REDIS_HOST','localhost'), port=int(os.getenv('REDIS_PORT',36379)), decode_responses=True)
msg = {
    'job_id': 'manual_test:daily_collect',
    'job_type': 'stock_daily_collect',
    'triggered_at': '2026-06-24T00:00:00',
    'timeout': '600',
    'max_retries': '2',
    'payload': '{}',
}
r.xadd('cron:jobs:stock_queue_1', msg)
print('Message pushed')
"
```

```bash
cd /e/workspaces/a_stock_quant_system && timeout 30 python scripts/run_workers.py --worker stock 2>&1 || true
```

Expected: 日志输出 `stock_daily_collect 开始` → 采集 688017 → `stock_daily_collect 完成`

- [ ] **Step 8: 验证 K 线和估值数据已写入**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from src.collector.stock import StockStorage
s = StockStorage()
conn = s.connect()
cur = conn.cursor()
cur.execute(\"SELECT COUNT(*) FROM stock_daily WHERE code = '688017'\")
print('Kline rows for 688017:', cur.fetchone()[0])
cur.execute(\"SELECT COUNT(*) FROM stock_valuation WHERE code = '688017'\")
print('Valuation rows for 688017:', cur.fetchone()[0])
s.return_conn(conn)
"
```

Expected: 两项均 > 0

---

### Task 8: 最终提交

- [ ] **Step 1: 运行全部测试确认无回归**

```bash
cd /e/workspaces/a_stock_quant_system && python -m pytest tests/ -v
```

- [ ] **Step 2: 如需清理手动插入的测试数据**

```bash
cd /e/workspaces/a_stock_quant_system && python -c "
from src.collector.stock import StockStorage
s = StockStorage()
conn = s.connect()
cur = conn.cursor()
cur.execute(\"DELETE FROM stock_valuation WHERE code = '688017'\")
cur.execute(\"DELETE FROM stock_daily WHERE code = '688017'\")
cur.execute(\"UPDATE stock_info SET active = FALSE WHERE code = '688017'\")
conn.commit()
print('Cleaned up test data for 688017')
s.return_conn(conn)
"
```
