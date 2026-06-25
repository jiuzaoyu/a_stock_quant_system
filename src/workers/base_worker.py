import logging
import threading
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

    def _recover_pending(self) -> int:
        """通过 XAUTOCLAIM 回收闲置超过 10 秒的 PEL 滞留消息。"""
        claimed = 0
        start_id = "0-0"
        while True:
            try:
                result = self._redis.xautoclaim(
                    self._stream, self._group, self._consumer,
                    min_idle_time=10000, start_id=start_id, count=10,
                )
            except ResponseError:
                break

            if not result:
                break

            next_start_id, messages = result
            for msg_id, data in messages:
                job_type = data.get("job_type", "")
                handler = self._handlers.get(job_type)
                if handler is None:
                    log.warning("PEL 回收: 无 handler job_type=%s, 直接 ACK", job_type)
                    self._redis.xack(self._stream, self._group, msg_id)
                    continue
                try:
                    handler(data)
                except Exception:
                    log.exception("PEL 回收: handler 失败 job_type=%s, 放回 PEL", job_type)
                    continue
                self._redis.xack(self._stream, self._group, msg_id)
                claimed += 1

            if next_start_id == "0-0" or not messages:
                break
            start_id = next_start_id

        return claimed

    def register(self, job_type: str, handler: Callable[[dict[str, str]], None]) -> None:
        self._handlers[job_type] = handler

    def start(self, block_ms: int = 5000) -> None:
        self._running = True
        log.info("Worker %s 开始监听 Stream %s (group=%s)", self._consumer, self._stream, self._group)

        # 启动时回收 PEL 中滞留的未确认消息（上次异常退出遗留）
        pending = self._recover_pending()
        if pending:
            log.info("启动时回收 PEL 滞留消息: %d 条", pending)

        loop_count = 0
        while self._running:
            try:
                self._process_one(block_ms)
                loop_count += 1
                # 每约 30 秒回收一次 PEL 滞留消息
                if loop_count % 6 == 0:
                    recovered = self._recover_pending()
                    if recovered:
                        log.info("PEL 定期回收: %d 条", recovered)
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


def start_workers(workers: list["BaseWorker"]) -> None:
    """在新线程中启动所有 worker（每个 worker.start() 是阻塞循环）。"""
    threads = []
    for w in workers:
        t = threading.Thread(target=w.start, daemon=True, name=w._consumer)
        t.start()
        threads.append(t)
        log.info("Worker 线程已启动: %s", w._consumer)

    for t in threads:
        t.join()
