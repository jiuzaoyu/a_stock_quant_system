# 股票定时采集系统设计

**日期**: 2026-06-24
**状态**: 待评审

## 1. 目标

对全市场 A 股中用户标记为活跃的股票，按定时任务方式完成 K 线和估值数据的初始化与增量更新。

## 2. 数据库变更

`stock_info` 表新增 `active` 字段：

```sql
ALTER TABLE stock_info ADD COLUMN active BOOLEAN NOT NULL DEFAULT FALSE;
```

- 默认 `FALSE`，不参与采集
- 用户手动 `UPDATE stock_info SET active = TRUE WHERE code = '...'` 挑选需要跟踪的标的
- 已存在的股票变更 `active` 状态不影响历史数据

## 3. 定时任务

所有任务由外部调度器（如系统 crontab）触发。调度器向 Redis Stream `cron:jobs:stock_queue_1` 发送消息，Stock Worker 消费处理。

### 3.1 股票列表同步 — `stock_list_sync`

- **频率**: 每周一次（如周一 8:00）
- **数据源**: mootdx（替代不稳定的 AkShare）
- **逻辑**: 拉全市场 A 股列表，新股票 INSERT（`active` 默认 `FALSE`），已有股票 UPDATE `name`（保留用户手动设置的 `active` 值）
- **幂等性**: `PRIMARY KEY (code)` 保证

### 3.2 历史数据补齐 — `stock_history_collect`

- **频率**: 每周一次（如周日 3:00）
- **范围**: `SELECT code FROM stock_info WHERE active = TRUE`
- **逻辑**: 对每只活跃股票，拉最近 N 天 K 线（通过 mootdx）和估值数据（通过腾讯财经），写入 `stock_daily` 和 `stock_valuation`
- **回溯天数**: 从 `config/stock_collector.yaml` 的 `history_lookback_days` 读取（默认 500 天）
- **并发**: 用 `ThreadPoolExecutor`，并发数从配置 `concurrency` 读取
- **幂等性**: `ON CONFLICT (code, trade_date) DO NOTHING`
- **首次运行**: 会执行实质性拉取，后续基本空跑

### 3.3 每日增量采集 — `stock_daily_collect`

- **频率**: 每个交易日收盘后（如 15:30）
- **范围**: `SELECT code FROM stock_info WHERE active = TRUE`
- **逻辑**: 对每只活跃股票，拉最近 N 天增量 K 线和估值，写入对应表
- **回溯天数**: 从 `config/stock_collector.yaml` 的 `daily_lookback_days` 读取（默认 7 天）
- **交易日判断**: handler 开头调用 `is_trading_day()`，非交易日直接返回
- **幂等性**: 同上

## 4. 配置变更

`config/stock_collector.yaml` 新增两个字段：

```yaml
# 增量采集回溯天数
daily_lookback_days: 7

# 历史补齐回溯天数
history_lookback_days: 500
```

完整配置路径通过 `ConfigLoader` 读取，传递给 `StockCollector`。

## 5. 代码变更范围

| 文件 | 变更 |
|------|------|
| `src/collector/stock/fetcher.py` | 新增 `fetch_stock_list()` — 通过 mootdx 获取全市场 A 股列表 |
| `src/collector/stock/storage.py` | 新增 `sync_stock_list()` — INSERT 新股票（`active=FALSE`），UPDATE 已有股票名称（不修改 `active`） |
| `src/workers/stock_worker.py` | 新增 3 个 handler 工厂函数 + 注册到 Worker |
| `config/stock_collector.yaml` | 新增 `daily_lookback_days`、`history_lookback_days` |

## 6. 数据流

```
外部调度器 (crontab)
    │
    │ XADD "cron:jobs:stock_queue_1" "*" job_type stock_list_sync ...
    │ XADD "cron:jobs:stock_queue_1" "*" job_type stock_history_collect ...
    │ XADD "cron:jobs:stock_queue_1" "*" job_type stock_daily_collect ...
    v
Redis Stream "cron:jobs:stock_queue_1"
    │ XREADGROUP (blocking)
    v
stock_worker.py (BaseWorker, consumer_group: stock_queue_group)
    │
    ├─ stock_list_sync
    │   └─ Fetcher.fetch_stock_list() → Storage.sync_stock_list() → stock_info
    │
    ├─ stock_history_collect
    │   └─ 查 active=TRUE 股票
    │       → ThreadPoolExecutor (concurrency=N)
    │       → Fetcher.fetch_kline(offset=history_lookback_days)
    │       → Fetcher.fetch_tencent_valuation(codes)
    │       → Storage.append_daily() + append_valuation()
    │       → stock_daily + stock_valuation
    │
    └─ stock_daily_collect
        └─ is_trading_day() 判断
            → 查 active=TRUE 股票
            → ThreadPoolExecutor (concurrency=N)
            → Fetcher.fetch_kline(offset=daily_lookback_days)
            → Fetcher.fetch_tencent_valuation(codes)
            → Storage.append_daily() + append_valuation()
            → stock_daily + stock_valuation
```

## 7. 异常处理

| 场景 | 处理方式 |
|------|----------|
| mootdx 连接失败 | 捕获异常，记录日志，该只股票记入失败列表，不阻塞其他 |
| 腾讯财经接口超时 | 同上 |
| 单只股票 DB 写入失败 | 捕获异常，记录 code + 错误信息，继续下一只 |
| handler 整体抛异常 | 消息留在 Redis PEL，BaseWorker 现有重试机制生效 |
| 非交易日触发 `stock_daily_collect` | handler 开头返回，不执行采集 |

## 8. 外部 crontab 参考

```cron
# 每周一 8:00 同步股票列表
0 8 * * 1 redis-cli XADD cron:jobs:stock_queue_1 "*" job_type stock_list_sync job_id "list_sync:$(date -Iseconds)" triggered_at "$(date -Iseconds)" timeout "600" max_retries "3"

# 每周日 3:00 补齐历史数据
0 3 * * 0 redis-cli XADD cron:jobs:stock_queue_1 "*" job_type stock_history_collect job_id "history:$(date -Iseconds)" triggered_at "$(date -Iseconds)" timeout "7200" max_retries "2"

# 每个交易日 15:30 增量采集
30 15 * * 1-5 redis-cli XADD cron:jobs:stock_queue_1 "*" job_type stock_daily_collect job_id "daily:$(date -Iseconds)" triggered_at "$(date -Iseconds)" timeout "3600" max_retries "3"
```
