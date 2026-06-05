# 项目更新记录

## 2026-06-05

- **数据库迁移: SQLite → PostgreSQL** — 引入 `src/utils/database.py` 连接池管理模块（基于 psycopg2 ThreadedConnectionPool），统一管理 PostgreSQL 连接。三个 storage 模块（daily / fund / stock）全部适配 PostgreSQL：
  - 占位符 `?` → `%s`，`executemany` → `execute_values` 批量写入
  - `INSERT OR IGNORE/REPLACE` → `INSERT ... ON CONFLICT DO NOTHING/UPDATE`
  - 时间字段 `datetime('now')` → `TIMESTAMPTZ DEFAULT NOW()`
  - 新增 `COMMENT ON TABLE/COLUMN` 字段注释
  - 连接管理从 `sqlite3.connect/close` 改为连接池 `get_connection/return_connection`
  - 字符串数据增加 `sanitize()` 清洗（去除 NUL、\r、反斜杠转义）
  - `_safe_int` / `_safe_float` 安全类型转换处理空值
- **配置精简** — 移除各 yaml 中的本地 `database` 路径配置，统一通过 `.env` 的 `DATABASE_URL` 指定数据库连接。
- **股票采集模块** — 新增 `src/stock_collector/`，仿照 fund_collector 架构，通过 mootdx (TCP) 采集 K 线数据、腾讯财经 (HTTP) 采集估值数据，存入 quant.db 的 stock_info / stock_daily / stock_valuation 三张表。支持全量历史采集和增量更新。
- **mootdx API 文档** — 整理 mootdx + 腾讯财经接口的数据字段、用法说明，放在 `tests/mootdxAPI/market_data_api.md`。

- **股票采集模块** — 新增 `src/stock_collector/`，仿照 fund_collector 架构，通过 mootdx (TCP) 采集 K 线数据、腾讯财经 (HTTP) 采集估值数据，存入 quant.db 的 stock_info / stock_daily / stock_valuation 三张表。支持全量历史采集和增量更新。
- **mootdx API 文档** — 整理 mootdx + 腾讯财经接口的数据字段、用法说明，放在 `tests/mootdxAPI/market_data_api.md`。

## 2026-06-04

- **TA-Lib 集成** — 添加 TA-Lib wheel 包和指标测试脚本。
- **基金采集增强** — 基金采集器扩展：加入基金经理信息和持仓数据采集支持，采用异步并发架构。

## 2026-05-29

- **调度器微服务化** — 移除内嵌调度器，改用 Redis Streams Consumer Group 作为消息总线，由外部 cron-scheduler 发 job，本项目 worker 消费。
- **统一 Worker 入口** — `scripts/run_workers.py` 支持多进程启动 fund / screener worker。
- **FundWorker** — 订阅 `cron:jobs:fund_incremental` 和 `cron:jobs:fund_list_refresh`，处理基金增量采集和列表刷新。
- **ScreenerWorker** — 订阅选股 job，实现交易日判断逻辑。
- **BaseWorker** — 封装 Redis Streams Consumer Group 的通用消费循环、消息分发和异常处理。

## 2026-05-26

- **选股器设计文档** — 新增日内选股器功能规格和技术设计文档。
- **接口探索** — 整理和测试各种行情数据 API 接口。

## 2026-05-24

- **项目初始化** — A 股量化研究系统骨架搭建，包含基础目录结构、配置管理、日志工具、skills-lock.json。
