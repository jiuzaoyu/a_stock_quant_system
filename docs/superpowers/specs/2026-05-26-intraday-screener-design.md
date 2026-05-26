# 盘中实时选股筛选器 — 设计文档

## 需求概述

交易日 14:30 自动运行，筛选符合条件的 A 股，输出 CSV。

### 筛选条件

| 条件 | 参数 | 数据来源 |
|------|------|---------|
| 市值 | 50亿 - 200亿 | 东方财富实时行情 `stock_zh_a_spot_em()` |
| 当日涨幅 | 3% - 5% | 同上 |
| 量比 | >= 1 | 同上 |
| 换手率 | 5% - 10% | 同上 |
| 近20日有涨停 | 20个交易日内至少1次涨停 | 日线历史 `stock_zh_a_hist()`，提前缓存 |
| 股价在分时均线上方 | 全天所有分钟K线 low >= VWAP | 分钟线 `stock_zh_a_hist_min_em()` |

### 非功能性约束

- 数据源：AKShare（免费），预留切聚宽/JQData 的接口
- 股票池：全市场预筛（先用市值/涨幅等快条件缩圈，再对候选股拉分钟线）
- 调度：APScheduler，交易日历判断，非交易日跳过
- 输出：`output/screener/YYYY-MM-DD.csv`

---

## 模块结构

```
config/screener.yaml          ← 筛选阈值、调度时间
src/screener/
    __init__.py               ← 导出 ScreenerEngine, run_scheduler
    engine.py                 ← 筛选引擎，编排：拉数据 → 过滤 → 输出
    filters.py                ← 每个筛选条件一个纯函数，链式调用，可单测
    scheduler.py              ← APScheduler 封装 + 交易日判断
scripts/run_screener.py       ← 启动入口（薄脚本）
output/screener/              ← CSV 输出目录，按日期命名
tests/test_screener.py        ← 筛选逻辑 + 交易日判断测试
```

### 复用现有模块

- `src/data/fetcher.py` — `DataFetcher`，复用 AKShare 调用逻辑
- `src/data/service.py` — `DataService`，拉日线数据用于涨停历史预筛
- `src/utils/config.py` — `load_config()`，读 YAML 配置
- `src/utils/logger.py` — 日志

---

## 数据流

```
14:30 触发
  │
  ├─ 1. 拉全市场实时快照 (stock_zh_a_spot_em)
  │      └─ 一次 API 调用，含市值/涨幅/量比/换手率/成交额
  │
  ├─ 2. 预筛选（DataFrame filter，毫秒级）
  │      市值 50-200亿 + 涨幅 3%-5% + 量比 >= 1 + 换手率 5%-10%
  │
  ├─ 3. 涨停历史过滤（用缓存日线数据）
  │      对候选股逐一检查近20日是否有涨幅 >= 9.8% 的日期
  │
  ├─ 4. 分时均线过滤（对剩余候选股，逐只拉分钟K线）
  │      VWAP = 累计成交额 / 累计成交量
  │      所有分钟 K 线的 low >= VWAP → 满足条件
  │
  └─ 5. 输出 CSV → output/screener/YYYY-MM-DD.csv
```

筛选执行顺序从快到慢，分时均线放最后（需逐只 API 调用），前几层筛完后候选股预计几十只以内。

---

## 配置设计 (`config/screener.yaml`)

```yaml
screener:
  scheduler:
    trigger_time: "14:30"
    timezone: "Asia/Shanghai"
    max_instances: 1
    misfire_grace_time: 300

  filters:
    market_cap:
      min: 50    # 亿
      max: 200
    pct_change:
      min: 3     # %
      max: 5
    volume_ratio:
      min: 1.0
    turnover_rate:
      min: 5
      max: 10
    limit_up_history:
      days: 20           # 近N个交易日
      threshold: 9.8     # 涨停阈值 %
    vwap:
      mode: "above"      # 股价在分时均线上方

  output:
    dir: "output/screener"
    format: "csv"

  data_source:
    primary: "akshare"
    fallback: "jqdata"
```

---

## 各模块职责

### `scheduler.py`
- 封装 `BackgroundScheduler`
- `is_trading_day(date) -> bool`：用 `ak.tool_trade_date_hist_sina()` 查交易日历
- `start()` / `stop()` 接口
- 触发时调用 `engine.run()`

### `engine.py` — `ScreenerEngine`
- `run(filters_config) -> pd.DataFrame`：编排全流程，返回选中股票列表
- 不依赖调度器，可独立调用测试
- 日志记录每层筛选后的剩余数量 + 总耗时

### `filters.py`
每个条件一个纯函数，签名统一：

```python
def filter_by_market_cap(df: pd.DataFrame, low: float, high: float) -> pd.DataFrame:
    """筛选市值在 [low, high] 亿之间的股票"""
    return df[(df["总市值"] / 1e8 >= low) & (df["总市值"] / 1e8 <= high)]
```

链式调用：
```python
df = filter_by_market_cap(df, 50, 200)
df = filter_by_pct_change(df, 3, 5)
df = filter_by_volume_ratio(df, 1.0)
df = filter_by_turnover_rate(df, 5, 10)
df = filter_by_limit_up_history(df, daily_cache, days=20)
df = filter_by_vwap(df, fetcher)  # 需要 API 调用
```

### `run_screener.py`
```python
from src.screener import run_scheduler
run_scheduler()
```

---

## 测试策略

| 测试内容 | 方式 |
|---------|------|
| `filters.py` 各函数 | 单元测试，构造假 DataFrame 验证过滤逻辑 |
| `is_trading_day()` | 用已知交易日/非交易日验证 |
| `engine.run()` | 集成测试，用少量股票 + 宽松条件验证端到端 |
| 分时均线逻辑 | 用历史某天的分钟数据回放验证 |

---

## 待定项

- 日线缓存策略：首次运行全量拉取，后续增量更新；缓存存储在 `data/cache/daily_cache.parquet`
- 科创50 / 行业分类圈定：v1 先跑全市场，v2 加入行业预筛
