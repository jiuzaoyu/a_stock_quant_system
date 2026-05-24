# 脚本目录（`scripts/`）

存放**可执行的批处理任务**，与 `src/` 中可复用库代码分离：

| 脚本 | 说明 | 核心实现 |
|------|------|----------|
| `collect_hs300_daily.py` | 沪深300成分股日线采集入库 | `src/data/hs300_collector.py` |

## 运行方式

在**项目根目录**执行：

```bash
python scripts/collect_hs300_daily.py
```

参数（日期范围、请求间隔等）在 `config/base.yaml` 的 `data.hs300_collector` 中修改，无需改脚本。

## 与 `notebooks/` 的区别

- `notebooks/`：探索性实验（实验室）
- `scripts/`：可重复、可配置的数据管线（工厂入口）
- `src/data/`：采集与存储的具体实现（供脚本和后续策略读取）
