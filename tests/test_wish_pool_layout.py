import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import discord

from cogs.wish_pool import cog, general_views, views


class WishLayoutTests(unittest.TestCase):
    def test_paragraphs_and_replies_have_no_generated_quote_markers(self):
        entry = {
            "id": "wish", "content": "第一段\r\n\r\n第二段\n第三行",
            "status": "rejected", "status_reason": "原因一\n\n原因二",
            "replies": [{"role": "owner", "content": "回复一\n\n回复二"}],
        }
        for builder in (views.build_entry_embed, general_views.build_general_entry_embed):
            embed = builder(entry)
            fields = {field.name: field.value for field in embed.fields}
            content = fields.get("📝 投稿内容", fields.get("📝 愿望内容"))
            self.assertEqual(content, "第一段\n\n第二段\n第三行")
            self.assertEqual(fields["🌙 不受理理由"], "原因一\n\n原因二")
            self.assertIn("回复一\n\n回复二", fields["📻 往来电波"])
            self.assertFalse(any(line == ">" for field in embed.fields for line in field.value.splitlines()))

    def test_many_short_lines_fit_discord_field_limit(self):
        for builder in (views.build_entry_embed, general_views.build_general_entry_embed):
            embed = builder({"content": "字\n" * 1500})
            self.assertTrue(all(len(field.value) <= 1024 for field in embed.fields))


class WishRefreshTests(unittest.IsolatedAsyncioTestCase):
    async def test_refreshes_old_cards_in_place_and_skips_missing_and_current(self):
        author = object()
        entries = [dict(id=str(i), scope=scope, channel_id="10", message_id=str(i), content="第一段\n\n第二段")
                   for i, scope in enumerate(("phone", "general", "phone", "phone"), start=1)]
        messages = {str(i): SimpleNamespace(author=author, embeds=[discord.Embed(title="old")], edit=AsyncMock()) for i in (1, 2, 4)}
        messages["4"].embeds = [views.build_entry_embed(entries[3])]

        async def fetch(message_id):
            if message_id == 3:
                raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "deleted")
            return messages[str(message_id)]

        channel = SimpleNamespace(fetch_message=AsyncMock(side_effect=fetch))
        bot = SimpleNamespace(user=author, wait_until_ready=AsyncMock(), get_channel=Mock(return_value=channel))
        instance = cog.WishPoolCog(bot)
        with patch.object(cog, "get_published_entries", return_value=entries), patch.object(cog, "get_entry", side_effect=lambda key: entries[int(key) - 1]):
            await instance.refresh_saved_entries()
        for key in ("1", "2"):
            messages[key].edit.assert_awaited_once()
            kwargs = messages[key].edit.call_args.kwargs
            self.assertNotIn("view", kwargs)
            self.assertEqual(kwargs["allowed_mentions"].to_dict()["parse"], [])
        self.assertIn("通用许愿", messages["2"].edit.call_args.kwargs["embed"].title)
        messages["4"].edit.assert_not_awaited()

    async def test_ready_runs_refresh_only_once(self):
        instance = cog.WishPoolCog(SimpleNamespace(add_view=Mock()))
        with patch.object(instance, "check_and_post_wish_panel", new=AsyncMock()), patch.object(instance, "refresh_saved_entries", new=AsyncMock()) as refresh:
            await instance.on_ready()
            task = instance._entry_refresh_task
            await task
            await instance.on_ready()
            self.assertIs(instance._entry_refresh_task, task)
            refresh.assert_awaited_once()
        instance.cog_unload()
