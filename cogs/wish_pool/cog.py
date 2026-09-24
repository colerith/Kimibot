import asyncio

import discord
from discord.ext import commands

from config import PHONE_WISH_CHANNEL_ID, WISH_CHANNEL_ID
from .general_views import (
    GENERAL_PANEL_MARKER,
    GeneralWishPanelView,
    WishActionView,
    build_general_panel_embed,
)
from .storage import get_panel_info, set_panel_info
from .views import (
    PANEL_MARKER as PHONE_PANEL_MARKER,
    PhoneWishEntryView,
    PhoneWishPanelView,
    build_panel_embed as build_phone_panel_embed,
)


GENERAL_PANEL = "general"
PHONE_PANEL = "phone"


class WishPoolCog(commands.Cog):
    """同时管理通用许愿池与电波手机专用投稿面板。"""

    def __init__(self, bot):
        self.bot = bot
        self.wish_panel_message_id = None
        self.phone_panel_message_id = None
        self._panel_locks = {
            GENERAL_PANEL: asyncio.Lock(),
            PHONE_PANEL: asyncio.Lock(),
        }
        self._refresh_tasks = {}
        self._ready_started = False

    @commands.Cog.listener()
    async def on_ready(self):
        if self._ready_started:
            return
        self._ready_started = True
        self.bot.add_view(GeneralWishPanelView())
        self.bot.add_view(WishActionView())
        self.bot.add_view(PhoneWishPanelView())
        self.bot.add_view(PhoneWishEntryView())
        print("[Wish Pool] 通用许愿池与电波手机面板的持久化视图已注册。")
        asyncio.create_task(self.check_and_post_wish_panel())

    @staticmethod
    def _is_general_panel_message(message: discord.Message) -> bool:
        if not message.embeds:
            return False
        title = getattr(message.embeds[0], "title", "") or ""
        return GENERAL_PANEL_MARKER in title

    @staticmethod
    def _is_phone_panel_message(message: discord.Message) -> bool:
        if not message.embeds:
            return False
        footer = getattr(message.embeds[0].footer, "text", "") or ""
        return PHONE_PANEL_MARKER in footer

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        """两套频道分别监听；机器人发布的投稿也会触发对应面板下移。"""
        channel_id = int(getattr(message.channel, "id", 0) or 0)
        if channel_id == int(WISH_CHANNEL_ID):
            if self._is_general_panel_message(message):
                self.wish_panel_message_id = message.id
                return
            self.request_panel_refresh(GENERAL_PANEL, message.channel)
            return

        if channel_id == int(PHONE_WISH_CHANNEL_ID):
            if self._is_phone_panel_message(message):
                self.phone_panel_message_id = message.id
                return
            self.request_panel_refresh(PHONE_PANEL, message.channel)

    def request_panel_refresh(self, panel_kind: str, channel=None) -> None:
        """独立防抖，避免两套面板互相取消刷新任务。"""
        previous = self._refresh_tasks.get(panel_kind)
        if previous and not previous.done():
            previous.cancel()

        async def delayed_refresh():
            try:
                await asyncio.sleep(0.75)
                await self.move_panel_to_bottom(panel_kind, channel)
            except asyncio.CancelledError:
                return

        self._refresh_tasks[panel_kind] = asyncio.create_task(delayed_refresh())

    async def _get_channel(self, channel_id: int):
        channel = self.bot.get_channel(int(channel_id))
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(int(channel_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        return channel

    def _tracked_message_id(self, panel_kind: str) -> int | None:
        if panel_kind == GENERAL_PANEL:
            return self.wish_panel_message_id
        return self.phone_panel_message_id

    def _set_tracked_message_id(self, panel_kind: str, message_id: int) -> None:
        if panel_kind == GENERAL_PANEL:
            self.wish_panel_message_id = message_id
        else:
            self.phone_panel_message_id = message_id

    def _is_expected_panel(self, panel_kind: str, message: discord.Message) -> bool:
        if panel_kind == GENERAL_PANEL:
            return self._is_general_panel_message(message)
        return self._is_phone_panel_message(message)

    async def _delete_known_panel(self, panel_kind: str, channel) -> None:
        candidate_ids = []
        tracked_id = self._tracked_message_id(panel_kind)
        if tracked_id:
            candidate_ids.append(int(tracked_id))

        if panel_kind == PHONE_PANEL:
            guild_id = int(getattr(getattr(channel, "guild", None), "id", 0) or 0)
            if guild_id:
                stored = get_panel_info(guild_id)
                stored_id = int(stored.get("message_id", 0) or 0)
                if stored_id and stored_id not in candidate_ids:
                    candidate_ids.append(stored_id)

        for message_id in candidate_ids:
            try:
                message = await channel.fetch_message(message_id)
                if self._is_expected_panel(panel_kind, message):
                    await message.delete()
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                continue

    async def post_panel(self, panel_kind: str, channel=None):
        channel_id = WISH_CHANNEL_ID if panel_kind == GENERAL_PANEL else PHONE_WISH_CHANNEL_ID
        channel = channel or await self._get_channel(channel_id)
        if not channel:
            print(f"[Wish Pool] 找不到 {panel_kind} 面板频道 {channel_id}。")
            return None

        if panel_kind == GENERAL_PANEL:
            embed = build_general_panel_embed()
            view = GeneralWishPanelView()
        else:
            embed = build_phone_panel_embed()
            view = PhoneWishPanelView()

        try:
            message = await channel.send(embed=embed, view=view)
            self._set_tracked_message_id(panel_kind, message.id)
            if panel_kind == PHONE_PANEL:
                guild_id = int(getattr(getattr(channel, "guild", None), "id", 0) or 0)
                if guild_id:
                    set_panel_info(guild_id, channel_id=channel.id, message_id=message.id)
            return message
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[Wish Pool] 无法在频道 {channel.id} 发送 {panel_kind} 面板：{type(error).__name__}")
            return None

    async def post_wish_panel(self):
        """保留旧管理入口语义：刷新通用许愿池。"""
        return await self.post_panel(GENERAL_PANEL)

    async def move_panel_to_bottom(self, panel_kind: str, channel=None):
        async with self._panel_locks[panel_kind]:
            channel_id = WISH_CHANNEL_ID if panel_kind == GENERAL_PANEL else PHONE_WISH_CHANNEL_ID
            channel = channel or await self._get_channel(channel_id)
            if not channel:
                return None
            await self._delete_known_panel(panel_kind, channel)
            return await self.post_panel(panel_kind, channel)

    async def _clean_panels_in_channel(self, panel_kind: str, channel) -> int:
        removed = 0
        try:
            async for message in channel.history(limit=100):
                if message.author == self.bot.user and self._is_expected_panel(panel_kind, message):
                    await message.delete()
                    removed += 1
        except (discord.Forbidden, discord.HTTPException) as error:
            print(f"[Wish Pool] 清理频道 {channel.id} 的 {panel_kind} 面板失败：{type(error).__name__}")
        return removed

    async def check_and_post_wish_panel(self):
        """分别清理和发布两套面板，绝不跨频道删除。"""
        await self.bot.wait_until_ready()
        general_channel = await self._get_channel(WISH_CHANNEL_ID)
        phone_channel = await self._get_channel(PHONE_WISH_CHANNEL_ID)

        if general_channel:
            async with self._panel_locks[GENERAL_PANEL]:
                removed = await self._clean_panels_in_channel(GENERAL_PANEL, general_channel)
                await self.post_panel(GENERAL_PANEL, general_channel)
            print(f"[Wish Pool] 通用许愿池已刷新，清理旧面板 {removed} 条。")
        else:
            print(f"[Wish Pool] 找不到通用许愿池频道 {WISH_CHANNEL_ID}。")

        if phone_channel:
            async with self._panel_locks[PHONE_PANEL]:
                removed = await self._clean_panels_in_channel(PHONE_PANEL, phone_channel)
                await self.post_panel(PHONE_PANEL, phone_channel)
            print(f"[Wish Pool] 电波手机许愿面板已刷新，清理旧面板 {removed} 条。")
        else:
            print(f"[Wish Pool] 找不到电波手机许愿频道 {PHONE_WISH_CHANNEL_ID}。")
