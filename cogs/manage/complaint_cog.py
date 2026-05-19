import json
from pathlib import Path

import discord
from discord.ext import commands

from ..shared.utils import is_super_egg
from .complaint_views import (
    ComplaintPanelView,
    EditComplaintNoticeModal,
    DEFAULT_NOTICE,
    PANEL_BUTTON_ID,
    build_complaint_panel_embed,
)


PANEL_CHANNEL_ID = 1506134402659254403
CACHE_FILE = Path("data/manage_complaint_notice_cache.json")


class ComplaintCog(commands.Cog, name="投诉面板"):
    def __init__(self, bot):
        self.bot = bot
        self._persistent_registered = False
        self.notice_cache = self._load_cache()

    def _load_cache(self):
        if not CACHE_FILE.exists():
            return {}
        try:
            return json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_cache(self):
        try:
            CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            CACHE_FILE.write_text(
                json.dumps(self.notice_cache, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_notice_for_message(self, message_id: int):
        return self.notice_cache.get(str(message_id), DEFAULT_NOTICE)

    def set_notice_for_message(self, message_id: int, notice_text: str):
        self.notice_cache[str(message_id)] = notice_text
        self._save_cache()

    def _prune_notice_cache(self, valid_message_ids: set[int]):
        valid_keys = {str(mid) for mid in valid_message_ids}
        stale_keys = [k for k in self.notice_cache.keys() if k not in valid_keys]
        if not stale_keys:
            return
        for key in stale_keys:
            self.notice_cache.pop(key, None)
        self._save_cache()

    def _is_panel_message(self, message: discord.Message):
        if message.author.id != self.bot.user.id:
            return False
        if not message.components:
            return False

        for row in message.components:
            for child in getattr(row, "children", []):
                if getattr(child, "custom_id", None) == PANEL_BUTTON_ID:
                    return True
        return False

    async def refresh_panel_message(self, message: discord.Message, notice_text: str | None = None):
        notice = notice_text or self.get_notice_for_message(message.id)
        embed = build_complaint_panel_embed(notice)
        view = ComplaintPanelView()
        await message.edit(embed=embed, view=view)

    async def ensure_panel(self):
        channel = self.bot.get_channel(PANEL_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(PANEL_CHANNEL_ID)
            except Exception:
                return

        if not isinstance(channel, discord.TextChannel):
            return

        panel_messages = []
        async for message in channel.history(limit=50):
            if self._is_panel_message(message):
                panel_messages.append(message)

        # 自动清理重复旧面板：保留最新一条，删除其余旧面板。
        if panel_messages:
            primary_panel = panel_messages[0]
            for old_panel in panel_messages[1:]:
                try:
                    await old_panel.delete(reason="清理重复投诉面板")
                except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                    pass

            self._prune_notice_cache({primary_panel.id})
            await self.refresh_panel_message(primary_panel)
            return

        view = ComplaintPanelView()
        sent = await channel.send(embed=build_complaint_panel_embed(DEFAULT_NOTICE), view=view)
        self.set_notice_for_message(sent.id, DEFAULT_NOTICE)

    @commands.Cog.listener()
    async def on_ready(self):
        if not self._persistent_registered:
            self.bot.add_view(ComplaintPanelView())
            self._persistent_registered = True

        await self.ensure_panel()

    @discord.message_command(name="✏️编辑投诉面板文案")
    @is_super_egg()
    async def edit_panel_context(self, ctx: discord.ApplicationContext, message: discord.Message):
        if message.channel_id != PANEL_CHANNEL_ID or not self._is_panel_message(message):
            return await ctx.respond("❌ 选中的消息不是投诉面板。", ephemeral=True)

        current_notice = self.get_notice_for_message(message.id)
        await ctx.send_modal(EditComplaintNoticeModal(self, message, current_notice))

    @discord.slash_command(name="刷新投诉面板", description="手动刷新投诉面板消息")
    @is_super_egg()
    async def refresh_complaint_panel(self, ctx: discord.ApplicationContext):
        await ctx.defer(ephemeral=True)
        await self.ensure_panel()
        await ctx.followup.send("✅ 已刷新投诉面板。", ephemeral=True)
