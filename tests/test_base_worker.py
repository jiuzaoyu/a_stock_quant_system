import json
import time
from threading import Thread

import fakeredis
import pytest

from src.workers.base_worker import BaseWorker


class TestBaseWorker:
    @pytest.fixture
    def redis_client(self):
        return fakeredis.FakeRedis(decode_responses=True)

    @pytest.fixture
    def worker(self, redis_client):
        return BaseWorker(
            redis_client,
            stream="cron:jobs:test_job",
            group="test_group",
            consumer="test_consumer_1",
        )

    def test_register_and_handle_message(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("test_job", handler)

        # Simulate a message arriving in the stream
        msg_data = {
            "job_id": "test_job:2026-01-01T00:00:00+00:00",
            "job_type": "test_job",
            "triggered_at": "2026-01-01T00:00:00+00:00",
            "timeout": "300",
            "max_retries": "2",
            "payload": json.dumps({"key": "value"}),
        }
        redis_client.xadd("cron:jobs:test_job", msg_data)

        # Process one message manually (not using the blocking loop)
        worker._process_one()

        assert len(handler_called) == 1
        received = handler_called[0]
        assert received["job_type"] == "test_job"
        assert received["timeout"] == "300"
        assert json.loads(received["payload"]) == {"key": "value"}

    def test_process_one_acks_message(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("test_job", handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        # Verify message was ACKed — PEL should be empty
        pending = redis_client.xpending("cron:jobs:test_job", "test_group")
        assert pending["pending"] == 0

    def test_unregistered_job_type_is_skipped(self, worker, redis_client):
        handler_called = []

        def handler(message):
            handler_called.append(message)

        worker.register("other_job", handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        assert len(handler_called) == 0

    def test_handler_exception_leaves_message_in_pending(self, worker, redis_client):
        def failing_handler(message):
            raise RuntimeError("handler error")

        worker.register("test_job", failing_handler)

        msg_data = {"job_id": "x", "job_type": "test_job", "triggered_at": "t",
                     "timeout": "0", "max_retries": "0", "payload": "{}"}
        msg_id = redis_client.xadd("cron:jobs:test_job", msg_data)

        worker._process_one()

        # Message NOT ACKed — stays in PEL
        pending = redis_client.xpending("cron:jobs:test_job", "test_group")
        assert pending["pending"] == 1
