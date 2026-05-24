"""从环境变量读取敏感配置（由 python-dotenv 从 config/.env 注入）。"""

import os
from typing import Optional


def get_env(key: str, default: Optional[str] = None) -> Optional[str]:
    """读取环境变量；未设置时返回 default。"""
    return os.getenv(key, default)


def require_env(key: str) -> str:
    """读取必填环境变量；缺失时抛出明确错误。"""
    value = os.getenv(key)
    if not value:
        raise RuntimeError(
            f"缺少环境变量 {key}。请复制 config/.env.example 为 config/.env 并填写。"
        )
    return value
