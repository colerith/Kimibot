import unittest
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, Mock, patch
import discord
from cogs.welcome.cog import WelcomeCog
from cogs.shared import sqlite_store


class PanelRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_old_panel_is_edited_and_saved_without_duplicate_send(self):
        state = {}
        message = NS(id=1499984826931871808, author=NS(id=1),
            embeds=[discord.Embed(title='📝 新兵蛋子入站答题', description='旧文案：10题2分钟')],
            components=[], edit=AsyncMock())
        async def edit(**kwargs):
            message.embeds = [kwargs['embed']]
            message.components = [NS(children=[NS(custom_id='quiz_entry_quota')])]
        message.edit.side_effect = edit
        async def history(**kwargs):
            yield message
        channel = NS(fetch_message=AsyncMock(return_value=message), send=AsyncMock(), history=history)
        cog = WelcomeCog(NS(user=NS(id=1), get_channel=Mock(return_value=channel)))
        with patch.object(sqlite_store,'load_json_namespace',side_effect=lambda *a,**kw:dict(state)), \
             patch.object(sqlite_store,'save_json_namespace',side_effect=lambda key,value:state.update(value)), \
             patch('cogs.welcome.cog.asyncio.sleep',new_callable=AsyncMock):
            await cog.deploy_quiz_panel()
            await cog.deploy_quiz_panel()
        message.edit.assert_awaited_once()
        channel.send.assert_not_awaited()
        self.assertEqual(state['message_ids'],[message.id])
        self.assertIn('15道题',message.embeds[0].description)
        self.assertIn('5 分钟',message.embeds[0].description)
        self.assertIn('查看今日次数',message.embeds[0].description)
