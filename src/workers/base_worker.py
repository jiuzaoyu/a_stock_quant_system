import logging
from typing import Callable

from redis import Redis
from redis.exceptions import ResponseError

log = logging.getLogger(__name__)


class BaseWorker:
    def __init__(self, redis_client: Redis, stream: str, group: str, consumer: str):
        self._redis = redis_client
        self._stream = stream
        self._group = group
        self._consumer = consumer
        self._handlers: dict[str, Callable] = {}
        self._running = False
        self._init_group()

    def _init_group(self) -> None:
        try:
            self._redis.xgroup_create(self._stream, self._group, mkstream=True)
        except ResponseError:
            pass

    def register(self, job_type: str, handler: Callable[[dict[str, str]], None]) -> None:
        self._handlers[job_type] = handler

    def start(self, block_ms: int = 5000) -> None:
        self._running = True
        log.info("Worker %s listening on stream %s (group=%s)", self._consumer, self._stream, self._group)
        while self._running:
            try:
                self._process_one(block_ms)
            except Exception:
                log.exception("Worker loop error, continuing")

    def stop(self) -> None:
        self._running = False

    def _process_one(self, block_ms: int = 1000) -> None:
        messages = self._redis.xreadgroup(
            self._group, self._consumer,
            {self._stream: ">"}, block=block_ms, count=1,
        )
        if not messages:
            return

        for stream_name, msgs in messages:
            for msg_id, data in msgs:
                job_type = data.get("job_type", "")
                handler = self._handlers.get(job_type)
                if handler is None:
                    log.warning("No handler for job_type=%s on stream %s, acking anyway", job_type, self._stream)
                    self._redis.xack(self._stream, self._group, msg_id)
                    continue

                try:
                    handler(data)
                except Exception:
                    log.exception("Handler failed for job_type=%s msg=%s, message left in PEL", job_type, msg_id)
                    continue

                self._redis.xack(self._stream, self._group, msg_id)
