# 调度服务微服务化 — 设计文档

## 需求概述

将定时任务调度从业务项目中完全剥离，拆分为两个独立项目：

1. **`nb-cron-scheduler`**（新建，独立仓库）— 通用调度服务，不包含任何业务逻辑
2. **`stock-quant-system`**（当前项目，改造）— 纯业务模块，通过 Redis Streams 消费调度消息

### 动机

- 定时任务调度和业务逻辑本质上是解耦的
- 一个通用调度服务可以被多个项目复用（本项目、未来其他量化项目等）
- 当前项目内同时存在 `nb_cron` 和 `APScheduler` 两套调度机制，缺乏统一性

---

## 架构概览

```
┌──────────────────────────┐         Redis Streams          ┌──────────────────────────┐
│   nb-cron-scheduler       │                               │   stock-quant-system      │
│   (通用调度服务)           │                               │   (业务项目)               │
│                           │   XADD jobs:fund_incremental   │                           │
│   FastAPI + nb_cron       │ ─────────────────────────────>│   workers/fund_worker.py  │
│   Web UI (:8080)          │                               │   → FundCollector         │
│                           │   XADD jobs:screener_intraday  │                           │
│   jobs/definitions.yaml   │ ─────────────────────────────>│   workers/screener_worker │
│   ↓ 纯声明式 job 配置      │                               │   → ScreenerEngine        │
│   不关心谁在消费           │                               │                           │
│                           │                               │   XREADGROUP + ACK        │
└──────────────────────────┘                               └──────────────────────────┘
                                       ▲
                                       │
                              Redis (共享中间件)
                                       │
                                       ▼
                               ┌──────────────────┐
                               │   未来其他项目     │
                               │   XREADGROUP     │
                               └──────────────────┘
```

### 关键设计决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 通信方式 | Redis Streams + Consumer Group | 轻量、可靠（ACK/重试）、Redis 大概率已在技术栈中 |
| 调度服务是否感知业务 | 不感知 — 只发消息 | 调度服务不知道也不需要知道谁在消费、消费结果如何 |
| Job 定义方式 | 声明式 YAML | 新增 job 不写代码，只需加一段 YAML |
| 消费者端可靠性 | Consumer Group + ACK | 消息不丢，worker 挂了重启后从 PEL 续传 |

---

## 项目一：nb-cron-scheduler

### 定位

通用的、零业务逻辑的 cron → Redis Stream 消息转发器。

### 项目结构

```
nb-cron-scheduler/
├── config/
│   └── scheduler.yaml       # 调度服务自身配置（Redis 连接、端口等）
├── src/
│   ├── __init__.py
│   ├── app.py               # FastAPI + nb_cron 启动入口
│   ├── job_registry.py      # 从 definitions.yaml 加载 job 并注册到 nb_cron
│   └── publisher.py         # Redis Streams 消息发布（XADD）
├── jobs/
│   └── definitions.yaml     # 声明式 job 配置（唯一需要改的地方）
├── tests/
│   └── test_publisher.py
├── requirements.txt
├── Dockerfile
└── README.md
```

### `jobs/definitions.yaml` 设计

每个 job 是一条声明式配置，job 注册器解析后自动注册到 nb_cron：

```yaml
redis:
  host: "127.0.0.1"
  port: 6379
  db: 0
  stream_prefix: "cron:jobs"       # Stream 命名前缀

jobs:
  - name: fund_incremental
    cron: "0 30 16 * * 1-5"
    stream: "cron:jobs:fund_incremental"
    payload:
      job_type: "fund_incremental"
    timeout: 600
    max_retries: 3

  - name: fund_list_refresh
    cron: "0 30 17 * * 5"
    stream: "cron:jobs:fund_list_refresh"
    payload:
      job_type: "fund_list_refresh"
    timeout: 900
    max_retries: 2

  - name: screener_intraday
    cron: "0 30 14 * * 1-5"
    stream: "cron:jobs:screener_intraday"
    payload:
      job_type: "screener_intraday"
    timeout: 300
    max_retries: 2
```

### 消息格式（XADD 的 message body）

```json
{
  "job_id": "fund_incremental:2026-05-29T16:30:00",
  "job_type": "fund_incremental",
  "triggered_at": "2026-05-29T16:30:00",
  "timeout": 600,
  "max_retries": 3,
  "payload": {}
}
```

- `job_id` — 每次触发唯一，格式 `{name}:{ISO8601}`
- `triggered_at` — 调度服务打的时间戳，消费者可用于判断延迟
- `payload` — 透传 YAML 中定义的自定义字段

### 核心职责（必须）

- 解析 `definitions.yaml`，注册 cron job
- 到时间 → 构造消息 → `XADD stream * field value ...`
- Web UI 查看/手动触发/启停 job
- 不关心 Consumer Group、ACK、重试 —— 那是消费者的事

### 不做什么（明确边界）

- 不执行业务逻辑
- 不管理 Consumer Group
- 不做消息重试 / 死信处理（消费者的责任）
- 不做消费者状态监控（可后续扩展，但 v1 不做）

---

## 项目二：stock-quant-system（改造）

### 改动总览

| 操作 | 文件/目录 | 说明 |
|------|----------|------|
| **删除** | `scripts/run_fund_scheduler.py` | 不再需要 nb_cron 启动入口 |
| **删除** | `scripts/run_screener.py` | 替代为 worker 模式 |
| **删除** | `src/screener/scheduler.py` | APScheduler 封装移除 |
| **删除** | `config/fund_collector.yaml` 中 scheduler/server 段 | 调度配置移交 nb-cron-scheduler |
| **删除** | `config/screener.yaml` 中 scheduler 段 | 同上 |
| **修改** | `requirements.txt` | 移除 `nb-cron-nb[fastapi,sqlalchemy]`、`apscheduler`；新增 `redis` |
| **新增** | `src/workers/base_worker.py` | Redis Streams Consumer Group 基类 |
| **新增** | `src/workers/fund_worker.py` | 监听 fund 相关 stream，调用 FundCollector |
| **新增** | `src/workers/screener_worker.py` | 监听 screener stream，调用 ScreenerEngine |
| **新增** | `scripts/run_workers.py` | 统一 worker 启动入口 |

### 新增模块设计

#### `src/workers/base_worker.py`

Consumer Group 通用封装：

```
class BaseWorker:
    __init__(redis_client, stream, group, consumer)
    register(job_type, handler)           # 注册 job_type → handler 映射
    start(block_ms=5000)                  # 阻塞消费循环
    _process(message)                     # 分发 → handler → ACK
```

要点：
- 自动创建 Consumer Group（`MKSTREAM` + `XGROUP CREATE`，幂等）
- 消费循环：`XREADGROUP` → 分发 handler → `XACK`
- handler 异常时 `XACK` 不做（消息留在 PEL），下次重新投递
- 保证幂等：同一个 `job_id` 重复消费不会导致数据重复（由各 handler 自行保证）

#### `src/workers/fund_worker.py`

```
worker = BaseWorker(redis, "cron:jobs:fund_incremental", "fund_group", "fund_consumer_1")
worker.register("fund_incremental", collect_today_nav)
worker.register("fund_list_refresh", refresh_fund_list)
worker.start()
```

#### `src/workers/screener_worker.py`

```
worker = BaseWorker(redis, "cron:jobs:screener_intraday", "screener_group", "screener_consumer_1")
worker.register("screener_intraday", screener_job_handler)
worker.start()
```

其中 `screener_job_handler` 包含交易日判断逻辑（原 `screener/scheduler.py` 中的 `is_trading_day()` 移入 worker）。

#### `scripts/run_workers.py`

启动入口：

```
python scripts/run_workers.py                      # 启动所有 worker
python scripts/run_workers.py --worker fund        # 只启动 fund worker
python scripts/run_workers.py --worker screener    # 只启动 screener worker
```

内部用 `multiprocessing` 或 `asyncio.gather` 并行运行多个 worker。

### 保留的手动模式

原 `--manual` 参数的能力保留，直接在 `src/fund_collector/collector.py` 和 `src/screener/engine.py` 的函数上调用即可，不依赖调度：

```python
# 手动触发
from src.fund_collector.collector import collect_today_nav
collect_today_nav()

from src.screener.engine import ScreenerEngine
engine = ScreenerEngine(config)
engine.run()
```

---

## 部署拓扑

```
┌────────────────────────────────────────────┐
│  机器 / 服务器                               │
│                                            │
│  ┌──────────────┐  ┌──────────────────┐    │
│  │ Redis        │  │ stock-quant      │    │
│  │ (127.0.0.1)  │  │ run_workers.py   │    │
│  └──────┬───────┘  └────────▲─────────┘    │
│         │                   │              │
│         │   Redis Streams   │              │
│         │                   │              │
│  ┌──────┴───────┐           │              │
│  │ nb-cron-     │───────────┘              │
│  │ scheduler    │                          │
│  │ (FastAPI)    │                          │
│  └──────────────┘                          │
└────────────────────────────────────────────┘
```

- 三个组件可以在同一台机器、同一个 Docker Compose 里部署
- 也可以分开部署在不同机器（Redis 地址可配置）
- 调度服务和业务项目各自独立启停，互不影响

---

## 测试策略

### nb-cron-scheduler

- 单元测试：`publisher.py` 消息构造、`job_registry.py` YAML 解析
- 集成测试：启动 Redis，注册 job，手动触发，验证 Stream 中有消息

### stock-quant-system

- `base_worker.py`：用 fakeredis 做 Consumer Group 逻辑测试
- `fund_worker.py` / `screener_worker.py`：mock handler，验证消息分发
- 现有 `tests/test_screener.py` 不受影响（纯筛选逻辑测试）

---

## 迁移步骤（高层）

1. 创建 `nb-cron-scheduler` 仓库，实现核心功能
2. 在本项目中新增 `src/workers/`，实现消费者端
3. 两端联调通过
4. 删除本项目中的旧调度代码（`run_fund_scheduler.py`、`run_screener.py`、`scheduler.py`、相关配置段）
5. 更新 `requirements.txt`，移除旧依赖
