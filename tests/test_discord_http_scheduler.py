import asyncio
import unittest
from types import SimpleNamespace

from cogs.shared.discord_http_scheduler import (
    DiscordRequestScheduler,
    install_discord_http_scheduler,
)


class DiscordRequestSchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_requests_are_started_in_fifo_order_with_bounded_concurrency(self):
        started = []
        active = 0
        max_active = 0
        release = asyncio.Event()

        async def request(route, **kwargs):
            nonlocal active, max_active
            started.append(route)
            active += 1
            max_active = max(max_active, active)
            await release.wait()
            active -= 1
            return route

        scheduler = DiscordRequestScheduler(
            request, requests_per_second=1000, max_concurrency=2
        )
        tasks = [asyncio.create_task(scheduler.request(index)) for index in range(5)]
        await asyncio.sleep(0.03)

        self.assertEqual(started, [0, 1])
        self.assertEqual(max_active, 2)
        release.set()
        self.assertEqual(await asyncio.gather(*tasks), list(range(5)))
        self.assertEqual(started, list(range(5)))
        await scheduler.close()

    async def test_cancelled_queue_entry_does_not_block_following_request(self):
        started = []
        release = asyncio.Event()

        async def request(route, **kwargs):
            started.append(route)
            if route == "first":
                await release.wait()
            return route

        scheduler = DiscordRequestScheduler(
            request, requests_per_second=1000, max_concurrency=1
        )
        first = asyncio.create_task(scheduler.request("first"))
        cancelled = asyncio.create_task(scheduler.request("cancelled"))
        last = asyncio.create_task(scheduler.request("last"))
        await asyncio.sleep(0.02)
        cancelled.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await cancelled

        release.set()
        self.assertEqual(await first, "first")
        self.assertEqual(await last, "last")
        self.assertEqual(started, ["first", "last"])
        await scheduler.close()

    async def test_cancelled_in_flight_request_returns_the_concurrency_lease(self):
        victim_started = asyncio.Event()
        hold_victim = asyncio.Event()

        async def request(route, **kwargs):
            if route == "victim":
                victim_started.set()
                await hold_victim.wait()
            return route

        scheduler = DiscordRequestScheduler(
            request, requests_per_second=1000, max_concurrency=1
        )
        victim = asyncio.create_task(scheduler.request("victim"))
        last = asyncio.create_task(scheduler.request("last"))
        await victim_started.wait()
        victim.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await victim
        self.assertEqual(await asyncio.wait_for(last, timeout=0.5), "last")
        await scheduler.close()

    async def test_install_is_idempotent_and_wraps_the_http_client(self):
        async def request(route, **kwargs):
            return route

        bot = SimpleNamespace(http=SimpleNamespace(request=request))
        scheduler = install_discord_http_scheduler(
            bot, requests_per_second=1000
        )

        self.assertIs(install_discord_http_scheduler(bot), scheduler)
        self.assertEqual(await bot.http.request("route"), "route")
        await scheduler.close()
    async def test_uniform_pacing_prevents_a_startup_burst(self):
        starts = []

        async def request(route, **kwargs):
            starts.append(asyncio.get_running_loop().time())
            return route

        scheduler = DiscordRequestScheduler(
            request, requests_per_second=20, max_concurrency=5
        )
        await asyncio.gather(*(scheduler.request(index) for index in range(3)))

        gaps = [later - earlier for earlier, later in zip(starts, starts[1:])]
        self.assertTrue(all(gap >= 0.04 for gap in gaps), gaps)
        await scheduler.close()


if __name__ == "__main__":
    unittest.main()