"""Process-wide pacing for authenticated Discord REST requests.

Pycord already handles Discord's per-route buckets and retries 429 responses. This
module adds a conservative limiter before Pycord's HTTP client so independent
cogs cannot collectively burst through Discord's global request budget.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
from collections.abc import Awaitable, Callable
from typing import Any


log = logging.getLogger(__name__)


class DiscordRequestScheduler:
    """FIFO request gate with uniform pacing and bounded in-flight work."""

    def __init__(
        self,
        request: Callable[..., Awaitable[Any]],
        *,
        requests_per_second: float = 40.0,
        max_concurrency: int = 8,
        max_queue_size: int = 5000,
        queue_warning_size: int = 250,
    ) -> None:
        if requests_per_second <= 0:
            raise ValueError("requests_per_second must be greater than zero")
        if max_concurrency <= 0:
            raise ValueError("max_concurrency must be greater than zero")
        if max_queue_size < 0:
            raise ValueError("max_queue_size cannot be negative")

        self._request = request
        self._interval = 1.0 / requests_per_second
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._queue: asyncio.PriorityQueue[tuple[int, int, asyncio.Future[None]]] = (
            asyncio.PriorityQueue(max_queue_size)
        )
        self._sequence = itertools.count()
        self._queue_warning_size = max(0, queue_warning_size)
        self._dispatcher: asyncio.Task[None] | None = None
        self._next_start = 0.0
        self._closed = False
        self._warning_emitted = False

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    def _ensure_dispatcher(self) -> None:
        if self._closed:
            raise RuntimeError("Discord request scheduler is closed")
        if self._dispatcher is None or self._dispatcher.done():
            self._dispatcher = asyncio.create_task(
                self._dispatch_loop(), name="discord-http-dispatcher"
            )

    async def request(
        self,
        route: Any,
        *,
        files: Any = None,
        form: Any = None,
        **kwargs: Any,
    ) -> Any:
        """Queue one logical Pycord request and execute it when a slot is granted."""
        self._ensure_dispatcher()
        loop = asyncio.get_running_loop()
        permit = loop.create_future()

        queued = False
        try:
            priority = self._request_priority(route)
            await self._queue.put((priority, next(self._sequence), permit))
            queued = True
            queue_size = self._queue.qsize()
            if self._queue_warning_size and queue_size >= self._queue_warning_size:
                if not self._warning_emitted:
                    log.warning(
                        "Discord HTTP queue backlog reached %s requests; applying backpressure.",
                        queue_size,
                    )
                    self._warning_emitted = True

            await permit
        except BaseException:
            if queued and permit.done() and not permit.cancelled():
                # The dispatcher granted a semaphore lease just as this caller
                # was cancelled, so no request coroutine exists to return it.
                self._semaphore.release()
            else:
                permit.cancel()
            raise

        try:
            return await self._request(route, files=files, form=form, **kwargs)
        finally:
            self._semaphore.release()

    @staticmethod
    def _request_priority(route: Any) -> int:
        """Prioritize interaction ACKs, which Discord requires within 3 seconds."""
        path = str(getattr(route, "path", "") or "")
        if path.startswith("/interactions/") and path.endswith("/callback"):
            return 0
        return 10

    async def _dispatch_loop(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            _, _, permit = await self._queue.get()
            acquired = False
            try:
                if permit.cancelled():
                    continue

                await self._semaphore.acquire()
                acquired = True
                if permit.cancelled():
                    self._semaphore.release()
                    acquired = False
                    continue

                delay = self._next_start - loop.time()
                if delay > 0:
                    await asyncio.sleep(delay)
                self._next_start = loop.time() + self._interval

                if not permit.done():
                    permit.set_result(None)
                    acquired = False

                if self._warning_emitted and self._queue.qsize() < self._queue_warning_size:
                    log.info("Discord HTTP queue backlog recovered to %s.", self._queue.qsize())
                    self._warning_emitted = False
            except asyncio.CancelledError:
                if not permit.done():
                    permit.cancel()
                raise
            finally:
                if acquired:
                    self._semaphore.release()
                self._queue.task_done()

    async def close(self) -> None:
        """Stop the dispatcher and wake callers that are still queued."""
        if self._closed:
            return
        self._closed = True
        if self._dispatcher is not None:
            self._dispatcher.cancel()
            await asyncio.gather(self._dispatcher, return_exceptions=True)

        while True:
            try:
                _, _, permit = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if not permit.done():
                permit.cancel()
            self._queue.task_done()


def install_discord_http_scheduler(
    bot: Any,
    *,
    requests_per_second: float = 40.0,
    max_concurrency: int = 8,
    max_queue_size: int = 5000,
    queue_warning_size: int = 250,
) -> DiscordRequestScheduler:
    """Install one scheduler on a bot. Repeated installation is idempotent."""
    existing = getattr(bot, "discord_http_scheduler", None)
    if isinstance(existing, DiscordRequestScheduler):
        return existing

    scheduler = DiscordRequestScheduler(
        bot.http.request,
        requests_per_second=requests_per_second,
        max_concurrency=max_concurrency,
        max_queue_size=max_queue_size,
        queue_warning_size=queue_warning_size,
    )
    bot.http.request = scheduler.request
    bot.discord_http_scheduler = scheduler
    return scheduler
