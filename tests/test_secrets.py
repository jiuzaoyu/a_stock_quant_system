import os

import pytest

from src.utils.config import load_dotenv_file
from src.utils.secrets import get_env, require_env


def test_require_env_missing(monkeypatch):
    monkeypatch.delenv("TEST_MISSING_KEY", raising=False)
    with pytest.raises(RuntimeError, match="缺少环境变量"):
        require_env("TEST_MISSING_KEY")


def test_get_env_default(monkeypatch):
    monkeypatch.delenv("TEST_OPTIONAL_KEY", raising=False)
    assert get_env("TEST_OPTIONAL_KEY", "fallback") == "fallback"


def test_load_dotenv_file_no_crash(tmp_path):
    load_dotenv_file(tmp_path)
