import asyncio
import unittest
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from cogs.tickets.core import Tickets, build_ticket_channel_name
from cogs.tickets.views import ArchiveRequestView
from cogs.tickets import core


class GroupConfirmationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.cog = Tickets.__new__(Tickets)
        self.cog.bot = SimpleNamespace()
        self.cog.group_confirmation_locks = {}
        self.cog.ticket_order_locks = {}
        self.cog.save_group_confirmations = Mock()
        self.cog.ensure_ticket_creator_access = AsyncMock(return_value=None)
        self.channel = SimpleNamespace(id=12)
        self.cog.group_confirmations = {"12": {
            "approved_at": 100, "deadline": core.discord.utils.utcnow().timestamp() + 1800,
            "status": "待确认", "message_id": 90,
        }}

    async def test_choices_appear_in_archive(self):
        for choice in ("已加群", "不加群"):
            self.setUp()
            with patch.object(core, "execute_archive", new=AsyncMock(return_value=True)) as archive:
                self.assertTrue(await self.cog.finish_group_confirmation(self.channel, choice))
                self.assertEqual(archive.call_args.kwargs["group_status"], choice)
                self.assertFalse(archive.call_args.kwargs["automatic"])
                self.assertNotIn("12", self.cog.group_confirmations)

    async def test_deadline_wins_over_late_click(self):
        self.cog.group_confirmations["12"]["deadline"] = 1
        with patch.object(core, "execute_archive", new=AsyncMock(return_value=True)) as archive:
            await self.cog.finish_group_confirmation(self.channel, "已加群")
            self.assertEqual(archive.call_args.kwargs["group_status"], "超时未确认")
            self.assertTrue(archive.call_args.kwargs["automatic"])

    async def test_timer_does_not_archive_early(self):
        with patch.object(core, "execute_archive", new=AsyncMock()) as archive:
            self.assertFalse(await self.cog.finish_group_confirmation(self.channel))
            archive.assert_not_awaited()

    async def test_concurrent_clicks_archive_once(self):
        with patch.object(core, "execute_archive", new=AsyncMock(return_value=True)) as archive:
            await asyncio.gather(
                self.cog.finish_group_confirmation(self.channel, "已加群"),
                self.cog.finish_group_confirmation(self.channel, "不加群"),
            )
            archive.assert_awaited_once()

    async def test_failed_archive_keeps_first_choice_for_retry(self):
        with patch.object(core, "execute_archive", new=AsyncMock(side_effect=[False, True])) as archive:
            await self.cog.finish_group_confirmation(self.channel, "已加群")
            self.assertEqual(self.cog.group_confirmations["12"]["status"], "已加群")
            await self.cog.finish_group_confirmation(self.channel, "不加群")
            self.assertEqual(archive.call_args.kwargs["group_status"], "已加群")

    async def test_other_user_cannot_confirm(self):
        interaction = SimpleNamespace(
            channel=SimpleNamespace(topic="创建者ID: 123"), user=SimpleNamespace(id=456),
            response=SimpleNamespace(send_message=AsyncMock()),
        )
        await ArchiveRequestView().process(interaction, "已加群")
        interaction.response.send_message.assert_awaited_once()

    async def test_approval_sends_qr_and_keeps_ticket_open(self):
        self.cog.group_confirmations = {}
        self.cog.reposition_approved_ticket = AsyncMock()
        channel = SimpleNamespace(
            id=12, topic="工单ID: 123 | 创建者ID: 42 | 创建者: test | 测试模式: 是",
            edit=AsyncMock(), send=AsyncMock(return_value=SimpleNamespace(id=90)),
        )
        channel.edit.return_value = channel
        interaction = SimpleNamespace(channel=channel, guild=SimpleNamespace(get_member=lambda uid: None),
                                      followup=SimpleNamespace(send=AsyncMock()))
        with patch.object(core, "execute_archive", new=AsyncMock()) as archive:
            self.assertTrue(await self.cog._approve_ticket_logic_unlocked(interaction))
            archive.assert_not_awaited()
        self.assertFalse(self.cog.ensure_ticket_creator_access.call_args.kwargs["allow_upload"])
        state = self.cog.group_confirmations["12"]
        self.assertEqual(state["deadline"] - state["approved_at"], 1800)
        self.assertEqual(channel.send.call_args.kwargs["embed"].image.url,
                         "https://i.postimg.cc/sxh3MQkh/2tytko.png")
        self.assertEqual([b.label for b in channel.send.call_args.kwargs["view"].children],
                         ["我已经加群啦", "暂时不加群"])
        self.assertTrue(channel.edit.call_args.kwargs["name"].startswith("已过审-"))
        original_deadline = state["deadline"]
        await self.cog._approve_ticket_logic_unlocked(interaction)
        self.assertEqual(state["deadline"], original_deadline)
        channel.send.assert_awaited_once()

    async def test_reloaded_deadline_is_not_extended(self):
        self.cog.group_confirmations["12"]["deadline"] = 1
        self.cog.bot.get_channel = lambda channel_id: self.channel
        self.cog.bot.wait_until_ready = AsyncMock()
        with patch.object(core, "execute_archive", new=AsyncMock(return_value=True)) as archive:
            await Tickets.check_group_confirmations.coro(self.cog)
            self.assertEqual(archive.call_args.kwargs["group_status"], "超时未确认")

    def test_test_ticket_also_starts_with_approved_prefix(self):
        self.assertTrue(build_ticket_channel_name({"测试模式": "是"}, "已过审").startswith("已过审-"))


class TicketExtensionLoadTests(unittest.IsolatedAsyncioTestCase):
    async def test_extension_loads_with_real_storage_and_restores_confirmation(self):
        from cogs.shared import sqlite_store
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "test.sqlite3")
            with patch.object(sqlite_store, "APP_STATE_DB_FILE", database), \
                 patch.object(sqlite_store, "_SCHEMA_READY", False), \
                 patch.object(core, "AUDIT_SCHEDULE_FILE", str(Path(directory) / "missing.json")):
                bot = core.discord.Bot(intents=core.discord.Intents.none())
                try:
                    bot.load_extension("cogs.tickets")
                    cog = bot.get_cog("Tickets")
                    self.assertIsNotNone(cog)
                    self.assertEqual(cog.group_confirmations, {})
                    state = {"approved_at": 100, "deadline": 1900, "status": "待确认"}
                    cog.group_confirmations["12"] = state
                    cog.save_group_confirmations()
                    bot.unload_extension("cogs.tickets")
                    bot.load_extension("cogs.tickets")
                    self.assertEqual(bot.get_cog("Tickets").group_confirmations["12"], state)
                finally:
                    if bot.get_cog("Tickets"):
                        bot.unload_extension("cogs.tickets")
