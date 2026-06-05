# A 股行情数据 API 文档

> 数据源: **mootdx (TCP)** + **腾讯财经 (HTTP)** — 均免费、无需 API Key、不封 IP

---

## 一、数据采集能力总览

| 类别 | 函数 | 数据源 | 说明 |
|------|------|--------|------|
| K 线 | `get_kline()` | mootdx | 日/周/月/分钟 K 线 |
| 实时报价 + 五档盘口 | `get_realtime_quotes()` | mootdx | 现价、买卖五档、成交量等 |
| 逐笔成交 | `get_transactions()` | mootdx | 每笔成交明细 (交易时段) |
| 财务快照 | `get_finance()` | mootdx | 37 字段季报数据 |
| 公司 F10 资料 | `get_f10()` | mootdx | 公司概况、财务分析、股东研究等 |
| 估值 + 市场指标 | `tencent_quote()` | 腾讯财经 | PE/PB/市值/换手率/涨跌停价 |
| 综合行情 | `quick_view()` | mootdx + 腾讯 | 一键获取完整行情 |

---

## 二、各接口详细说明

### 2.1 K 线数据 — `get_kline(code, category, offset)`

**数据源**: mootdx (TCP 7709)

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位股票代码，如 `"688017"` |
| `category` | int | 周期: `4`=日线, `5`=周线, `6`=月线, `7`=1分钟, `8`=5分钟, `9`=15分钟, `10`=30分钟, `11`=60分钟 |
| `offset` | int | 返回最近 N 根 K 线 |

**返回字段 (DataFrame)**:

| 字段 | 说明 |
|------|------|
| `open` | 开盘价 |
| `close` | 收盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `volume` | 成交量 |
| `amount` | 成交额 |
| `datetime` | 日期时间 |

**示例**:
```python
from market_data import get_kline
df = get_kline("688017", category=4, offset=10)  # 最近10根日线
```

---

### 2.2 实时报价 + 五档盘口 — `get_realtime_quotes(codes)`

**数据源**: mootdx (TCP 7709)

| 参数 | 类型 | 说明 |
|------|------|------|
| `codes` | list[str] | 股票代码列表，如 `["000001", "600519"]` |

**返回字段 (DataFrame)**:

| 字段 | 说明 |
|------|------|
| `market` | 市场标识 |
| `code` | 股票代码 |
| `price` | 最新价 |
| `last_close` | 昨收价 |
| `open` | 开盘价 |
| `high` | 最高价 |
| `low` | 最低价 |
| `vol` | 成交量 |
| `amount` | 成交额 |
| `s_vol` | 内盘/外盘 |
| `servertime` | 服务器时间 |
| `bid1` ~ `bid5` | 买一 ~ 买五 价格 |
| `bid_vol1` ~ `bid_vol5` | 买一 ~ 买五 挂单量 |
| `ask1` ~ `ask5` | 卖一 ~ 卖五 价格 |
| `ask_vol1` ~ `ask_vol5` | 卖一 ~ 卖五 挂单量 |
| `active1` | 活跃度 |

**示例**:
```python
from market_data import get_realtime_quotes
df = get_realtime_quotes(["000001", "600519", "300476"])
```

---

### 2.3 逐笔成交 — `get_transactions(code, date)`

**数据源**: mootdx (TCP 7709)

> 注意: 仅交易时段有数据，非交易时间返回空

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位股票代码 |
| `date` | str | 日期 `"YYYYMMDD"`，默认今天 |

**返回字段 (DataFrame)**:

| 字段 | 说明 |
|------|------|
| `time` | 成交时间 |
| `price` | 成交价 |
| `vol` | 成交量 |
| `num` | 成交笔数 |
| `buyorsell` | 方向: `0`=买, `1`=卖, `2`=中性 |

**示例**:
```python
from market_data import get_transactions
df = get_transactions("000001", date="20250603")
```

---

### 2.4 财务快照 — `get_finance(code)`

**数据源**: mootdx (TCP 7709)

**返回 37 个字段的季报数据 (Series)**:

| 字段 (拼音) | 中文含义 |
|-------------|----------|
| `meigujingzichan` | 每股净资产 |
| `meigushouyi` | 每股收益 |
| `jingzichanshouyilv` | 净资产收益率 |
| `jinglirun` | 净利润 |
| `zhuyingshouru` | 主营收入 |
| `yingyelirun` | 营业利润 |
| `touzishouyu` | 投资收益 |
| `liutongguben` | 流通股本 |
| `zongguben` | 总股本 |
| `jingzichan` | 净资产 |
| `zibengongjijin` | 资本公积金 |
| `weifenpeilirun` | 未分配利润 |
| `meigugongjijin` | 每股公积金 |
| `meiguweifenpei` | 每股未分配利润 |
| `gudongrenshu` | 股东人数 |
| `ipo_date` | 上市日期 |
| `updated_date` | 财报更新日 |
| ... | 等共 37 项 |

**示例**:
```python
from market_data import get_finance
fin = get_finance("000001")
```

---

### 2.5 公司 F10 资料 — `get_f10(code, category)`

**数据源**: mootdx (TCP 7709)

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位股票代码 |
| `category` | str | 资料类别 (见下表) |

**可查询的 F10 类别**:

| category 参数值 | 内容说明 |
|-----------------|----------|
| `"最新提示"` | 最新公告摘要、业绩预告 |
| `"公司概况"` | 公司基本信息、主营业务 |
| `"财务分析"` | 财务指标分析 |
| `"股东研究"` | 股东户数、十大股东 |
| `"股本结构"` | 股本变动、限售解禁 |
| `"资本运作"` | 增发、并购等 |
| `"业内点评"` | 券商研报点评 |
| `"行业分析"` | 行业对比分析 |
| `"公司大事"` | 重大事项时间线 |

**示例**:
```python
from market_data import get_f10
text = get_f10("000001", category="最新提示")
```

---

### 2.6 估值 + 市场指标 — `tencent_quote(codes)`

**数据源**: 腾讯财经 (HTTP, GBK 编码)

> 支持个股、指数、ETF 三类标的

| 参数 | 类型 | 说明 |
|------|------|------|
| `codes` | list[str] | 个股 `["000001","600519"]` / 指数 `["000001","000300","399006"]` / ETF `["510050","510300"]` |

**返回 dict `{code: {字段}}`**:

| 字段 | 说明 | 单位 |
|------|------|------|
| `name` | 股票名称 | — |
| `price` | 最新价 | 元 |
| `last_close` | 昨收 | 元 |
| `open` | 今开 | 元 |
| `high` | 最高 | 元 |
| `low` | 最低 | 元 |
| `change_amt` | 涨跌额 | 元 |
| `change_pct` | 涨跌幅 | % |
| `amount_wan` | 成交额 | 万元 |
| `turnover_pct` | 换手率 | % |
| `pe_ttm` | 市盈率 (TTM) | — |
| `pe_static` | 市盈率 (静态) | — |
| `pb` | 市净率 | — |
| `mcap_yi` | 总市值 | 亿元 |
| `float_mcap_yi` | 流通市值 | 亿元 |
| `amplitude_pct` | 振幅 | % |
| `limit_up` | 涨停价 | 元 |
| `limit_down` | 跌停价 | 元 |
| `vol_ratio` | 量比 | — |

**示例**:
```python
from market_data import tencent_quote
data = tencent_quote(["000001", "600519", "000300", "510050"])
for code, q in data.items():
    print(f"{q['name']}: PE={q['pe_ttm']} PB={q['pb']} 市值={q['mcap_yi']}亿")
```

---

### 2.7 综合行情 — `quick_view(code)`

**数据源**: mootdx + 腾讯财经 (双源合并)

> 一次调用同时获取盘口数据和估值数据

| 参数 | 类型 | 说明 |
|------|------|------|
| `code` | str | 6 位股票代码 |

**返回 dict**:

| 字段 | 说明 | 来源 |
|------|------|------|
| `code` | 股票代码 | — |
| `name` | 股票名称 | 腾讯 |
| `price` | 最新价 | 腾讯 |
| `open` / `high` / `low` | 开/高/低 | 腾讯 |
| `last_close` | 昨收 | 腾讯 |
| `change_pct` | 涨跌幅 | 腾讯 |
| `amount_wan` | 成交额 (万元) | 腾讯 |
| `turnover_pct` | 换手率 | 腾讯 |
| `vol_ratio` | 量比 | 腾讯 |
| `pe_ttm` | 市盈率 (TTM) | 腾讯 |
| `pb` | 市净率 | 腾讯 |
| `mcap_yi` | 总市值 (亿) | 腾讯 |
| `float_mcap_yi` | 流通市值 (亿) | 腾讯 |
| `limit_up` / `limit_down` | 涨跌停价 | 腾讯 |
| `bid1` | 买一价 | mootdx |
| `ask1` | 卖一价 | mootdx |

**示例**:
```python
from market_data import quick_view
info = quick_view("600519")
```

---

## 三、辅助函数

| 函数 | 说明 | 示例 |
|------|------|------|
| `normalize_code(raw)` | 归一化为纯 6 位代码 | `"SH688017"` → `"688017"` |
| `get_prefix(code)` | 代码 → 市场前缀 | `"688017"` → `"sh"`, `"000001"` → `"sz"` |

---

## 四、运行方式

```bash
# 全部 demo
python tests/mootdxAPI/market_data.py

# 单独模块
python tests/mootdxAPI/market_data.py --kline     # K 线
python tests/mootdxAPI/market_data.py --quote     # 实时盘口
python tests/mootdxAPI/market_data.py --tencent   # 腾讯估值
python tests/mootdxAPI/market_data.py --finance   # 财务快照
python tests/mootdxAPI/market_data.py --quick     # 综合行情
python tests/mootdxAPI/market_data.py --all       # 全部
```

## 五、依赖

```bash
pip install mootdx pandas
```

## 六、数据源覆盖对比

| 数据类型 | mootdx | 腾讯财经 |
|----------|:------:|:--------:|
| K线 (日/周/月/分钟) | ✅ | ❌ |
| 实时报价 | ✅ | ✅ |
| 五档盘口 (买卖价量) | ✅ | ❌ |
| 逐笔成交 | ✅ | ❌ |
| 财务快照 (37字段) | ✅ | ❌ |
| F10 公司资料 | ✅ | ❌ |
| PE / PB / 市值 | ❌ | ✅ |
| 换手率 / 量比 | ❌ | ✅ |
| 涨跌停价 | ❌ | ✅ |
| 指数行情 | ❌ | ✅ |
| ETF 行情 | ❌ | ✅ |
