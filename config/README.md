# 配置说明

| 文件 | 内容 | 是否提交 Git |
|------|------|----------------|
| `base.yaml` | 路径、日志级别等非敏感项 | ✅ |
| `strategy.yaml` | 均线周期、止损比例、回测资金等 | ✅ |
| `.env.example` | 敏感项占位模板 | ✅ |
| `.env` | 真实 API Key、密码 | ❌ |

应用启动时由 `src.utils.config.load_config()` 自动加载 YAML 与 `.env`。
