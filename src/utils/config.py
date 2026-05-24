"""加载配置：非敏感参数用 YAML，敏感信息用 .env + 环境变量。"""

from pathlib import Path
from typing import Any, Dict

import yaml
from dotenv import load_dotenv

from .secrets import get_env


def load_yaml(path: Path) -> Dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_dotenv_file(config_dir: Path) -> None:
    """加载 config/.env（若存在）。切勿将 .env 提交到 Git。"""
    env_path = config_dir / ".env"
    load_dotenv(env_path, override=False)


def load_config(config_dir: Path | None = None) -> Dict[str, Any]:
    """
    加载完整配置。

    - config/base.yaml、strategy.yaml：非敏感参数（均线周期、止损比例等）
    - config/.env：API Key、数据库密码等（通过环境变量读取）
    """
    root = Path(__file__).resolve().parents[2]
    cfg_dir = config_dir or root / "config"

    load_dotenv_file(cfg_dir)

    return {
        "base": load_yaml(cfg_dir / "base.yaml"),
        "strategy": load_yaml(cfg_dir / "strategy.yaml"),
        "env": {
            "tushare_token": get_env("TUSHARE_TOKEN"),
            "jqdata_user": get_env("JQDATA_USER"),
            "jqdata_password": get_env("JQDATA_PASSWORD"),
            "database_url": get_env("DATABASE_URL"),
        },
    }
