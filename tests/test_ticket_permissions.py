import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
from cogs.tickets.core import Tickets, IDS


class TicketPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.member = SimpleNamespace(id=42, mention="<@42>")
        self.overwrite = discord.PermissionOverwrite(
            view_channel=False, read_message_history=False, send_messages=True,
            attach_files=True, manage_messages=False,
        )
        self.guild = SimpleNamespace(
            get_member=lambda uid: self.member,
            fetch_member=AsyncMock(return_value=self.member),
        )
        self.channel = SimpleNamespace(
            id=12, name="已提交-123-test", guild=self.guild,
            topic="工单ID: 123 | 创建者ID: 42 | 上传状态: 进行中 | 上传开始: 1 | 上传截止: 2",
            overwrites_for=lambda member: self.overwrite,
            set_permissions=AsyncMock(), edit=AsyncMock(), send=AsyncMock(),
        )
        self.category = SimpleNamespace(text_channels=[self.channel])
        self.cog = Tickets.__new__(Tickets)
        self.cog.group_confirmations = {}
        self.cog.material_submission_times = {}
        self.cog.bot = SimpleNamespace(
            wait_until_ready=AsyncMock(),
            get_channel=lambda cid: self.category if cid == IDS["FIRST_REVIEW_CHANNEL_ID"] else None,
        )
        self.cog.mark_material_submitted = AsyncMock()

    def assert_read_only(self):
        overwrite = self.channel.set_permissions.call_args.kwargs["overwrite"]
        self.assertTrue(overwrite.view_channel)
        self.assertTrue(overwrite.read_message_history)
        self.assertFalse(overwrite.send_messages)
        self.assertFalse(overwrite.attach_files)
        self.assertFalse(overwrite.manage_messages)
        self.assertIs(self.channel.set_permissions.call_args.args[0], self.member)

    async def test_read_only_restores_view_and_history_preserving_other_permissions(self):
        await self.cog.ensure_ticket_creator_access(self.channel, {"创建者ID": "42"}, allow_upload=False)
        self.assert_read_only()

    async def test_cache_miss_fetches_member_before_restoring_access(self):
        self.guild.get_member = lambda uid: None
        await self.cog.ensure_ticket_creator_access(self.channel, {"创建者ID": "42"}, allow_upload=False)
        self.guild.fetch_member.assert_awaited_once_with(42)
        self.assert_read_only()

    async def test_upload_deadline_keeps_ticket_visible(self):
        async def history(**kwargs):
            yield SimpleNamespace(author=self.member, attachments=[object()], created_at=discord.utils.utcnow())
        self.channel.history = history
        await Tickets.check_upload_windows.coro(self.cog)
        self.assert_read_only()
        self.assertIn("上传状态: 已截止", self.channel.edit.call_args.kwargs["topic"])
        self.channel.send.assert_awaited_once()
        self.assertIn("材料提交时间:", self.channel.edit.call_args.kwargs["topic"])

    async def test_startup_repairs_existing_approved_ticket_without_reopening_upload(self):
        self.cog.group_confirmations["12"] = {"status": "待确认"}
        self.channel.topic = "工单ID: 123 | 创建者ID: 42 | 上传状态: 进行中 | 上传截止: 9999999999"
        await self.cog.restore_ticket_creator_access()
        self.assert_read_only()

    async def test_startup_preserves_active_upload_window(self):
        self.channel.topic = "工单ID: 123 | 创建者ID: 42 | 上传状态: 进行中 | 上传截止: 9999999999"
        await self.cog.restore_ticket_creator_access()
        overwrite = self.channel.set_permissions.call_args.kwargs["overwrite"]
        self.assertTrue(overwrite.view_channel)
        self.assertTrue(overwrite.read_message_history)
        self.assertTrue(overwrite.send_messages)
        self.assertTrue(overwrite.attach_files)

    async def test_correct_permissions_do_not_trigger_repeated_api_writes(self):
        self.overwrite.update(view_channel=True, read_message_history=True, send_messages=False, attach_files=False)
        await self.cog.ensure_ticket_creator_access(self.channel, {"创建者ID": "42"}, allow_upload=False)
        self.channel.set_permissions.assert_not_awaited()
