"""In-process background job runner (asyncio workers + durable job rows in the database).

Jobs are persisted before they are queued, so a crash or redeploy never loses work: on
startup ``recover()`` re-queues anything left ``queued``/``running``. Swapping this for
Celery/Arq/RQ only requires another implementation of ``enqueue``.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

Handler = Callable[[str], Awaitable[None]]


class JobRunner:
    def __init__(self, handler: Handler, *, workers: int = 2) -> None:
        self._handler = handler
        self._workers = max(1, workers)
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._tasks: list[asyncio.Task[None]] = []

    @property
    def running(self) -> bool:
        return bool(self._tasks)

    def start(self) -> None:
        if self._tasks:
            return
        self._tasks = [
            asyncio.create_task(self._worker(i), name=f"docmind-ingest-{i}")
            for i in range(self._workers)
        ]

    async def enqueue(self, job_id: str) -> None:
        await self._queue.put(job_id)

    async def recover(self, job_ids: list[str]) -> None:
        for job_id in job_ids:
            await self.enqueue(job_id)
        if job_ids:
            log.info("re-queued %d unfinished ingestion job(s)", len(job_ids))

    async def join(self) -> None:
        """Wait until every queued job has been processed (useful in tests and CLI)."""
        await self._queue.join()

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._tasks = []

    async def _worker(self, index: int) -> None:
        while True:
            job_id = await self._queue.get()
            try:
                await self._handler(job_id)
            except Exception:
                log.exception("worker %d: job %s failed unexpectedly", index, job_id)
            finally:
                self._queue.task_done()
