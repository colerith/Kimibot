import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

from cogs.entertainment.core import EntertainmentCog
from cogs.entertainment.engine import Entertainment


class EntertainmentCogTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.cog = object.__new__(EntertainmentCog)
        self.cog.game = Entertainment(Path(self.tmp.name)/'fun.db', 'discord')

    async def test_slash_and_text_share_daily_balance(self):
        ctx = SimpleNamespace(guild=SimpleNamespace(id=1), author=SimpleNamespace(id=2), interaction=SimpleNamespace(id=3), defer=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        await self.cog.reply(ctx, '奇米签到')
        message = SimpleNamespace(guild=ctx.guild, author=SimpleNamespace(id=2,bot=False), webhook_id=None, content='奇米签到', id=4, channel=SimpleNamespace(send=AsyncMock()))
        await self.cog.on_message(message)
        self.assertIn('已经来过', message.channel.send.call_args.args[0])

    async def test_bots_and_dm_ignored(self):
        message = SimpleNamespace(guild=None, channel=SimpleNamespace(send=AsyncMock()))
        await self.cog.on_message(message)
        message.guild = SimpleNamespace(id=1)
        message.author = SimpleNamespace(bot=True)
        await self.cog.on_message(message)
        message.channel.send.assert_not_awaited()
