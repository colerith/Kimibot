import asyncio
import datetime
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.tickets.core import Tickets, IDS


class TicketOrderTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = Tickets.__new__(Tickets)
        self.cog.ticket_order_locks = {}
        self.cog.group_confirmations = {}
        self.cog.material_submission_times = {}
        self.guild = SimpleNamespace(id=1, fetch_channels=AsyncMock(),
                                     _state=SimpleNamespace(http=SimpleNamespace(bulk_channel_update=AsyncMock())))
        self.category_id = IDS["FIRST_REVIEW_CHANNEL_ID"]

    def channel(self, cid, position, state="待提交", timestamp=10, *, category=None, ticket=True):
        return SimpleNamespace(
            id=cid, position=position, name=state, _sorting_bucket=0,
            category_id=self.category_id if category is None else category,
            created_at=datetime.datetime.fromtimestamp(cid, tz=datetime.timezone.utc),
            topic=(f"工单ID: {cid} | 材料状态: {state} | 材料提交时间: {timestamp} | 过审时间: {timestamp}") if ticket else "",
            guild=self.guild,
        )

    def payload_ids(self):
        return [item["id"] for item in self.guild._state.http.bulk_channel_update.call_args.args[1]]

    async def test_whole_queue_sorted_without_moving_other_channels(self):
        channels = [self.channel(8, 0, "已过审", 20), self.channel(99, 1, ticket=False),
                    self.channel(3, 2), self.channel(5, 3, "已提交", 20),
                    self.channel(4, 4, "已提交", 10), self.channel(2, 5),
                    self.channel(7, 6, "已过审", 10), self.channel(100, 7, category=999)]
        self.guild.fetch_channels.return_value = channels
        await self.cog.synchronize_ticket_order(self.guild)
        self.assertEqual(self.payload_ids(), [4, 99, 5, 2, 3, 7, 8, 100])
        self.guild._state.http.bulk_channel_update.assert_awaited_once()

    async def test_correct_queue_does_not_send_a_write(self):
        self.guild.fetch_channels.return_value = [self.channel(1, 0, "已提交"), self.channel(2, 1), self.channel(3, 2, "已过审")]
        await self.cog.synchronize_ticket_order(self.guild)
        self.guild._state.http.bulk_channel_update.assert_not_awaited()

    async def test_approval_state_overrides_stale_submitted_topic(self):
        approved = self.channel(1, 0, "已提交")
        pending = self.channel(2, 1)
        self.cog.group_confirmations["1"] = {"approved_at": 50}
        self.guild.fetch_channels.return_value = [approved, pending]
        await self.cog.reposition_approved_ticket(approved)
        self.assertEqual(self.payload_ids(), [2, 1])

    async def test_concurrent_requests_fetch_again_after_previous_write(self):
        first, second = self.channel(2, 0), self.channel(1, 1)
        ordered_first, ordered_second = self.channel(1, 0), self.channel(2, 1)
        self.guild.fetch_channels.side_effect = [[first, second], [ordered_first, ordered_second]]
        await asyncio.gather(self.cog.synchronize_ticket_order(self.guild), self.cog.synchronize_ticket_order(self.guild))
        self.assertEqual(self.guild.fetch_channels.await_count, 2)
        self.guild._state.http.bulk_channel_update.assert_awaited_once()

    async def test_persisted_submission_time_controls_order_after_restart(self):
        self.guild.fetch_channels.return_value = [self.channel(1, 0, "已提交", 30), self.channel(2, 1, "已提交", 10)]
        await self.cog.synchronize_ticket_order(self.guild)
        self.assertEqual(self.payload_ids(), [2, 1])

    async def test_equal_timestamps_have_stable_id_tiebreaker(self):
        self.guild.fetch_channels.return_value = [self.channel(3, 0, "已过审"), self.channel(2, 1, "已过审")]
        await self.cog.synchronize_ticket_order(self.guild)
        self.assertEqual(self.payload_ids(), [2, 3])

    async def test_periodic_repair_deduplicates_guilds(self):
        self.cog.bot = SimpleNamespace(wait_until_ready=AsyncMock(), get_channel=lambda cid: SimpleNamespace(guild=self.guild))
        self.guild.fetch_channels.return_value = [self.channel(2, 0), self.channel(1, 1)]
        await Tickets.reconcile_ticket_order.coro(self.cog)
        self.guild.fetch_channels.assert_awaited_once()
        self.assertEqual(self.payload_ids(), [1, 2])
