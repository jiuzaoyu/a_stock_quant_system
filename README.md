# A 股量化研究系统

`a_stock_quant_system` — 面向 A 股的量化研究骨架，遵循**关注点分离**：配置与代码分离、数据与逻辑分离、研究与生产分离。每一层可独立开发、测试与替换，便于长期维护。

## 设计原则

| 分离维度 | 做法 |
|----------|------|
| 配置 ↔ 代码 | 参数写在 `config/`，改策略参数不动源码 |
| 数据 ↔ 逻辑 | 行情经 `DataService` 进入，策略不直连 AkShare/Tushare |
| 研究 ↔ 生产 | `notebooks/` 做探索；`main.py` + `src/` 做可复现流水线 |
| 策略 ↔ 回测 | 策略只产出 `signal`；回测引擎只负责模拟成交与绩效 |

## 目录结构

```
a_stock_quant_system/
├── config/                   # 配置文件
│   ├── base.yaml            # 基础配置（路径、日志级别等）
│   ├── strategy.yaml        # 策略参数（均线、止损等非敏感项）
│   ├── .env.example         # 敏感信息模板
│   ├── .env                 # 真实密钥（本地创建，已 gitignore）
│   └── README.md            # 配置说明
├── data/                     # 数据存储（按处理阶段分层）
│   ├── raw/                 # 原始下载数据
│   ├── processed/           # 清洗后数据（可追溯）
│   └── cache/               # 临时缓存
├── notebooks/                # Jupyter：实验室，非生产工厂
│   ├── 01_data_exploration.ipynb
│   ├── 02_factor_analysis.ipynb
│   └── 03_strategy_research.ipynb
├── src/                      # 可复用 Python 模块
│   ├── data/                # 数据获取与处理（含 DataService）
│   ├── strategy/            # 策略（统一 BaseStrategy 接口）
│   ├── backtest/            # 回测引擎
│   ├── risk/                # 风控
│   └── utils/               # 日志、配置加载等
├── scripts/                  # 批处理入口（ETL，如沪深300采集）
│   └── collect_hs300_daily.py
├── tests/                    # 单元测试
├── output/                   # 图表、报告
├── logs/                     # 运行日志
├── main.py                   # 策略回测入口（编排各层）
├── environment.yml
├── requirements.txt
└── README.md
```

### 各目录用途与设计考量

**`config/`** — 集中管理数据库路径、策略参数、日志级别等。配置与代码分离后，调参不必改源码，降低误提交风险。

**`data/`** — 按阶段分层：

- `raw/`：数据源原始落盘  
- `processed/`：清洗后可复用数据  
- `cache/`：临时缓存  

流程清晰、便于排查与重跑。

**`notebooks/`** — 仅用于数据探索与策略原型，是**实验室**而非**工厂**。验证通过的逻辑应迁入 `src/` 并由 `tests/` 覆盖。

**`scripts/`** — 一次性或定期跑的数据管线入口（如沪深300日线入库）。脚本应很薄，只负责读配置和调用 `src/data/`；核心逻辑放在 `hs300_collector.py`、`storage.py`。数据库文件默认 `data/database/hs300_daily.db`（见 `paths.database`）。

**`src/`** — 按功能划分子模块，通过各包 `__init__.py` 暴露稳定公开 API，避免外部依赖内部文件路径。

**`tests/`** — 至少覆盖数据处理与核心策略；`pytest` 保证重构后行为不变。

**`output/`、`logs/`** — 产物与日志外置，不污染源码树。

---

## 架构与职责边界

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐     ┌──────────────┐
│   config/   │────▶│ DataService  │────▶│  Strategy   │────▶│   Backtest   │
│  YAML/.env  │     │  (src/data)  │     │ (仅 signal) │     │ (模拟+绩效)  │
└─────────────┘     └──────────────┘     └─────────────┘     └──────────────┘
                           │                    ▲
                     data/raw|processed          │ 不拉数、不下单
                     notebooks 探索              │
```

### 1. 策略与回测解耦

- **策略类**：实现 `BaseStrategy.generate_signals()`，只根据输入 DataFrame 生成 `signal` 列。  
- **回测引擎**：`BacktestEngine.run(price_data, signals)` 只负责撮合、资金曲线与收益统计。  

同一引擎可测 CTA、多因子等不同策略；同一策略也可换引擎做交叉验证。

```python
from src.strategy import CTA
from src.backtest import BacktestEngine

signals = CTA(fast_period=10, slow_period=30).generate_signals(ohlcv)
result = BacktestEngine().run(ohlcv, signals)
```

`run_with_strategy()` 仅为编排便捷，生产入口推荐在 `main.py` 中显式分步调用。

### 2. 数据服务层

策略与回测**不得**直接 `import akshare` / `tushare`。统一通过：

```python
from src.data import DataService

ohlcv = DataService().get_daily_ohlcv("000001", "2023-01-01", "2024-12-31")
```

更换数据源时只改 `fetcher.py`（或注入自定义 `DataFetcher`），策略代码零改动。

### 3. 统一策略接口

所有策略继承 `BaseStrategy`：

```python
class BaseStrategy(ABC):
    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame: ...
```

### 4. 模块公开 API（`__init__.py`）

优先简洁导入，内部文件调整时不影响调用方：

```python
from src.strategy import CTA, MultiFactorStrategy, BaseStrategy
from src.data import DataService, DataProcessor
from src.backtest import BacktestEngine
from src.risk import RiskManager
```

避免：`from src.strategy.cta import CTAStrategy`（仅在本包内部使用）。

### 5. 单元测试

| 测试文件 | 覆盖 |
|----------|------|
| `tests/test_processor.py` | 数据清洗 |
| `tests/test_strategy.py` | 策略信号 |
| `tests/test_backtest.py` | 回测引擎 |
| `tests/test_risk.py` | 风控规则 |

```bash
pytest tests/ -q
```

---

## 配置与敏感信息管理

**永远不要**将 API 密钥、数据库密码等敏感信息硬编码在代码或 Jupyter 单元格里。

### 分工原则

| 类型 | 存放位置 | 读取方式 | 提交 Git |
|------|----------|----------|----------|
| 敏感信息 | `config/.env` | `python-dotenv` → 环境变量 | ❌ |
| 非敏感参数 | `config/*.yaml` | `load_config()` | ✅ |
| 模板 | `config/.env.example` | 供成员复制填写 | ✅ |

- **`.env`**：如 `TUSHARE_TOKEN`、`JQDATA_USER`、`JQDATA_PASSWORD`、`DATABASE_URL`  
- **`strategy.yaml`**：如均线周期 `fast_period`、止损 `stop_loss_pct`、回测初始资金等 —— **调参只改 YAML，不改代码**

### 首次配置

```bash
# Windows
copy config\.env.example config\.env

# Linux / macOS
cp config/.env.example config/.env
```

编辑 `config/.env` 填入真实密钥。`.env` 已在 `.gitignore` 中（含 `config/.env`），避免意外推送。

### 代码中如何读取

```python
from src.utils import load_config, require_env

# 启动时加载 YAML + .env
cfg = load_config()
fast = cfg["strategy"]["cta"]["fast_period"]   # 来自 YAML

# 敏感项只从环境变量读（fetcher 内部已按此实现）
token = require_env("TUSHARE_TOKEN")
```

`DataFetcher` 在使用 `source="tushare"` 或 `source="jqdata"` 时会自动 `require_env`，未配置时给出明确报错，而不是在源码里写死密钥。

### 团队协作风味

1. 新成员：复制 `.env.example` → `.env`，本地填写，不向仓库提交。  
2. 新增敏感项：先更新 `.env.example` 占位说明，再在代码中用 `require_env("新变量名")` 读取。  
3. Code Review：拒绝任何包含真实 Token / 密码的 PR。

更多说明见 [config/README.md](config/README.md)。

---

## 环境安装

**Conda**

```bash
cd a_stock_quant_system
conda env create -f environment.yml
conda activate a_stock_quant
```

**pip**

```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
cp config\.env.example config\.env
```

## 快速开始

```bash
python main.py                        # 策略回测流水线
python scripts/collect_hs300_daily.py # 沪深300日线采集入库
pytest tests/ -q                      # 单元测试
jupyter lab notebooks/                # 研究笔记本
```

采集参数（日期、请求间隔 `request_delay_seconds`）在 `config/base.yaml` → `data.hs300_collector` 调整。

## 开发约定（贡献代码时请遵守）

1. **新策略**：继承 `BaseStrategy`，放在 `src/strategy/`，并在 `strategy/__init__.py` 导出。  
2. **新数据源**：扩展 `DataFetcher`，不修改策略文件。  
3. **Notebook**：可做快速试验；合并前将稳定逻辑迁入 `src/` 并补测试。  
4. **配置**：非敏感参数写入 `config/*.yaml`；API Key、密码只放 `config/.env`，用 `require_env()` 读取。  
5. **禁止**：硬编码密钥；在 `src/strategy/` 内调用行情 API；在 `src/backtest/` 内实现 alpha 逻辑。

---

## 免责声明

本项目仅供学习与研究，不构成任何投资建议。
