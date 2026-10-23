import tempfile
import unittest
import discord
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from cogs.shared import sqlite_store
from cogs.shared.third_party_notice import DEFAULT_NOTICE, load_notice, save_notice
from cogs.thread_tools.cog import ThreadToolsCog


class NoticeStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = sqlite_store.APP_STATE_DB_FILE
        sqlite_store.APP_STATE_DB_FILE = str(Path(self.temp.name) / "state.sqlite3")
        sqlite_store._SCHEMA_READY = False

    def tearDown(self):
        sqlite_store.APP_STATE_DB_FILE = self.old_path
        sqlite_store._SCHEMA_READY = False
        self.temp.cleanup()

    def test_default_and_persistent_guild_override(self):
        self.assertLessEqual(len(DEFAULT_NOTICE), 2000)
        self.assertEqual(load_notice(1), DEFAULT_NOTICE)
        save_notice(1, "# 修改后的提醒\n正文")
        sqlite_store._SCHEMA_READY = False
        self.assertEqual(load_notice(1), "# 修改后的提醒\n正文")
        self.assertEqual(load_notice(2), DEFAULT_NOTICE)

    def test_invalid_content_does_not_replace_saved_notice(self):
        save_notice(1, "有效内容")
        for content in ("  \n", "字" * 2001):
            with self.assertRaises(ValueError):
                save_notice(1, content)
        self.assertEqual(load_notice(1), "有效内容")


class NoticeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def test_command_registration_matches_normalized_discord_response(self):
        bot = discord.Bot()
        bot.add_cog(ThreadToolsCog(bot))

        async def register(application_id, guild_id, payload):
            return [dict(item, id=str(index), type=item.get("type", 1), name=item["name"].replace("\ufe0f", "").replace(" ", ""))
                    for index, item in enumerate(payload, 1)]

        with patch.object(bot.http, "bulk_upsert_guild_commands", new=AsyncMock(side_effect=register)):
            registered = await bot.register_commands(guild_id=123, force=True)
        notice = next(item for item in registered if "第三方违规提醒" in item["name"])
        self.assertEqual(notice["name"], "🚨第三方违规提醒")
        self.assertIs(bot._application_commands[notice["id"]], bot.get_cog("帖子工具").third_party_notice)

    async def test_reply_uses_current_content_without_mass_mentions(self):
        ctx = SimpleNamespace(guild=SimpleNamespace(id=1), defer=AsyncMock(), followup=SimpleNamespace(send=AsyncMock()))
        message = SimpleNamespace(reply=AsyncMock())
        with patch("cogs.thread_tools.cog.load_notice", return_value="最新文案 @everyone"):
            await ThreadToolsCog.third_party_notice.callback(ThreadToolsCog(None), ctx, message)
        ctx.defer.assert_awaited_once_with(ephemeral=True)
        self.assertEqual(message.reply.await_args.args, ("最新文案 @everyone",))
        self.assertEqual(message.reply.await_args.kwargs["allowed_mentions"].to_dict(), {"parse": []})
        self.assertTrue(ThreadToolsCog.third_party_notice.checks)

    async def test_management_panel_still_fits_discord_rows(self):
        from cogs.roles.views import CommunityPanelManageView

        view = CommunityPanelManageView(SimpleNamespace(author=SimpleNamespace(id=1)), None)
        options = [option.value for child in view.children for option in getattr(child, "options", [])]
        self.assertIn("third_party_notice", options)
        self.assertLessEqual(len(view.children), 25)


if __name__ == "__main__":
    unittest.main()
