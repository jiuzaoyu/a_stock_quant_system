# nb-cron-scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a standalone, zero-business-logic cron scheduling service that reads job definitions from YAML and publishes trigger messages to Redis Streams.

**Architecture:** FastAPI + nb_cron provides the scheduling runtime and Web UI. A job registry parses `jobs/definitions.yaml` and programmatically registers cron jobs. When a job fires, `publisher.py` constructs a standard message and calls `XADD` on the configured Redis stream. The service knows nothing about message consumers.

**Tech Stack:** Python 3.11, FastAPI, nb-cron-nb, redis-py, PyYAML, uvicorn

---

## File Structure

```
e:\workspaces\nb-cron-scheduler/
├── config/
│   └── scheduler.yaml          # 调度服务自身配置
├── src/
│   ├── __init__.py
│   ├── app.py                  # FastAPI + nb_cron 启动入口 + 自定义端点
│   ├── config_loader.py        # YAML 配置加载
│   ├── job_registry.py         # 从 definitions.yaml 加载 job 并注册到 nb_cron
│   └── publisher.py            # Redis Streams 消息发布
├── jobs/
│   └── definitions.yaml        # 声明式 job 配置
├── tests/
│   ├── __init__.py
│   ├── test_config_loader.py
│   ├── test_publisher.py
│   └── test_job_registry.py
├── requirements.txt
├── .gitignore
└── README.md
```

---

### Task 1: Project Scaffolding

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\.gitignore`
- Create: `e:\workspaces\nb-cron-scheduler\requirements.txt`
- Create: `e:\workspaces\nb-cron-scheduler\config\scheduler.yaml`
- Create: `e:\workspaces\nb-cron-scheduler\jobs\definitions.yaml`
- Create: `e:\workspaces\nb-cron-scheduler\src\__init__.py`
- Create: `e:\workspaces\nb-cron-scheduler\tests\__init__.py`

- [ ] **Step 1: Create project directory structure**

```bash
mkdir -p e:/workspaces/nb-cron-scheduler/{config,src,jobs,tests}
```

- [ ] **Step 2: Write `.gitignore`**

```
__pycache__/
*.pyc
*.pyo
.env
.venv/
venv/
*.egg-info/
dist/
build/
.idea/
.vscode/
*.log
```

- [ ] **Step 3: Write `requirements.txt`**

```
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
nb-cron-nb[fastapi]>=0.1.0
redis>=5.0.0
pyyaml>=6.0
pytest>=8.0.0
fakeredis[lua]>=2.20.0
```

- [ ] **Step 4: Write `src/__init__.py`** (empty file)

```python
```

- [ ] **Step 5: Write `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 6: Write `config/scheduler.yaml`**

```yaml
server:
  host: "127.0.0.1"
  port: 8080

redis:
  host: "127.0.0.1"
  port: 6379
  db: 0
  stream_prefix: "cron:jobs"

scheduler:
  timezone: "Asia/Shanghai"
  tick_seconds: 1.0
  misfire_grace_seconds: 60
```

- [ ] **Step 7: Write `jobs/definitions.yaml`**

```yaml
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

- [ ] **Step 8: Install dependencies**

```bash
cd e:/workspaces/nb-cron-scheduler && pip install -r requirements.txt
```

- [ ] **Step 9: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git init && git add -A && git commit -m "feat: scaffold nb-cron-scheduler project"
```

---

### Task 2: Config Loader

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\src\config_loader.py`
- Create: `e:\workspaces\nb-cron-scheduler\tests\test_config_loader.py`

- [ ] **Step 1: Write the failing test**

```python
import tempfile
from pathlib import Path
from src.config_loader import load_scheduler_config, load_job_definitions


def test_load_scheduler_config():
    yaml_content = """
server:
  host: "0.0.0.0"
  port: 9090
redis:
  host: "10.0.0.1"
  port: 6380
  db: 1
  stream_prefix: "test:jobs"
scheduler:
  timezone: "UTC"
  tick_seconds: 2.0
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        cfg = load_scheduler_config(tmp_path)
        assert cfg["server"]["host"] == "0.0.0.0"
        assert cfg["server"]["port"] == 9090
        assert cfg["redis"]["host"] == "10.0.0.1"
        assert cfg["redis"]["stream_prefix"] == "test:jobs"
        assert cfg["scheduler"]["timezone"] == "UTC"
    finally:
        Path(tmp_path).unlink()


def test_load_job_definitions():
    yaml_content = """
jobs:
  - name: test_job
    cron: "*/5 * * * *"
    stream: "test:jobs:demo"
    payload:
      key: value
    timeout: 60
    max_retries: 1
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        tmp_path = f.name

    try:
        jobs = load_job_definitions(tmp_path)
        assert len(jobs) == 1
        assert jobs[0]["name"] == "test_job"
        assert jobs[0]["cron"] == "*/5 * * * *"
        assert jobs[0]["stream"] == "test:jobs:demo"
        assert jobs[0]["payload"] == {"key": "value"}
    finally:
        Path(tmp_path).unlink()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_config_loader.py -v
```
Expected: FAIL (ModuleNotFoundError or ImportError)

- [ ] **Step 3: Write `src/config_loader.py`**

```python
from pathlib import Path
from typing import Any

import yaml


def load_scheduler_config(config_path: str) -> dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_job_definitions(definitions_path: str) -> list[dict[str, Any]]:
    with open(definitions_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("jobs", [])
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_config_loader.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add src/config_loader.py tests/test_config_loader.py && git commit -m "feat: add config loader for scheduler and job definitions"
```

---

### Task 3: Redis Publisher

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\src\publisher.py`
- Create: `e:\workspaces\nb-cron-scheduler\tests\test_publisher.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from datetime import datetime, timezone, timedelta

import pytest
from redis import Redis

from src.publisher import MessagePublisher, build_message


class TestBuildMessage:
    def test_build_message_fields(self):
        job_def = {
            "name": "fund_incremental",
            "timeout": 600,
            "max_retries": 3,
            "payload": {"job_type": "fund_incremental"},
        }
        msg = build_message(job_def)

        assert msg["job_type"] == "fund_incremental"
        assert msg["timeout"] == 600
        assert msg["max_retries"] == 3
        assert msg["payload"] == {"job_type": "fund_incremental"}
        assert msg["job_id"].startswith("fund_incremental:")
        # ISO8601 timestamp
        datetime.fromisoformat(msg["triggered_at"])
        datetime.fromisoformat(msg["job_id"].split(":", 1)[1])

    def test_build_message_timestamps_are_utc(self):
        job_def = {
            "name": "test_job",
            "timeout": 60,
            "max_retries": 1,
            "payload": {},
        }
        before = datetime.now(timezone.utc)
        msg = build_message(job_def)
        after = datetime.now(timezone.utc)

        triggered = datetime.fromisoformat(msg["triggered_at"])
        assert before - timedelta(seconds=1) <= triggered <= after + timedelta(seconds=1)


class TestMessagePublisher:
    @pytest.fixture
    def redis_client(self):
        import fakeredis
        return fakeredis.FakeRedis()

    def test_publish_adds_message_to_stream(self, redis_client):
        publisher = MessagePublisher(redis_client)
        job_def = {
            "name": "test_job",
            "stream": "cron:jobs:test_job",
            "timeout": 60,
            "max_retries": 1,
            "payload": {"job_type": "test_job"},
        }
        msg_id = publisher.publish(job_def)

        assert msg_id is not None
        # Verify message is in the stream
        messages = redis_client.xrange("cron:jobs:test_job", "-", "+")
        assert len(messages) == 1
        stream_msg_id, stream_data = messages[0]
        assert stream_msg_id == msg_id.encode() if isinstance(msg_id, str) else msg_id
        # fakeredis returns bytes keys
        data = {k.decode() if isinstance(k, bytes) else k: v.decode() if isinstance(v, bytes) else v
                for k, v in stream_data.items()}
        assert data["job_type"] == "test_job"
        parsed = json.loads(data["payload"])
        assert parsed == {"job_type": "test_job"}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_publisher.py -v
```
Expected: FAIL (cannot import)

- [ ] **Step 3: Write `src/publisher.py`**

```python
import json
from datetime import datetime, timezone
from typing import Any

from redis import Redis


def build_message(job_def: dict[str, Any]) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    job_name = job_def["name"]
    return {
        "job_id": f"{job_name}:{now.isoformat()}",
        "job_type": job_def.get("payload", {}).get("job_type", job_name),
        "triggered_at": now.isoformat(),
        "timeout": job_def.get("timeout", 300),
        "max_retries": job_def.get("max_retries", 0),
        "payload": json.dumps(job_def.get("payload", {})),
    }


class MessagePublisher:
    def __init__(self, redis_client: Redis):
        self._redis = redis_client

    def publish(self, job_def: dict[str, Any]) -> str:
        message = build_message(job_def)
        stream = job_def["stream"]
        msg_id = self._redis.xadd(stream, message, maxlen=10000)
        return msg_id
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_publisher.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add src/publisher.py tests/test_publisher.py && git commit -m "feat: add Redis Streams message publisher"
```

---

### Task 4: Job Registry

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\src\job_registry.py`
- Create: `e:\workspaces\nb-cron-scheduler\tests\test_job_registry.py`

- [ ] **Step 1: Write the failing test**

```python
import json
from unittest.mock import MagicMock, call

import pytest

from src.job_registry import register_jobs
from src.publisher import build_message


class TestRegisterJobs:
    @pytest.fixture
    def mock_cron(self):
        cron = MagicMock()
        return cron

    @pytest.fixture
    def mock_publisher(self):
        publisher = MagicMock()
        return publisher

    @pytest.fixture
    def sample_jobs(self):
        return [
            {
                "name": "test_job_1",
                "cron": "*/5 * * * *",
                "stream": "cron:jobs:test_1",
                "payload": {"job_type": "test_1"},
                "timeout": 60,
                "max_retries": 1,
            },
            {
                "name": "test_job_2",
                "cron": "0 9 * * 1-5",
                "stream": "cron:jobs:test_2",
                "payload": {"job_type": "test_2"},
                "timeout": 300,
                "max_retries": 0,
            },
        ]

    def test_register_jobs_calls_add_job_for_each(self, mock_cron, mock_publisher, sample_jobs):
        register_jobs(mock_cron, mock_publisher, sample_jobs)

        assert mock_cron.add_job.call_count == 2

        # Verify first job registration
        first_call_args = mock_cron.add_job.call_args_list[0]
        assert first_call_args[1]["job_id"] == "test_job_1"
        assert first_call_args[1]["expression"] == "*/5 * * * *"
        assert first_call_args[1]["name"] == "test_job_1"

        # Verify second job registration
        second_call_args = mock_cron.add_job.call_args_list[1]
        assert second_call_args[1]["job_id"] == "test_job_2"
        assert second_call_args[1]["expression"] == "0 9 * * 1-5"

    def test_register_jobs_trigger_calls_publish(self, mock_cron, mock_publisher, sample_jobs):
        register_jobs(mock_cron, mock_publisher, sample_jobs)

        # Extract the function that was registered for the first job and call it
        func = mock_cron.add_job.call_args_list[0][0][0]
        func()

        mock_publisher.publish.assert_called_once_with(sample_jobs[0])

    def test_register_jobs_empty_list(self, mock_cron, mock_publisher):
        register_jobs(mock_cron, mock_publisher, [])
        mock_cron.add_job.assert_not_called()
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_job_registry.py -v
```
Expected: FAIL (ImportError)

- [ ] **Step 3: Write `src/job_registry.py`**

```python
from typing import Any

from src.publisher import MessagePublisher


def register_jobs(cron, publisher: MessagePublisher, job_defs: list[dict[str, Any]]) -> None:
    for job_def in job_defs:
        _register_one(cron, publisher, job_def)


def _register_one(cron, publisher: MessagePublisher, job_def: dict[str, Any]) -> None:
    job_name = job_def["name"]
    cron_expression = job_def["cron"]

    def _fire():
        publisher.publish(job_def)

    cron.add_job(
        _fire,
        cron_expression,
        trigger="cron",
        job_id=job_name,
        name=job_name,
    )
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_job_registry.py -v
```
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add src/job_registry.py tests/test_job_registry.py && git commit -m "feat: add job registry that wires YAML definitions to nb_cron"
```

---

### Task 5: FastAPI App Entry Point

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\src\app.py`

- [ ] **Step 1: Write `src/app.py`**

```python
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI
from nb_cron import NbCron
from nb_cron.web import get_fastapi_app
from redis import Redis

from src.config_loader import load_job_definitions, load_scheduler_config
from src.job_registry import register_jobs
from src.publisher import MessagePublisher

ROOT = Path(__file__).resolve().parents[1]


def create_app(config_path: str | None = None, job_defs_path: str | None = None):
    config_path = config_path or str(ROOT / "config" / "scheduler.yaml")
    job_defs_path = job_defs_path or str(ROOT / "jobs" / "definitions.yaml")

    cfg = load_scheduler_config(config_path)
    job_defs = load_job_definitions(job_defs_path)

    redis_cfg = cfg["redis"]
    redis_client = Redis(
        host=redis_cfg["host"],
        port=redis_cfg["port"],
        db=redis_cfg["db"],
        decode_responses=True,
    )
    publisher = MessagePublisher(redis_client)

    sched_cfg = cfg["scheduler"]
    cron = NbCron(
        "nb-cron-scheduler",
        tick_seconds=sched_cfg.get("tick_seconds", 1.0),
        misfire_grace_seconds=sched_cfg.get("misfire_grace_seconds", 60),
        tz=sched_cfg.get("timezone", "Asia/Shanghai"),
    )

    register_jobs(cron, publisher, job_defs)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        cron.start()
        yield
        cron.stop()

    app = get_fastapi_app(cron, title="nb-cron-scheduler", lifespan=lifespan)

    @app.get("/health")
    def health():
        return {"status": "ok", "jobs": len(job_defs)}

    return app, cfg


def main():
    app, cfg = create_app()
    server_cfg = cfg["server"]

    uvicorn.run(
        app,
        host=server_cfg["host"],
        port=server_cfg["port"],
        log_level="info",
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify app imports work**

```bash
cd e:/workspaces/nb-cron-scheduler && python -c "from src.app import create_app; print('Import OK')"
```
Expected: `Import OK`

- [ ] **Step 3: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add src/app.py && git commit -m "feat: add FastAPI entry point with nb_cron lifecycle"
```

---

### Task 6: Integration Test

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\tests\test_integration.py`

- [ ] **Step 1: Write integration test**

```python
import json
import tempfile
from pathlib import Path

import fakeredis
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def redis_client():
    return fakeredis.FakeRedis(decode_responses=True)


@pytest.fixture
def app_with_fake_redis(redis_client, monkeypatch):
    from redis import Redis

    import src.app as app_module

    # Patch Redis to return fake client
    def mock_redis(*args, **kwargs):
        return redis_client

    monkeypatch.setattr(app_module, "Redis", mock_redis)

    from src.app import create_app

    app, _ = create_app()
    return app


class TestHealthEndpoint:
    def test_health_returns_ok(self, app_with_fake_redis):
        client = TestClient(app_with_fake_redis)
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "jobs" in data


class TestJobExecution:
    def test_manual_trigger_publishes_to_stream(self, app_with_fake_redis, redis_client):
        from src.publisher import MessagePublisher

        publisher = MessagePublisher(redis_client)

        job_def = {
            "name": "integration_test_job",
            "stream": "cron:jobs:integration_test",
            "timeout": 60,
            "max_retries": 1,
            "payload": {"job_type": "integration_test"},
        }

        msg_id = publisher.publish(job_def)
        assert msg_id is not None

        messages = redis_client.xrange("cron:jobs:integration_test", "-", "+")
        assert len(messages) == 1

        _, data = messages[0]
        assert data["job_type"] == "integration_test"
        assert data["timeout"] == "60"
        assert json.loads(data["payload"]) == {"job_type": "integration_test"}
```

- [ ] **Step 2: Run integration tests**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/test_integration.py -v
```
Expected: PASS (2 tests)

- [ ] **Step 3: Run all tests**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/ -v
```
Expected: All tests pass (10 tests)

- [ ] **Step 4: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add tests/test_integration.py && git commit -m "test: add integration tests for health endpoint and publisher"
```

---

### Task 7: README

**Files:**
- Create: `e:\workspaces\nb-cron-scheduler\README.md`

- [ ] **Step 1: Write `README.md`**

````markdown
# nb-cron-scheduler

通用定时任务调度服务 — 按 cron 表达式触发，往 Redis Streams 发布消息。

零业务逻辑。不关心谁在消费、消费结果如何。

## 快速开始

```bash
pip install -r requirements.txt
python src/app.py
```

服务启动后：
- Web UI: http://127.0.0.1:8080/nb_cron/ui/
- Health: http://127.0.0.1:8080/health

## 添加 Job

编辑 `jobs/definitions.yaml`：

```yaml
jobs:
  - name: my_job
    cron: "0 9 * * 1-5"
    stream: "cron:jobs:my_job"
    payload:
      job_type: "my_job"
    timeout: 300
    max_retries: 3
```

重启服务即生效。

## 消息格式

每次触发，向对应 Redis Stream 发送：

```json
{
  "job_id": "my_job:2026-05-29T09:00:00+00:00",
  "job_type": "my_job",
  "triggered_at": "2026-05-29T09:00:00+00:00",
  "timeout": 300,
  "max_retries": 3,
  "payload": "{\"job_type\": \"my_job\"}"
}
```

## 配置

`config/scheduler.yaml`：

```yaml
server:
  host: "127.0.0.1"
  port: 8080

redis:
  host: "127.0.0.1"
  port: 6379
  db: 0
  stream_prefix: "cron:jobs"

scheduler:
  timezone: "Asia/Shanghai"
```

## 消费者接入

业务项目作为 Redis Streams Consumer Group 消费消息：

```python
from redis import Redis

r = Redis(decode_responses=True)

# 创建 Consumer Group（幂等）
try:
    r.xgroup_create("cron:jobs:my_job", "my_group", mkstream=True)
except Exception:
    pass

# 消费循环
while True:
    messages = r.xreadgroup("my_group", "consumer_1",
                            {"cron:jobs:my_job": ">"}, block=5000, count=1)
    for stream, msgs in messages:
        for msg_id, data in msgs:
            handle_job(data)
            r.xack("cron:jobs:my_job", "my_group", msg_id)
```
````

- [ ] **Step 2: Commit**

```bash
cd e:/workspaces/nb-cron-scheduler && git add README.md && git commit -m "docs: add README with quickstart and consumer guide"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
cd e:/workspaces/nb-cron-scheduler && python -m pytest tests/ -v
```
Expected: All tests pass

- [ ] **Start the service (requires real Redis)**

```bash
cd e:/workspaces/nb-cron-scheduler && python src/app.py
```
Expected: Service starts, Web UI accessible at http://127.0.0.1:8080/nb_cron/ui/
