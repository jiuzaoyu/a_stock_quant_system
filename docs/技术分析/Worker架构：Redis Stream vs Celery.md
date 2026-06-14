# Worker 架构：Redis Stream 自研方案 vs Celery

## 概述

本项目没有使用 Celery，而是基于 Redis Streams + Python 多进程实现了一套轻量级的任务消费框架。`scripts/run_workers.py` 就是这个体系中的 worker 启动入口，角色等价于 `celery worker` 命令。

## 架构对照

| 概念 | Celery | 本项目 |
|------|--------|--------|
| Worker 进程 | `celery -A app worker` | `python scripts/run_workers.py` |
| 注册任务 | `@app.task` 装饰器 | `worker.register("job_type", handler)` |
| 消息队列 | RabbitMQ / Redis List | Redis Stream (`XADD` / `XREADGROUP`) |
| 生产者投递 | `task.delay()` / `task.apply_async()` | `redis.xadd("cron:jobs:xxx", {"job_type": "xxx"})` |
| 消费确认 | 自动 ACK | 手动 `XACK`，异常时留在 PEL |
| 消费组 | Celery 内部队列 | `XGROUP CREATE` + `XREADGROUP` |
| 并发模型 | prefork / gevent / eventlet | `multiprocessing.Process` 多进程 |
| 任务重试 | `autoretry_for` / `retry()` | PEL 中未 ACK 的消息等待重新消费 |
| 定时调度 | Celery Beat | 外部 cron 服务向 stream 投递 `XADD` |

## 项目核心组件

### 1. BaseWorker（`src/workers/base_worker.py`）

通用 worker 基类，封装了 Redis Stream 消费循环：

- **`start()`** — 无限循环，阻塞读取 stream 中的新消息（`XREADGROUP block=5000ms`）
- **`_process_one()`** — 取一条消息 → 按 `job_type` 匹配 handler → 执行 → `XACK`；失败则留在 PEL，不 ACK
- **`register()`** — 绑定 `job_type` 到 handler 函数
- **消费组机制** — 自动创建消费组（`mkstream=True`），已存在则忽略（`ResponseError` 被吞掉）

### 2. 具体 Worker 工厂

每个业务域有自己的 `create_xxx_worker` 工厂函数，负责：
- 初始化对应 `Storage` 层并建表
- 注册该域需要的任务类型

| Worker | 监听 Stream | 注册任务 |
|--------|------------|---------|
| `fund_worker` | `cron:jobs:fund_incremental` | `fund_incremental`（采集净值）、`fund_list_refresh`（刷新基金列表） |
| `nav_estimation_worker` | `cron:jobs:nav_estimation` | `nav_estimation`（盘中净值估算） |
| `screener_worker` | `cron:jobs:screener` | `screener`（股票筛选） |

### 3. 启动入口（`scripts/run_workers.py`）

```
python scripts/run_workers.py              # 启动全部 worker（3 个进程）
python scripts/run_workers.py --worker fund  # 只启动 fund worker
```

使用 `multiprocessing.Process` 将每个 worker 拆成独立进程，各自维护独立的 Redis 连接和日志文件。

## 关键差异

### 为什么自研而不是用 Celery

1. **依赖负担小** — Celery 引入 Kombu、billiard、vine 等依赖链，自研仅依赖 `redis-py`，项目本身已经接入 Redis
2. **学习曲线平** — Redis Stream 的 `XADD` / `XREADGROUP` / `XACK` 语义直观，没有 Celery 的 routing、exchange、queue 抽象层
3. **调试透明** — 消息生命周期一目了然：`XADD` 入队 → PEL 待处理 → `XACK` 确认。出问题直接 `XINFO` / `XPENDING` 排查，不需要 `celery inspect` 那一套
4. **调度解耦** — Celery Beat 和 worker 耦合在同一进程树中，本项目把调度（外部 cron）和执行（worker）完全分离，各自独立部署和重启
5. **量级匹配** — 当前任务量是"每交易日几条～几十条消息"，不需要 Celery 的复杂路由和优先级队列

### 自研方案的不足

1. **无内置重试策略** — Celery 有 `max_retries`、指数退避、`autoretry_for`，本方案失败消息只留在 PEL，需要有额外的 PEL 巡检机制
2. **无任务结果存储** — Celery 有 `result_backend` 返回异步结果，本方案任务结果仅体现在日志和数据库写操作
3. **无 Flower 监控** — `celery flower` 提供开箱即用的 Web 面板，本方案监控依赖 `redis-cli XINFO` 和日志文件
4. **无任务路由** — 所有消息投到同一个 stream，没有按优先级/队列分流的能力
5. **进程管理原始** — 直接用 `multiprocessing.Process`，没有 worker 崩溃自动重启、平滑关闭等运维特性

## 消息流全景

```
外部 cron 服务
    │
    │  XADD cron:jobs:fund_incremental job_type=fund_incremental
    ▼
┌─────────────────────────────────┐
│  Redis Stream                   │
│  cron:jobs:fund_incremental     │
│  ┌─────────────────────────────┐│
│  │ PEL (Pending Entries List)  ││  ← 未 ACK 的消息
│  └─────────────────────────────┘│
└──────────┬──────────────────────┘
           │ XREADGROUP block=5000
           ▼
┌──────────────────────────┐
│  run_workers.py          │
│  ┌──────────────────────┐│
│  │ Process: fund_worker ││   handler → collect_today_nav()
│  │ Process: screener    ││   handler → run_screen()
│  │ Process: nav_est     ││   handler → estimate_nav()
│  └──────────────────────┘│
└──────────────────────────┘
           │
           │ handler 执行成功 → XACK
           │ handler 执行失败 → 留在 PEL，等待重新消费
           ▼
        数据库 / 日志
```

## 运维要点

- Worker 必须**常驻运行**，通过 `systemd` / `supervisord` / Docker 管理进程生命周期
- 启动前确保 Redis 和 PostgreSQL 可达，`.env` 配置正确
- 检查 PEL 积压：`redis-cli XPENDING cron:jobs:fund_incremental fund_group`
- 各 worker 日志独立输出到 `logs/<name>_worker.log`
