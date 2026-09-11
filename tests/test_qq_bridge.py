"""Focused bridge tests; isolate tickets package to avoid starting unrelated cogs."""
import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import discord

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = '_qimi_bridge_test'
package = types.ModuleType(PACKAGE)
package.__path__ = [str(ROOT / 'cogs' / 'tickets')]
sys.modules[PACKAGE] = package
utils = types.ModuleType(PACKAGE + '.utils')
utils.ApprovedTicketArchiveView = discord.ui.View
utils.archive_edit_lock = lambda message_id: asyncio.Lock()
sys.modules[utils.__name__] = utils
spec = importlib.util.spec_from_file_location(PACKAGE + '.qq_bridge', ROOT / 'cogs/tickets/qq_bridge.py')
bridge = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bridge
spec.loader.exec_module(bridge)


def embed(qq='尚未录入'):
    result = discord.Embed(title='✅ 已过审工单 · #123456')
    result.add_field(name='🧾 工单编号', value='`123456`')
    result.add_field(name='🐧 QQ 号码', value=f'`{qq}`')
    result.add_field(name='💬 加群状态', value='未确认')
    return result


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.worker = object.__new__(bridge.QQBridge)
        self.worker.group_ids = {100}
        self.worker.bot = types.SimpleNamespace(user=types.SimpleNamespace(id=1))
        self.worker.box = bridge.Mailbox(Path(self.tmp.name) / 'bridge.db')
        self.worker.box.add(100, 123456789, '123456', 'flag', __import__('time').time())
        self.row = self.worker.box.pending()[0]
        self.message = types.SimpleNamespace(author=types.SimpleNamespace(id=1), embeds=[embed()], edit=AsyncMock())
        self.channel = types.SimpleNamespace(fetch_message=AsyncMock(return_value=self.message), guild=types.SimpleNamespace(text_channels=[]))

    async def test_archive_author_and_title(self):
        self.assertIsNotNone(bridge.archive_info(self.message, 1))
        self.assertIsNone(bridge.archive_info(self.message, 2))

    async def test_wait_then_archive_and_join(self):
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'pending')
        self.worker.box.index(42, '123456', True)
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'done')
        new = self.message.edit.call_args.kwargs['embed']
        fields = {f.name: f.value for f in new.fields}
        self.assertEqual(fields['🐧 QQ 号码'], '`123456789`')
        self.assertIn('尚未核实', fields['💬 加群状态'])
        self.row['joined'] = 100
        updated = bridge.update_embed(new, self.row)
        self.assertTrue(any('已观察到入群' in f.value for f in updated.fields))

    async def test_manual_value_preserved(self):
        self.worker.box.index(42, '123456', True)
        self.message.embeds = [embed('999999')]
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'conflict')
        self.message.edit.assert_not_awaited()

    async def test_duplicates_and_rejected(self):
        self.worker.box.index(42, '123456', False)
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'conflict')
        self.worker.box.index(43, '123456', True)
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'conflict')
        self.message.edit.assert_not_awaited()

    async def test_idempotent_edit(self):
        self.worker.box.index(42, '123456', True)
        self.message.embeds = [bridge.update_embed(embed(), self.row)]
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'done')
        self.message.edit.assert_not_awaited()

    async def test_whitelist_and_active_collision(self):
        self.row['gid'] = 200
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'conflict')
        self.row['gid'] = 100
        self.worker.box.index(42, '123456', True)
        self.channel.guild.text_channels = [types.SimpleNamespace(topic='创建者ID: 55 | 工单ID: 123456 | 材料状态: 待提交')]
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'pending')
        self.message.edit.assert_not_awaited()

    async def test_approved_live_ticket_can_admit_before_archive(self):
        self.channel.guild.text_channels = [types.SimpleNamespace(id=5, topic='工单ID: 123456 | 审核状态: 已过审')]
        self.worker.bot.fetch_channel = AsyncMock(return_value=self.channel.guild.text_channels[0])
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'ready')
        self.message.edit.assert_not_awaited()

    async def test_unapproved_live_ticket_cannot_admit(self):
        self.channel.guild.text_channels = [types.SimpleNamespace(id=5, topic='工单ID: 123456 | 审核状态: 一审中')]
        self.worker.bot.fetch_channel = AsyncMock(return_value=self.channel.guild.text_channels[0])
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'pending')

    async def test_competing_qq_cannot_claim_ticket(self):
        self.worker.box.index(42, '123456', True)
        self.worker.box.reserve('123456', 99999)
        self.assertEqual((await self.worker.process(self.channel, self.row))[0], 'conflict')
        self.message.edit.assert_not_awaited()
