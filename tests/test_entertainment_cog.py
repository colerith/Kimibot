import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from cogs.points import storage as points

from cogs.entertainment.core import EntertainmentCog
from cogs.entertainment.engine import Entertainment


class EntertainmentCogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        for name, value in [('POINTS_DB_FILE', str(Path(self.tmp.name) / 'points.db')),
                            ('POINTS_DATA_FILE', str(Path(self.tmp.name) / 'points.json')),
                            ('_POINTS_DB_READY', False)]:
            patcher = patch.object(points, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cog = object.__new__(EntertainmentCog)
        self.cog.game = Entertainment(Path(self.tmp.name)/'fun.db', 'discord')

    async def test_slash_and_text_share_daily_fortune(self):
        ctx = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2), interaction=SimpleNamespace(id=3), defer=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        await self.cog.reply(ctx, '今日运势')
        message = SimpleNamespace(guild=ctx.guild, author=SimpleNamespace(id=2,bot=False), webhook_id=None, content='今日运势', id=4, channel=SimpleNamespace(send=AsyncMock()))
        await self.cog.on_message(message)
        panel = message.channel.send.call_args.kwargs['embed']
        self.assertEqual(panel.to_dict(), ctx.followup.send.call_args.kwargs['embed'].to_dict())
        self.assertIn('奇米悄悄话', panel.description)

    async def test_checkin_removed(self):
        names = {command.name for command in self.cog.kimi.subcommands}
        self.assertNotIn('签到', names)
        self.assertNotIn('饭粒', names)
        self.assertNotIn('蛋壳', names)
        message = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2, bot=False), webhook_id=None, content='奇米签到', channel=SimpleNamespace(send=AsyncMock()))
        await self.cog.on_message(message)
        message.channel.send.assert_not_awaited()

    async def test_bots_and_dm_ignored(self):
        message = SimpleNamespace(guild=None, channel=SimpleNamespace(send=AsyncMock()))
        await self.cog.on_message(message)
        message.guild = SimpleNamespace(id=1)
        message.author = SimpleNamespace(bot=True)
        await self.cog.on_message(message)
        message.channel.send.assert_not_awaited()
